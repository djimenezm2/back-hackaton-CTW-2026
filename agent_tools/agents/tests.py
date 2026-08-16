"""
Tests for the agent layer, without an LLM.

What is worth testing here is everything except the model: that the prompts carry the rules
the tools deliberately do not, that a run is translated into events a browser can read, and
that the endpoint refuses bad input before it opens a stream it cannot take back.

The model itself is out of scope by design — asserting on generated prose tests the
weather, and any test that called the provider would stop the suite from being hermetic.
"""

import json
from unittest.mock import patch

from django.conf import settings
from django.test import Client, TestCase
from django.urls import reverse
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from psycopg.conninfo import conninfo_to_dict

from agent_tools.agents import render_prompt, translate_chunk
from agent_tools.agents.build import load_prompt
from agent_tools.agents.checkpointer import build_connection_string
from agent_tools.agents.llm import LLMNotConfigured, accepts_temperature, build_chat_model
from agent_tools.agents.streaming import stream_agent, summarize_tool_result
from agent_tools.registry import TOOLSETS
from ayudagente.radar.tests.factories import make_event


class PromptTests(TestCase):
    """Prompts carry behaviour. Everything they promise has to be true of the tools."""

    def setUp(self):
        self.event = make_event(name="Sismo demo")

    def test_every_toolset_has_a_prompt(self):
        for toolset in TOOLSETS:
            with self.subTest(toolset=toolset):
                self.assertTrue(load_prompt(toolset).strip())

    def test_a_missing_prompt_fails_loudly_instead_of_running_empty(self):
        with self.assertRaises(FileNotFoundError):
            load_prompt("no_such_agent")

    def test_the_event_is_rendered_into_the_prompt(self):
        prompt = render_prompt("coordination", self.event)

        self.assertIn("Sismo demo", prompt)
        self.assertIn(str(self.event.id), prompt)
        self.assertIn("Colombia", prompt)
        self.assertNotIn("{event_name}", prompt)  # nothing left unfilled

    def test_the_coordination_prompt_states_the_rules_the_tools_cannot_enforce(self):
        prompt = render_prompt("coordination", self.event).lower()

        self.assertIn("get_balance", prompt)  # orientation call comes first
        self.assertIn("do not translate", prompt)  # the catalog is Spanish
        self.assertIn("saturated", prompt)  # an absent row is not an absent need
        self.assertIn("road_distance", prompt)  # straight-line distance is a floor

    def test_the_frontier_prompt_defends_forced_exploration(self):
        prompt = render_prompt("frontier", self.event).lower()

        self.assertIn("is_unexplored", prompt)
        self.assertIn("rationale", prompt)
        self.assertNotIn("find_requirements", prompt)  # not in its world at all


class TranslateChunkTests(TestCase):
    """The mapping from LangGraph's shapes to the frontend's."""

    def test_a_token_becomes_a_token_event(self):
        events = translate_chunk("messages", (AIMessageChunk(content="En Quibdó"), {}))

        self.assertEqual(events, [{"type": "token", "text": "En Quibdó"}])

    def test_empty_tokens_are_not_sent(self):
        self.assertEqual(translate_chunk("messages", (AIMessageChunk(content=""), {})), [])

    def test_a_tool_call_is_announced_before_it_runs(self):
        message = AIMessage(
            content="",
            tool_calls=[
                {"name": "get_balance", "args": {"event_id": 1}, "id": "call_1"},
            ],
        )

        events = translate_chunk("updates", {"model": {"messages": [message]}})

        self.assertEqual(events[0]["type"], "tool_start")
        self.assertEqual(events[0]["name"], "get_balance")
        self.assertEqual(events[0]["args"], {"event_id": 1})

    def test_a_tool_result_is_summarized_not_replayed(self):
        rows = [{"resource_key": f"recurso_{i}"} for i in range(12)]
        payload = json.dumps({"count": 12, "truncated": True, "balance": rows})
        message = ToolMessage(content=payload, name="get_balance", tool_call_id="call_1")

        events = translate_chunk("updates", {"tools": {"messages": [message]}})

        self.assertEqual(events[0]["type"], "tool_end")
        self.assertEqual(events[0]["result"], {"ok": True, "count": 12, "truncated": True})
        self.assertNotIn("recurso_0", str(events[0]))  # the rows never reach the browser

    def test_a_tool_failure_is_visible_without_parsing_the_payload(self):
        message = ToolMessage(
            content=json.dumps({"error": "unknown resource 'water'", "available": []}),
            name="find_requirements",
            tool_call_id="call_2",
        )

        result = translate_chunk("updates", {"tools": {"messages": [message]}})[0]["result"]

        self.assertFalse(result["ok"])
        self.assertIn("water", result["error"])

    def test_chunks_carrying_nothing_a_user_needs_produce_no_events(self):
        self.assertEqual(translate_chunk("updates", {"model": {"messages": []}}), [])
        self.assertEqual(translate_chunk("updates", "not a dict"), [])
        self.assertEqual(translate_chunk("values", {"anything": 1}), [])
        self.assertEqual(
            translate_chunk("updates", {"model": {"messages": [HumanMessage(content="hi")]}}),
            [],
        )

    def test_a_non_json_tool_result_is_still_reported(self):
        self.assertEqual(summarize_tool_result("plain text"), {"ok": True, "preview": "plain text"})


class FakeGraph:
    """A compiled agent's `stream`, without a model behind it."""

    def __init__(self, chunks=None, raises=None):
        self.chunks = chunks or []
        self.raises = raises
        self.config: dict = {}

    def stream(self, _input, config=None, stream_mode=None):
        self.config = config or {}
        if self.raises:
            raise self.raises
        yield from self.chunks


def streamed_body(response) -> str:
    """Drain a `StreamingHttpResponse` into text."""
    return b"".join(response.streaming_content).decode()


class StreamAgentTests(TestCase):
    def _events(self, graph):
        return [
            json.loads(line.removeprefix("data: ")) for line in stream_agent(graph, "hola", "t1")
        ]

    def test_a_run_is_bracketed_by_start_and_done(self):
        events = self._events(FakeGraph())

        self.assertEqual(events[0], {"type": "start", "thread_id": "t1"})
        self.assertEqual(events[-1], {"type": "done", "thread_id": "t1"})

    def test_the_thread_id_reaches_the_graph_so_the_conversation_continues(self):
        graph = FakeGraph()
        list(stream_agent(graph, "hola", "t42"))

        self.assertEqual(graph.config["configurable"]["thread_id"], "t42")

    def test_a_failure_mid_run_is_streamed_rather_than_raised(self):
        # The status code is long gone by now; raising would just drop the connection
        events = self._events(FakeGraph(raises=RuntimeError("the provider said no")))

        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("the provider said no", events[-1]["error"])

    def test_a_full_turn_streams_tools_then_prose(self):
        graph = FakeGraph(
            chunks=[
                (
                    "updates",
                    {
                        "model": {
                            "messages": [
                                AIMessage(
                                    content="",
                                    tool_calls=[{"name": "get_balance", "args": {}, "id": "c1"}],
                                )
                            ]
                        }
                    },
                ),
                (
                    "updates",
                    {
                        "tools": {
                            "messages": [
                                ToolMessage(
                                    content=json.dumps({"count": 3}),
                                    name="get_balance",
                                    tool_call_id="c1",
                                )
                            ]
                        }
                    },
                ),
                ("messages", (AIMessageChunk(content="Faltan 2600 L"), {})),
            ]
        )

        kinds = [event["type"] for event in self._events(graph)]

        self.assertEqual(kinds, ["start", "tool_start", "tool_end", "token", "done"])


class CheckpointerTests(TestCase):
    def test_a_password_with_url_metacharacters_survives(self):
        # As a URL this reparses into a different host and database, and says neither
        db = {
            "USER": "hackaton",
            "PASSWORD": "p@ss/w:rd#1",
            "HOST": "localhost",
            "PORT": "5433",
            "NAME": "hackaton",
        }
        with self.settings(DATABASES={"default": db}):
            conninfo = build_connection_string()

        parsed = conninfo_to_dict(conninfo)
        self.assertEqual(parsed["password"], "p@ss/w:rd#1")
        self.assertEqual(parsed["host"], "localhost")
        self.assertEqual(parsed["dbname"], "hackaton")


class LLMConfigTests(TestCase):
    """One source of truth for which model runs: the role map the rest of the system uses."""

    def _build(self, model_name="gpt-5.6-sol", **overrides) -> ChatOpenAI:
        """Build with a key present and one role mapped, narrowed to the concrete class."""
        models = {**settings.OPENAI_MODELS, "reasoning": model_name}
        with self.settings(OPENAI_API_KEY="sk-test", OPENAI_MODELS=models, **overrides):
            model = build_chat_model()
        assert isinstance(model, ChatOpenAI)
        return model

    def test_a_missing_key_names_the_variable_to_set(self):
        with self.settings(OPENAI_API_KEY=""), self.assertRaises(LLMNotConfigured) as ctx:
            build_chat_model()

        self.assertIn("OPENAI_API_KEY", str(ctx.exception))

    def test_a_role_with_no_model_configured_is_refused(self):
        models = {**settings.OPENAI_MODELS, "reasoning": ""}
        with (
            self.settings(OPENAI_API_KEY="sk-test", OPENAI_MODELS=models),
            self.assertRaises(LLMNotConfigured) as ctx,
        ):
            build_chat_model()

        self.assertIn("reasoning", str(ctx.exception))

    def test_the_agent_runs_the_model_the_reasoning_role_names(self):
        # Not its own variable: a second one would drift from OPENAI_MODEL_REASONING
        self.assertEqual(self._build(model_name="gpt-5.6-sol").model_name, "gpt-5.6-sol")
        self.assertEqual(self._build(model_name="gpt-4o").model_name, "gpt-4o")

    def test_a_reasoning_model_is_sent_no_temperature(self):
        # Reasoning models reject `temperature` outright — sending it is a 400 every call
        self.assertIsNone(self._build(model_name="gpt-5.6-sol").temperature)

    def test_a_classic_model_still_gets_one(self):
        self.assertEqual(self._build(model_name="gpt-4o").temperature, 0.2)

    def test_the_capability_split_matches_the_model_families(self):
        for name in ("gpt-5.6-sol", "gpt-5.6-luna", "o3-mini"):
            self.assertFalse(accepts_temperature(name), name)
        for name in ("gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"):
            self.assertTrue(accepts_temperature(name), name)


class AgentEndpointTests(TestCase):
    """Everything the endpoint must settle before a single byte is streamed."""

    def setUp(self):
        self.client = Client()
        self.event = make_event()
        self.url = reverse("radar:agent-coordination")

    def _post(self, payload):
        return self.client.post(self.url, data=payload, content_type="application/json")

    def test_a_missing_message_is_a_400_not_a_stream(self):
        response = self._post({"event_id": self.event.id})

        self.assertEqual(response.status_code, 400)
        self.assertIn("message", response.json()["error"])

    def test_an_unknown_event_is_refused_before_the_model_runs(self):
        response = self._post({"event_id": 99999, "message": "hola"})

        self.assertEqual(response.status_code, 400)

    def test_an_oversized_message_is_refused(self):
        response = self._post({"event_id": self.event.id, "message": "x" * 5000})

        self.assertEqual(response.status_code, 400)

    def test_a_broken_body_is_reported_as_such(self):
        response = self.client.post(self.url, data="{[", content_type="application/json")

        self.assertEqual(response.status_code, 400)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_missing_credentials_are_a_503_with_the_reason(self):
        # Overridden through settings, not the environment: that is where the key is read
        with self.settings(OPENAI_API_KEY=""):
            response = self._post({"event_id": self.event.id, "message": "hola"})

        self.assertEqual(response.status_code, 503)
        self.assertIn("OPENAI_API_KEY", response.json()["error"])

    def test_the_stream_is_event_stream_and_unbuffered(self):
        graph = FakeGraph(chunks=[("messages", (AIMessageChunk(content="hola"), {}))])
        with patch("ayudagente.radar.agent_views.build_agent", return_value=graph):
            response = self._post({"event_id": self.event.id, "message": "hola"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/event-stream")
        self.assertEqual(response["X-Accel-Buffering"], "no")  # or a proxy buffers it all

        body = streamed_body(response)
        self.assertIn('"type": "start"', body)
        self.assertIn("hola", body)
        self.assertIn('"type": "done"', body)

    def test_a_thread_id_round_trips_so_follow_ups_continue(self):
        graph = FakeGraph()
        with patch("ayudagente.radar.agent_views.build_agent", return_value=graph):
            response = self._post(
                {"event_id": self.event.id, "message": "hola", "thread_id": "mine"}
            )
            body = streamed_body(response)

        self.assertIn('"thread_id": "mine"', body)
        self.assertEqual(graph.config["configurable"]["thread_id"], "mine")

    def test_the_frontier_agent_has_its_own_endpoint(self):
        graph = FakeGraph()
        with patch("ayudagente.radar.agent_views.build_agent", return_value=graph) as build:
            self.client.post(
                reverse("radar:agent-frontier"),
                data={"event_id": self.event.id, "message": "¿dónde busco?"},
                content_type="application/json",
            )

        self.assertEqual(build.call_args.args[0], "frontier")
