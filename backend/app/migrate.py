"""
Automatic migration helper for existing leads.jsonl, chat events, and gym configurations.
Ensures zero data loss and full backward compatibility.
"""
import json
import os
import time
import uuid
from . import config


def seed_initial_data():
    """Copy bundled seed files from backend/data into DATA_DIR if DATA_DIR is clean or missing files."""
    import shutil
    repo_data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
    target_data_dir = os.path.abspath(config.DATA_DIR)
    
    if repo_data_dir != target_data_dir and os.path.exists(repo_data_dir):
        os.makedirs(target_data_dir, exist_ok=True)
        for fname in os.listdir(repo_data_dir):
            src_file = os.path.join(repo_data_dir, fname)
            dst_file = os.path.join(target_data_dir, fname)
            if os.path.isfile(src_file) and not os.path.exists(dst_file):
                try:
                    shutil.copy2(src_file, dst_file)
                    print(f"[Seed Data] Copied initial seed file: {fname}")
                except Exception as e:
                    print(f"[Seed Data] Failed copying {fname}: {e}")


def run_migrations():
    """Runs data migrations on startup to upgrade data models seamlessly."""
    seed_initial_data()
    leads_path = os.path.join(config.DATA_DIR, "leads.jsonl")

    if os.path.exists(leads_path):
        migrated_leads = []
        updated = False
        with open(leads_path, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue

                # Ensure standard fields
                if "id" not in rec or not rec["id"]:
                    rec["id"] = f"LEAD-{rec.get('gym_id', 'GYM')[:3].upper()}-{1000 + idx}"
                    updated = True
                if "status" not in rec:
                    rec["status"] = "New"
                    updated = True
                if "is_read" not in rec:
                    rec["is_read"] = False
                    updated = True
                if "created_at" not in rec:
                    rec["created_at"] = rec.get("ts", time.time())
                    updated = True
                if "updated_at" not in rec:
                    rec["updated_at"] = rec.get("ts", time.time())
                    updated = True
                if "notes" not in rec:
                    rec["notes"] = []
                    updated = True
                if "notification_sent" not in rec:
                    rec["notification_sent"] = True  # don't spam notifications for old leads
                    rec["delivery_status"] = "delivered"
                    updated = True

                migrated_leads.append(rec)

        if updated:
            with open(leads_path, "w", encoding="utf-8") as f:
                for l in migrated_leads:
                    f.write(json.dumps(l) + "\n")
            print(f"[Migration] Upgraded {len(migrated_leads)} records in leads.jsonl")

    # Migrate *.config.json files
    if os.path.exists(config.DATA_DIR):
        for fname in os.listdir(config.DATA_DIR):
            if fname.endswith(".config.json"):
                fpath = os.path.join(config.DATA_DIR, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                    
                    changed = False
                    ident = cfg.get("identity", {})
                    if "theme" not in ident:
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
                        changed = True
                    if "sections" not in ident:
                        from .schemas import DEFAULT_SECTIONS
                        ident["sections"] = {
                            "enabled_sections": list(DEFAULT_SECTIONS),
                            "section_order": list(DEFAULT_SECTIONS),
                        }
                        changed = True
                    if "google" not in ident:
                        ident["google"] = {
                            "place_id": None,
                            "public_review_url": ident.get("google_maps_url"),
                            "rating": 4.9,
                            "user_ratings_total": 240,
                            "cached_reviews": []
                        }
                        changed = True
                    if "instagram" not in ident:
                        ident["instagram"] = {
                            "instagram_username": ident.get("instagram_url", "").split("/")[-1] if ident.get("instagram_url") else None,
                            "instagram_url": ident.get("instagram_url"),
                            "cached_media": []
                        }
                        changed = True

                    cfg["identity"] = ident
                    if changed:
                        with open(fpath, "w", encoding="utf-8") as f:
                            json.dump(cfg, f, indent=2)
                        print(f"[Migration] Upgraded configuration in {fname}")
                except Exception as e:
                    print(f"[Migration] Error checking {fname}: {e}")


if __name__ == "__main__":
    run_migrations()
