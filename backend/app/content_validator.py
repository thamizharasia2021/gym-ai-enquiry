"""
Reusable content validation and conditional-rendering utilities.
Guarantees that empty, null, undefined, placeholder, or unanswered fields
are strictly omitted from generated websites and consumer views.
"""
import re
from typing import Any, Optional

INVALID_PATTERNS = {
    "",
    "0",
    "null",
    "undefined",
    "none",
    "n/a",
    "na",
    "nil",
    "zero",
    "no",
    "false",
    "not provided",
    "not set",
    "not available",
    "not offered",
    "unknown",
    "—",
    "-",
}

NEGATIVE_PREFIXES = (
    "we don't",
    "we do not",
    "no,",
    "no ",
    "0 ",
    "not currently",
    "not available",
    "not offered",
    "not provided",
    "i don't have confirmed",
    "sorry,",
    "currently unavailable",
)


def is_valid_value(val: Any) -> bool:
    """Checks whether a field value contains meaningful, displayable information."""
    if val is None:
        return False
    if val == 0 or val == "0" or val is False:
        return False
    if isinstance(val, (int, float)):
        return True
    if isinstance(val, (list, tuple, set, dict)):
        return len(val) > 0
    
    text = str(val).strip()
    if not text:
        return False
    
    low = text.lower()
    if low in INVALID_PATTERNS:
        return False
    
    # Check for placeholder syntax like "{field}" or "[field not set]"
    if re.match(r"^\[.*not set.*\]$", low) or re.match(r"^\{.*\}$", low):
        return False
    
    return True


def clean_text(val: Any, default: str = "") -> str:
    """Sanitizes text, stripping placeholders and returning default if invalid."""
    if not is_valid_value(val):
        return default
    return str(val).strip()


def clean_list(items: list[Any]) -> list[str]:
    """Filters out invalid, empty, or duplicate items while preserving order."""
    seen = set()
    cleaned = []
    for item in items:
        if is_valid_value(item):
            s = str(item).strip()
            if s.lower() not in seen and looks_positive(s):
                seen.add(s.lower())
                cleaned.append(s)
    return cleaned


def looks_positive(text: str) -> bool:
    """Returns True if the resolved text expresses an available/affirmative facility or feature."""
    if not is_valid_value(text):
        return False
    low = text.strip().lower()
    if low in INVALID_PATTERNS:
        return False
    if low.endswith(". 0") or low.endswith(" 0") or "available. 0" in low or "available: 0" in low or "available 0" in low or "count: 0" in low:
        return False
    if any(low.startswith(neg) for neg in NEGATIVE_PREFIXES):
        return False
    return not any(f" {neg}" in low for neg in NEGATIVE_PREFIXES)


# Canonical question IDs to human-readable clean names
FACILITY_NAME_MAP = {
    "PARK_001": "Two-Wheeler & Car Parking",
    "PARK_002": "Dedicated Car Parking",
    "PARK_003": "Valet Parking Service",
    "FAC_001": "Air Conditioning (Fully AC)",
    "FAC_002": "Locker Facility",
    "FAC_003": "Showers & Changing Rooms",
    "FAC_004": "Purified Drinking Water",
    "FAC_005": "High-Speed Member WiFi",
    "FAC_006": "Steam & Sauna Bath",
    "FAC_007": "Cafeteria & Juice Bar",
    "FAC_008": "Music & Sound System",
    "FAC_009": "CCTV Security Surveillance",
    "FAC_010": "First Aid & AED Kit",
    "HYG_001": "Daily Sanitization & Hygiene Protocols",
    "HYG_002": "Shoe Policy / Clean Indoor Footwear",
}

PROGRAM_NAME_MAP = {
    "PROG_001": "Strength & Weight Training",
    "PROG_002": "Cardiovascular Endurance & HIIT",
    "PROG_003": "Personal Training (1-on-1)",
    "PROG_004": "Weight Loss & Body Transformation",
    "PROG_005": "Muscle Building & Hypertrophy",
    "PROG_006": "Functional & Cross-Training",
    "PROG_007": "Yoga & Flexibility Classes",
    "PROG_008": "Zumba & Dance Fitness",
    "PROG_009": "Pilates & Core Conditioning",
    "PROG_010": "Senior Fitness & Mobility",
    "PROG_011": "Youth & Teen Athletic Training",
    "PT_001": "Certified Personal Coaching",
    "PT_002": "Customized Diet & Nutrition Plans",
}

EQUIPMENT_NAME_MAP = {
    "EQP_001": "Heavy Dumbbells & Free Weights",
    "EQP_002": "Olympic Barbells & Bumper Plates",
    "EQP_003": "Squat Racks & Power Cages",
    "EQP_004": "Cable Crossover & Functional Trainer",
    "EQP_005": "Motorized Treadmills",
    "EQP_006": "Ellipticals & Cross-Trainers",
    "EQP_007": "Stationary & Spin Bikes",
    "EQP_008": "Rowing Machines",
    "EQP_009": "Leg Press & Hack Squat Machine",
    "EQP_010": "Lat Pulldown & Seated Row",
    "EQP_011": "Smith Machine",
    "EQP_012": "Chest Press & Pec Deck Fly",
}


def extract_positive_items(resolved_answers: list[dict], name_map: dict[str, str], fallback_category: Optional[str] = None) -> list[str]:
    """
    Transforms resolved canonical QA items into clean, customer-friendly bullet items.
    Filters out 'Yes, ... is available' phrases, keeping only clean item titles.
    """
    items = []
    for r in resolved_answers:
        qid = r.get("id", "")
        answer = r.get("answer", "")
        configured = r.get("configured", False)
        
        if not configured or not looks_positive(answer):
            continue
        
        if qid in name_map:
            items.append(name_map[qid])
        elif fallback_category and r.get("category") == fallback_category:
            # Clean up the question or intent into a clean bullet label
            label = r.get("question", "").replace("Do you have", "").replace("Is there", "").replace("available?", "").replace("?", "").strip()
            if label and is_valid_value(label):
                items.append(label.title())
                
    return clean_list(items)


def validate_gym_section(section_key: str, identity_dict: dict, resolved_answers: list[dict], extra_data: Optional[dict] = None) -> bool:
    """
    Returns True if a specific website section has enough valid, meaningful data to render.
    If all fields in the section are empty, returns False so the entire section is omitted.
    """
    extra = extra_data or {}
    
    if section_key == "hero":
        return bool(is_valid_value(identity_dict.get("gym_name")))
    
    elif section_key == "trust_strip":
        return bool(
            is_valid_value(identity_dict.get("member_count_range")) or
            is_valid_value(identity_dict.get("google", {}).get("rating")) or
            is_valid_value(identity_dict.get("primary_phone"))
        )
        
    elif section_key == "about":
        return bool(
            is_valid_value(identity_dict.get("short_description")) or
            is_valid_value(identity_dict.get("detailed_description")) or
            is_valid_value(identity_dict.get("city"))
        )
        
    elif section_key == "programs":
        programs = extract_positive_items(resolved_answers, PROGRAM_NAME_MAP, fallback_category="Classes & Programs")
        return len(programs) > 0 or bool(extra.get("programs"))
        
    elif section_key == "facilities":
        facilities = extract_positive_items(resolved_answers, FACILITY_NAME_MAP, fallback_category="Parking & Facilities")
        return len(facilities) > 0 or bool(extra.get("facilities"))
        
    elif section_key == "membership":
        plans = extra.get("plans", [])
        return len(plans) > 0 or any(r.get("category_code") == "MEM" and r.get("configured") for r in resolved_answers)
        
    elif section_key == "trainers":
        trainers = extra.get("trainers", [])
        return len(trainers) > 0 or any(r.get("category_code") == "PT" and r.get("configured") for r in resolved_answers)
        
    elif section_key == "reviews":
        google_cfg = identity_dict.get("google", {})
        return bool(
            is_valid_value(identity_dict.get("google_maps_url")) or
            is_valid_value(google_cfg.get("place_id")) or
            len(google_cfg.get("cached_reviews", [])) > 0 or
            extra.get("reviews")
        )
        
    elif section_key == "instagram":
        return bool(
            is_valid_value(identity_dict.get("instagram_url")) or
            is_valid_value(identity_dict.get("instagram", {}).get("instagram_username"))
        )
        
    elif section_key == "timings":
        return any(r.get("category_code") == "TIME" and r.get("configured") for r in resolved_answers) or bool(extra.get("hours"))
        
    elif section_key == "location":
        return bool(
            is_valid_value(identity_dict.get("city")) or
            is_valid_value(identity_dict.get("google_maps_url")) or
            any(r.get("category_code") == "LOC" and r.get("configured") for r in resolved_answers)
        )
        
    elif section_key == "faq":
        faqs = [r for r in resolved_answers if r.get("configured") and is_valid_value(r.get("answer"))]
        return len(faqs) > 0 or bool(extra.get("custom_qa"))
        
    elif section_key == "trial_cta":
        return bool(is_valid_value(identity_dict.get("primary_phone")) or is_valid_value(identity_dict.get("whatsapp_number")))
        
    return True
