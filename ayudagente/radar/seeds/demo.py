"""
Synthetic scenario for exercising the services and the graph API end to end.

Ported from a data migration into a seed so it can be reloaded and cleared at will. Seed data
in a migration runs once and can only be refreshed by unapplying it, and it puts 590 lines of
content into a ledger that should only record how the schema changed.

The evidence invariant holds even here: every requirement is backed by an Observation created
through a manual HarvestJob.

Geography:
- IMPACT zone (reports needs): Pereira, Dosquebradas, Quibdó, Cali and Manizales with 20
  barrios each, plus towns of Risaralda, Quindío and Valle.
- SUPPORT zone (offers help): Bogotá, Medellín, Bucaramanga, Barranquilla, Ibagué, Neiva.
- 1 in 4 rows flips direction so both exist everywhere.

Deliberate coverage:
- a dog-food offer that must match a generic food need through the resource tree
- two transport offers, one with a fixed destination and one for the solver to place
- one need with no reachable offer at all, so the unreachable-demand alert always fires
- one saturated requirement, never proposed again

Note:
    City centers are real coordinates; barrio points are a deterministic golden-angle spiral
    0.5-4 km around them, which looks like urban scatter without geocoding 200 barrios.
"""

import math
from datetime import timedelta

from django.contrib.gis.geos import Point
from django.utils import timezone

from ayudagente.radar.models import (
    Actor,
    AdminUnit,
    ContactPoint,
    Event,
    Extraction,
    FrontierNode,
    HarvestJob,
    Location,
    Observation,
    Requirement,
    ResourceType,
)
from ayudagente.radar.seeds.base import Counts, Seed, Writer

DEMO_EVENT_NAME = "Sismo demo Eje Cafetero"

# lon, lat — real city centers
CENTERS = {
    "pereira": (-75.6961, 4.8133),
    "dosquebradas": (-75.6727, 4.8318),
    "quibdo": (-76.6611, 5.6947),
    "cali": (-76.5320, 3.4516),
    "manizales": (-75.5138, 5.0703),
    "santa_rosa": (-75.6210, 4.8675),
    "la_virginia": (-75.8828, 4.8997),
    "marsella": (-75.7387, 4.9367),
    "armenia": (-75.6811, 4.5339),
    "salento": (-75.5709, 4.6372),
    "filandia": (-75.6584, 4.6742),
    "cartago": (-75.9117, 4.7464),
    "tulua": (-76.1954, 4.0847),
    "buga": (-76.2977, 3.9010),
    "palmira": (-76.3036, 3.5394),
    "yumbo": (-76.4950, 3.5828),
    "bogota": (-74.0721, 4.7110),
    "medellin": (-75.5812, 6.2442),
    "bucaramanga": (-73.1227, 7.1193),
    "barranquilla": (-74.7813, 10.9685),
    "ibague": (-75.2322, 4.4389),
    "neiva": (-75.2819, 2.9273),
}

# Curated fine-grained points inside Pereira/DQ/Quibdó/Cali/Manizales
POINTS = {
    "barrio_cuba": (-75.7360, 4.7996),
    "hospital_sj": (-75.6893, 4.8163),
    "cruz_roja_sede": (-75.6980, 4.8110),
    "utp": (-75.6902, 4.7924),
    "el_poblado_pei": (-75.7263, 4.8129),
    "terminal_pereira": (-75.6994, 4.8043),
    "vereda_florida": (-75.6103, 4.7666),
    "dq_la_popa": (-75.6664, 4.8296),
    "dq_santa_monica": (-75.6668, 4.8455),
    "quibdo_coliseo": (-76.6580, 5.6923),
    "cali_base": (-76.5006, 3.4626),
    "mzl_chipre": (-75.5310, 5.0730),
}

# (code, name, level, parent_code, center_key, population)
ADMIN_UNITS = [
    ("66", "Risaralda", "admin_1", None, "pereira", 961055),
    ("27", "Chocó", "admin_1", None, "quibdo", 544764),
    ("76", "Valle del Cauca", "admin_1", None, "cali", 4589594),
    ("17", "Caldas", "admin_1", None, "manizales", 1018453),
    ("63", "Quindío", "admin_1", None, "armenia", 555401),
    ("11", "Bogotá D.C.", "admin_1", None, "bogota", 7968095),
    ("05", "Antioquia", "admin_1", None, "medellin", 6994792),
    ("68", "Santander", "admin_1", None, "bucaramanga", 2280908),
    ("08", "Atlántico", "admin_1", None, "barranquilla", 2835509),
    ("73", "Tolima", "admin_1", None, "ibague", 1339998),
    ("41", "Huila", "admin_1", None, "neiva", 1122622),
    ("66001", "Pereira", "admin_2", "66", "pereira", 481128),
    ("66170", "Dosquebradas", "admin_2", "66", "dosquebradas", 214731),
    ("66682", "Santa Rosa de Cabal", "admin_2", "66", "santa_rosa", 73028),
    ("66400", "La Virginia", "admin_2", "66", "la_virginia", 32355),
    ("66440", "Marsella", "admin_2", "66", "marsella", 23470),
    ("27001", "Quibdó", "admin_2", "27", "quibdo", 130825),
    ("76001", "Cali", "admin_2", "76", "cali", 2264748),
    ("76147", "Cartago", "admin_2", "76", "cartago", 134972),
    ("76834", "Tuluá", "admin_2", "76", "tulua", 218812),
    ("76111", "Buga", "admin_2", "76", "buga", 12970),
    ("76520", "Palmira", "admin_2", "76", "palmira", 354285),
    ("76892", "Yumbo", "admin_2", "76", "yumbo", 139558),
    ("17001", "Manizales", "admin_2", "17", "manizales", 446459),
    ("63001", "Armenia", "admin_2", "63", "armenia", 301226),
    ("63690", "Salento", "admin_2", "63", "salento", 7247),
    ("63272", "Filandia", "admin_2", "63", "filandia", 13571),
    ("11001", "Bogotá", "admin_2", "11", "bogota", 7968095),
    ("05001", "Medellín", "admin_2", "05", "medellin", 2612958),
    ("68001", "Bucaramanga", "admin_2", "68", "bucaramanga", 613400),
    ("08001", "Barranquilla", "admin_2", "08", "barranquilla", 1326588),
    ("73001", "Ibagué", "admin_2", "73", "ibague", 541101),
    ("41001", "Neiva", "admin_2", "41", "neiva", 366634),
]


ACTORS = [
    # (slug, name, kind, point_key, admin_code, credibility)
    ("jac_cuba", "JAC Barrio Cuba", "community", "barrio_cuba", "66001", 0.7),
    (
        "coliseo_quibdo",
        "Coliseo Mayor de Quibdó (La Yesquita)",
        "collection_center",
        "quibdo_coliseo",
        "27001",
        0.85,
    ),
    ("vereda_florida", "Vereda La Florida", "community", "vereda_florida", "66001", 0.6),
    ("hospital_sj", "Hospital San Jorge", "public_entity", "hospital_sj", "66001", 0.95),
    ("familia_dq", "Familia Ramírez (La Popa)", "person", "dq_la_popa", "66170", 0.5),
    (
        "cruz_roja",
        "Cruz Roja Risaralda (Circunvalar)",
        "nonprofit",
        "cruz_roja_sede",
        "66001",
        0.95,
    ),
    ("acopio_utp", "Centro de Acopio UTP (Álamos)", "collection_center", "utp", "66001", 0.9),
    ("bodega_cali", "Distribuidora El Valle (La Base)", "company", "cali_base", "76001", 0.75),
    (
        "vol_manizales",
        "Voluntarios Manizales (Chipre)",
        "volunteer_group",
        "mzl_chipre",
        "17001",
        0.65,
    ),
    ("andres", "Andrés (camioneta, El Poblado)", "person", "el_poblado_pei", "66001", 0.55),
    (
        "transcafe",
        "Transportes del Café SAS (Terminal)",
        "company",
        "terminal_pereira",
        "66001",
        0.85,
    ),
    ("dono_mascotas", "Vecina Santa Mónica", "person", "dq_santa_monica", "66170", 0.5),
]

CONTACTS = [
    (
        "cruz_roja",
        "email",
        "contacto@cruzrojarisaralda.org",
        "contacto@cruzrojarisaralda.org",
        0.92,
    ),
    ("acopio_utp", "email", "acopio@utp.edu.co", "acopio@utp.edu.co", 0.9),
    ("transcafe", "email", "operaciones@transcafe.co", "operaciones@transcafe.co", 0.88),
    ("transcafe", "whatsapp", "+573104445566", "310 444 5566", 0.8),
    ("andres", "whatsapp", "+573001112233", "300 111 2233", 0.85),
    ("familia_dq", "whatsapp", "+573207778899", "320 777 8899", 0.6),
    ("coliseo_quibdo", "phone", "+576724567890", "(672) 456 7890", 0.7),
]

REQUIREMENTS = [
    # slug, actor, direction, resource, qty, covered, unit, urgency, origin, destination, text
    (
        "req_agua_quibdo",
        "coliseo_quibdo",
        "needs",
        "water",
        5000,
        0,
        "litros",
        "critical",
        "quibdo_coliseo",
        "27001",
        None,
        None,
        "Necesitamos agua potable urgente en el Coliseo Mayor, llegaron 400 familias",
    ),
    (
        "req_meds_hospital",
        "hospital_sj",
        "needs",
        "medicine",
        200,
        0,
        "kits",
        "critical",
        "hospital_sj",
        "66001",
        None,
        None,
        "Hospital San Jorge requiere kits de primeros auxilios e insulina",
    ),
    (
        "req_carpas_vereda",
        "vereda_florida",
        "needs",
        "tents",
        50,
        0,
        "unidades",
        "high",
        "vereda_florida",
        "66001",
        None,
        None,
        "En la vereda La Florida 50 familias durmiendo a la intemperie",
    ),
    (
        "req_alimentos_cuba",
        "jac_cuba",
        "needs",
        "food",
        300,
        0,
        "kg",
        "high",
        "barrio_cuba",
        "66001",
        None,
        None,
        "Barrio Cuba necesita mercados, olla comunitaria para 200 personas",
    ),
    (
        "req_voluntarios_cuba",
        "jac_cuba",
        "needs",
        "volunteers",
        20,
        18,
        "personas",
        "medium",
        "barrio_cuba",
        "66001",
        None,
        None,
        "Faltan manos para remover escombros en Cuba",
    ),
    (
        "req_colchonetas_coliseo",
        "coliseo_quibdo",
        "needs",
        "bedding",
        30,
        30,
        "unidades",
        "high",
        "quibdo_coliseo",
        "27001",
        None,
        None,
        "Colchonetas para el coliseo (YA CUBIERTO según última publicación)",
    ),
    (
        "req_plantas_quibdo",
        "coliseo_quibdo",
        "needs",
        "generators",
        2,
        0,
        "unidades",
        "high",
        "quibdo_coliseo",
        "27001",
        None,
        None,
        "Sin luz en el coliseo, se necesitan plantas eléctricas",
    ),
    (
        "off_agua_cali",
        "bodega_cali",
        "offers",
        "water",
        12000,
        0,
        "litros",
        "medium",
        "cali_base",
        "76001",
        None,
        None,
        "Tenemos 12000 litros de agua embotellada listos para despachar desde Cali",
    ),
    (
        "off_alimentos_utp",
        "acopio_utp",
        "offers",
        "food",
        800,
        0,
        "kg",
        "medium",
        "utp",
        "66001",
        None,
        None,
        "Acopio UTP con 800kg de mercados clasificados",
    ),
    (
        "off_mascotas_dq",
        "dono_mascotas",
        "offers",
        "pet_food",
        50,
        0,
        "kg",
        "low",
        "dq_santa_monica",
        "66170",
        None,
        None,
        "Tengo 50kg de comida para perros, ¿dónde la llevo?",
    ),
    (
        "off_cobijas_cr",
        "cruz_roja",
        "offers",
        "bedding",
        200,
        0,
        "unidades",
        "medium",
        "cruz_roja_sede",
        "66001",
        None,
        None,
        "Cruz Roja dispone de 200 colchonetas y cobijas",
    ),
    (
        "off_voluntarios_mzl",
        "vol_manizales",
        "offers",
        "volunteers",
        15,
        0,
        "personas",
        "medium",
        "mzl_chipre",
        "17001",
        None,
        None,
        "Grupo de 15 voluntarios disponibles fin de semana",
    ),
    (
        "off_transcafe",
        "transcafe",
        "offers",
        "transport",
        3,
        0,
        "vehículos",
        "high",
        "terminal_pereira",
        "66001",
        "quibdo_coliseo",
        "27001",
        "Tres camiones de 5t Pereira-Quibdó, salida diaria",
    ),
    (
        "off_andres",
        "andres",
        "offers",
        "transport",
        1,
        0,
        "vehículos",
        "medium",
        "el_poblado_pei",
        "66001",
        None,
        None,
        "Tengo camioneta, puedo mover cosas donde se necesite",
    ),
]

# admin_code → (center_key, dominant direction, barrios). 1 in 4 rows flips direction
ZONES = {
    # --- IMPACT: main cities, 20 barrios each
    "66001": (
        "pereira",
        "needs",
        [
            "Centro",
            "Cuba",
            "Álamos",
            "El Poblado",
            "Villa Santana",
            "Kennedy",
            "El Jardín",
            "Providencia",
            "Boston",
            "San Nicolás",
            "Corocito",
            "El Vergel",
            "Los Rosales",
            "Pinares",
            "Circunvalar",
            "Ciudad Jardín",
            "Nacederos",
            "Belmonte",
            "San Joaquín",
            "La Aurora",
        ],
    ),
    "66170": (
        "dosquebradas",
        "needs",
        [
            "La Popa",
            "Santa Mónica",
            "Frailes",
            "La Badea",
            "Santa Teresita",
            "Guadalupe",
            "El Japón",
            "Los Molinos",
            "La Pradera",
            "Bosques de la Acuarela",
            "Santiago Londoño",
            "La Capilla",
            "Buenos Aires",
            "Playa Rica",
            "La Romelia",
            "Villa Fanny",
            "Camilo Torres",
            "Aguazul",
            "La Esperanza",
            "El Balso",
        ],
    ),
    "27001": (
        "quibdo",
        "needs",
        [
            "La Yesquita",
            "Yescagrande",
            "Kennedy",
            "Niño Jesús",
            "Roma",
            "Alameda Reyes",
            "Tomás Pérez",
            "San Vicente",
            "Cristo Rey",
            "Las Mercedes",
            "El Caraño",
            "Medrano",
            "Buenos Aires",
            "Samper",
            "Pablo Sexto",
            "La Aurora",
            "Palenque",
            "San Judas",
            "Monserrate",
            "Las Margaritas",
        ],
    ),
    "76001": (
        "cali",
        "needs",
        [
            "San Fernando",
            "Granada",
            "San Antonio",
            "El Peñón",
            "Versalles",
            "Alameda",
            "Tequendama",
            "Ciudad Jardín",
            "El Ingenio",
            "Meléndez",
            "La Flora",
            "Chipichape",
            "Menga",
            "Salomia",
            "Junín",
            "El Refugio",
            "Nápoles",
            "La Base",
            "Santa Mónica Norte",
            "San Bosco",
        ],
    ),
    "17001": (
        "manizales",
        "needs",
        [
            "Chipre",
            "Palermo",
            "El Cable",
            "Milán",
            "La Enea",
            "Fátima",
            "Versalles",
            "Campohermoso",
            "San Jorge",
            "La Sultana",
            "Betania",
            "El Carmen",
            "Solferino",
            "Villa Pilar",
            "La Francia",
            "Malhabar",
            "La Estrella",
            "Aranjuez",
            "Lusitania",
            "El Bosque",
        ],
    ),
    # --- IMPACT: towns, 6 points each
    "66682": (
        "santa_rosa",
        "needs",
        [
            "Centro",
            "Las Araucarias",
            "La Hermosa",
            "Cedralito",
            "Monserrate",
            "La Capilla",
        ],
    ),
    "66400": (
        "la_virginia",
        "needs",
        [
            "Centro",
            "Balsillas",
            "El Progreso",
            "Pedro Pablo Bello",
            "San Fernando",
            "La Playa",
        ],
    ),
    "66440": (
        "marsella",
        "needs",
        [
            "Centro",
            "El Rayo",
            "La Miranda",
            "Beltrán",
            "Estación Pereira",
            "Alto Cauca",
        ],
    ),
    "63001": (
        "armenia",
        "needs",
        [
            "Centro",
            "La Castellana",
            "Granada",
            "El Recreo",
            "Ciudad Dorada",
            "La Fachada",
        ],
    ),
    "63690": (
        "salento",
        "needs",
        [
            "Centro",
            "Boquía",
            "Cocora",
            "Llano Grande",
            "Palestina",
            "Canaán",
        ],
    ),
    "63272": (
        "filandia",
        "needs",
        [
            "Centro",
            "La India",
            "Cruces",
            "El Placer",
            "La Julia",
            "Bambuco Bajo",
        ],
    ),
    "76147": (
        "cartago",
        "needs",
        [
            "Centro",
            "Santa Ana",
            "El Prado",
            "La Platanera",
            "Zaragoza",
            "San Jerónimo",
        ],
    ),
    "76834": (
        "tulua",
        "needs",
        [
            "Centro",
            "Victoria",
            "Alvernia",
            "Sajonia",
            "La Trinidad",
            "Farfán",
        ],
    ),
    "76111": (
        "buga",
        "needs",
        [
            "Centro",
            "La Merced",
            "José María Cabal",
            "El Albergue",
            "Santa Bárbara",
            "Fuenmayor",
        ],
    ),
    "76520": (
        "palmira",
        "needs",
        [
            "Centro",
            "Zamorano",
            "La Emilia",
            "Las Delicias",
            "Santa Rita",
            "El Recreo",
        ],
    ),
    "76892": (
        "yumbo",
        "needs",
        [
            "Centro",
            "Las Américas",
            "Uribe",
            "Bellavista",
            "Puerto Isaacs",
            "Guacandá",
        ],
    ),
    # --- SUPPORT: rest of the country, 8 points each, offers help
    "11001": (
        "bogota",
        "offers",
        [
            "Chapinero",
            "Suba",
            "Kennedy",
            "Usaquén",
            "Teusaquillo",
            "Engativá",
            "Fontibón",
            "Bosa",
        ],
    ),
    "05001": (
        "medellin",
        "offers",
        [
            "El Poblado",
            "Laureles",
            "Belén",
            "Robledo",
            "Manrique",
            "Castilla",
            "Aranjuez",
            "Buenos Aires",
        ],
    ),
    "68001": (
        "bucaramanga",
        "offers",
        [
            "Cabecera",
            "San Francisco",
            "Girardot",
            "La Concordia",
            "Provenza",
            "Álvarez",
            "Sotomayor",
            "Mutis",
        ],
    ),
    "08001": (
        "barranquilla",
        "offers",
        [
            "El Prado",
            "Alto Prado",
            "Riomar",
            "Las Flores",
            "Rebolo",
            "La Concepción",
            "Boston",
            "Simón Bolívar",
        ],
    ),
    "73001": (
        "ibague",
        "offers",
        [
            "La Pola",
            "Belén",
            "Cádiz",
            "El Salado",
            "Picaleña",
            "Ambalá",
            "El Jordán",
            "Interlaken",
        ],
    ),
    "41001": (
        "neiva",
        "offers",
        [
            "Centro",
            "Las Granjas",
            "Cándido",
            "El Altico",
            "Ipanema",
            "Los Mártires",
            "Timanco",
            "Buganviles",
        ],
    ),
}

# generators stays out, so the curated "no reachable supply" scenario keeps firing
BULK_RESOURCES = [
    ("water", 400),
    ("food", 150),
    ("medicine", 40),
    ("tents", 15),
    ("bedding", 60),
    ("volunteers", 10),
    ("pet_food", 25),
    ("shelter", 20),
]
BULK_KINDS = ["community", "person", "church", "school", "person"]
BULK_URGENCIES = ["critical", "high", "medium", "high", "medium", "low"]

# (admin_code, platform, zone, explored)
FRONTIER = [
    ("66001", "x", "impact", True),
    ("27001", "x", "impact", True),
    ("76001", "x", "impact", True),
    ("66170", "instagram", "impact", False),
    ("17001", "facebook", "impact", False),
    ("63690", "x", "impact", False),
    ("11001", "x", "support", False),
    ("05001", "x", "support", False),
]


def _pt(pair: tuple[float, float]) -> Point:
    """Build a WGS84 point from a (longitude, latitude) pair."""
    return Point(pair[0], pair[1], srid=4326)


def load(write: Writer) -> Counts:
    """
    Build the demo scenario.

    Args:
        write (Writer): Progress sink.

    Returns:
        Counts: What was created, all zeros when the scenario is already loaded.

    Note:
        Idempotency is decided on the event alone. Everything else hangs off it, so if the
        event is there the scenario is there, and rebuilding half of it would be worse than
        skipping.
    """
    if Event.objects.filter(name=DEMO_EVENT_NAME).exists():
        write(f"  {DEMO_EVENT_NAME} is already loaded")
        return {"events": 0, "observations": 0, "requirements": 0, "actors": 0}

    now = timezone.now()

    units = {}
    for code, name, level, parent_code, center_key, population in ADMIN_UNITS:
        units[code], _ = AdminUnit.objects.get_or_create(
            country_code="CO",
            code=code,
            defaults={
                "name": name,
                "name_norm": name.lower(),
                "level": level,
                "parent": units.get(parent_code),
                "centroid": _pt(CENTERS[center_key]),
                "population": population,
            },
        )

    # The taxonomy is a shared catalog, loaded by its own seed rather than invented here
    resources = {resource.key: resource for resource in ResourceType.objects.all()}

    event = Event.objects.create(
        hazard="earthquake",
        name=DEMO_EVENT_NAME,
        occurred_at=now - timedelta(days=2),
        epicenter=_pt(CENTERS["pereira"]),
        magnitude=6.8,
        depth_km=28.0,
        country_code="CO",
        languages=["es"],
        detection_source="manual",
        lexicon={
            "hashtags": ["#SismoEjeCafetero", "#FuerzaRisaralda"],
            "nicknames": ["el temblor del martes"],
            "negatives": ["Venezuela", "Perú", "Indonesia"],
        },
    )
    impact_units = [
        units[code] for code, (_c, direction, _b) in ZONES.items() if direction == "needs"
    ]
    impact_parents = {u.parent for u in impact_units if u.parent is not None}
    event.affected_units.set(impact_units + list(impact_parents))

    job = HarvestJob.objects.create(
        event=event,
        platform="x",
        apify_actor="manual-seed",
        actor_input={"note": "datos demo, no ejecutado contra Apify"},
        decided_by="manual",
        rationale="Seed de demostración: publicaciones representativas del pilotaje.",
        status="done",
        items_returned=len(REQUIREMENTS),
        items_new=len(REQUIREMENTS),
        finished_at=now,
    )

    def make_location(point, admin_code, text, precision="neighborhood"):
        location, _ = Location.objects.get_or_create(
            text_norm=text.lower(),
            admin_unit=units[admin_code],
            defaults={
                "point": point,
                "precision": precision,
                "raw_text": text,
                "source": "manual",
            },
        )
        return location

    def make_observation(platform_id, text, author, hours_ago):
        observation = Observation.objects.create(
            event=event,
            job=job,
            platform="x",
            platform_id=platform_id,
            permalink=f"https://x.com/demo/status/{abs(hash(platform_id)) % 10**12}",
            posted_at=now - timedelta(hours=hours_ago),
            text=text,
            author_handle=author.lower().replace(" ", "_")[:100],
            author_name=author,
            raw={"seed": True},
        )
        return observation

    def make_requirement(
        actor,
        direction,
        resource_key,
        quantity,
        covered,
        urgency,
        location,
        destination,
        text,
        observation,
        confidence=0.85,
    ):
        Extraction.objects.create(
            observation=observation,
            model="seed",
            prompt_version="demo-1",
            classification="need" if direction == "needs" else "offer",
            confidence=confidence,
            payload={"resource": resource_key, "quantity": quantity},
            geocode_query=location.raw_text,
        )
        requirement = Requirement.objects.create(
            event=event,
            actor=actor,
            direction=direction,
            resource=resources[resource_key],
            free_text=text[:300],
            quantity=quantity,
            unit=resources[resource_key].default_unit,
            covered_quantity=covered,
            location=location,
            destination=destination,
            urgency=urgency,
            status="partial"
            if 0 < covered < quantity
            else ("covered" if covered >= quantity else "open"),
            confidence=confidence,
            last_seen_at=now,
        )
        requirement.evidence.add(observation)
        return requirement

    # ---- Curated scenario ----------------------------------------------------------
    actors = {}
    for slug, name, kind, point_key, admin_code, credibility in ACTORS:
        actors[slug] = Actor.objects.create(
            event=event,
            kind=kind,
            canonical_name=name,
            name_norm=name.lower(),
            location=make_location(_pt(POINTS[point_key]), admin_code, name),
            credibility=credibility,
            first_seen_at=now - timedelta(days=1),
            last_seen_at=now,
        )

    for actor_slug, kind, value, raw, confidence in CONTACTS:
        ContactPoint.objects.create(
            actor=actors[actor_slug],
            kind=kind,
            value=value,
            raw_value=raw,
            confidence=confidence,
        )

    for i, row in enumerate(REQUIREMENTS):
        (
            slug,
            actor_slug,
            direction,
            resource_key,
            qty,
            covered,
            _unit,  # the taxonomy owns the unit now
            urgency,
            point_key,
            admin_code,
            dest_point_key,
            dest_admin_code,
            text,
        ) = row
        observation = make_observation(
            f"demo-{slug}", text, actors[actor_slug].canonical_name, 30 - i
        )
        make_requirement(
            actors[actor_slug],
            direction,
            resource_key,
            qty,
            covered,
            urgency,
            make_location(_pt(POINTS[point_key]), admin_code, f"{slug} lugar"),
            make_location(_pt(POINTS[dest_point_key]), dest_admin_code, f"{slug} destino")
            if dest_point_key
            else None,
            text,
            observation,
        )

    # ---- Bulk barrio coverage ------------------------------------------------------
    for admin_code, (center_key, main_direction, barrios) in ZONES.items():
        center = _pt(CENTERS[center_key])
        for i, barrio in enumerate(barrios):
            # Golden-angle spiral: deterministic, non-overlapping urban scatter
            angle = i * 2.39996
            radius_deg = 0.005 + 0.0016 * i
            point = Point(
                center.x + radius_deg * math.cos(angle),
                center.y + radius_deg * 0.85 * math.sin(angle),
                srid=4326,
            )
            kind = BULK_KINDS[i % len(BULK_KINDS)]
            actor = Actor.objects.create(
                event=event,
                kind=kind,
                canonical_name=f"Comunidad {barrio} ({units[admin_code].name})",
                name_norm=f"comunidad {barrio} {units[admin_code].name}".lower(),
                location=make_location(point, admin_code, f"Barrio {barrio}"),
                credibility=0.4 + (i % 5) * 0.1,
                first_seen_at=now - timedelta(days=1),
                last_seen_at=now,
            )
            direction = (
                main_direction if i % 4 else ("offers" if main_direction == "needs" else "needs")
            )
            resource_key, base_qty = BULK_RESOURCES[i % len(BULK_RESOURCES)]
            quantity = base_qty * (1 + i % 3)
            text = (
                f"{'Se necesita' if direction == 'needs' else 'Ofrecemos'} "
                f"{resources[resource_key].name.lower()} en el barrio {barrio} "
                f"({units[admin_code].name})"
            )
            observation = make_observation(
                f"demo-bulk-{admin_code}-{i}", text, f"Comunidad {barrio}", 20 - (i % 18)
            )
            make_requirement(
                actor,
                direction,
                resource_key,
                quantity,
                0,
                BULK_URGENCIES[i % len(BULK_URGENCIES)],
                actor.location,
                None,
                text,
                observation,
                confidence=0.6 + (i % 4) * 0.1,
            )

    for admin_code, platform, zone, explored in FRONTIER:
        FrontierNode.objects.create(
            event=event,
            admin_unit=units[admin_code],
            platform=platform,
            zone=zone,
            yield_rate=12.0 if explored else 0,
            avg_credibility=0.75 if explored else 0.5,
            distance_km=0 if zone == "impact" else 300,
            passes=3 if explored else 0,
            total_items=140 if explored else 0,
            actionable_items=17 if explored else 0,
        )
    counts = {
        "events": 1,
        "observations": Observation.objects.filter(event=event).count(),
        "requirements": Requirement.objects.filter(event=event).count(),
        "actors": Actor.objects.filter(event=event).count(),
    }
    write(f"  built {counts['requirements']} requirements across {counts['actors']} actors")
    return counts


def clear(write: Writer) -> int:
    """
    Remove the scenario, including the catalog rows it invented.

    Args:
        write (Writer): Progress sink.

    Returns:
        int: Rows removed across every cascaded table.

    Note:
        The admin units carry real DIVIPOLA codes, so they have to go or a proper gazetteer
        load would collide with them on the (country, level, code) constraint. The resource
        taxonomy is not touched: it is a shared catalog with its own seed.
    """
    # Cascades take actors, requirements, matches, observations, jobs and frontier
    deleted, _ = Event.objects.filter(name=DEMO_EVENT_NAME).delete()
    Location.objects.filter(
        source="manual",
        admin_unit__country_code="CO",
        admin_unit__code__in=[c for c, *_ in ADMIN_UNITS],
    ).delete()
    for code, *_ in reversed(ADMIN_UNITS):
        AdminUnit.objects.filter(country_code="CO", code=code).delete()
    write("  removed the demo catalog rows as well")
    return deleted


SEED = Seed(
    name="demo",
    description="Synthetic Eje Cafetero scenario: 228 requirements, curated edge cases",
    event_names=(DEMO_EVENT_NAME,),
    load=load,
    clear=clear,
)
