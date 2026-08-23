"""
Turns a submitted GymConfig into:
  1. A resolved, human-readable Q&A knowledge PDF (the artifact the owner
     reviews/approves and that becomes the RAG source document).
  2. A flat list of (question, answer, metadata) chunks ready for embedding —
     returned alongside the PDF so main.py can hand them straight to the
     vector store without re-parsing the PDF.

Design choice: we DON'T embed the PDF bytes themselves. PDF text extraction
is lossy and unnecessary here — we already have the structured answer text
in memory, so we embed that directly and only render the PDF for human
review / audit trail / re-upload elsewhere.
"""
import json
import os
import re
from datetime import date
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ReportLab's built-in Helvetica has no glyph for ₹ (and most non-Latin1
# symbols) — it silently prints a placeholder box instead, which then
# extracts as garbage text if the PDF is re-parsed (see pdf_ingest.py).
# Register a Unicode-capable font so prices/currency always render and
# extract correctly.
_FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
]
BASE_FONT, BOLD_FONT = "Helvetica", "Helvetica-Bold"
for _regular, _bold in _FONT_CANDIDATES:
    if os.path.exists(_regular) and os.path.exists(_bold):
        pdfmetrics.registerFont(TTFont("DejaVuSans", _regular))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", _bold))
        BASE_FONT, BOLD_FONT = "DejaVuSans", "DejaVuSans-Bold"
        break
# If neither path exists (different OS/container), Helvetica is the
# fallback — currency symbols may render as boxes there; install
# fonts-dejavu-core (Debian/Ubuntu) to fix.

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "qa_schema.json")
with open(SCHEMA_PATH) as f:
    QA_SCHEMA = json.load(f)
QA_BY_ID = {q["id"]: q for q in QA_SCHEMA}

UNANSWERED_FALLBACK = "I don't have confirmed information about this yet. Would you like me to connect you with the gym team?"


def resolve_answers(config) -> list[dict]:
    """
    For every canonical question, resolve the owner's selection into final
    text. Unconfigured questions fall back to the safe 'unknown' answer so
    the assistant never guesses.
    Returns: list of {id, category, question, answer, intent} dicts.
    """
    selections = {a.id: a for a in config.answers}
    resolved = []
    for q in QA_SCHEMA:
        sel = selections.get(q["id"])
        answer_text = UNANSWERED_FALLBACK
        if sel:
            situation = next(
                (s for s in q["situations"] if s["label"] == sel.situation_label), None
            )
            if situation:
                text = situation["template"]
                for field in situation["fields"]:
                    val = sel.field_values.get(field, "").strip()
                    text = text.replace("{" + field + "}", val if val else f"[{field} not set]")
                answer_text = text
        resolved.append({
            "id": q["id"],
            "category": q["category"],
            "category_code": q["category_code"],
            "question": q["question"],
            "intent": q["intent"],
            "answer": answer_text,
            "configured": sel is not None,
        })
    return resolved


def _identity_dict(identity) -> dict:
    """Normalizes either a GymIdentity pydantic model (wizard path) or a
    plain dict (PDF-only ingestion path, from extract_identity()) into one
    shape so render_pdf() doesn't care which source it came from."""
    if hasattr(identity, "model_dump"):
        return identity.model_dump()
    return dict(identity or {})


def render_pdf(identity, resolved: list[dict], custom_qa: list, gym_id: str, output_path: str, source_note: str = "owner configuration wizard"):
    """Pure rendering: takes already-resolved Q&A data (from either
    resolve_answers() for a wizard config, or a merged view built by
    /ingest-pdf) and writes the knowledge PDF. Always includes the full
    identity header + contact table + membership/plan answers + every
    category, regardless of which path produced `resolved` — so "View PDF"
    never shows a different document than what's actually indexed."""
    ident = _identity_dict(identity)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleX", parent=styles["Title"], fontName=BOLD_FONT, fontSize=20, spaceAfter=4)
    sub_style = ParagraphStyle("Sub", parent=styles["Normal"], fontName=BASE_FONT, textColor=colors.grey, fontSize=10)
    section_style = ParagraphStyle("Section", parent=styles["Heading2"], fontName=BOLD_FONT, fontSize=13, spaceBefore=14, spaceAfter=6,
                                    textColor=colors.HexColor("#0f172a"))
    cat_style = ParagraphStyle("Cat", parent=styles["Heading1"], fontName=BOLD_FONT, fontSize=15, spaceBefore=16, spaceAfter=6,
                                textColor=colors.HexColor("#1a3c34"))
    q_style = ParagraphStyle("Q", parent=styles["Heading3"], fontName=BOLD_FONT, fontSize=11, spaceBefore=10, spaceAfter=2,
                              textColor=colors.HexColor("#0f172a"))
    a_style = ParagraphStyle("A", parent=styles["Normal"], fontName=BASE_FONT, fontSize=10, leading=14, spaceAfter=2)
    meta_style = ParagraphStyle("Meta", parent=styles["Normal"], fontName=BASE_FONT, fontSize=7.5, textColor=colors.grey)

    doc = SimpleDocTemplate(output_path, pagesize=A4,
                             topMargin=20 * mm, bottomMargin=18 * mm,
                             leftMargin=18 * mm, rightMargin=18 * mm)
    story = []

    gym_name = ident.get("gym_name") or gym_id
    story.append(Paragraph(f"{gym_name} — AI Assistant Knowledge Base", title_style))
    story.append(Paragraph(
        f"Generated {date.today().isoformat()} · gym_id: {gym_id} · Source: {source_note}", sub_style))
    if ident.get("short_description"):
        story.append(Spacer(1, 6))
        story.append(Paragraph(ident["short_description"], a_style))
    story.append(Spacer(1, 4))

    # ---- Gym Identity section — always present, regardless of source -----
    story.append(Paragraph("Gym Identity", section_style))
    contact_rows = [
        ["Brand name", ident.get("brand_name") or "—", "Member count", ident.get("member_count_range") or "—"],
        ["Phone", ident.get("primary_phone") or "—", "WhatsApp", ident.get("whatsapp_number") or "—"],
        ["Email", ident.get("email") or "—", "Website", ident.get("website") or "—"],
        ["City", ident.get("city") or "—", "Maps", ident.get("google_maps_url") or "—"],
        ["Instagram", ident.get("instagram_url") or "—", "", ""],
    ]
    t = Table(contact_rows, colWidths=[25 * mm, 65 * mm, 25 * mm, 65 * mm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), BASE_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.grey),
        ("TEXTCOLOR", (2, 0), (2, -1), colors.grey),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#e5e7eb")),
    ]))
    story.append(t)

    # ---- Membership Plans summary — pulled straight out of the resolved --
    # ---- Membership & Offers answers so it's impossible for this to drift
    # ---- out of sync with what the chatbot actually says ------------------
    mem_items = [r for r in resolved if r["category_code"] == "MEM" and r["configured"]]
    if mem_items:
        story.append(Paragraph("Membership Plans & Offers (configured)", section_style))
        for item in mem_items:
            story.append(Paragraph(f"• {item['question']}", a_style))
            story.append(Paragraph(item["answer"], meta_style))
    story.append(PageBreak())

    current_cat = None
    for item in resolved:
        if item["category"] != current_cat:
            current_cat = item["category"]
            story.append(Paragraph(current_cat, cat_style))
        story.append(Paragraph(f"{item['id']} — {item['question']}", q_style))
        story.append(Paragraph(item["answer"], a_style))
        flag = "" if item["configured"] else "  (not configured — safe fallback shown)"
        story.append(Paragraph(f"intent: {item['intent']}{flag}", meta_style))

    if custom_qa:
        story.append(Paragraph("Custom Questions (owner-added)", cat_style))
        for i, cqa in enumerate(custom_qa, start=1):
            question = cqa.question if hasattr(cqa, "question") else cqa["question"]
            answer = cqa.answer if hasattr(cqa, "answer") else cqa["answer"]
            story.append(Paragraph(f"CUSTOM_{i} — {question}", q_style))
            story.append(Paragraph(answer, a_style))

    doc.build(story)


def build_pdf(config, output_path: str) -> list[dict]:
    resolved = resolve_answers(config)
    render_pdf(config.identity, resolved, config.custom_qa, config.gym_id, output_path,
               source_note="owner configuration wizard")
    return resolved


def build_rag_chunks_from_resolved(gym_id: str, resolved: list[dict], custom_qa: list) -> list[dict]:
    """
    Convert resolved Q&A pairs into embedding-ready chunks. One chunk per
    question keeps retrieval precise (each chunk maps to exactly one intent),
    which matters more here than long-context chunking would. `resolved`
    should already be filtered to configured-only items — this doesn't
    re-check, so callers merging multiple sources (wizard + PDF import) can
    pass in exactly the set they want embedded.
    """
    chunks = []
    for item in resolved:
        text = f"Category: {item['category']}\nQ: {item['question']}\nA: {item['answer']}"
        chunks.append({
            "id": f"{gym_id}::{item['id']}",
            "text": text,
            "metadata": {
                "gym_id": gym_id,
                "question_id": item["id"],
                "category": item["category_code"],
                "intent": item["intent"],
                "question": item["question"],
                "answer": item["answer"],
            },
        })

    # owner-authored custom Q&A gets embedded the same way, under its own
    # synthetic ids/category so it's retrievable just like canonical answers
    for i, cqa in enumerate(custom_qa, start=1):
        qid = f"CUSTOM_{i}"
        question = cqa.question if hasattr(cqa, "question") else cqa["question"]
        answer = cqa.answer if hasattr(cqa, "answer") else cqa["answer"]
        text = f"Category: Custom Questions\nQ: {question}\nA: {answer}"
        chunks.append({
            "id": f"{gym_id}::{qid}",
            "text": text,
            "metadata": {
                "gym_id": gym_id,
                "question_id": qid,
                "category": "CUSTOM",
                "intent": "custom_question",
                "question": question,
                "answer": answer,
            },
        })
    return chunks


def build_rag_chunks(config, resolved: list[dict]) -> list[dict]:
    """Back-compat wrapper around build_rag_chunks_from_resolved() for
    callers that still have a full GymConfig object (the /config endpoint)."""
    configured_only = [r for r in resolved if r["configured"]]
    return build_rag_chunks_from_resolved(config.gym_id, configured_only, config.custom_qa)
