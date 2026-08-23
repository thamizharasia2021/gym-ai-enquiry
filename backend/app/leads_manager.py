"""
Dedicated Multi-Tenant Lead Lifecycle and Notification Engine.
Provides complete CRUD, status transitions, follow-up notes, read/unread tracking,
and multi-channel notification dispatch with duplicate prevention.
"""
import json
import os
import re
import smtplib
import time
import urllib.parse
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, Any
import httpx

from . import config
from .schemas import Lead, LeadNote, LeadStatus


LEAD_STATUS_VALUES = [
    "New",
    "Contacted",
    "Interested",
    "Trial booked",
    "Converted",
    "Closed",
]


def _leads_file_path() -> str:
    return os.path.join(config.DATA_DIR, "leads.jsonl")


def _read_all_leads() -> list[dict]:
    path = _leads_file_path()
    leads = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    leads.append(json.loads(line))
                except Exception:
                    continue
    return leads


def _write_all_leads(leads: list[dict]):
    path = _leads_file_path()
    with open(path, "w", encoding="utf-8") as f:
        for lead in leads:
            f.write(json.dumps(lead) + "\n")


def normalize_phone(phone: str) -> str:
    """Normalizes phone number to standard 10 digits or cleaned format."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    elif len(digits) > 10 and digits[-10] in "6789":
        # Handle cases with leading country codes (e.g. +91, 0091)
        digits = digits[-10:]
    return digits or (phone or "").strip()


def is_valid_phone(phone: str) -> bool:
    """Validates whether phone number is a valid 10-digit Indian mobile number."""
    if not phone:
        return False
    digits = normalize_phone(phone)
    return len(digits) == 10 and digits[0] in "6789"


def create_lead(
    gym_id: str,
    name: str = "Website Visitor",
    phone: str = "",
    interest: str = "General inquiry",
    preferred_time: str = "",
    channel: str = "web",
    message: str = "",
) -> dict:
    """
    Creates a new lead with tenant isolation, sets initial 'New' status,
    marks unread, persists to storage, and safely dispatches notifications.
    """
    clean_phone = normalize_phone(phone)
    lead_id = f"LEAD-{gym_id.replace('-', '')[:4].upper()}-{str(uuid.uuid4())[:6].upper()}"
    now = time.time()

    # Source mapping
    source_map = {
        "web": "Website Chatbot",
        "chat": "Website Chatbot",
        "form": "Website Enquiry Form",
        "trial": "Website Free Trial Form",
        "whatsapp": "WhatsApp Business API",
    }
    source_name = source_map.get(channel.lower(), channel.capitalize())

    lead_record = {
        "id": lead_id,
        "gym_id": gym_id,
        "name": (name or "Website Visitor").strip(),
        "phone": clean_phone,
        "source": source_name,
        "interest": (interest or "General inquiry").strip(),
        "preferred_time": (preferred_time or "").strip(),
        "message": (message or "").strip(),
        "status": "New",
        "is_read": False,
        "created_at": now,
        "updated_at": now,
        "notes": [],
        "notification_sent": False,
        "delivery_status": "pending",
        "delivery_error": None,
        "ts": now,  # legacy compatibility
        "channel": channel,  # legacy compatibility
    }

    # Append to leads file
    path = _leads_file_path()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(lead_record) + "\n")

    # Safe Notification Dispatch (Duplicate Prevention & Non-blocking)
    try:
        dispatch_notifications(lead_record)
    except Exception as e:
        lead_record["delivery_status"] = "failed"
        lead_record["delivery_error"] = str(e)

    return lead_record


def list_leads(
    gym_id: str,
    status: Optional[str] = None,
    search: Optional[str] = None,
    is_read: Optional[bool] = None,
    limit: int = 200,
) -> list[dict]:
    """Retrieves tenant-isolated leads with filtering and newest-first sorting."""
    all_leads = _read_all_leads()
    results = []

    search_term = search.strip().lower() if search else None
    target_status = status.strip() if status else None

    for lead in all_leads:
        # Strict Tenant Isolation
        if gym_id and lead.get("gym_id") != gym_id:
            continue

        if target_status and target_status.lower() != "all" and lead.get("status", "").lower() != target_status.lower():
            continue

        if is_read is not None and lead.get("is_read", False) != is_read:
            continue

        if search_term:
            name_m = search_term in lead.get("name", "").lower()
            phone_m = search_term in lead.get("phone", "").lower()
            int_m = search_term in lead.get("interest", "").lower()
            src_m = search_term in lead.get("source", "").lower()
            id_m = search_term in lead.get("id", "").lower()
            if not (name_m or phone_m or int_m or src_m or id_m):
                continue

        results.append(lead)

    # Sort descending by created_at or ts
    results.sort(key=lambda r: r.get("created_at", r.get("ts", 0)), reverse=True)
    return results[:limit]


def get_lead(gym_id: str, lead_id: str) -> Optional[dict]:
    """Finds a single lead by ID within the tenant scope."""
    all_leads = _read_all_leads()
    for lead in all_leads:
        if lead.get("gym_id") == gym_id and lead.get("id") == lead_id:
            return lead
    return None


def update_lead(gym_id: str, lead_id: str, updates: dict) -> Optional[dict]:
    """Updates lead fields (status, is_read, notes, etc.) within tenant boundary."""
    all_leads = _read_all_leads()
    found_idx = None
    target_lead = None

    for idx, lead in enumerate(all_leads):
        if lead.get("gym_id") == gym_id and lead.get("id") == lead_id:
            found_idx = idx
            target_lead = lead
            break

    if found_idx is None or target_lead is None:
        return None

    now = time.time()
    old_status = target_lead.get("status", "New")
    if "status" in updates and updates["status"]:
        new_status = updates["status"]
        target_lead["status"] = new_status
        if new_status != old_status and not updates.get("note"):
            note_text = f"Human Action: Status updated to {new_status}"
            note_obj = {
                "id": str(uuid.uuid4())[:8],
                "text": note_text,
                "created_at": now,
                "author": updates.get("author", "Human Admin"),
            }
            notes_list = target_lead.get("notes", [])
            notes_list.append(note_obj)
            target_lead["notes"] = notes_list

    if "is_read" in updates and updates["is_read"] is not None:
        target_lead["is_read"] = bool(updates["is_read"])
    if "interest" in updates and updates["interest"]:
        target_lead["interest"] = updates["interest"]
    if "preferred_time" in updates:
        target_lead["preferred_time"] = updates["preferred_time"]

    # Append note if explicitly provided
    if "note" in updates and updates["note"]:
        note_obj = {
            "id": str(uuid.uuid4())[:8],
            "text": updates["note"].strip(),
            "created_at": now,
            "author": updates.get("author", "Human Admin"),
        }
        notes_list = target_lead.get("notes", [])
        notes_list.append(note_obj)
        target_lead["notes"] = notes_list

    target_lead["updated_at"] = now
    all_leads[found_idx] = target_lead
    _write_all_leads(all_leads)
    return target_lead


def delete_lead(gym_id: str, lead_id: str) -> bool:
    """Permanently deletes a lead within tenant boundary."""
    all_leads = _read_all_leads()
    initial_len = len(all_leads)
    remaining_leads = [
        l for l in all_leads
        if not (l.get("id") == lead_id and (not gym_id or l.get("gym_id") == gym_id))
    ]
    if len(remaining_leads) == initial_len:
        return False
    _write_all_leads(remaining_leads)
    return True


def clear_all_leads(gym_id: Optional[str] = None) -> int:
    """Bulk clears all lead entries (or leads belonging to a specific tenant gym_id)."""
    all_leads = _read_all_leads()
    if not gym_id:
        count = len(all_leads)
        _write_all_leads([])
        return count
    else:
        remaining = [l for l in all_leads if l.get("gym_id") != gym_id]
        cleared_count = len(all_leads) - len(remaining)
        _write_all_leads(remaining)
        return cleared_count



def get_unread_count(gym_id: str) -> int:
    """Returns number of unread leads for the tenant."""
    leads = _read_all_leads()
    return sum(1 for l in leads if l.get("gym_id") == gym_id and not l.get("is_read", False))


def _get_gym_identity(gym_id: str) -> dict:
    """Loads identity information for a specific gym tenant."""
    if not gym_id:
        return {}
    ident_path = os.path.join(config.DATA_DIR, f"{gym_id}.identity.json")
    if os.path.exists(ident_path):
        try:
            with open(ident_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass

    config_path = os.path.join(config.DATA_DIR, f"{gym_id}.config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "identity" in data:
                    return data["identity"]
        except Exception:
            pass
    return {}


def _send_smtp_email(to_email: str, subject: str, body_text: str, body_html: str) -> tuple[bool, str]:
    """Dispatches lead notification email using configured SMTP server."""
    if not config.SMTP_HOST or not to_email:
        return False, "smtp_not_configured"
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = config.SMTP_FROM
        msg["To"] = to_email

        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        if config.SMTP_USE_SSL:
            server = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=10)
        else:
            server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10)
            if config.SMTP_USE_TLS:
                server.starttls()

        if config.SMTP_USER and config.SMTP_PASSWORD:
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)

        server.sendmail(config.SMTP_FROM, [to_email], msg.as_string())
        server.quit()
        return True, "email_sent_ok"
    except Exception as e:
        return False, f"email_err:{e}"


def dispatch_notifications(lead: dict, gym_id: Optional[str] = None) -> dict:
    """
    Sends owner notifications across configured channels:
    1. Tenant-specific WhatsApp number (from gym details / identity)
    2. Tenant-specific Email address (from gym details / identity)
    3. External webhook (if configured)
    Prevents duplicate notifications and records delivery status without breaking flow.
    """
    if lead.get("notification_sent"):
        return {"status": "already_dispatched", "delivery_status": lead.get("delivery_status")}

    target_gym_id = gym_id or lead.get("gym_id") or config.DEFAULT_GYM_ID
    identity = _get_gym_identity(target_gym_id)

    gym_name = identity.get("gym_name") or target_gym_id.replace("-", " ").title()
    gym_whatsapp = identity.get("whatsapp_number") or identity.get("primary_phone") or config.OWNER_NOTIFICATION_WHATSAPP
    gym_email = identity.get("email") or config.OWNER_NOTIFICATION_EMAIL

    lead_name = lead.get("name", "Website Visitor")
    lead_phone = lead.get("phone", "")
    lead_interest = lead.get("interest", "General Inquiry")
    lead_source = lead.get("source", "Website")
    lead_time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(lead.get("created_at", time.time())))
    lead_id = lead.get("id", "")

    # Construct instant WhatsApp alert URLs (Click-to-Alert and Click-to-Prospect)
    lead_alert_msg = (
        f"🚨 *New Gym Lead Received!*\n\n"
        f"🏢 *Gym:* {gym_name}\n"
        f"👤 *Name:* {lead_name}\n"
        f"📞 *Phone:* {lead_phone}\n"
        f"🎯 *Interest:* {lead_interest}\n"
        f"📌 *Source:* {lead_source}\n"
        f"⏰ *Received:* {lead_time_str}\n"
        f"🔗 *CRM Lead ID:* {lead_id}"
    )

    clean_gym_wa = re.sub(r"\D", "", gym_whatsapp or "")
    if clean_gym_wa and len(clean_gym_wa) == 10:
        clean_gym_wa = "91" + clean_gym_wa

    clean_prospect_phone = re.sub(r"\D", "", lead_phone or "")
    if clean_prospect_phone and len(clean_prospect_phone) == 10:
        clean_prospect_phone = "91" + clean_prospect_phone

    if clean_gym_wa:
        lead["whatsapp_alert_url"] = f"https://wa.me/{clean_gym_wa}?text={urllib.parse.quote(lead_alert_msg)}"
    else:
        lead["whatsapp_alert_url"] = f"https://wa.me/?text={urllib.parse.quote(lead_alert_msg)}"

    if clean_prospect_phone:
        prospect_reply = f"Hi {lead_name}! Thank you for reaching out to {gym_name}. We noticed you're interested in {lead_interest}. How can our fitness coaches assist you today?"
        lead["prospect_whatsapp_url"] = f"https://wa.me/{clean_prospect_phone}?text={urllib.parse.quote(prospect_reply)}"
    else:
        lead["prospect_whatsapp_url"] = ""

    delivery_statuses = []

    # 1. External Webhook (e.g. Google Sheets / Zapier / CRM)
    if config.LEAD_WEBHOOK_URL:
        try:
            with httpx.Client(timeout=6) as client:
                resp = client.post(config.LEAD_WEBHOOK_URL, json=lead)
                if resp.status_code < 400:
                    delivery_statuses.append("webhook_ok")
                else:
                    delivery_statuses.append(f"webhook_status_{resp.status_code}")
        except Exception as ex:
            delivery_statuses.append(f"webhook_err:{ex}")

    # 2. WhatsApp Owner Notification (Meta Cloud API to Gym WhatsApp number)
    if config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_NUMBER_ID and clean_gym_wa:
        try:
            url = f"https://graph.facebook.com/v20.0/{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
            headers = {
                "Authorization": f"Bearer {config.WHATSAPP_TOKEN}",
                "Content-Type": "application/json",
            }
            payload = {
                "messaging_product": "whatsapp",
                "to": clean_gym_wa,
                "type": "text",
                "text": {"body": lead_alert_msg},
            }
            with httpx.Client(timeout=6) as client:
                resp = client.post(url, headers=headers, json=payload)
                if resp.status_code < 400:
                    delivery_statuses.append("whatsapp_api_ok")
                else:
                    delivery_statuses.append(f"whatsapp_status_{resp.status_code}")
        except Exception as ex:
            delivery_statuses.append(f"whatsapp_err:{ex}")

    # 3. Email Notification to Gym Email
    if gym_email:
        email_subject = f"🚨 New Lead Alert: {lead_name} ({lead_interest}) — {gym_name}"
        email_text = (
            f"New Lead Captured for {gym_name}\n\n"
            f"Name: {lead_name}\n"
            f"Phone: {lead_phone}\n"
            f"Interest: {lead_interest}\n"
            f"Source: {lead_source}\n"
            f"Time: {lead_time_str}\n"
            f"Lead ID: {lead_id}\n\n"
            f"Open Leads CRM: https://{config.APP_DOMAIN}/leads?lead_id={lead_id}"
        )
        email_html = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden;">
          <div style="background: #0f172a; color: #ffffff; padding: 20px; text-align: center;">
            <h2 style="margin: 0; font-size: 20px;">🏋️ {gym_name} — New Lead Alert</h2>
          </div>
          <div style="padding: 24px; color: #1e293b;">
            <p style="font-size: 15px; margin-top: 0;">A new prospect has submitted an enquiry:</p>
            <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
              <tr style="border-bottom: 1px solid #f1f5f9;"><td style="padding: 8px 0; font-weight: 700; color: #64748b; width: 30%;">Name:</td><td style="padding: 8px 0; font-weight: 600; font-size: 16px;">{lead_name}</td></tr>
              <tr style="border-bottom: 1px solid #f1f5f9;"><td style="padding: 8px 0; font-weight: 700; color: #64748b;">Phone:</td><td style="padding: 8px 0; font-weight: 600; font-size: 16px;"><a href="tel:{lead_phone}" style="color: #16a34a; text-decoration: none;">📞 {lead_phone}</a></td></tr>
              <tr style="border-bottom: 1px solid #f1f5f9;"><td style="padding: 8px 0; font-weight: 700; color: #64748b;">Interest:</td><td style="padding: 8px 0; font-weight: 600;">{lead_interest}</td></tr>
              <tr style="border-bottom: 1px solid #f1f5f9;"><td style="padding: 8px 0; font-weight: 700; color: #64748b;">Source:</td><td style="padding: 8px 0; color: #475569;">{lead_source}</td></tr>
              <tr style="border-bottom: 1px solid #f1f5f9;"><td style="padding: 8px 0; font-weight: 700; color: #64748b;">Time:</td><td style="padding: 8px 0; color: #475569;">{lead_time_str}</td></tr>
            </table>
            <div style="margin-top: 24px; text-align: center;">
              {f'<a href="https://wa.me/{clean_prospect_phone}" target="_blank" style="display: inline-block; background: #16a34a; color: #ffffff; padding: 10px 20px; border-radius: 8px; text-decoration: none; font-weight: 700; margin-right: 8px;">💬 Message on WhatsApp</a>' if clean_prospect_phone else ''}
              <a href="tel:{lead_phone}" style="display: inline-block; background: #0f172a; color: #ffffff; padding: 10px 20px; border-radius: 8px; text-decoration: none; font-weight: 700;">📞 Call Prospect</a>
            </div>
          </div>
          <div style="background: #f8fafc; border-top: 1px solid #e2e8f0; padding: 12px; text-align: center; font-size: 12px; color: #94a3b8;">
            Gym AI Assistant CRM · Lead ID: {lead_id}
          </div>
        </div>
        """
        ok, status_msg = _send_smtp_email(gym_email, email_subject, email_text, email_html)
        if ok:
            delivery_statuses.append("email_ok")
        else:
            delivery_statuses.append(status_msg)

    # Update lead record with notification delivery status
    lead["notification_sent"] = True
    lead["notified_whatsapp"] = gym_whatsapp or "none"
    lead["notified_email"] = gym_email or "none"
    lead["delivery_status"] = "delivered" if any("ok" in s for s in delivery_statuses) else ("skipped_no_creds" if not delivery_statuses else "pending")
    if delivery_statuses:
        lead["delivery_error"] = "; ".join(delivery_statuses)

    all_leads = _read_all_leads()
    for idx, l in enumerate(all_leads):
        if l.get("id") == lead.get("id"):
            all_leads[idx] = lead
            break
    _write_all_leads(all_leads)
    return {"status": "dispatched", "delivery_status": lead["delivery_status"], "whatsapp": lead.get("notified_whatsapp"), "email": lead.get("notified_email")}
