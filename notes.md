# Notas — Validación hipótesis Apify MCP (Hackathon CTW 2026)

## Objetivo

Validar que un agente puede descubrir, de forma autónoma y efectiva, información accionable
sobre un desastre natural (terremoto Colombia, 10 de agosto de 2026) scrapeando redes sociales:
personas que necesitan ayuda, lugares afectados, puntos de acopio, empresas y voluntarios que
ofrecen recursos — y conectar oferta con demanda.

Prueba **black box**: el único dato de partida es la fecha del evento.

---

## Setup

MCP remoto de Apify, scope `local` (en `~/.claude.json`, no toca el repo).

```bash
claude mcp add --transport http apify \
  "https://mcp.apify.com?tools=actors,docs,storage,runs" \
  --header "Authorization: Bearer $APIFY_TOKEN" \
  --scope local
```

- Endpoint: `https://mcp.apify.com` (streamable HTTP). SSE queda deprecado el 1 de abril de 2026.
- Auth por Bearer token o OAuth. Se usó token porque la sesión no puede completar el flujo OAuth.
- Requiere reiniciar Claude Code: los servidores MCP se cargan al arrancar.
- Rate limit: 30 req/s por usuario.
- Token de validación — rotar o borrar al terminar el hackathon.

---

## Arquitectura de Apify: dos capas

**Capa 1 — Store (los Actors).** ~6.000 programas de scraping, cada uno hace una cosa. Viven en
la nube de Apify, no se instalan. Cada Actor tiene su propio *input schema* y su propio precio.

**Capa 2 — MCP (el puente).** No expone scrapers, expone tools genéricas para operar el catálogo:

| Tool | Función |
|---|---|
| `search-actors` | descubrir Actors en el Store |
| `fetch-actor-details` | leer el input schema de un Actor |
| `call-actor` | ejecutarlo con un JSON de input → devuelve `datasetId` |
| `get-dataset-items` | leer los resultados |
| `get-actor-run` / `get-actor-log` | debug |

Los Actors se descubren en **runtime**. Esa es la propiedad que hace posible la prueba black box:
no hay que codear de antemano qué herramienta se usa.

---

## Costes

- Free tier Apify: **$5/mes** de crédito. Planes: Starter $29, Scale $199, Business $999.
- Scrapers de X, pago por resultado:
  - `apidojo/tweet-scraper` — $0.40 / 1K tweets
  - `kaitoeasyapi/twitter-x-data-tweet-scraper-pay-per-result-cheapest` — $0.18 / 1K
  - `api-ninja/x-twitter-advanced-search` — 50+ filtros (geo, tiempo, engagement)
  - `knowten/twitter-scraper-ultra` — $0.30 / 1K, con análisis de sentimiento
- Presupuesto del piloto: **$5** (todo el free tier).

---

## Diseño del agente (producción)

Orquestador autónomo de descubrimiento y priorización: parte de un evento, scrapea, guarda
entidades (posts, comentarios, perfiles, historias, hashtags, ubicaciones), puntúa relevancia /
credibilidad / actividad / cercanía al evento, y decide qué explorar después. Mantiene una
frontera de búsqueda priorizada y reasigna presupuesto dinámicamente.

Patrón: **focused crawler con frontera priorizada** + asignación tipo *multi-armed bandit*.

Stack previsto: deepagents (LangGraph) + MCP de Apify.

### MCP vs API directa — híbrido

- **MCP** para el bucle de descubrimiento: el agente necesita `search-actors` y
  `fetch-actor-details` en runtime para usar herramientas que nadie codeó de antemano.
- **`apify-client` directo** para lo ya decidido: cuando el agente resuelve "esta cuenta se
  scrapea cada 15 min", eso baja a una tarea determinista. Un LLM en el camino crítico de un
  cron que corre 500 veces al día es caro, lento y no determinista.

### Tres problemas de diseño

1. **El recurso escaso es el crédito, no el tiempo.** El score debe ser coste-beneficio, no solo
   relevancia. Sin coste en la función, el agente quema el presupuesto en las fuentes caras.
2. **Cold start.** Una cuenta nueva no tiene score. Si el agente solo explota lo ya puntuado, se
   encierra en una burbuja y nunca encuentra la vereda incomunicada de la que nadie hablaba hace
   20 minutos — el caso de mayor valor. Hace falta exploración forzada (ε-greedy o similar).
3. **Los runs de Apify son asíncronos.** `call-actor` vía MCP bloquea. Con una frontera de 200
   fuentes no escala: en producción hacen falta runs lanzados + webhooks.

---

## Riesgos de la hipótesis

1. **El cuello de botella es la verificación, no el scraping.** Sacar 20K posts es trivial. Un
   punto de acopio que ya cerró, o un "necesitamos agua" ya resuelto, es *peor que nada*: desvía
   recursos reales. Frescura y estado son el problema difícil.
2. **Geolocalización.** Casi ningún post trae geo. Hay que inferirla del texto
   ("vereda El Palmar, Líbano"). Aquí se va el tiempo.
3. **X puede no ser donde pasa esto en Colombia.** La coordinación real de desastres en LatAm
   vive en WhatsApp y grupos de Facebook. X da la capa mediática y de ONGs. Si se confirma,
   es el hallazgo más importante — cambia hacia dónde apunta el producto.

---

## Plan del piloto

**Presupuesto: $5. Alcance: X (Twitter) + Instagram.** Facebook se deja para después de validar.

**Fase 0 — Ground truth (gratis).** Fuentes primarias (SGC, USGS) para magnitud, epicentro y
municipios. Sin esto no hay vocabulario de búsqueda: hacen falta los nombres reales de veredas
y municipios, que es lo que la gente escribe.

**Fase 1 — Cosecha en dos ejes.**
- *Demanda*: "necesitamos", "no ha llegado ayuda", "estamos incomunicados", "se cayó",
  "damnificados", "urgente" + municipio.
- *Oferta*: "punto de acopio", "recibimos donaciones", "tengo camioneta", "llevo mercados",
  "voluntarios", "cuenta de recolección".

**Fase 2 — Estructuración.** Por item: tipo (oferta/demanda), categoría (agua, comida, medicina,
techo, transporte, rescate), ubicación, contacto, timestamp, confianza.

**Fase 3 — Matching** oferta ↔ demanda. Aquí está el producto.

### Criterio de éxito

Con ≤$5 de crédito, el piloto es **viable** si produce:

- ≥30 items estructurados y accionables (con contacto o ubicación concreta)
- ≥60% de precisión al verificarlos a mano
- ≥5 matches plausibles oferta ↔ demanda

Si el resultado son 500 tweets de medios diciendo "sismo de magnitud X" y cero personas pidiendo
ayuda concreta, la hipótesis se cae — y ese también es un resultado válido.

---

# RESULTADOS DEL PILOTO (15 de agosto de 2026)

**Veredicto: hipótesis validada. Gasto $0.39 de $5.**

## Ground truth (Fase 0, sin coste)

Terremoto de magnitud 7,4 el lunes 10 de agosto de 2026, 07:34 hora local (12:34 UTC).
Epicentro en San José del Palmar, Chocó (4.99 N, -76.29 O), profundidad ~103 km.
294+ muertos, 3.970+ heridos, 379+ desaparecidos, 47 réplicas, 21 municipios afectados.

Más golpeados: Pereira (66 muertos, toque de queda), Cali (edificio Vanessa, HUV parcialmente
colapsado), Quimbaya (450 casas destruidas, 800 familias damnificadas), Quibdó, Manizales,
Buenaventura. Aeropuertos suspendidos en Pereira, Manizales, Quibdó, Armenia, Cartago,
Buenaventura y Cali. Vías cerradas: Cali-Loboguerrero, Quimbaya-Montenegro.

## Ejecución

| Plataforma | Actor | Resultado | Coste |
|---|---|---|---|
| X | `kaitoeasyapi/twitter-x-data-tweet-scraper-...` | 400 tweets, 10 queries, 339 autores únicos | $0.10 |
| Instagram | `apify/instagram-hashtag-scraper` | 112 posts, 5 hashtags | $0.29 |

## Contra el criterio de éxito

| Umbral | Resultado |
|---|---|
| ≥30 items accionables | **77** (39 en X + 38 en IG) |
| ≥60% precisión | ~85% en la muestra revisada a mano |
| ≥5 matches oferta↔demanda | **8** |

### Matches encontrados

1. Pereira sector Gamma/La Villa, "gente sin comer" (15 ago) ↔ camión Barranquilla→Pereira
   saliendo el 16, punto de acopio Metro Plaza Local 101
2. Cali, Bueno Madrid Cra 5 norte con calle 34, 8+ familias desalojadas sin colchonetas ni
   carpas ↔ Ciudadela Petronio, Unidad Deportiva Alberto Galindo, Cali
3. Quibdó sector Cabí, familias esperando evaluación ↔ Palacio de los Deportes, Calle 63
   #54A-06 Bogotá, acopio exclusivo para Chocó hasta el 16 de agosto
4. Manizales, "se agotaron las ayudas" ↔ camión Medellín→Manizales para Villamaría y veredas
   La Nueva Primavera y San Julián; Coliseo Menor recibiendo donaciones
5. Puntos de acopio de Cali con excedente ↔ particular ofreciendo sus buses para redistribuir
   a municipios del norte del Valle
6. Pereira, cobijas y manos para remover escombros ↔ +57 310 4142969, Taller el Adorno, Pereira
7. Calima-El Darién ↔ camión saliendo el domingo 16, pide colchonetas y sábanas
8. Pereira, 2 fundaciones caninas destruidas piden material de construcción ↔ PMU Animal Cali
   y colectivos de rescate animal yendo al Chocó

## Hallazgos que cambian el diseño

**1. X e Instagram cubren ejes distintos, no son redundantes.**
X trae **oferta y demanda**; es la única fuente donde aparece el particular diciendo "en este
barrio hay gente sin comer". Instagram es casi **solo oferta**: comercios, fundaciones y marcas
anunciando puntos de acopio con dirección y horario. Hay que scrapear ambas, con queries
distintas. Facebook probablemente refuerce el eje demanda — vale la pena la siguiente ronda.

**2. Toda query necesita anclaje toponímico colombiano.**
Sin nombre de municipio, las búsquedas se contaminan con los terremotos de Venezuela, Perú,
Indonesia, Granada y Ecuador (19/400 en el sondeo). El término "punto de acopio" solo también
trae ruido de Perú. El anclaje geográfico no es un filtro opcional: es parte de la query.

**3. La geolocalización confirmada como el problema difícil.**
Solo 6 de 400 tweets (1,5%) traen campo `place`. Instagram va mucho mejor: 37 de 110 (34%)
traen `locationName`. Pero la ubicación útil casi siempre está en el **texto**
("sector Gamma y La Villa, por el estadio", "Cra 5 norte con calle 34") y hay que extraerla
y geocodificarla con NER.

**4. Frescura: la demanda sigue viva a los 5 días.**
El post de Pereira con "gente sin comer" es del 15 de agosto, cinco días después del sismo.
La ventana de utilidad es mucho más larga de lo que asumía el diseño inicial.

**5. Aparece un tipo de ruido no previsto: la disputa política.**
Parte sustancial del volumen es discusión sobre el manejo gubernamental de las ayudas, no
información operativa. El clasificador necesita una clase explícita de descarte para esto,
o inunda la frontera de búsqueda.

**6. El scraper de hashtags de Instagram no filtra por fecha.**
Devolvió posts de 2019. Hay que filtrar por `timestamp` en post-proceso.

## Rendimiento por query (X)

Funcionan: "punto de acopio" + municipio, "damnificados" + municipio, albergue/mercados.
Fallan: frases genéricas sin anclaje ("estamos incomunicados", "sin agua") y las de recursos
propios ("tengo camioneta") — falsos positivos casi puros. Los hashtags dan cobertura mediática,
no accionable.

---

# RONDA 2 — FACEBOOK (15 de agosto de 2026)

Actor: `scraper_one/facebook-posts-search`, $0.0025 por resultado. Tres queries, 100 posts,
$0.26. Ojo: `searchType` solo acepta `top` o `latest`, no `posts` — falla la validación.

**37 de 100 accionables: la mejor densidad de las tres plataformas.**

## Facebook resuelve el problema de la cola larga

Es el hallazgo de esta ronda. La query de veredas y corregimientos sacó municipios pequeños
que no aparecieron ni en X ni en Instagram ni en la cobertura de prensa:

- **Herveo, Tolima** — 80 familias afectadas, la alcaldesa pidiendo ayuda a nivel nacional.
  Tolima ni siquiera figuraba en el ground truth de departamentos afectados.
- **Resguardo Tocordo Balsalito, Litoral del San Juan, Chocó** — comunidades del pueblo
  Wounaan, familias sin vivienda. Zona rural indígena, invisible para la prensa.
- **Vereda Guaimía, corregimiento 8 de Buenaventura** — organización de mujeres
  afrocolombianas movilizándose.
- **Vijes (Valle)** — "apadrinado" por la alcaldía de Soacha.

Una de las fuentes lo dice explícitamente: *"varios municipios pequeños donde también hubo
emergencia de infraestructura no han tenido la relevancia pública debida para recibir las
ayudas"*. El sesgo mediático hacia las capitales es justamente el hueco que el producto llena.

## Facebook también trae los datos de pago

Cuentas Bancolombia, Nequi, Davivienda y llaves Bre-B aparecen literales en el texto, cosa que
casi no pasa en X. Y trae direcciones completas de puntos de acopio con horario.

## El modelo Soacha→Vijes

Municipios no afectados "apadrinando" municipios afectados: Soacha→Vijes,
Fusagasugá→Quibdó, Medellín→Pereira, Barranquilla→Pereira, Bogotá→Chocó.
Esto confirma el modelo de dos zonas: las ciudades no afectadas no son ruido, son
**nodos de oferta**. Hay que scrapearlas con queries distintas.

---

# COMPARATIVA FINAL DE PLATAFORMAS

| | X | Instagram | Facebook |
|---|---|---|---|
| Actor | `kaitoeasyapi/twitter-x-data-...` | `apify/instagram-hashtag-scraper` | `scraper_one/facebook-posts-search` |
| Coste unitario | $0.00025 | $0.0026 | $0.0025 |
| Muestra | 400 | 112 | 100 |
| Accionables | 39 (9,8%) | 38 (34%) | 37 (37%) |
| Coste por accionable | **$0.0026** | $0.0077 | $0.0070 |
| Geo estructurado | 1,5% (`place`) | 34% (`locationName`) | ninguno |
| Eje demanda | sí | casi nulo | **sí, el mejor** |
| Eje oferta | sí | **sí, el mejor** | sí |
| Cola larga rural | no | no | **sí** |
| Datos de pago | raro | a veces | **frecuente** |
| Filtro de fecha nativo | sí | **no** | sí |

**X** es el más barato por item accionable y el único con buen filtrado temporal y de volumen:
sirve para barrido amplio y para el eje demanda urbano.
**Instagram** es el directorio de puntos de acopio comerciales, con geo estructurado.
**Facebook** es el que encuentra a quien nadie está mirando. Es el más valioso para la misión
aunque no sea el más barato.

Gasto total tras tres plataformas: **$0.65 de $5**.

---

# RONDA 3 — TIKTOK (15 de agosto de 2026)

## Un actor caído, y cómo se detecta

`apidojo/tiktok-scraper` ($0.0003/post, el más barato del Store) devuelve `noResults` para
todo, incluido un control con la keyword `"podcast"` sin filtros. No es un problema de queries:
el actor está roto o bloqueado. **Un run que devuelve `SUCCEEDED` con `itemCount: 10` y un solo
campo `noResults` no es un run vacío legítimo — es un fallo silencioso.** El agente tiene que
detectar esa firma y hacer failover a otro actor, no interpretarlo como "no hay señal".

Failover: `clockworks/tiktok-scraper`, $0.0037 por video. 12× más caro pero funciona.

## Resultados

100 videos, **9 accionables en captions (9%)** — la densidad más baja de las cuatro plataformas.
Coste por accionable: **$0.041**, 16× peor que X. TikTok no sirve para barrido.

**Pero la calidad de lo que sí trae no tiene comparación.** Dos ejemplos:

> 📍Vereda Kilómetro 41 📲Número de contacto: 314 483 7303 Yensi Paola, persona que tiene
> contacto directo con las familias afectadas

> Se necesita ayudas en esta zona. En Cuba, Pereira. Persona encargada 300 2377012 Janeth
> (deben subir por Villa Ligia porque si suben por Leningrado hay gente no damnificada
> aprovechándose y quedándose con las cosas)

El segundo es inteligencia operativa que no existe en ninguna fuente oficial: no solo dónde
está la necesidad y quién la coordina, sino **por qué ruta entrar para que la ayuda no se
desvíe**. Eso no lo publica una alcaldía.

## Geolocalización: la granularidad más fina

`locationMeta.locationName` viene en el 19% de los videos, por debajo de Instagram (34%), pero
la granularidad es mucho mejor: `"Vereda Kilómetro 41"`, `"Cuchilla de los Castros, Cuba,
PEREIRA"`. Instagram da ciudad; TikTok da vereda y barrio. Para el eje demanda eso vale más
que la tasa de cobertura.

## Señal de emergencia encadenada

TikTok fue la única fuente que trajo los desastres secundarios: **inundaciones en Quibdó** en
la noche del 14 tras el terremoto, y un **vendaval en el corregimiento de Casacará (Agustín
Codazzi, Cesar)**. El agente debe tratar esto como disparador de re-evaluación del evento, no
como ruido: una zona ya golpeada que se inunda cambia por completo la prioridad.

## Comentarios: 227 analizados

Probada la hipótesis original de minar comentarios. Resultado matizado:

| Señal | Aciertos |
|---|---|
| Teléfono de contacto | 0 / 227 |
| Lugar fino (barrio, vereda, sector) | 5 / 227 |
| Necesidad expresada | 14 / 227 |
| Persona buscando cómo ayudar | 2 / 227 |

**Como fuente de items estructurados, los comentarios son malos** (~6% de densidad, muy por
debajo de FB o IG). Pero contienen algo que ninguna otra capa tiene:

> «hola tengo niños y los alimentos escasearon dónde puedo ir»
> «Para las personas que necesitan comida ¿dónde se puede ir?»
> «¿siguen necesitando voluntarios en el Coliseo Mayor???»
> «vayan para la zona norte de Quibdó, barrio La Victoria»
> «mi municipio que queda en el departamento del Chocó necesita ayuda»

Los comentarios son donde vive la **demanda insatisfecha de información**. Gente que necesita
ayuda y no sabe a dónde ir; gente que quiere ayudar y no sabe dónde. Son literalmente los
usuarios del producto, escribiendo su necesidad en texto plano. Y los locales nombran barrios
desatendidos que ninguna otra capa reportó.

**Conclusión: los comentarios no son capa de cosecha, son capa de descubrimiento.** Sirven para
alimentar la frontera con topónimos nuevos y para medir demanda de producto, no para llenar la
base de datos de items.

Nota operativa: los contactos migran a mensaje directo («comunicarse al interno»). El teléfono
casi nunca queda en el comentario público.

## Papel de TikTok

No es plataforma de barrido. Es **instrumento de precisión para el anillo T0**: pocas consultas,
alta frecuencia, solo sobre la zona de impacto, donde su granularidad hasta vereda y su acceso
a coordinadores locales de a pie justifica pagar 16× más por item.

Gasto total del piloto: **$1.32 de $5**.
