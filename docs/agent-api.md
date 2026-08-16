# Consuming the agent

How a frontend talks to the two agents. Endpoints, the event stream, and the failure modes
worth handling.

Architecture in [`agent-tools.md`](agent-tools.md); models in
[`data-model.md`](data-model.md).

---

## The shape of it

One POST opens a stream. The response is `text/event-stream` and stays open while the agent
works — typically ten to forty seconds — sending events as it goes. There is no polling and
no websocket.

Every response ends with exactly one terminal event, `done` or `error`. If the connection
closes without either, the request was cut short and the turn should be treated as failed.

```
POST /api/agent/coordination/     answers a coordinator's questions, proposes actions
POST /api/agent/frontier/         decides where to harvest next
```

Both take the same body and speak the same stream.

---

## Request

```http
POST /api/agent/coordination/
Content-Type: application/json

{
  "event_id": 1,
  "message": "¿qué falta en Quibdó?",
  "thread_id": "0f1c…"        // omit on the first turn
}
```

| Field | Required | Notes |
|---|---|---|
| `event_id` | yes | From `GET /api/events/`. Everything is scoped to one emergency. |
| `message` | yes | Spanish. Up to 2000 characters. |
| `thread_id` | no | Omit to start a conversation; the server returns one to reuse. |

Both endpoints need the API key, like everything under `/api/`. Send it in `X-API-Key` or as
`Authorization: Bearer <key>` — see [`api.md`](api.md) for the scheme and the CORS settings.
CSRF is exempt here, because the key already establishes who is calling.

### Conversations

Leave `thread_id` out on the first message. The `start` event carries the id the server
generated; send it back on every following message and the agent keeps its context, so
"¿y quién puede surtirlo?" works without repeating what "lo" was.

State lives in Postgres, so a thread survives a server restart. Keep one thread per
conversation in the UI and start a new one when the user clears the chat.

---

## The stream

Events are standard SSE: one `data:` line carrying JSON, then a blank line.

```
data: {"type": "start", "thread_id": "0f1c…"}

data: {"type": "tool_start", "name": "get_balance", "args": {"event_id": 1}, "node": "model"}

data: {"type": "tool_end", "name": "get_balance", "result": {"ok": true, "count": 3}}

data: {"type": "token", "text": "En Quibdó"}

data: {"type": "token", "text": " faltan 2600 L"}

data: {"type": "done", "thread_id": "0f1c…"}
```

| `type` | When | Payload |
|---|---|---|
| `start` | Once, first | `thread_id` — store it |
| `tool_start` | The agent decided to call a tool | `name`, `args`, `node` |
| `tool_end` | That tool returned | `name`, `result` (a summary, see below) |
| `token` | A piece of the answer | `text` — append it, do not replace |
| `done` | Once, last, on success | `thread_id` |
| `error` | Once, last, on failure | `error` — a string safe to show |

A turn usually alternates: some tool pairs, then tokens. Several tools can run in one step,
so expect more than one `tool_start` before the matching `tool_end`s; match them by `name`.

`token` events carry fragments, not sentences. Concatenate in arrival order. Do not trim
them — the spaces between words arrive inside the fragments.

### `tool_end.result`

A summary, never the rows. The agent got the full payload; the browser gets enough to draw
a step.

```json
{"ok": true, "count": 12, "truncated": true}
{"ok": false, "error": "unknown resource 'water'"}
{"ok": true, "match_id": 41}
```

`ok` is the only field always present. The others appear when they apply: `count`,
`truncated`, `distance_km`, `match_id`, `outreach_id`, `job_id`.

**`ok: false` is not a bug.** Tools report bad arguments as data so the agent can correct
itself, and it usually does on the next call. Render it as a step that missed, not as a
failed request — the turn is still going and will very likely succeed.

To show what a tool actually returned, call the underlying read endpoint yourself, or use
the ids the agent surfaces in its answer.

---

## Reading it in the browser

`EventSource` cannot POST, so use `fetch` and read the body:

```js
async function askAgent({ agent, eventId, message, threadId, onEvent, signal }) {
  const response = await fetch(`/api/agent/${agent}/`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-API-Key": apiKey },
    body: JSON.stringify({ event_id: eventId, message, thread_id: threadId }),
    signal,
  });

  if (!response.ok) throw new Error((await response.json()).error);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // Events are separated by a blank line; the tail may be a partial event
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.trim();
      if (line.startsWith("data: ")) onEvent(JSON.parse(line.slice(6)));
    }
  }
}
```

The buffering matters: a chunk from the network can split an event in half, and parsing per
chunk instead of per blank line produces sporadic JSON errors under load that are painful to
reproduce.

Pass an `AbortSignal` so leaving the view stops the request.

---

## Failures

Two kinds, and they need different handling.

**Before the stream opens** — a normal JSON response with a non-200 status. Nothing was
sent, nothing to clean up.

| Status | Body | Meaning |
|---|---|---|
| 400 | `{"error": "message is required"}` | Missing, empty or oversized message |
| 400 | `{"error": "event_id does not exist"}` | Bad `event_id` |
| 400 | `{"error": "body must be JSON"}` | Malformed body |
| 401 / 403 | `{"error": "…"}` | Missing or unknown API key |
| 404 | Django's own page, not JSON | Wrong path — only the two above exist |
| 405 | — | Not a POST |
| 503 | `{"error": "agent is not configured: …"}` | `OPENAI_API_KEY` is not set on the server |

**During the stream** — status 200 was already sent, so a failure arrives as a final
`error` event. Show its text, keep whatever tokens already arrived, and let the user retry
on the same `thread_id`.

```json
{"type": "error", "error": "RateLimitError: rate limit exceeded"}
```

### Proxies

The response sets `Cache-Control: no-cache` and `X-Accel-Buffering: no`. If a proxy between
you and Django buffers anyway, the whole turn lands at once at the end — correct, but the
streaming is gone. That is the first thing to check when it works locally and not deployed.

---

## What each agent does

### Coordination

Answers questions about needs and offers, and proposes actions. Tools, in the order it
usually reaches for them:

| Tool | Shown as |
|---|---|
| `get_balance` | Comparing supply and demand |
| `find_requirements` | Searching needs / offers |
| `get_actor_contacts` | Looking up how to reach them |
| `road_distance` | Measuring the real drive |
| `plan_trip_stops` | Ordering the stops |
| `propose_match` | Proposing a pairing |
| `draft_outreach` | Drafting a message |

The last two **write**. `propose_match` creates a proposal for a human to review;
`draft_outreach` creates a draft and a link. Neither delivers anything or contacts anyone.

When `draft_outreach` succeeds, the outreach row carries a `target_url` — a `wa.me` or
`mailto:` link with the text already filled in. **The system never sends it.** Show it as a
button a person clicks. That is the whole outreach design, not a limitation to work around.

### Frontier

Decides where to look for information next. Two tools: `get_frontier` reads the scoreboard
of places and accounts being watched, `create_harvest_job` queues a harvest.

It cannot read a post through any tool it holds, by construction. Its answers are about
where to spend attention, never about what someone said.

Normally it runs on a schedule. The endpoint exists so a dashboard can trigger a round by
hand and show the reasoning.

---

## Getting an `event_id`

```http
GET /api/events/
```

```json
{"events": [{"id": 1, "name": "Sismo demo Eje Cafetero", "hazard": "earthquake",
             "occurred_at": "2026-08-15T…", "magnitude": 6.1,
             "epicenter": {"lat": 4.81, "lon": -75.69}}]}
```

`GET /api/events/<id>/graph/` returns the whole graph for one event — actors as nodes,
matches as edges, open requirements attached. That is the map view's data; the agent is the
conversation over it.

---

## Notes for the UI

**Show the tool steps.** The wait is long enough that a spinner alone reads as broken. Users
tolerate thirty seconds when they can see what is happening, and the tool names are legible
enough to narrate.

**Do not render `args` verbatim.** They are internal ids and slugs. Map `name` to a phrase,
as in the table above.

**A `count: 0` from a tool does not mean "there is nothing".** It can mean everything found
was already saturated. The agent knows this and says so in its answer — let the prose speak
rather than drawing a conclusion from the counter.

**One request at a time per thread.** Sending a second message while the first is streaming
will interleave writes to the same conversation. Disable the input until `done` or `error`.

---

## Server requirements

```bash
OPENAI_API_KEY=...                      # without it every agent request is a 503
OPENAI_MODEL_REASONING=gpt-5.6-sol      # the model both agents run on
```

Both agents use the `reasoning` role from the shared model map, the same one the rest of
the pipeline reads. There is no separate variable for the agent, so changing
`OPENAI_MODEL_REASONING` changes what answers you.

That is also the dial worth knowing about from the frontend: a heavier model means better
answers and noticeably longer turns. If a turn feels slow, check which model is configured
before blaming the stream.

Postgres must be reachable: conversation state is checkpointed there, and the tables are
created on first use.
