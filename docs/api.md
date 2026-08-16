# HTTP API

The contract the web frontend codes against. Two read endpoints that return the whole picture,
two streaming endpoints that talk to the agents, and one authentication scheme over all four.

The agents have their own document — [`agent-api.md`](agent-api.md) covers the stream format,
the tool events and the failure modes worth handling. This one covers everything else.

Models in [`data-model.md`](data-model.md).

---

## Base URL and authentication

```
http://localhost:8000/api/
```

Every path under `/api/` requires a key. Send it in either header, whichever is easier:

```http
X-API-Key: <key>
```
```http
Authorization: Bearer <key>
```

Keys are issued per consumer, not per user — the frontend holds one, a dashboard would hold
another. There is no login, no session and no cookie: the API authenticates the *client*, and
who the human is has no meaning to it yet.

The key belongs in the server that proxies your requests, not in browser JavaScript. Anything
shipped to the browser is public, and a key in a bundle is a key on the internet.

| Status | Body | Meaning |
|---|---|---|
| 401 | `{"error": "missing API key; send it in X-API-Key"}` | Neither header carried one |
| 403 | `{"error": "unknown API key"}` | The key is not on the server's list |
| 503 | `{"error": "the API has no keys configured"}` | `API_KEYS` is empty on the server |

That last one is a server misconfiguration, not your bug. An unconfigured deployment closes
the API rather than opening it, so a stripped environment file fails loudly instead of
publishing the data.

`/admin/` is not under `/api/` and keeps its own session login. CORS preflight (`OPTIONS`) is
never challenged — a browser cannot attach a custom header to a preflight, and requiring one
would forbid cross-origin calls entirely.

### CORS

While `DEBUG=True` every origin is allowed. For anything else, set `CORS_ALLOWED_ORIGINS` on
the server to a comma-separated list. `x-api-key` is on the allowed-headers list, so the
preflight passes it through.

---

## `GET /api/events/`

Active events, newest first. The frontend's entry point: everything else is scoped to one
`event_id`.

```json
{
  "events": [
    {
      "id": 1,
      "name": "Sismo Eje Cafetero",
      "hazard": "earthquake",
      "occurred_at": "2026-08-10T14:32:00Z",
      "magnitude": 6.1,
      "epicenter": {"lat": 4.8133, "lon": -75.6961}
    }
  ]
}
```

`magnitude` and `epicenter` are null for hazards that have neither. Archived and paused events
are not listed.

---

## `GET /api/events/{event_id}/graph/`

The whole graph for one event in a single response — actors as nodes, matches as edges, open
requirements hanging off their node. Computed fresh on every call, so "real time" here means
no snapshot lag rather than a socket.

404 when the event does not exist.

```json
{
  "event": {"id": 1, "name": "Sismo Eje Cafetero", "epicenter": {"lat": 4.81, "lon": -75.69}},
  "nodes": [ … ],
  "edges": [ … ]
}
```

### Nodes

One per actor. Merged duplicates never appear — an actor that was resolved into another is
gone from this payload, and its requirements now hang off the survivor.

```json
{
  "id": 42,
  "name": "Coliseo Mayor de Pereira",
  "kind": "collection_center",
  "credibility": 0.72,
  "verified": false,
  "location": {"lat": 4.8133, "lon": -75.6961},
  "precision": "neighborhood",
  "admin_unit": "Pereira",
  "requirements": [ … ]
}
```

| Field | Type | Notes |
|---|---|---|
| `id` | int | Stable. Use it as the React key and for `find_requirements` filters. |
| `name` | string | The canonical name after identity resolution, not what one post said. |
| `kind` | enum | See [Actor kinds](#actor-kinds). |
| `credibility` | float 0–1 | Derived from followers, verification and engagement. |
| `verified` | bool | The platform's badge, not our judgment. |
| `location` | point \| null | Falls back to the actor's first open requirement when the actor has no location of its own. |
| `precision` | enum \| null | How exact that point is. See [Location precision](#location-precision). |
| `admin_unit` | string \| null | Municipality or equivalent. |
| `requirements` | array | Only `open` and `partial`. Can be empty. |

**Do not draw a marker without checking `precision`.** A `country` point is the centroid of
Colombia and drawing it as a pin says something false. Treat anything coarser than
`admin_2` as an area, not a place.

### Requirements

A need or an offer. Attached to the node that owns it.

```json
{
  "id": 118,
  "direction": "needs",
  "resource": "Drinking water",
  "resource_key": "water_drinking",
  "free_text": "agua para 40 familias",
  "urgency": "critical",
  "status": "partial",
  "quantity": 100.0,
  "covered_quantity": 25.0,
  "outstanding": 75.0,
  "unit": "L",
  "destination": {"lat": 4.81, "lon": -75.69},
  "confidence": 0.82
}
```

| Field | Type | Notes |
|---|---|---|
| `direction` | enum | `needs` or `offers`. The single most load-bearing field. |
| `resource` | string | Display name. `resource_key` is the stable slug — filter on that. |
| `free_text` | string | What the post actually said, in Spanish. Good for a tooltip. |
| `urgency` | enum | `critical` / `high` / `medium` / `low`. |
| `status` | enum | Only `open` and `partial` appear here. |
| `quantity` | float \| null | **Frequently null.** Most posts say "necesitamos agua", not "100 L". |
| `covered_quantity` | float | How much matching has already allocated. |
| `outstanding` | float \| null | `quantity - covered_quantity`. Null when quantity is. |
| `unit` | string | Free text: `L`, `kg`, `familias`, `mercados`. Not an enum. |
| `destination` | point \| null | Where an *offer* should be delivered, when it differs from the actor. |
| `confidence` | float 0–1 | The extractor's confidence. Below 0.40 never reaches the API. |

**A null `quantity` is the normal case, not missing data.** Sort by `urgency` first and treat
quantity as a bonus when it exists; a UI that needs a number to render a row will show almost
nothing.

### Edges

One per proposed or accepted match. Direction is always offer → need.

```json
{
  "id": 7,
  "from_actor": 42,
  "to_actor": 19,
  "resource": "Drinking water",
  "status": "proposed",
  "score": 0.84,
  "distance_km": 12.4,
  "committed_quantity": 25.0,
  "via_transport_actor": 55,
  "rationale": "Centro de acopio a 12 km con agua disponible"
}
```

| Field | Type | Notes |
|---|---|---|
| `from_actor` / `to_actor` | int | Node ids. Both are always present in `nodes`. |
| `status` | enum | `proposed` / `contacted` / `confirmed` / `delivered`. Failed and discarded matches are not returned. |
| `score` | float 0–1 | How good the pairing is. Not a probability. |
| `distance_km` | float \| null | Road distance when it was computed, straight line otherwise. |
| `via_transport_actor` | int \| null | Someone offering transport for this leg — the third node of a three-way match. |
| `rationale` | string | One sentence in Spanish, written to be shown. |

A `via_transport_actor` means the delivery needs a carrier: the edge is really two hops. Draw
it as one line through that node rather than as a separate edge, or the graph doubles.

---

## `POST /api/agent/coordination/` and `POST /api/agent/frontier/`

Streaming conversations with the two agents. Body, event format, tool events and error
handling are all in [`agent-api.md`](agent-api.md).

Two things that document predates and that matter here: both endpoints now require the API
key like everything else, and `EventSource` cannot be used — it is GET-only and cannot set
headers. Use `fetch` with a body reader, as that document shows.

---

## Enumerations

Values are stable slugs. Labels are yours to write — the API sends the slug, and every
user-facing string is a product decision, in Spanish, that belongs in the frontend.

### Hazard

`earthquake` · `flood` · `landslide` · `cyclone` · `wildfire` · `windstorm` · `other`

### Actor kinds

`person` · `collection_center` · `nonprofit` · `company` · `public_entity` · `media_outlet` ·
`community` · `church` · `school` · `volunteer_group`

### Direction

`needs` · `offers`

### Urgency

`critical` · `high` · `medium` · `low`

### Requirement status

`open` · `partial` · `covered` · `expired` · `unverified` · `discarded`

The graph endpoint only ever returns the first two.

### Match status

`proposed` · `contacted` · `confirmed` · `delivered` · `failed` · `discarded`

The graph endpoint returns the first four. Past `proposed`, a human is already involved and
the matching pass will not rewrite it.

### Location precision

Coarse to fine, and the order is load-bearing:

`country` · `admin_1` · `admin_2` · `admin_3` · `neighborhood` · `street_address` ·
`exact_point`

---

## What is not here yet

Worth knowing before you design around it:

- **No pagination.** The graph endpoint returns everything for an event. At pilot size that is
  a few hundred nodes; if it grows past what a browser can draw, that is when paging arrives.
- **No evidence endpoint.** A requirement does not yet expose the posts behind it — the
  screenshot, the permalink, the author. The data exists (`Requirement.evidence`); the
  endpoint does not.
- **No outreach endpoint.** Drafts are created by the coordination agent through
  `draft_outreach` and carry a `target_url`, but there is no way to list them over HTTP.
- **No write endpoints.** Everything a human does — confirming a match, dismissing a draft —
  goes through the admin for now.

The first two are the ones a real UI hits soonest. Ask before building around their absence.

---

## Local setup

```bash
make up          # Postgres and Redis
make migrate
make seed        # loads the demo event, so the graph is not empty
make run
```

The server reads `API_KEYS` from `.env` as a comma-separated list. `make init` copies
`.env.example`, which leaves it empty — fill it in or every request is a 503.

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

```http
GET http://localhost:8000/api/events/
X-API-Key: <the key you generated>
```
