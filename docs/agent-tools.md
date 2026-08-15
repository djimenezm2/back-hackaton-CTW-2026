# Tools del agente — estado y continuación

Guía para seguir desarrollando la capa de tools sobre los modelos de `ayudagente.radar`.
Contexto de modelos en [`data-model.md`](data-model.md); estrategia de búsqueda en
[`../HANDBOOK.md`](../HANDBOOK.md).

## Principio de diseño

**El juicio es del modelo; las funciones son de código.** Toda tool es una función Python
determinista sobre Postgres/PostGIS/OSRM, sin LLM adentro. El agente (LangGraph +
deepagents) decide *cuándo* llamarlas y redacta con sus resultados. Nunca se le pide al
LLM calcular distancias, agregar cantidades ni ordenar paradas.

---

## Estado actual

### Hecho — `ayudagente/radar/services/`

| Función | Archivo | Qué hace |
|---|---|---|
| `find_requirements(event_id, direction, resource?, near?, radius_km?, min_precision?, only_unsaturated=True)` | `requirements.py` | Requirements abiertos. Expande la familia del árbol `ResourceType` (ancestros + descendientes: "comida de perros" ↔ "alimentos"), filtra precisión mínima, excluye saturados, ordena por distancia PostGIS |
| `get_balance(event_id, resource?)` | `requirements.py` | Déficit/superávit agregado por recurso × municipio × dirección |
| `resource_family(resource)` | `requirements.py` | IDs compatibles en el árbol — usada por búsqueda y matching |
| `road_distance(origin, destination)` | `routing.py` | Km/minutos por carretera real (OSRM), con geometría para mapa |
| `plan_trip_stops(stops)` | `routing.py` | Orden óptimo de paradas multi-stop (OSRM `/trip`). El caller decide QUÉ va en el camión; esto decide EN QUÉ ORDEN |
| `propose_match(need, offer, via_transport?, ...)` | `matching.py` | Crea/actualiza un match respetando `FROZEN_MATCH_STATES`. Valida direcciones y que `via_transport` sea familia `transporte` |
| `run_matching_pass(event_id)` | `matching.py` | Allocation global (Hungarian, scipy) sobre pares compatibles. Pares > 30 km solo con transporte puente. Devuelve `unreachable_need_ids` — la alerta de necesidades sin oferta alcanzable |
| `draft_outreach(match, contact_point, body)` | `outreach.py` | Draft idempotente. `automatic` SOLO vía `allows_automatic_outreach()` — fail-closed, no ampliar jamás |

Tests: `uv run manage.py test ayudagente.radar.tests` (11 verdes, sin red ni LLM).
Factories reutilizables en `ayudagente/radar/tests/factories.py`.

### Decisiones ya tomadas (no reabrir sin razón)

1. Distancia de candidatos en el matching pass = geodésica (rápida, en memoria); OSRM solo
   para enriquecer propuestas aceptadas y para itinerarios. No llamar OSRM por cada par.
2. Compatibilidad de recursos = familia completa (exacto > pariente; el score ya pondera).
3. `Match` con `destination=null` en el transporte = el solver decide el destino (caso
   "transportador sin ruta"). Ya funciona así.
4. `run_matching_pass` borra solo proposals stale en estado `proposed`. Congelados intactos.
5. Puntos siempre `Point(lon, lat, srid=4326)` — lon primero.

---

## Pendiente, en orden sugerido

### 1. Tools de frontera (para el agente cosechador)

- `get_frontier(event_id)` — serializar el scoreboard `FrontierNode` (~50 filas → dict
  compacto, ~2k tokens). Única lectura del agente de frontera.
- `create_harvest_job(event_id, admin_unit_id, platform, budget_usd, rationale)` —
  validar `event.can_spend()`, `rationale` obligatorio, `decided_by=agent`.

### 2. Registro como tools de LangGraph

Módulo nuevo `ayudagente/radar/agent/tools.py`: wrappers `@tool` (langchain) sobre los
servicios. Reglas:

- El wrapper solo traduce tipos (ids → objetos, dicts → texto) y trunca listas largas.
- Serializar para el LLM: nada de objetos Django crudos; dicts con ids + nombres + números.
- `find_requirements` para el LLM debe devolver máx ~10 filas con distancia en km.

### 3. Enriquecimiento OSRM de matches

Task (Celery) post-matching: para matches `proposed` con score alto, reemplazar
`distance_km` geodésico por km reales de `road_distance` y guardar geometría (¿campo JSON
nuevo o cache aparte? decidir — el front la necesita para pintar la ruta).

### 4. Itinerarios de transportador

Servicio `build_transporter_itinerary(via_transport_id)`: matches que comparten ese
requirement de transporte → paradas pickup/dropoff → `plan_trip_stops` → respuesta con
ETA y carga vs capacidad. Sin modelo nuevo hasta que el front pida persistirlo.

### 5. Gaps abiertos (decidir con el equipo)

| Gap | Opciones |
|---|---|
| Cierres de vía (derrumbes) | Tabla `RoadClosure` chica + excluir en OSRM con `exclude`, o solo nota en rationale. OSRM público no sabe de cierres de hoy |
| Canales directos (WhatsApp/radio entrantes) | `Platform` no tiene esos choices. Agregar + tratar cada mensaje como `Observation` (mantiene evidencia→interpretación→estado) |
| Geometría de rutas persistida | Campo en `Match` vs endpoint que la calcula al vuelo |
| Seeds demo | Management command con cadena de evidencia completa (checklist en la conversación de diseño: DIVIPOLA 4 deptos, árbol ~15 recursos, ~10 actores con contactos, ~15 requirements balanceados, ≥2 transportes, 1 necesidad inalcanzable, 1 saturable) |

---

## Entorno

```bash
uv sync
# DB local: imagen PostGIS+pgvector en puerto 5433 (ver README)
uv run manage.py migrate
uv run manage.py test ayudagente.radar.tests
```

- `.env`: DB local en 5433. Credenciales Azure comentadas — bloqueadas hasta permitir
  `POSTGIS, VECTOR, PG_TRGM, UNACCENT` en `azure.extensions` (portal → Parámetros del
  servidor).
- Hosts con GDAL duplicado: setear `GDAL_LIBRARY_PATH`/`GEOS_LIBRARY_PATH` en `.env`
  (ya soportado en `settings.py`).
- `OSRM_BASE_URL` (env) apunta al server público; para demo confiable, self-host con el
  extract de Colombia de Geofabrik.

## Invariantes al escribir tools nuevas

1. Nada entra a `Requirement` sin `Observation` detrás.
2. `Match` pasado `proposed` no se reescribe ni borra.
3. Outreach automático: solo lo que `allows_automatic_outreach()` permita. Fail-closed.
4. Toda decisión del agente que persiste lleva `rationale` en texto plano.
5. Tools de lectura no mutan; tools de escritura una sola responsabilidad.
