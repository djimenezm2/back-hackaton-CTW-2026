"""
The canonical resource taxonomy, shared by every event.

Keys are English because they are database identifiers; names are Spanish because they are
what a Colombian coordinator reads on screen. The hierarchy is what lets a need for sleeping
mats be met by an offer of bedding when nothing closer exists, so a resource without a parent
can only ever match itself.

Note:
    The extractor guesses one of these keys per item. An unrecognised guess is not an error —
    the ingest step creates it as a parentless leaf, which is exactly the "add a resource
    mid-emergency without a migration" case the table exists for. It just will not participate
    in category fallback until someone gives it a parent.

    Such a leaf is created with its name equal to its key, and that equality is the marker for
    "auto-created, never named by a human". Adding the key to `RESOURCES` and reloading adopts
    it: the seed fills in the Spanish name, the parent and the unit. A row somebody has already
    named is never overwritten.

    `LEGACY_KEYS` exists because this seed replaced a data migration that keyed the catalog in
    Spanish, and `clear` only ever removed what this file declares. Any database seeded before
    the change still carries both halves of every entry, and a duplicate here is not cosmetic:
    `agua` beside `water` splits one resource into two that can never match each other.
"""

from ayudagente.radar.models import Requirement, ResourceType
from ayudagente.radar.seeds.base import Counts, Seed, Writer

# (key, display name, parent key, default unit, perishable)
RESOURCES = [
    ("water", "Agua", None, "litros", False),
    ("food", "Alimentos", None, "kg", False),
    ("perishable_food", "Alimentos perecederos", "food", "kg", True),
    ("pet_food", "Alimento para mascotas", "food", "kg", False),
    ("medicine", "Medicamentos", None, "kits", False),
    ("medical_care", "Atención médica", "medicine", "personas", False),
    ("hygiene", "Aseo e higiene", None, "kits", False),
    ("shelter", "Refugio", None, "unidades", False),
    ("tents", "Carpas", "shelter", "unidades", False),
    ("bedding", "Colchonetas y cobijas", "shelter", "unidades", False),
    ("clothing", "Ropa", "shelter", "unidades", False),
    ("construction_materials", "Materiales de construcción", None, "unidades", False),
    ("transport", "Transporte", None, "vehículos", False),
    ("machinery", "Maquinaria", None, "unidades", False),
    ("power", "Energía", None, "unidades", False),
    ("generators", "Plantas eléctricas", "power", "unidades", False),
    ("communications", "Comunicaciones", None, "unidades", False),
    ("volunteers", "Voluntarios", None, "personas", False),
    ("rescue", "Rescate", "volunteers", "personas", False),
    ("mental_health", "Apoyo psicosocial", None, "personas", False),
    ("cash", "Dinero", None, "COP", False),
    ("collection_point", "Punto de acopio", None, "unidades", False),
    ("humanitarian_aid", "Ayuda humanitaria", None, "kits", False),
    ("support", "Apoyo general", "volunteers", "personas", False),
]

# Spanish-keyed duplicates, folded into their English key on load
LEGACY_KEYS = {
    "agua": "water",
    "alimentos": "food",
    "alimentos_perecederos": "perishable_food",
    "alimentos_mascotas": "pet_food",
    "medicamentos": "medicine",
    "refugio": "shelter",
    "carpas": "tents",
    "colchonetas": "bedding",
    "transporte": "transport",
    "plantas_electricas": "generators",
    "voluntarios": "volunteers",
}


def load(write: Writer) -> Counts:
    """
    Bring the catalog to the canonical state: create what is missing, adopt what the pipeline
    invented, and retire the Spanish-keyed duplicates.

    Args:
        write (Writer): Progress sink.

    Returns:
        Counts: How many types were created, adopted and retired. All zero on a second run.

    Note:
        This does more than insert because the catalog is shared and long-lived, and a
        duplicate in it is not cosmetic: `agua` beside `water` splits one resource into two
        that never match each other, and the frontend's filter menu shows every entry twice.
    """
    created = 0
    adopted = 0
    by_key: dict[str, ResourceType] = {}

    for key, name, parent_key, unit, perishable in RESOURCES:
        parent = by_key.get(parent_key) if parent_key else None
        resource, was_created = ResourceType.objects.get_or_create(
            key=key,
            defaults={
                "name": name,
                "parent": parent,
                "default_unit": unit,
                "perishable": perishable,
            },
        )
        by_key[key] = resource
        created += int(was_created)

        if not was_created and resource.name == resource.key:
            resource.name = name
            resource.parent = parent
            resource.default_unit = unit
            resource.perishable = perishable
            resource.save(update_fields=["name", "parent", "default_unit", "perishable"])
            adopted += 1

    retired = _retire_legacy_keys(by_key)

    write(f"  {created} resource types created, {len(RESOURCES) - created} already present")
    if adopted:
        write(f"  {adopted} auto-created types adopted into the taxonomy")
    if retired:
        write(f"  {retired} Spanish-keyed duplicates retired")
    return {"resource_types": created, "adopted": adopted, "retired": retired}


def _retire_legacy_keys(by_key: dict[str, ResourceType]) -> int:
    """
    Fold every legacy Spanish key into its canonical English one.

    Args:
        by_key (dict[str, ResourceType]): The canonical types, freshly loaded.

    Returns:
        int: How many duplicates were removed.

    Note:
        Requirements and child types are repointed before the delete rather than after, because
        `Requirement.resource` is `PROTECT` — a duplicate that anything still references would
        raise instead of merging, and the merge is the whole point.
    """
    retired = 0
    for legacy_key, canonical_key in LEGACY_KEYS.items():
        legacy = ResourceType.objects.filter(key=legacy_key).first()
        canonical = by_key.get(canonical_key)
        if legacy is None or canonical is None:
            continue

        Requirement.objects.filter(resource=legacy).update(resource=canonical)
        ResourceType.objects.filter(parent=legacy).update(parent=canonical)
        legacy.delete()
        retired += 1
    return retired


def clear(write: Writer) -> int:
    """
    Remove the taxonomy, children before parents.

    Args:
        write (Writer): Progress sink.

    Returns:
        int: Rows removed. A resource still referenced by a requirement is protected and
            survives, which is correct — the catalog outlives any one event's data.
    """
    removed = 0
    for key, *_ in reversed(RESOURCES):
        deleted, _ = ResourceType.objects.filter(key=key, children__isnull=True).delete()
        removed += deleted
    write(f"  removed {removed} resource types")
    return removed


SEED = Seed(
    name="taxonomy",
    description="Canonical resource taxonomy, shared by every event",
    event_names=(),
    load=load,
    clear=clear,
)
