"""
Central configuration. All values are read from environment variables so the
same code runs locally, in Docker, or on any host.
"""
import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
GEMINI_CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-2.0-flash")
CHAT_TEMPERATURE = float(os.getenv("CHAT_TEMPERATURE", "0.4"))  # Configured 0.3 - 0.5
EMBED_DIM = int(os.getenv("EMBED_DIM", "768"))

# Domain & Routing configuration
APP_DOMAIN = os.getenv("APP_DOMAIN", "tarvos.fit")
CHAT_SUBDOMAIN = os.getenv("CHAT_SUBDOMAIN", f"chat.{APP_DOMAIN}")
DEFAULT_GYM_ID = os.getenv("DEFAULT_GYM_ID", "tarvos-fit")
ADMIN_KEY = os.getenv("ADMIN_KEY", "admin123")
ADMIN_SESSION_SECRET = os.getenv("ADMIN_SESSION_SECRET", "gym_admin_secret_token_99")

# Security & Rate Limiting
RATE_LIMIT_CHAT_PER_MIN = int(os.getenv("RATE_LIMIT_CHAT_PER_MIN", "30"))
RATE_LIMIT_LEADS_PER_MIN = int(os.getenv("RATE_LIMIT_LEADS_PER_MIN", "10"))
MAX_INPUT_CHARS = int(os.getenv("MAX_INPUT_CHARS", "500"))

VECTOR_BACKEND = os.getenv("VECTOR_BACKEND", "faiss")  # "faiss" | "qdrant"
QDRANT_URL = os.getenv("QDRANT_URL", "")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")

DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
os.makedirs(DATA_DIR, exist_ok=True)

# WhatsApp Cloud API (Meta) — https://developers.facebook.com/docs/whatsapp/cloud-api
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "gym_ai_verify_token")

# Lead capture webhook & notifications
LEAD_WEBHOOK_URL = os.getenv("LEAD_WEBHOOK_URL", "")
OWNER_NOTIFICATION_EMAIL = os.getenv("OWNER_NOTIFICATION_EMAIL", "")
OWNER_NOTIFICATION_WHATSAPP = os.getenv("OWNER_NOTIFICATION_WHATSAPP", "")

# SMTP Email Configuration (for lead email alerts)
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "noreply@tarvos.fit"))
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "false").lower() in ("true", "1", "yes")

# Google Places API (Official Reviews Integration)
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")

# Instagram Graph API (Official Media Feed Integration)
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
INSTAGRAM_USER_ID = os.getenv("INSTAGRAM_USER_ID", "")

CHUNK_SIZE_CHARS = int(os.getenv("CHUNK_SIZE_CHARS", "1200"))
CHUNK_OVERLAP_CHARS = int(os.getenv("CHUNK_OVERLAP_CHARS", "150"))
TOP_K = int(os.getenv("TOP_K", "5"))
