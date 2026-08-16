"""
Turning a LangGraph run into a stream a browser can read.

The coordinator watching this is waiting during an emergency, so silence is expensive. What
makes the wait tolerable is not speed — it is seeing *what the agent is doing*: which tool
it reached for, what came back, then the answer arriving word by word.

Note:
    `translate_chunk` is deliberately pure. Everything interesting about this module is the
    mapping from LangGraph's shapes to the frontend's, and keeping it free of the graph, the
    model and the request is what lets it be tested without any of them.
"""

import json
from collections.abc import Iterator
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

# Tool results can be large; the stream carries a summary and the frontend asks for detail
MAX_PREVIEW_CHARS = 400


def sse(payload: dict) -> str:
    """
    Format one event for `text/event-stream`.

    Returns:
        str: A `data:` line and the blank line that terminates the event. `ensure_ascii` is
            off because the payload is Spanish and escaping every accent doubles the bytes.
    """
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def summarize_tool_result(content: Any) -> dict:
    """
    Describe what a tool returned without replaying all of it.

    Returns:
        dict: `ok` is false when the tool reported a failure, so the frontend can mark the
            step without parsing the payload. Row counts are surfaced because "found 12"
            is the useful part of a result the user is not going to read.
    """
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except (ValueError, TypeError):
            return {"ok": True, "preview": content[:MAX_PREVIEW_CHARS]}

    if not isinstance(content, dict):
        return {"ok": True, "preview": str(content)[:MAX_PREVIEW_CHARS]}

    summary: dict[str, Any] = {"ok": "error" not in content}
    if "error" in content:
        summary["error"] = content["error"]
    for key in ("count", "truncated", "match_id", "outreach_id", "job_id", "distance_km"):
        if key in content:
            summary[key] = content[key]
    return summary


def translate_chunk(mode: str, chunk: Any) -> list[dict]:
    """
    Map one LangGraph stream chunk to zero or more frontend events.

    Args:
        mode (str): The stream mode that produced the chunk — `messages` or `updates`.
        chunk (Any): Whatever that mode yields.

    Returns:
        list[dict]: Events to send. Empty for the many chunks that carry nothing a user
            needs to see, which is most of them.
    """
    events: list[dict] = []

    if mode == "messages":
        message = chunk[0] if isinstance(chunk, tuple) else chunk
        if (
            isinstance(message, AIMessageChunk)
            and isinstance(message.content, str)
            and message.content
        ):
            events.append({"type": "token", "text": message.content})
        return events

    if mode != "updates" or not isinstance(chunk, dict):
        return events

    for node, update in chunk.items():
        if not isinstance(update, dict):
            continue
        for message in update.get("messages", []) or []:
            if isinstance(message, ToolMessage):
                events.append(
                    {
                        "type": "tool_end",
                        "name": message.name,
                        "result": summarize_tool_result(message.content),
                    }
                )
            elif isinstance(message, AIMessage) and message.tool_calls:
                events.extend(
                    {
                        "type": "tool_start",
                        "name": call["name"],
                        "args": call.get("args", {}),
                        "node": node,
                    }
                    for call in message.tool_calls
                )
    return events


def stream_agent(graph, message: str, thread_id: str) -> Iterator[str]:
    """
    Run one turn and yield it as server-sent events.

    Args:
        graph: A compiled agent.
        message (str): What the user asked.
        thread_id (str): Conversation to continue, or start.

    Yields:
        str: Formatted SSE events, ending with `done` or `error`.

    Note:
        Failures are streamed, not raised. The response status is already sent by the time
        the model runs, so an exception here would close the connection with no explanation
        and the frontend would show a conversation that simply stopped.
    """
    yield sse({"type": "start", "thread_id": thread_id})

    try:
        for mode, chunk in graph.stream(
            {"messages": [{"role": "user", "content": message}]},
            config={"configurable": {"thread_id": thread_id}},
            stream_mode=["updates", "messages"],
        ):
            for event in translate_chunk(mode, chunk):
                yield sse(event)
    except Exception as exc:
        yield sse({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
        return

    yield sse({"type": "done", "thread_id": thread_id})
