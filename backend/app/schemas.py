"""
Pydantic models for the owner-configuration payload, theme styling,
website sections, verified external integrations, and CRM leads management.
"""
import time
import uuid
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, model_validator


class QuestionAnswerSelection(BaseModel):
    """One answer the owner picked for one canonical question."""
    id: str                      # e.g. "LOC_001"
    situation_label: str         # e.g. "Full address known"
    field_values: dict[str, str] = Field(default_factory=dict)  # placeholder -> value


class CustomQA(BaseModel):
    """A fully owner-authored question/answer pair outside canonical schema."""
    question: str
    answer: str


class ThemeConfig(BaseModel):
    """Unified theme configuration shared across website and chatbot."""
    primary_color: str = "#16a34a"
    secondary_color: str = "#0f172a"
    accent_color: str = "#16a34a"
    background_color: str = "#ffffff"
    text_color: str = "#0f172a"
    button_color: str = "#16a34a"
    chatbot_header_color: str = "#0f172a"
    user_msg_color: str = "#16a34a"
    bot_msg_color: str = "#f1f5f9"
    font_family: str = "Inter"
    preset_name: Optional[str] = "emerald"


DEFAULT_SECTIONS = [
    "hero",
    "trust_strip",
    "about",
    "equipment",
    "health_diet",
    "nutrition",
    "policies",
    "programs",
    "facilities",
    "membership",
    "trainers",
    "gallery",
    "timings",
    "location",
    "faq",
    "trial_cta",
]


class SectionConfig(BaseModel):
    """Owner's selected website sections and their custom display order."""
    enabled_sections: list[str] = Field(default_factory=lambda: list(DEFAULT_SECTIONS))
    section_order: list[str] = Field(default_factory=lambda: list(DEFAULT_SECTIONS))

    @model_validator(mode="before")
    @classmethod
    def handle_aliases(cls, data):
        if isinstance(data, dict):
            if "enabled" in data and "enabled_sections" not in data:
                data["enabled_sections"] = data["enabled"]
            if "order" in data and "section_order" not in data:
                data["section_order"] = data["order"]
        return data


class GoogleIntegrationConfig(BaseModel):
    """Official Google Places API integration metadata and cached verified reviews."""
    place_id: Optional[str] = None
    public_review_url: Optional[str] = None
    rating: Optional[float] = 4.9
    user_ratings_total: Optional[int] = 240
    last_synced_at: Optional[float] = None
    cached_reviews: list[dict] = Field(default_factory=list)


class InstagramIntegrationConfig(BaseModel):
    """Official Instagram Graph API & oEmbed integration metadata."""
    instagram_username: Optional[str] = None
    instagram_url: Optional[str] = None
    transformation_url: Optional[str] = None   # URL to post/Reel showing member transformations
    events_url: Optional[str] = None           # URL to post/Reel showing gym events & challenges
    about_url: Optional[str] = None            # URL to post/Reel showing gym tour / about us
    last_synced_at: Optional[float] = None
    cached_media: list[dict] = Field(default_factory=list)


class GymIdentity(BaseModel):
    gym_name: str
    brand_name: Optional[str] = None
    short_description: Optional[str] = None
    detailed_description: Optional[str] = None
    primary_phone: Optional[str] = None
    whatsapp_number: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    supported_languages: list[str] = Field(default_factory=lambda: ["en"])
    currency: str = "INR"
    city: Optional[str] = None
    google_maps_url: Optional[str] = None
    instagram_url: Optional[str] = None
    instagram_transformation_url: Optional[str] = None
    instagram_events_url: Optional[str] = None
    instagram_about_url: Optional[str] = None
    logo_url: Optional[str] = None  # data: URL or hosted URL
    member_count_range: Optional[str] = None  # "<100" | "100-500" | ">500"
    gallery: list[dict] = Field(default_factory=list)  # list of {id, url, caption, category}
    theme: ThemeConfig = Field(default_factory=ThemeConfig)
    sections: SectionConfig = Field(default_factory=SectionConfig)
    google: GoogleIntegrationConfig = Field(default_factory=GoogleIntegrationConfig)
    instagram: InstagramIntegrationConfig = Field(default_factory=InstagramIntegrationConfig)


class GymConfig(BaseModel):
    gym_id: str                          # slug, used as the tenant/collection key
    identity: GymIdentity
    answers: list[QuestionAnswerSelection] = Field(default_factory=list)
    custom_qa: list[CustomQA] = Field(default_factory=list)
    theme: Optional[ThemeConfig] = None
    sections: Optional[SectionConfig] = None
    google: Optional[GoogleIntegrationConfig] = None
    instagram: Optional[InstagramIntegrationConfig] = None


class ChatMessage(BaseModel):
    gym_id: str
    session_id: str
    message: str
    channel: str = "web"  # "web" | "whatsapp"


class ChatResponse(BaseModel):
    reply: str
    lead_capture_prompt: bool = False
    sources: list[str] = Field(default_factory=list)


class LeadStatus(str, Enum):
    NEW = "New"
    PENDING = "Pending"
    CONTACTED = "Contacted"
    INTERESTED = "Interested"
    TRIAL_BOOKED = "Trial booked"
    JOINED = "Joined"
    COMPLETED = "Completed"
    CONVERTED = "Converted"
    CLOSED = "Closed"


class LeadNote(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    text: str
    created_at: float = Field(default_factory=time.time)
    author: str = "Gym Owner"


class Lead(BaseModel):
    id: str = Field(default_factory=lambda: "LEAD-" + str(uuid.uuid4())[:8].upper())
    gym_id: str
    name: str = "Website Visitor"
    phone: str
    source: str = "Website Form"   # "Website Form" | "Website Chatbot" | "WhatsApp Business API" | "Trial Booking"
    interest: str = "General inquiry"
    preferred_time: Optional[str] = ""
    message: Optional[str] = ""
    status: str = "New"
    is_read: bool = False
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    notes: list[dict] = Field(default_factory=list)
    notification_sent: bool = False
    delivery_status: str = "pending"  # "sent" | "delivered" | "failed" | "skipped"
    delivery_error: Optional[str] = None


class LeadPayload(BaseModel):
    name: Optional[str] = "Website Visitor"
    phone: str
    interest: Optional[str] = "General inquiry"
    preferred_time: Optional[str] = ""
    message: Optional[str] = ""
    channel: Optional[str] = "web"


class LeadUpdatePayload(BaseModel):
    status: Optional[str] = None
    is_read: Optional[bool] = None
    note: Optional[str] = None
    interest: Optional[str] = None
    preferred_time: Optional[str] = None
