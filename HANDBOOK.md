# Frontera de Búsqueda

**Manual operativo** — cómo un agente autónomo encuentra, acota y persigue información
accionable durante un desastre, sin recorrer indiscriminadamente toda la red.

> Validado sobre el terremoto de Chocó (M7.4, 10 de agosto de 2026).
> 712 publicaciones en X, Instagram, Facebook y TikTok, más 227 comentarios, por $1.32 de
> crédito Apify. Hackathon CTW 2026 · v1 · 15 de agosto de 2026.

---

## La premisa: no puedes barrer todo

Toda la arquitectura existe para resolver una sola tensión: quieres cobertura hasta la vereda
más pequeña, pero el barrido exhaustivo cuesta más de lo que vale.

Colombia tiene más de 1.100 municipios. Un barrido nacional completo — cada municipio, cuatro
plataformas, 40 publicaciones cada uno — son unas 176.000 publicaciones por pasada. A precios
reales de Apify eso ronda los **$400 por pasada**. Cada 30 minutos, 48 pasadas al día:
**~$19.000 al día**. Insostenible, y además desperdiciado: el 95% de esos municipios no tiene
nada que decir sobre el evento.

Los tokens de LLM sí son baratos y ahí puedes ser generoso. Los créditos de scraping no. La
frontera priorizada no es una optimización elegante: es lo que hace la diferencia entre $150 y
$19.000 al día.

> **Principio rector.** La detección es barata y global. La cosecha es cara y focalizada.
> Nunca dejes que la cosecha haga el trabajo de la detección.

---

## Etapa 01 — Vigilancia global

*Cada 30 minutos, sobre feeds oficiales. Coste: cero.*

El job de vigilancia **no scrapea redes sociales**. Redes es donde vas después de saber que algo
pasó. Para enterarte existen feeds sismológicos y humanitarios públicos, estructurados y
gratuitos, que ya te dan magnitud, coordenadas, profundidad y una estimación de severidad.

| Fuente | Cobertura | Por qué |
|---|---|---|
| `GDACS` | Multi-amenaza | Sismos, ciclones, inundaciones, volcanes. Ya trae score de alerta verde/naranja/rojo. La mejor fuente única de arranque. |
| `USGS FDSN` | Sismos global | Catálogo canónico, sin API key, consultable por magnitud y ventana temporal. |
| `EMSC` | Sismos global | Tiene WebSocket en tiempo real: te empuja el evento en vez de que lo consultes. |
| `ReliefWeb` | Humanitaria | Reportes de agencias. Más lento, pero valida severidad y da nombres de organizaciones respondiendo. |
| Servicio nacional | País | SGC y UNGRD en Colombia. Siempre más preciso y más rápido que las fuentes globales para su territorio. |

El umbral de disparo es tuyo. Magnitud sola no basta: un M7.4 a 600 km de profundidad bajo el
océano no hace daño, y un M5.8 superficial bajo una ciudad sí. Dispara con una combinación de
**magnitud, profundidad y población en el radio de sacudida** — o delega en el nivel de alerta
de GDACS, que ya modela eso.

### La vigilancia no se apaga al detectar

Los desastres se encadenan. Cuatro días después del terremoto, Quibdó — ya golpeada — se inundó
por lluvias nocturnas, y hubo un vendaval en Casacará (Agustín Codazzi, Cesar). Lo detectó
TikTok, no los feeds sísmicos. Una zona ya afectada que recibe un segundo golpe cambia por
completo su prioridad: la vigilancia sigue corriendo sobre el evento activo y puede reescribir
los anillos a mitad de operación.

> ⚠️ **Verificar antes de cablear.** Los cuatro sondeos de scraping de este manual están medidos
> con datos reales. Estos feeds de detección van por conocimiento previo: confirma endpoints,
> formatos y límites de cuota antes de construir sobre ellos.

---

## Etapa 02 — Anclaje de verdad

*Se dispara una vez por evento. Construye el vocabulario de todo lo demás.*

Antes de tocar redes sociales, el agente arma un **Registro de Evento**: hora exacta, epicentro
en coordenadas, profundidad, magnitud, y — lo más importante — la **lista oficial de unidades
administrativas afectadas**.

Esto no es burocracia. Es el vocabulario de búsqueda. Sin los nombres propios reales de
municipios, veredas y corregimientos, tus queries no tienen dónde anclarse y traen basura. En el
piloto el ground truth salió de prensa y fuentes primarias en minutos y sin coste, y produjo la
lista que hizo funcionar todo lo demás: Pereira, Quimbaya, Quibdó, Cali, Manizales,
Buenaventura, San José del Palmar, Calima-El Darién.

### Qué guarda el registro

- **Núcleo físico** — epicentro, hora, magnitud, profundidad, réplicas.
- **Unidades afectadas** — códigos administrativos oficiales, no cadenas de texto. En Colombia,
  DIVIPOLA del DANE.
- **Infraestructura caída** — aeropuertos, vías, hospitales. Las vías cerradas predicen dónde
  habrá comunidades incomunicadas.
- **Léxico del evento** — cómo lo llama la gente. Hashtags, apodos, el nombre del edificio que
  colapsó.
- **Respondedores oficiales** — cuentas de alcaldías, defensa civil, cruz roja. Semillas de alta
  credibilidad para la frontera.

---

## Etapa 03 — Alcance geográfico

*Dos zonas, no una. El error más caro es tratar el país como un solo territorio.*

Un municipio no afectado no es ruido. Barranquilla no sufrió el terremoto y aun así apareció
organizando un camión de donaciones hacia Pereira. Fusagasugá mandó insumos médicos a Quibdó.
Soacha «apadrinó» a Vijes. Las ciudades intactas son **nodos de oferta**, y hay que buscarlas —
con otras queries.

| | **Zona de impacto** → eje demanda | **Zona de soporte** → eje oferta |
|---|---|---|
| **Qué contiene** | Municipios en la lista oficial de afectados, más los anillos de distancia al epicentro | El resto del país, priorizando centros urbanos y municipios vecinos con acceso vial |
| **Qué se busca** | Necesidades sin cubrir · comunidades incomunicadas · albergues desbordados · personas desaparecidas · faltantes concretos (agua, medicinas, carpas) | Puntos de acopio con dirección y horario · vehículos y logística ofrecidos · campañas de recaudo y cuentas · voluntarios y brigadas · empresas donando en especie |

La expansión geográfica se hace sobre la división administrativa oficial del país, no sobre lo
que el modelo recuerde. Cargas el catálogo completo de municipios una vez, y el agente itera
sobre entidades reales con código, coordenadas y jerarquía
*departamento → municipio → corregimiento → vereda*. Así llegas a la cola larga sin alucinar
topónimos.

> **Anillos, no lista plana.** Ordena los municipios de la zona de impacto por distancia al
> epicentro y cruza con densidad de población. Eso te da los anillos de cadencia de la etapa 06,
> y además predice dónde *debería* haber señal aunque todavía no la hayas visto — que es
> exactamente donde vale la pena gastar exploración.

---

## Etapa 04 — Síntesis de queries

*Una query por combinación de plataforma × zona × eje. Nunca una query genérica.*

### Regla del anclaje toponímico

**Toda query lleva un topónimo colombiano.** Es la regla que más impacto tuvo en el piloto. Sin
anclaje, las búsquedas se contaminaron con los terremotos de Venezuela, Perú, Indonesia, Ecuador
y Granada; hasta un negocio de Perú apareció por decir «punto de acopio». La geografía no es un
filtro que aplicas después: es parte de la query.

**Eje demanda, zona de impacto**

```
// (síntoma) × (topónimo) × (ventana) × (idioma)
("no ha llegado ayuda" OR "estamos incomunicados" OR damnificados)
AND (Pereira OR Quimbaya OR Quibdó OR "San José del Palmar")
AND lang:es
AND since:2026-08-10_12:00:00_UTC until:2026-08-16_00:00:00_UTC
```

**Eje oferta, zona de soporte**

```
// (recurso) × (topónimo no afectado) × (ventana)
("punto de acopio" OR "recibimos donaciones" OR "sale un camión")
AND (Bogotá OR Medellín OR Barranquilla OR Bucaramanga)
AND (terremoto OR sismo OR damnificados)
AND lang:es
```

**Cola larga rural, solo Facebook**

```
// vocabulario administrativo rural, sin topónimo específico:
// es el propio término el que ancla en Colombia
vereda corregimiento resguardo incomunicada sismo ayuda humanitaria
```

### Qué funcionó y qué no

| Patrón | Veredicto | Por qué |
|---|---|---|
| `"punto de acopio"` + municipio | **Excelente** | Dirección, horario y qué se recibe, casi siempre en el mismo post. |
| `vereda / corregimiento / resguardo` | **Excelente** | La única que llegó a la cola larga rural. Encontró Herveo y el resguardo Wounaan. |
| `damnificados` + municipio | Bueno | Mezcla prensa con testimonios directos, pero los directos traen ubicación fina. |
| `albergue / mercados / carpas` | Bueno | Buen puente entre los dos ejes: quien menciona faltantes suele estar en el terreno. |
| `"estamos incomunicados"` sin municipio | Malo | Contaminación masiva con otros países. Sin anclaje no sirve. |
| `"tengo camioneta"`, `"presto mi"` | Inservible | Falsos positivos casi puros. La gente usa esas frases para presumir, no para ofrecer. |
| Hashtags del evento | Flojo | Alcance mediático y político. Volumen alto, accionabilidad baja. |

La lección sobre el eje de recursos propios es la más útil: **no busques la capacidad, busca la
convocatoria**. Quien presta su camión lo anuncia diciendo «sale un camión mañana hacia Pereira»,
no «tengo camioneta».

---

## Etapa 05 — Cosecha y estructuración

*Cuatro plataformas, cuatro papeles distintos. No son intercambiables.*

| Plataforma | Muestra | Accionables | $ / accionable | Geo | Papel |
|---|---:|---:|---:|---:|---|
| X | 400 | 39 · 9.8% | **$0.0026** | 1.5% | Barrido amplio y barato. Demanda urbana. |
| Instagram | 112 | 38 · 34% | $0.0077 | **34% ciudad** | Directorio de acopio comercial. Geo estructurado. |
| Facebook | 100 | **37 · 37%** | $0.0070 | — | Cola larga rural. Datos de pago. Demanda real. |
| TikTok | 100 | 9 · 9% | $0.041 | 19% vereda | Precisión en zona cero. Coordinadores de a pie. |
| Comentarios | 227 | ~6% | — | — | Descubrimiento, no cosecha. |

**Actors usados**

| Plataforma | Actor | Precio |
|---|---|---|
| X | `kaitoeasyapi/twitter-x-data-tweet-scraper-pay-per-result-cheapest` | $0.00025 / tweet |
| Instagram | `apify/instagram-hashtag-scraper` | $0.0026 / post |
| Facebook | `scraper_one/facebook-posts-search` | $0.0025 / post |
| TikTok | `clockworks/tiktok-scraper` | $0.0037 / video |
| Comentarios | `clockworks/tiktok-comments-scraper` | $0.00125 / comentario |

**X** es el más barato por item útil y el único con buen control de volumen y ventana temporal:
úsalo para barrer. **Instagram** es casi exclusivamente oferta — comercios y fundaciones
anunciando acopio — pero trae ubicación estructurada a nivel de ciudad. **Facebook** es el que
encuentra a quien nadie está mirando: los municipios pequeños que no salen en prensa, y con
frecuencia trae cuentas bancarias y direcciones completas.

### TikTok: caro para barrer, insustituible en zona cero

16 veces más caro por item útil, así que no sirve para barrer — pero su geolocalización llega a
vereda y barrio, no a ciudad, y sus autores son coordinadores de a pie. Es la única plataforma
que produjo inteligencia operativa de este tipo:

> *«Se necesita ayuda en esta zona. En Cuba, Pereira. Persona encargada 300 2377012 Janeth
> (deben subir por Villa Ligia porque si suben por Leningrado hay gente no damnificada
> aprovechándose y quedándose con las cosas)»*

Dónde está la necesidad, quién la coordina, su teléfono, y por qué ruta entrar para que la ayuda
no se desvíe. Ninguna fuente oficial publica lo último.

Úsalo como **instrumento de precisión sobre el anillo T0**: pocas consultas, alta frecuencia,
solo zona de impacto. Ahí su granularidad justifica el precio.

### Los comentarios son capa de descubrimiento, no de cosecha

Minar comentarios da mala densidad — de 227 analizados, cero teléfonos y solo 5 con ubicación
fina. Como fuente de items estructurados no compite con Facebook. Pero contienen algo que
ninguna otra capa tiene:

| **Demanda sin atender** | **Oferta bloqueada** |
|---|---|
| «hola tengo niños y los alimentos escasearon dónde puedo ir» | «¿siguen necesitando voluntarios en el Coliseo Mayor???» |
| «¿para las personas que necesitan comida dónde se puede ir?» | «¿necesitan personas para apoyo en logística?» |
| «vayan para la zona norte de Quibdó, barrio La Victoria» | «vamos a llevar hidratación hoy, comunicarse al interno» |

Los comentarios son donde vive la **demanda insatisfecha de información**: gente que necesita
ayuda y no sabe a dónde ir, gente que quiere ayudar y no sabe dónde. Son los usuarios del
producto escribiendo su necesidad en texto plano. Y los locales nombran barrios desatendidos que
ninguna otra capa reportó. Úsalos para **alimentar la frontera con topónimos nuevos**, no para
llenar la base de datos.

Detalle operativo: el contacto casi siempre migra a mensaje directo («comunicarse al interno»).
El teléfono rara vez queda en el comentario público.

### Extracción por item

| Campo | Fuente | Nota |
|---|---|---|
| `eje` | Clasificador | demanda · oferta · informativo · **descarte** |
| `categoria` | Clasificador | agua, comida, medicina, techo, transporte, rescate, animales, salud mental |
| `ubicacion` | NER + geocoding | Casi siempre en el texto libre, no en metadatos |
| `contacto` | Regex | Teléfono, Nequi, Bancolombia, llave Bre-B, dirección |
| `ventana` | Extracción | «hasta el 16 de agosto», «sale mañana» — caduca el item |
| `estado` | Derivado | activo · cumplido · caducado · no verificado |

> ⚠️ **Clase de descarte obligatoria.** Buena parte del volumen es discusión política sobre el
> manejo gubernamental de las ayudas. Sin una clase explícita de descarte para eso, inunda la
> frontera: alto engagement, cero accionabilidad, y el scoring la premia por error.

La geolocalización es el trabajo difícil y hay que asumirlo desde el diseño. Solo el 1.5% de los
tweets trae campo de ubicación. La ubicación útil casi siempre está en el texto — *«sector Gamma
y La Villa, por el estadio»*, *«Cra 5 norte con calle 34»* — y hay que extraerla con NER y
geocodificarla contra el catálogo administrativo.

---

## Etapa 06 — La frontera

*Dónde volver a gastar, cada cuánto, y cuándo dejar de gastar.*

Cada fuente descubierta — una cuenta, un hashtag, un municipio, una query — entra a la frontera
con una puntuación que se actualiza en cada cosecha. La puntuación decide la cadencia.

```
score = (rendimiento × credibilidad × proximidad × frescura) ÷ coste
```

| Factor | Definición |
|---|---|
| `rendimiento` | Items accionables por cada 100 recolectados en las últimas N pasadas. |
| `credibilidad` | Alta para alcaldías, defensa civil y medios locales; media para cuentas con historial verificado; baja para cuentas nuevas o sin historial. |
| `proximidad` | Distancia al epicentro, o pertenencia a la lista oficial de afectados. |
| `frescura` | Decaimiento desde la última publicación útil. Una fuente que lleva 6 horas callada baja sola. |
| `coste` | Precio real por pasada en esa plataforma. **Sin este divisor, el agente quema el presupuesto en las fuentes caras.** |

### Cadencia por anillos

| Anillo | Qué contiene | Municipios | Cadencia | $/día (X) |
|---|---|---:|---:|---:|
| T0 | Epicentro y municipios críticos | ~20 | 15 min | ~$19 |
| T1 | Departamentos afectados | ~100 | 1 h | ~$24 |
| T2 | Nodos de oferta urbanos | ~30 | 3 h | ~$2 |
| T3 | Cola larga nacional | ~950 | 24 h | ~$5 |

Unos **$50 al día en X** para el evento vivo, contra los ~$19.000 del barrido ciego. La mezcla de
plataformas sigue el mismo criterio de coste-beneficio: Facebook sobre T1 y T3 por la cola larga
rural, Instagram sobre T2 por el directorio de acopio, TikTok solo sobre T0 donde su precio se
justifica. Un evento activo se sostiene en el orden de **$100–150 diarios**.

### Dos reglas que evitan que la frontera se cierre

- **Exploración forzada.** Reserva un porcentaje fijo del presupuesto — 10% funciona — para
  fuentes sin historial. Sin esto el agente se encierra en lo que ya conoce y nunca encuentra la
  vereda de la que nadie hablaba hace 20 minutos, que es precisamente el caso de mayor valor.
- **Deduplicación contra lo visto, no contra lo aceptado.** Guarda todo lo que ya evaluaste,
  incluido lo que descartaste. Si deduplicas solo contra lo confirmado, lo rechazado reaparece en
  cada ronda y el bucle nunca converge.

---

## Desambiguación de eventos

*Cómo el agente no mezcla dos terremotos.*

Durante el piloto había al menos cuatro eventos sísmicos compitiendo en el mismo espacio de
búsqueda en español: Colombia, Venezuela, Indonesia y Granada, más un histórico de Perú. El 5% de
la muestra llegó contaminado. Tres defensas, en orden de eficacia:

1. **Anclaje toponímico en la query.** Barato y resuelve la mayoría. El topónimo va dentro de la
   búsqueda, no en el filtro posterior.
2. **Ventana temporal estricta.** Acotada a la hora exacta del evento en el registro. Elimina el
   histórico y la mayoría de los aniversarios.
3. **Verificación contra el registro de evento.** Para lo que sobrevive: el item debe ser
   consistente con magnitud, fecha y geografía del evento activo. Es la única que atrapa la
   mención cruzada — un post colombiano hablando del sismo de Venezuela.

Si corres varios eventos a la vez, cada uno tiene su propio registro, su propia frontera y su
propio presupuesto. No comparten estado más allá del catálogo geográfico.

---

## Modos de fallo

*Lo que va a romperse, en orden de probabilidad.*

1. **Información caducada presentada como viva.** El fallo más dañino, porque desvía recursos
   reales. Un punto de acopio que ya cerró es peor que ningún dato. Todo item necesita ventana de
   validez y estado; sin eso, el producto miente con confianza.
2. **Geolocalización silenciosamente incorrecta.** «La Villa» existe en varios municipios. Cuando
   el geocoding no es concluyente, marca el item como ubicación aproximada en vez de inventar
   coordenadas.
3. **Colapso de la frontera.** Sin exploración forzada, el agente converge a media docena de
   cuentas de alto engagement y deja de descubrir. Se detecta porque la tasa de fuentes nuevas por
   hora cae a cero.
4. **Actor caído que reporta éxito.** El más traicionero. El scraper de TikTok más barato del
   catálogo (`apidojo/tiktok-scraper`) devolvió `SUCCEEDED` con diez items de un solo campo
   `noResults` — para todas las queries, incluido un control con una palabra genérica y sin
   filtros. Un run así *parece* «no hay señal en esa zona» y el scoring castiga a un municipio que
   sí tenía señal. Diagnostícalo con una **query de control** periódica cuyo resultado conoces, y
   ante esa firma haz failover a otro Actor de la misma plataforma. Ten siempre un suplente
   identificado.
5. **Deriva del esquema de entrada.** Los Actors cambian su schema sin aviso. En este mismo
   piloto, `searchType` de Facebook rechazó un valor razonable (`"posts"`; solo acepta `top` o
   `latest`). El agente debe leer el schema, y ante error de validación reintentar leyendo los
   valores permitidos — no morir.
6. **Fuga de presupuesto por reintentos.** Un Actor que falla a medias puede cobrar igual. Hay que
   topar el gasto por evento y por pasada, con corte duro.
7. **Amplificación de desinformación.** Una alerta falsa de personas atrapadas ya circuló en
   Pereira durante este evento. Todo item de rescate necesita corroboración independiente antes de
   subir de prioridad.

---

## Ciclo completo

```
cada 30 min  vigilancia global sobre feeds oficiales        $0
             └─ ¿supera umbral de severidad?
                   │
una vez      ├─ anclar ground truth → Registro de Evento   $0
una vez      ├─ resolver alcance geográfico
             │     ├─ zona de impacto  → eje demanda
             │     └─ zona de soporte  → eje oferta
             │
por anillo   └─ bucle de cosecha
                   ├─ sintetizar queries (plataforma × zona × eje)
                   ├─ ejecutar Actors, deduplicar contra lo visto
                   ├─ extraer, clasificar, geocodificar
                   ├─ emparejar oferta ↔ demanda
                   ├─ repuntuar frontera  (90% explotar / 10% explorar)
                   └─ reasignar cadencia por anillo
                         │
                         └─ ¿evento inactivo N horas? → archivar
```

---

## Arquitectura de integración

**MCP para explorar, cliente directo para ejecutar.** El bucle de descubrimiento sí necesita MCP:
`search-actors` y `fetch-actor-details` en runtime le permiten al agente usar herramientas que
nadie codeó de antemano. Pero cuando el agente decide «esta cuenta se scrapea cada 15 minutos»,
eso baja a una tarea determinista con `apify-client`. Un LLM en el camino crítico de un cron que
corre 500 veces al día es caro, lento y no determinista.

**Los runs de Apify son asíncronos.** `call-actor` vía MCP bloquea esperando. Con una frontera de
200 fuentes no escala: en producción hacen falta runs lanzados con `waitSecs: 0` más webhooks.

---

*Cifras de plataforma, densidades y precios medidos empíricamente el 15 de agosto de 2026 sobre
el terremoto de Chocó (M7.4, 10 de agosto): 712 publicaciones en X, Instagram, Facebook y TikTok,
más 227 comentarios, por $1.32 de crédito Apify. Las fuentes de detección global de la etapa 01
son recomendaciones sin verificar en esta ronda.*
