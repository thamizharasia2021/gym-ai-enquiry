"""
Official Instagram Graph API & oEmbed Integration.
Handles media fetching for Instagram Creator/Business accounts,
supports dedicated post/Reel URLs for Transformations, Events, and About Us,
and generates responsive oEmbed embed structures.
"""
import json
import os
import time
import httpx
from typing import Optional

from . import config


def clean_instagram_post_url(url: Optional[str]) -> Optional[str]:
    """Cleans and standardizes an Instagram post or reel URL for oEmbed."""
    if not url:
        return None
    url = url.strip()
    if not url.startswith("http"):
        return None
    # Remove query strings
    base = url.split("?")[0].rstrip("/")
    if not base.endswith("/"):
        base += "/"
    return base


def get_instagram_embed_url(url: Optional[str]) -> Optional[str]:
    """Generates the iframe-compatible /embed/ URL for an Instagram post or Reel."""
    clean = clean_instagram_post_url(url)
    if not clean:
        return None
    return f"{clean}embed"


def fetch_instagram_media(access_token: Optional[str] = None, user_id: Optional[str] = None, limit: int = 12) -> list[dict]:
    """
    Fetches recent media (posts, carousels, videos/Reels) using the official Instagram Graph API.
    Never scrapes web pages.
    """
    token = access_token or config.INSTAGRAM_ACCESS_TOKEN
    if not token:
        return []

    endpoint = "https://graph.instagram.com/me/media"
    params = {
        "fields": "id,caption,media_type,media_url,permalink,thumbnail_url,timestamp",
        "access_token": token,
        "limit": limit,
    }
    try:
        with httpx.Client(timeout=10) as client:
            res = client.get(endpoint, params=params)
            if res.status_code == 200:
                data = res.json()
                raw_items = data.get("data", [])
                
                media_list = []
                for item in raw_items:
                    img_url = item.get("media_url")
                    if item.get("media_type") == "VIDEO":
                        img_url = item.get("thumbnail_url") or item.get("media_url")

                    media_list.append({
                        "id": item.get("id"),
                        "caption": (item.get("caption") or "Gym workout motivation").strip()[:100],
                        "media_type": item.get("media_type", "IMAGE"),
                        "media_url": img_url,
                        "permalink": item.get("permalink", "https://instagram.com"),
                        "timestamp": item.get("timestamp"),
                    })
                return media_list
            else:
                print(f"[InstagramAPI] Response error {res.status_code}: {res.text}")
    except Exception as e:
        print(f"[InstagramAPI] Error fetching media: {e}")

    return []


def sync_instagram_media(gym_id: str, access_token: Optional[str] = None) -> dict:
    """Synchronizes Instagram media feed, oEmbed links, and saves cache to gym config."""
    cfg_path = os.path.join(config.DATA_DIR, f"{gym_id}.config.json")
    if not os.path.exists(cfg_path):
        return {"status": "error", "message": f"Config not found for {gym_id}"}

    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    ident = cfg.get("identity", {})
    ig_cfg = ident.get("instagram", {})
    token = access_token or config.INSTAGRAM_ACCESS_TOKEN

    # Sync custom category URLs
    if ident.get("instagram_transformation_url"):
        ig_cfg["transformation_url"] = ident["instagram_transformation_url"]
    if ident.get("instagram_events_url"):
        ig_cfg["events_url"] = ident["instagram_events_url"]
    if ident.get("instagram_about_url"):
        ig_cfg["about_url"] = ident["instagram_about_url"]

    if not token:
        media_list = ig_cfg.get("cached_media", [])
        return {
            "status": "fallback",
            "message": "Instagram Access Token not configured. Using public Instagram profile & oEmbed links.",
            "instagram_url": ident.get("instagram_url") or ig_cfg.get("instagram_url") or "https://instagram.com",
            "instagram_username": ig_cfg.get("instagram_username") or (ident.get("instagram_url", "").split("/")[-1] if ident.get("instagram_url") else ""),
            "transformation_url": ig_cfg.get("transformation_url") or ident.get("instagram_transformation_url"),
            "events_url": ig_cfg.get("events_url") or ident.get("instagram_events_url"),
            "about_url": ig_cfg.get("about_url") or ident.get("instagram_about_url"),
            "cached_media": media_list,
            "media_count": len(media_list),
            "last_synced_at": ig_cfg.get("last_synced_at"),
        }

    media = fetch_instagram_media(token)
    now = time.time()
    
    if media:
        ig_cfg["cached_media"] = media
    ig_cfg["last_synced_at"] = now
    if not ig_cfg.get("instagram_url") and ident.get("instagram_url"):
        ig_cfg["instagram_url"] = ident.get("instagram_url")

    ident["instagram"] = ig_cfg
    cfg["identity"] = ident
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

    return {
        "status": "ok",
        "media_count": len(ig_cfg.get("cached_media", [])),
        "last_synced_at": now,
        "instagram_url": ig_cfg.get("instagram_url"),
        "transformation_url": ig_cfg.get("transformation_url"),
        "events_url": ig_cfg.get("events_url"),
        "about_url": ig_cfg.get("about_url"),
    }
