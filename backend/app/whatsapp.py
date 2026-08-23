"""
WhatsApp Cloud API (Meta) integration — the same chat_engine.answer() used
by the web widget, just fronted by a webhook instead of an HTTP call from
the browser. This means the RAG knowledge base is shared automatically:
whatever the owner configures in the wizard answers questions on both
channels with zero duplicate logic.

Setup:
  1. Create a Meta developer app -> WhatsApp product ->
     https://developers.facebook.com/docs/whatsapp/cloud-api/get-started
  2. Set WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_VERIFY_TOKEN
     in your .env
  3. Point the Meta webhook URL at:
     https://<your-domain>/webhook/whatsapp
  4. Map each gym's WhatsApp phone_number_id -> gym_id in
     data/whatsapp_gym_map.json, e.g.:
     { "1234567890123456": "downtown-fitness" }
     (a gym can also be provided via a query param during local testing)
"""
import json
import os
import httpx
from fastapi import APIRouter, Request, Response

from . import config
from . import chat_engine

router = APIRouter()

SESSIONS: dict[str, list[dict]] = {}


def _gym_for_phone_number_id(phone_number_id: str) -> str:
    map_path = os.path.join(config.DATA_DIR, "whatsapp_gym_map.json")
    if os.path.exists(map_path):
        with open(map_path) as f:
            mapping = json.load(f)
        if phone_number_id in mapping:
            return mapping[phone_number_id]
    # single-gym deployments can just fall back to WHATSAPP_PHONE_NUMBER_ID
    return "default-gym"


def _gym_name(gym_id: str) -> str:
    cfg_path = os.path.join(config.DATA_DIR, f"{gym_id}.config.json")
    if os.path.exists(cfg_path):
        with open(cfg_path) as f:
            return json.load(f).get("identity", {}).get("gym_name", gym_id)
    return gym_id


def _send_whatsapp_message(to: str, body: str, phone_number_id: str):
    url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {config.WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": body}}
    httpx.post(url, headers=headers, json=payload, timeout=10)


@router.get("")
def verify(request: Request):
    """Meta's webhook verification handshake."""
    params = request.query_params
    if params.get("hub.verify_token") == config.WHATSAPP_VERIFY_TOKEN:
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    return Response(status_code=403)


@router.post("")
async def incoming(request: Request):
    payload = await request.json()
    try:
        entry = payload["entry"][0]["changes"][0]["value"]
        phone_number_id = entry["metadata"]["phone_number_id"]
        message = entry["messages"][0]
        from_number = message["from"]
        text = message.get("text", {}).get("body", "")
    except (KeyError, IndexError):
        return {"status": "ignored"}  # delivery receipts / non-text events

    if not text:
        return {"status": "ignored"}

    gym_id = _gym_for_phone_number_id(phone_number_id)
    session_key = f"{gym_id}:{from_number}"
    history = SESSIONS.setdefault(session_key, [])

    result = chat_engine.answer(gym_id, _gym_name(gym_id), text, history, session_id=session_key, channel="whatsapp")
    history.append({"role": "user", "text": text})
    history.append({"role": "model", "text": result["reply"]})

    _send_whatsapp_message(from_number, result["reply"], phone_number_id)
    return {"status": "sent"}
