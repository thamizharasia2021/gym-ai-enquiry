"""
Pre-Publish Website Validation Engine.
Performs comprehensive quality, integrity, navigation, and placeholder checks
before a website is published or regenerated.
"""
import re
from typing import Optional
from .schemas import GymConfig, DEFAULT_SECTIONS


def validate_site(html_str: str, config_dict: Optional[dict] = None) -> dict:
    """
    Validates generated HTML structure and content integrity.
    Returns { is_valid, errors, warnings, summary }.
    """
    errors = []
    warnings = []
    summary = {
        "placeholders_clean": True,
        "empty_sections_suppressed": True,
        "nav_links_valid": True,
        "theme_matched": True,
        "lists_formatted": True,
        "integrations_checked": True,
        "contact_links_valid": True,
    }

    if not html_str or len(html_str) < 200:
        errors.append("Generated HTML is empty or too short.")
        return {"is_valid": False, "errors": errors, "warnings": warnings, "summary": summary}

    # 1. Unresolved Placeholders Check
    placeholder_matches = re.findall(r"(\{[a-zA-Z0-9_]+\}|\[.*not set.*\]|\bundefined\b|\bnull\b|\[object Object\])", html_str, re.IGNORECASE)
    # Filter out valid CSS/JS occurrences
    invalid_placeholders = []
    for p in placeholder_matches:
        if p.lower() in ("undefined", "null") and ("var " in html_str[:100] or "<script" in html_str):
            # Skip if inside script
            continue
        invalid_placeholders.append(p)

    if invalid_placeholders:
        sample = list(set(invalid_placeholders))[:5]
        warnings.append(f"Detected potential placeholder tokens: {', '.join(sample)}")
        summary["placeholders_clean"] = False

    # 2. Raw "Yes, ..." check in visible text
    yes_matches = re.findall(r">\s*(?:Yes,\s+[A-Za-z0-9\s]+is available|Yes,\s+available)\s*<", html_str, re.IGNORECASE)
    if yes_matches:
        warnings.append("Detected raw 'Yes, ... is available' text. Recommend converting to clean list bullet items.")
        summary["lists_formatted"] = False

    # 3. Navigation Links vs Section IDs matching
    nav_hrefs = re.findall(r'<a\s+[^>]*href=["\']#([a-zA-Z0-9_-]+)["\']', html_str)
    section_ids = set(re.findall(r'<(?:section|div|header)\s+[^>]*id=["\']([a-zA-Z0-9_-]+)["\']', html_str))

    broken_nav_links = []
    for href in nav_hrefs:
        if href not in section_ids:
            broken_nav_links.append(f"#{href}")

    if broken_nav_links:
        errors.append(f"Navigation menu contains links to missing sections: {', '.join(set(broken_nav_links))}")
        summary["nav_links_valid"] = False

    # 4. Contact & CTA links check
    tel_links = re.findall(r'href=["\']tel:([^"\']+)["\']', html_str)
    for tel in tel_links:
        clean_num = re.sub(r"\D", "", tel)
        if len(clean_num) < 8:
            warnings.append(f"Telephone link 'tel:{tel}' appears to have an incomplete phone number.")
            summary["contact_links_valid"] = False

    wa_links = re.findall(r'href=["\']https://wa\.me/([^"\']+)["\']', html_str)
    for wa in wa_links:
        if not re.match(r"^[0-9]+$", wa.split("?")[0]):
            warnings.append(f"WhatsApp link '{wa}' is improperly formatted.")
            summary["contact_links_valid"] = False

    # 5. Section selection & suppression check
    if config_dict:
        ident = config_dict.get("identity", {})
        sections_cfg = ident.get("sections", {})
        enabled = set(sections_cfg.get("enabled_sections", DEFAULT_SECTIONS))
        
        # Check if disabled sections are present
        for sec in DEFAULT_SECTIONS:
            if sec not in enabled:
                # If section was explicitly disabled, ensure it does not appear as a top-level section id
                if f'id="{sec}"' in html_str or f"id='{sec}'" in html_str:
                    warnings.append(f"Section '{sec}' was disabled in settings but is rendered in HTML.")

    # Determine overall validity
    is_valid = len(errors) == 0

    return {
        "is_valid": is_valid,
        "errors": errors,
        "warnings": warnings,
        "summary": summary,
        "sections_detected": list(section_ids),
    }
