"""
Enumerations shared across every model.

They live in one module because several cross layer boundaries: `Platform` is used by the
harvest layer, the observation layer and the contact layer, and a divergence between those
copies would break queries silently.
"""

from django.db import models


class Platform(models.TextChoices):
    X = "x", "X (Twitter)"
    INSTAGRAM = "instagram", "Instagram"
    FACEBOOK = "facebook", "Facebook"
    TIKTOK = "tiktok", "TikTok"


class HazardKind(models.TextChoices):
    EARTHQUAKE = "earthquake", "Earthquake"
    FLOOD = "flood", "Flood"
    LANDSLIDE = "landslide", "Landslide"
    CYCLONE = "cyclone", "Cyclone"
    WILDFIRE = "wildfire", "Wildfire"
    WINDSTORM = "windstorm", "Windstorm"
    OTHER = "other", "Other"


class EventStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    PAUSED = "paused", "Paused"
    ARCHIVED = "archived", "Archived"


class AdminLevel(models.TextChoices):
    DEPARTMENT = "department", "Department"
    MUNICIPALITY = "municipality", "Municipality"
    SETTLEMENT = "settlement", "Settlement"


class DecisionSource(models.TextChoices):
    AGENT = "agent", "Frontier agent"
    RULE = "rule", "Cadence rule"
    MANUAL = "manual", "Manual"


class JobStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    DONE = "done", "Done"
    EMPTY = "empty", "No results"
    FAILED = "failed", "Failed"
    ACTOR_DOWN = "actor_down", "Actor down"


class MediaKind(models.TextChoices):
    IMAGE = "image", "Image"
    VIDEO = "video", "Video"
    FRAME = "frame", "Video frame"
    COVER = "cover", "Video cover"


class ExtractionClass(models.TextChoices):
    NEED = "need", "Need"
    OFFER = "offer", "Offer"
    BOTH = "both", "Need and offer"
    INFORMATIONAL = "informational", "Informational"
    DISCARD = "discard", "Discard"


class LocationPrecision(models.TextChoices):
    DEPARTMENT = "department", "Department"
    MUNICIPALITY = "municipality", "Municipality"
    SETTLEMENT = "settlement", "Settlement"
    NEIGHBORHOOD = "neighborhood", "Neighborhood or rural district"
    STREET_ADDRESS = "street_address", "Street address"
    EXACT_POINT = "exact_point", "Exact point"


class GeocodeSource(models.TextChoices):
    GOOGLE = "google", "Google Geocoding"
    DIVIPOLA = "divipola", "DIVIPOLA catalog"
    PLATFORM = "platform", "Platform metadata"
    MANUAL = "manual", "Manual"


class ActorKind(models.TextChoices):
    PERSON = "person", "Person"
    COLLECTION_CENTER = "collection_center", "Collection center"
    NONPROFIT = "nonprofit", "Nonprofit or NGO"
    COMPANY = "company", "Company"
    PUBLIC_ENTITY = "public_entity", "Public entity"
    MEDIA_OUTLET = "media_outlet", "Media outlet"
    COMMUNITY = "community", "Community or local board"
    CHURCH = "church", "Church"
    SCHOOL = "school", "School or university"
    VOLUNTEER_GROUP = "volunteer_group", "Volunteer group"


class CredibilitySource(models.TextChoices):
    FOLLOWERS = "followers", "Follower count"
    VERIFIED = "verified", "Verified account"
    ENGAGEMENT = "engagement", "Engagement ratio"
    OFFICIAL_ENTITY = "official_entity", "Known official entity"
    NONE = "none", "No signal available"


class MentionRole(models.TextChoices):
    AUTHOR = "author", "Author of the post"
    MENTIONED = "mentioned", "Mentioned"
    SUBJECT = "subject", "Subject of the content"


class ResolutionMethod(models.TextChoices):
    HANDLE = "handle", "Same platform handle"
    PHONE = "phone", "Same phone number"
    TRIGRAM = "trigram", "Trigram name similarity"
    EMBEDDING = "embedding", "Embedding similarity"
    LLM = "llm", "Adjudicated by LLM"
    MANUAL = "manual", "Manual"


class ContactKind(models.TextChoices):
    HANDLE = "handle", "Platform handle"
    PHONE = "phone", "Phone"
    WHATSAPP = "whatsapp", "WhatsApp"
    EMAIL = "email", "Email"
    WEBSITE = "website", "Website"
    FORM = "form", "Web form"
    NEQUI = "nequi", "Nequi"
    DAVIPLATA = "daviplata", "Daviplata"
    BANK_ACCOUNT = "bank_account", "Bank account"
    BRE_B_KEY = "bre_b_key", "Bre-B key"
    CROWDFUNDING = "crowdfunding", "Crowdfunding link"
    STREET_ADDRESS = "street_address", "Street address"


class UnreachableReason(models.TextChoices):
    BOUNCED = "bounced", "Bounced"
    INVALID = "invalid", "Invalid format"
    OPTED_OUT = "opted_out", "Asked not to be contacted"
    SATURATED = "saturated", "Already contacted too many times"


class Direction(models.TextChoices):
    NEEDS = "needs", "Needs"
    OFFERS = "offers", "Offers"


class Urgency(models.TextChoices):
    CRITICAL = "critical", "Critical"
    HIGH = "high", "High"
    MEDIUM = "medium", "Medium"
    LOW = "low", "Low"


class RequirementStatus(models.TextChoices):
    OPEN = "open", "Open"
    PARTIAL = "partial", "Partially covered"
    COVERED = "covered", "Covered"
    EXPIRED = "expired", "Expired"
    UNVERIFIED = "unverified", "Unverified"
    DISCARDED = "discarded", "Discarded"


class MatchStatus(models.TextChoices):
    PROPOSED = "proposed", "Proposed"
    CONTACTED = "contacted", "Contacted"
    CONFIRMED = "confirmed", "Confirmed"
    DELIVERED = "delivered", "Delivered"
    FAILED = "failed", "Failed"
    DISCARDED = "discarded", "Discarded"


class OutreachChannel(models.TextChoices):
    EMAIL = "email", "Email"
    DIRECT_MESSAGE = "direct_message", "Direct message"
    COMMENT_REPLY = "comment_reply", "Comment reply"
    WHATSAPP = "whatsapp", "WhatsApp"
    PHONE_CALL = "phone_call", "Phone call"


class OutreachStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    APPROVED = "approved", "Approved"
    SENT = "sent", "Sent"
    BOUNCED = "bounced", "Bounced"
    ANSWERED = "answered", "Answered"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class Ring(models.TextChoices):
    T0 = "T0", "T0 · Epicenter"
    T1 = "T1", "T1 · Affected departments"
    T2 = "T2", "T2 · Supply hubs"
    T3 = "T3", "T3 · National long tail"


class Zone(models.TextChoices):
    IMPACT = "impact", "Impact zone"
    SUPPORT = "support", "Support zone"


class NodeStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    EXHAUSTED = "exhausted", "Exhausted"
    PAUSED = "paused", "Paused"
