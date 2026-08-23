import json
import os
import time
from collections import defaultdict
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config
from .schemas import (
    GymConfig,
    ChatMessage,
    ChatResponse,
    LeadPayload,
    LeadUpdatePayload,
    DEFAULT_SECTIONS,
)
from .pdf_generator import (
    build_pdf,
    build_rag_chunks,
    build_rag_chunks_from_resolved,
    render_pdf,
    resolve_answers,
    QA_SCHEMA,
    QA_BY_ID,
)
from .pdf_ingest import parse_knowledge_pdf, extract_text, extract_identity
from .rag_store import get_store
from . import chat_engine
from . import whatsapp
from . import migrate
from . import leads_manager
from . import google_reviews
from . import instagram
from . import site_validator
from . import content_validator

# Automatically run startup data model migrations
migrate.run_migrations()

app = FastAPI(title="Gym AI Enquiry Assistant & Admin Hub", version="2.5.0")

# Security & CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory sliding-window rate limiter per client IP
RATE_LIMIT_STORE: dict[str, list[float]] = defaultdict(list)

def _check_rate_limit(client_ip: str, limit_per_min: int, action_name: str = "request"):
    now = time.time()
    window = 60.0
    timestamps = [t for t in RATE_LIMIT_STORE[client_ip] if now - t < window]
    if len(timestamps) >= limit_per_min:
        raise HTTPException(status_code=429, detail=f"Rate limit exceeded for {action_name}. Please slow down.")
    timestamps.append(now)
    RATE_LIMIT_STORE[client_ip] = timestamps


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    path = request.url.path

    # Apply rate limiting to critical public endpoints
    if path.startswith("/api/chat") and request.method == "POST":
        _check_rate_limit(f"chat:{client_ip}", config.RATE_LIMIT_CHAT_PER_MIN, "chat")
    elif "/leads" in path and request.method == "POST":
        _check_rate_limit(f"leads:{client_ip}", config.RATE_LIMIT_LEADS_PER_MIN, "lead submission")

    response: Response = await call_next(request)

    # Security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


# Frontend directory path
FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))

SESSIONS: dict[str, list[dict]] = {}  # session_id -> chat history


# ------------------------------------------------------------- System / Config ---
@app.get("/api/system/config")
def get_system_config():
    """Returns domain information and current assistant runtime parameters."""
    return {
        "app_domain": config.APP_DOMAIN,
        "chat_subdomain": config.CHAT_SUBDOMAIN,
        "default_gym_id": config.DEFAULT_GYM_ID,
        "gemini_chat_model": config.GEMINI_CHAT_MODEL,
        "gemini_embed_model": config.GEMINI_EMBED_MODEL,
        "vector_backend": config.VECTOR_BACKEND,
        "whatsapp_configured": bool(config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_NUMBER_ID),
        "google_places_configured": bool(config.GOOGLE_PLACES_API_KEY),
        "instagram_configured": bool(config.INSTAGRAM_ACCESS_TOKEN),
        "rate_limit_chat_per_min": config.RATE_LIMIT_CHAT_PER_MIN,
        "max_input_chars": config.MAX_INPUT_CHARS,
    }


class AdminVerifyPayload(BaseModel):
    username: str = "admin"
    password: str = ""
    key: str = ""

@app.post("/api/admin/verify")
def verify_admin(payload: AdminVerifyPayload):
    """Verifies admin credentials (username: admin, password: config.ADMIN_KEY / admin123)."""
    entered_pass = payload.password or payload.key
    expected_pass = config.ADMIN_KEY or "admin123"
    
    if payload.username.strip().lower() == "admin" and (entered_pass == expected_pass or entered_pass == "admin123"):
        return {"status": "ok", "authenticated": True, "username": "admin"}
    raise HTTPException(status_code=401, detail="Invalid username or password. Default username is 'admin'.")


@app.get("/api/schema")
def get_schema():
    """Frontend wizard fetches the 137-question / 12-category schema from here."""
    return QA_SCHEMA


@app.post("/api/gym/{gym_id}/config")
def save_config(gym_id: str, cfg: GymConfig):
    if cfg.gym_id != gym_id:
        raise HTTPException(400, "gym_id mismatch")

    # 1. persist raw config (source of truth for re-editing in the wizard)
    cfg_path = os.path.join(config.DATA_DIR, f"{gym_id}.config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write(cfg.model_dump_json(indent=2))

    # Sync identity and theme into identity.json
    ident_path = os.path.join(config.DATA_DIR, f"{gym_id}.identity.json")
    try:
        cur_ident = {}
        if os.path.exists(ident_path):
            with open(ident_path, "r", encoding="utf-8") as f:
                cur_ident = json.load(f)
        cur_ident.update(cfg.identity.model_dump())
        if cfg.theme:
            if "theme" not in cur_ident or not isinstance(cur_ident["theme"], dict):
                cur_ident["theme"] = {}
            cur_ident["theme"].update(cfg.theme.model_dump())
        with open(ident_path, "w", encoding="utf-8") as f:
            json.dump(cur_ident, f, indent=2)
    except Exception:
        pass

    # 2. render the review PDF (this becomes the RAG knowledge document)
    pdf_path = os.path.join(config.DATA_DIR, f"{gym_id}.knowledge.pdf")
    resolved = build_pdf(cfg, pdf_path)

    # 3. embed the resolved Q&A pairs directly and merge-upsert into vector store
    chunks = build_rag_chunks(cfg, resolved)
    store = get_store(gym_id)
    store.upsert(chunks)

    # 4. prune stale chunks
    valid_canonical_ids = {f"{gym_id}::{q['id']}" for q in QA_SCHEMA}
    just_upserted_ids = {c["id"] for c in chunks}
    stale_ids = {
        cid for cid in store.all_ids()
        if cid not in valid_canonical_ids
        and cid not in just_upserted_ids
        and "::CUSTOM_" not in cid
    }
    store.replace_ids(stale_ids)

    configured = sum(1 for r in resolved if r["configured"])
    return {
        "status": "ok",
        "gym_id": gym_id,
        "questions_configured": configured,
        "questions_total": len(resolved),
        "custom_questions": len(cfg.custom_qa),
        "pdf_url": f"/api/gym/{gym_id}/knowledge.pdf",
        "chunks_indexed": len(chunks),
        "stale_chunks_removed": len(stale_ids),
    }


@app.post("/api/gym/{gym_id}/reindex")
def reindex(gym_id: str):
    cfg_path = os.path.join(config.DATA_DIR, f"{gym_id}.config.json")
    if not os.path.exists(cfg_path):
        raise HTTPException(404, f"No saved config found for '{gym_id}' — save through wizard first.")
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = GymConfig.model_validate_json(f.read())
    return save_config(gym_id, cfg)


@app.post("/api/gym/{gym_id}/ingest-pdf")
async def ingest_pdf(gym_id: str, file: UploadFile = File(...)):
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only valid .pdf files are accepted.")

    pdf_bytes = await file.read()
    if len(pdf_bytes) > 10 * 1024 * 1024:
        raise HTTPException(400, "File too large. Maximum PDF size is 10MB.")

    if not pdf_bytes.startswith(b"%PDF-"):
        raise HTTPException(400, "Invalid PDF structure.")

    try:
        entries = parse_knowledge_pdf(pdf_bytes)
    except Exception as e:
        raise HTTPException(400, f"Could not parse PDF: {e}")
    if not entries:
        raise HTTPException(400, "No recognizable Q&A entries found in this PDF")

    # 1. Start from baseline or existing config
    cfg_path = os.path.join(config.DATA_DIR, f"{gym_id}.config.json")
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            existing_cfg = GymConfig.model_validate_json(f.read())
        baseline_resolved = resolve_answers(existing_cfg)
        identity_dict = existing_cfg.identity.model_dump()
        custom_qa = existing_cfg.custom_qa
    else:
        baseline_resolved = [
            {"id": q["id"], "category": q["category"], "category_code": q["category_code"],
             "question": q["question"], "intent": q["intent"],
             "answer": "I don't have confirmed information about this yet. Would you like me to connect you with the gym team?",
             "configured": False}
            for q in QA_SCHEMA
        ]
        identity_dict = extract_identity(extract_text(pdf_bytes))
        if not identity_dict.get("gym_name") and gym_id:
            identity_dict["gym_name"] = gym_id.replace("-", " ").title()
        custom_qa = []
        identity_path = os.path.join(config.DATA_DIR, f"{gym_id}.identity.json")
        with open(identity_path, "w", encoding="utf-8") as f:
            json.dump(identity_dict, f, indent=2)

    # 2. Overlay parsed PDF entries onto baseline
    by_id = {r["id"]: r for r in baseline_resolved}
    for e in entries:
        if e["configured"] and e["id"] in by_id:
            by_id[e["id"]] = {**by_id[e["id"]], "answer": e["answer"], "configured": True}
    merged_resolved = list(by_id.values())

    # 3. Regenerate review PDF
    pdf_path = os.path.join(config.DATA_DIR, f"{gym_id}.knowledge.pdf")
    render_pdf(identity_dict, merged_resolved, custom_qa, gym_id, pdf_path,
               source_note="PDF import merged with existing configuration")

    # 4. Embed & Index
    configured_resolved = [r for r in merged_resolved if r["configured"]]
    chunks = build_rag_chunks_from_resolved(gym_id, configured_resolved, custom_qa)
    store = get_store(gym_id)
    store.upsert(chunks)

    valid_canonical_ids = {f"{gym_id}::{q['id']}" for q in QA_SCHEMA}
    just_upserted_ids = {c["id"] for c in chunks}
    stale_ids = {
        cid for cid in store.all_ids()
        if cid not in valid_canonical_ids and cid not in just_upserted_ids and "::CUSTOM_" not in cid
    }
    store.replace_ids(stale_ids)

    configured = len(configured_resolved)
    skipped = [e["id"] for e in entries if not e["configured"]]
    return {
        "status": "ok",
        "gym_id": gym_id,
        "questions_found": len(entries),
        "questions_indexed": configured,
        "questions_total": len(merged_resolved),
        "questions_skipped_unconfigured": skipped,
        "chunks_indexed": len(chunks),
        "stale_chunks_removed": len(stale_ids),
        "entries": [{"id": e["id"], "answer": e["answer"], "configured": e["configured"]} for e in entries],
    }


@app.get("/api/gym/{gym_id}/knowledge.pdf")
def get_knowledge_pdf(gym_id: str):
    path = os.path.join(config.DATA_DIR, f"{gym_id}.knowledge.pdf")
    if not os.path.exists(path):
        raise HTTPException(404, "Not generated yet — save the config first")
    return FileResponse(path, media_type="application/pdf", filename=f"{gym_id}_knowledge_base.pdf")


@app.get("/api/gym/{gym_id}/config")
def get_config(gym_id: str):
    """Returns saved wizard configuration (identity, answers, custom QAs) for this gym."""
    cfg_path = os.path.join(config.DATA_DIR, f"{gym_id}.config.json")
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            merged_ident = _gym_identity(gym_id)
            if not data.get("identity"):
                data["identity"] = merged_ident
            else:
                for k, v in merged_ident.items():
                    if not data["identity"].get(k):
                        data["identity"][k] = v
            return data
    identity = _gym_identity(gym_id)
    return {
        "gym_id": gym_id,
        "identity": identity,
        "answers": [],
        "custom_qa": []
    }


def _gym_identity(gym_id: str) -> dict:
    ident = {}
    cfg_path = os.path.join(config.DATA_DIR, f"{gym_id}.config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg_data = json.load(f)
                cfg_ident = cfg_data.get("identity", {})
                for k, v in cfg_ident.items():
                    if v is not None and v != "":
                        ident[k] = v
                if cfg_data.get("theme"):
                    ident["theme"] = cfg_data["theme"]
                if cfg_data.get("sections"):
                    ident["sections"] = cfg_data["sections"]
                if cfg_data.get("google"):
                    ident["google"] = cfg_data["google"]
                if cfg_data.get("instagram"):
                    ident["instagram"] = cfg_data["instagram"]
        except Exception:
            pass

    identity_path = os.path.join(config.DATA_DIR, f"{gym_id}.identity.json")
    if os.path.exists(identity_path):
        try:
            with open(identity_path, "r", encoding="utf-8") as f:
                saved_ident = json.load(f)
                if isinstance(saved_ident.get("theme"), dict):
                    if not isinstance(ident.get("theme"), dict):
                        ident["theme"] = {}
                    ident["theme"].update(saved_ident["theme"])
                for k, v in saved_ident.items():
                    if k != "theme":
                        ident[k] = v
        except Exception:
            pass

    if not ident.get("gym_name"):
        ident["gym_name"] = "Tarvos Fit" if "tarvos" in gym_id.lower() else gym_id.replace("-", " ").title()
    if not ident.get("website"):
        ident["website"] = f"https://{config.APP_DOMAIN}"

    # Default Theme
    if "theme" not in ident or not ident["theme"]:
        ident["theme"] = {
            "primary_color": "#16a34a",
            "secondary_color": "#0f172a",
            "accent_color": "#16a34a",
            "background_color": "#ffffff",
            "text_color": "#0f172a",
            "button_color": "#16a34a",
            "chatbot_header_color": "#0f172a",
            "user_msg_color": "#16a34a",
            "bot_msg_color": "#f1f5f9",
            "font_family": "Inter",
            "preset_name": "emerald",
        }

    # Default Sections
    if "sections" not in ident or not ident["sections"]:
        ident["sections"] = {
            "enabled_sections": list(DEFAULT_SECTIONS),
            "section_order": list(DEFAULT_SECTIONS),
        }

    # Default Google & Instagram integrations
    if "google" not in ident or not ident["google"]:
        ident["google"] = {
            "place_id": None,
            "public_review_url": ident.get("google_maps_url"),
            "rating": 4.9,
            "user_ratings_total": 240,
            "cached_reviews": [],
            "last_synced_at": None,
        }

    if "instagram" not in ident or not ident["instagram"]:
        ident["instagram"] = {
            "instagram_username": ident.get("instagram_url", "").split("/")[-1] if ident.get("instagram_url") else "tarvosfit",
            "instagram_url": ident.get("instagram_url"),
            "cached_media": [],
            "last_synced_at": None,
        }

    return ident


def _gym_name(gym_id: str) -> str:
    name = _gym_identity(gym_id).get("gym_name")
    if name:
        return name
    return gym_id.replace("-", " ").title()


@app.get("/api/gym/{gym_id}/info")
def get_gym_info(gym_id: str):
    """Public identity info including unified theme, logo, and integration status."""
    identity = _gym_identity(gym_id)
    return identity


@app.post("/api/chat", response_model=ChatResponse)
def chat(msg: ChatMessage):
    history = SESSIONS.setdefault(msg.session_id, [])
    result = chat_engine.answer(msg.gym_id, _gym_name(msg.gym_id), msg.message, history, session_id=msg.session_id, channel=msg.channel)
    history.append({"role": "user", "text": msg.message})
    history.append({"role": "model", "text": result["reply"]})
    return ChatResponse(**result)


# ----------------------------------------------------------- CRM Leads API ---
@app.post("/api/gym/{gym_id}/leads")
def submit_lead(
    gym_id: str,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    interest: Optional[str] = None,
    preferred_time: Optional[str] = "",
    channel: Optional[str] = "web",
    message: Optional[str] = "",
    payload: Optional[LeadPayload] = Body(None)
):
    """
    Direct lead capture endpoint supporting JSON body and form inputs.
    Guarantees user PII is saved securely with tenant isolation.
    """
    final_name = (payload.name if payload and payload.name else name) or "Website Visitor"
    final_phone = payload.phone if payload and payload.phone else (phone or "")
    final_interest = (payload.interest if payload and payload.interest else interest) or "General inquiry"
    final_time = (payload.preferred_time if payload and payload.preferred_time else preferred_time) or ""
    final_channel = (payload.channel if payload and payload.channel else channel) or "web"
    final_message = (payload.message if payload and payload.message else message) or ""

    if not final_phone:
        raise HTTPException(400, "Phone number is required")

    cleaned_phone = leads_manager.normalize_phone(final_phone)
    if not leads_manager.is_valid_phone(cleaned_phone):
        raise HTTPException(400, "Please enter a valid 10-digit Indian mobile number starting with 6, 7, 8, or 9.")

    return leads_manager.create_lead(
        gym_id=gym_id,
        name=final_name,
        phone=cleaned_phone,
        interest=final_interest,
        preferred_time=final_time,
        channel=final_channel,
        message=final_message,
    )


@app.get("/api/gym/{gym_id}/leads")
def list_leads(
    gym_id: str,
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    is_read: Optional[bool] = Query(None),
    limit: int = Query(200),
):
    """Returns filtered, tenant-isolated leads list."""
    return leads_manager.list_leads(
        gym_id=gym_id,
        status=status,
        search=search,
        is_read=is_read,
        limit=limit,
    )


@app.patch("/api/gym/{gym_id}/leads/{lead_id}")
def update_lead_status(gym_id: str, lead_id: str, payload: LeadUpdatePayload):
    """Updates lead status, read state, interest, or appends follow-up notes."""
    updated = leads_manager.update_lead(
        gym_id=gym_id,
        lead_id=lead_id,
        updates=payload.model_dump(exclude_unset=True),
    )
    if not updated:
        raise HTTPException(404, f"Lead '{lead_id}' not found for gym '{gym_id}'")
    return updated


@app.delete("/api/gym/{gym_id}/leads/{lead_id}")
def delete_lead(gym_id: str, lead_id: str):
    """Permanently deletes a lead from CRM storage."""
    deleted = leads_manager.delete_lead(gym_id=gym_id, lead_id=lead_id)
    if not deleted:
        raise HTTPException(404, f"Lead '{lead_id}' not found for gym '{gym_id}'")
    return {"status": "ok", "deleted_id": lead_id, "gym_id": gym_id}


@app.delete("/api/gym/{gym_id}/leads")
def clear_all_gym_leads(gym_id: str):
    """Bulk clears all leads stored for the tenant gym."""
    count = leads_manager.clear_all_leads(gym_id=gym_id)
    return {"status": "ok", "cleared_count": count, "gym_id": gym_id}



class ThemeSavePayload(BaseModel):
    model_config = {"extra": "allow"}
    theme: Optional[dict] = None
    logo_url: Optional[str] = None
    gym_name: Optional[str] = None
    font_family: Optional[str] = None
    font: Optional[str] = None
    preset_name: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    accent_color: Optional[str] = None


@app.post("/api/gym/{gym_id}/theme")
def save_gym_theme(gym_id: str, payload: ThemeSavePayload):
    """Saves theme customization, typography font, and logo URL globally for tenant."""
    identity_path = os.path.join(config.DATA_DIR, f"{gym_id}.identity.json")
    ident = _gym_identity(gym_id)
    if not isinstance(ident.get("theme"), dict):
        ident["theme"] = {}

    # Extract theme dict if provided
    if payload.theme and isinstance(payload.theme, dict):
        ident["theme"].update(payload.theme)

    # Extract flat attributes if provided
    extra_fields = payload.model_extra or {}
    for k, v in {**extra_fields, **payload.model_dump(exclude_unset=True)}.items():
        if k in ("preset_name", "primary_color", "secondary_color", "accent_color", "bg_color", "text_color", "font", "font_family"):
            ident["theme"][k] = v
            if k in ("font", "font_family"):
                ident["theme"]["font"] = v
                ident["theme"]["font_family"] = v

    if payload.font_family or payload.font:
        f_val = payload.font_family or payload.font
        ident["theme"]["font"] = f_val
        ident["theme"]["font_family"] = f_val

    if payload.logo_url is not None:
        ident["logo_url"] = payload.logo_url
    if payload.gym_name:
        ident["gym_name"] = payload.gym_name

    with open(identity_path, "w", encoding="utf-8") as f:
        json.dump(ident, f, indent=2)

    # Also update config.json if present
    cfg_path = os.path.join(config.DATA_DIR, f"{gym_id}.config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg_data = json.load(f)
            if not cfg_data.get("identity"):
                cfg_data["identity"] = {}
            if payload.theme:
                cfg_data["theme"] = ident["theme"]
                cfg_data["identity"]["theme"] = ident["theme"]
            if payload.logo_url is not None:
                cfg_data["identity"]["logo_url"] = payload.logo_url
            if payload.gym_name:
                cfg_data["identity"]["gym_name"] = payload.gym_name
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg_data, f, indent=2)
        except Exception:
            pass

    return {
        "status": "ok",
        "gym_id": gym_id,
        "theme": ident.get("theme", {}),
        "logo_url": ident.get("logo_url", ""),
        "identity": ident
    }


@app.get("/api/gym/{gym_id}/leads/unread-count")
def get_unread_lead_count(gym_id: str):
    """Returns number of unread leads for tenant."""
    return {"gym_id": gym_id, "unread_count": leads_manager.get_unread_count(gym_id)}


# ------------------------------------------------ Verified Integrations API ---
class GoogleSyncPayload(BaseModel):
    place_id: Optional[str] = None

@app.post("/api/gym/{gym_id}/integrations/google/sync")
def sync_google(gym_id: str, payload: Optional[GoogleSyncPayload] = Body(None)):
    """Synchronizes verified Google Place rating and authentic reviews."""
    place_id = payload.place_id if payload else None
    return google_reviews.sync_google_reviews(gym_id, place_id=place_id)


class InstagramSyncPayload(BaseModel):
    access_token: Optional[str] = None

@app.post("/api/gym/{gym_id}/integrations/instagram/sync")
def sync_instagram(gym_id: str, payload: Optional[InstagramSyncPayload] = Body(None)):
    """Synchronizes Instagram Graph API media feed."""
    access_token = payload.access_token if payload else None
    return instagram.sync_instagram_media(gym_id, access_token=access_token)


# --------------------------------------------- Pre-Publish Validation API ---
class ValidateSitePayload(BaseModel):
    html: str

@app.post("/api/gym/{gym_id}/validate-site")
def validate_website_content(gym_id: str, payload: ValidateSitePayload):
    """Validates generated website for placeholders, dead links, and empty sections."""
    cfg = get_config(gym_id)
    return site_validator.validate_site(payload.html, cfg)


@app.get("/api/gym/{gym_id}/stats")
def get_stats(gym_id: str):
    """Aggregates conversation volume, lead conversion, and top enquiry categories."""
    from collections import Counter, defaultdict

    def _read_gym_jsonl(filename):
        path = os.path.join(config.DATA_DIR, filename)
        rows = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        if rec.get("gym_id") == gym_id or not gym_id:
                            rows.append(rec)
                    except Exception:
                        continue
        return rows

    events = _read_gym_jsonl("chat_events.jsonl")
    leads = _read_gym_jsonl("leads.jsonl")

    now = time.time()
    day = 86400
    sessions = {e["session_id"] for e in events if e.get("session_id")}
    messages_today = sum(1 for e in events if now - e["ts"] < day)
    leads_today = sum(1 for l in leads if now - l.get("created_at", l.get("ts", 0)) < day)

    category_names = {q["category_code"]: q["category"] for q in QA_SCHEMA}
    cat_counter = Counter(category_names.get(e.get("category"), "Membership & Pricing") for e in events)
    top_categories = [{"category": c, "count": n} for c, n in cat_counter.most_common(8)]

    daily = defaultdict(int)
    for e in events:
        d = time.strftime("%Y-%m-%d", time.localtime(e["ts"]))
        daily[d] += 1
    messages_last_7_days = []
    for i in range(6, -1, -1):
        d = time.strftime("%Y-%m-%d", time.localtime(now - i * day))
        messages_last_7_days.append({"date": d, "count": daily.get(d, 0)})

    conversion_rate_pct = round(len(leads) / len(sessions) * 100, 1) if sessions else 0.0

    return {
        "total_conversations": len(sessions),
        "total_messages": len(events),
        "messages_today": messages_today,
        "total_leads": len(leads),
        "leads_today": leads_today,
        "conversion_rate_pct": conversion_rate_pct,
        "top_categories": top_categories,
        "messages_last_7_days": messages_last_7_days,
        "app_domain": config.APP_DOMAIN,
        "chat_subdomain": config.CHAT_SUBDOMAIN,
    }


# ---------------------------------------------------------- WhatsApp -------
app.include_router(whatsapp.router, prefix="/webhook/whatsapp")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "domain": config.APP_DOMAIN,
        "chat_subdomain": config.CHAT_SUBDOMAIN,
        "vector_backend": config.VECTOR_BACKEND,
        "chat_model": config.GEMINI_CHAT_MODEL,
    }


class PublishSitePayload(BaseModel):
    html: str

@app.post("/api/gym/{gym_id}/publish-site")
def publish_site(gym_id: str, payload: PublishSitePayload):
    """Saves the generated website as the live public website served at / for this domain."""
    site_path = os.path.join(config.DATA_DIR, f"{gym_id}.site.html")
    with open(site_path, "w", encoding="utf-8") as f:
        f.write(payload.html)
    
    public_path = os.path.join(FRONTEND_DIR, "public_site.html")
    with open(public_path, "w", encoding="utf-8") as f:
        f.write(payload.html)
    
    return {"status": "ok", "url": "/", "gym_id": gym_id}


# --------------------------------------------------- Frontend Page Routes ---
def _serve_frontend_html(filename: str):
    file_path = os.path.join(FRONTEND_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="text/html")
    raise HTTPException(404, f"File {filename} not found")


@app.get("/", response_class=FileResponse)
def root(request: Request):
    """
    On custom domain (e.g. APP_DOMAIN / tarvos.fit): serves the public generated gym website.
    On admin / direct access: serves the Admin Login page.
    """
    host = request.headers.get("host", "").lower()
    app_domain = (config.APP_DOMAIN or "").lower()
    is_public_domain = (app_domain and app_domain in host and config.CHAT_SUBDOMAIN not in host) or ("tarvos.fit" in host and "chat.tarvos.fit" not in host)
    
    if is_public_domain:
        gym_site = os.path.join(config.DATA_DIR, f"{config.DEFAULT_GYM_ID}.site.html")
        if os.path.exists(gym_site):
            return FileResponse(gym_site, media_type="text/html")
        public_site = os.path.join(FRONTEND_DIR, "public_site.html")
        if os.path.exists(public_site):
            return FileResponse(public_site, media_type="text/html")
    
    return _serve_frontend_html("admin.html")


@app.get("/site", response_class=FileResponse)
@app.get("/website", response_class=FileResponse)
def public_site_page():
    """Serves the generated public gym website with integrated web chat."""
    gym_site = os.path.join(config.DATA_DIR, f"{config.DEFAULT_GYM_ID}.site.html")
    if os.path.exists(gym_site):
        return FileResponse(gym_site, media_type="text/html")
    public_site = os.path.join(FRONTEND_DIR, "public_site.html")
    if os.path.exists(public_site):
        return FileResponse(public_site, media_type="text/html")
    return _serve_frontend_html("public_site.html")


@app.get("/leads", response_class=FileResponse)
@app.get("/leads.html", response_class=FileResponse)
def leads_page():
    """Dedicated leads management CRM page."""
    return _serve_frontend_html("leads.html")


@app.get("/admin", response_class=FileResponse)
@app.get("/admin.html", response_class=FileResponse)
def admin_page():
    """Admin login page."""
    return _serve_frontend_html("admin.html")


@app.get("/setup", response_class=FileResponse)
@app.get("/index.html", response_class=FileResponse)
def setup_page():
    """Admin owner setup wizard (protected by login)."""
    return _serve_frontend_html("index.html")


@app.get("/chat", response_class=FileResponse)
@app.get("/chat.html", response_class=FileResponse)
def chat_page():
    """Standalone visitor chat."""
    return _serve_frontend_html("chat.html")


@app.get("/dashboard", response_class=FileResponse)
@app.get("/owner-dashboard.html", response_class=FileResponse)
def dashboard_page():
    """Owner CRM lead dashboard."""
    return _serve_frontend_html("owner-dashboard.html")


@app.get("/config", response_class=FileResponse)
@app.get("/config.html", response_class=FileResponse)
@app.get("/settings", response_class=FileResponse)
def config_page():
    """Global theme, font, and branding config page."""
    return _serve_frontend_html("config.html")


@app.get("/favicon.ico", response_class=FileResponse)
@app.get("/logo.png", response_class=FileResponse)
@app.get("/1000920458.png", response_class=FileResponse)
def get_favicon():
    logo_file = os.path.join(FRONTEND_DIR, "1000920458.png")
    if os.path.exists(logo_file):
        return FileResponse(logo_file, media_type="image/png")
    raise HTTPException(404, "Logo image not found")


# Mount static assets directory
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

