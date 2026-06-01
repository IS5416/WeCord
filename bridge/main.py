"""
WeCord Bridge v2 — 全部 AI 通过 Gist，含真实文章测试端点
"""
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("wecord-bridge")

DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
GIST_BASE_URL = os.environ.get("GIST_BASE_URL", "http://gist:8080")
GIST_PUBLIC_URL = os.environ.get("GIST_PUBLIC_URL", GIST_BASE_URL)
GIST_USERNAME = os.environ.get("GIST_USERNAME", "")
GIST_PASSWORD = os.environ.get("GIST_PASSWORD", "")
GIST_FEED_ID = os.environ.get("GIST_FEED_ID", "")
MAX_SUMMARY_CHARS = int(os.environ.get("MAX_SUMMARY_CHARS", "300"))

_gist_token: str = ""
_gist_token_expiry: float = 0.0

app = FastAPI(title="WeCord Bridge", version="2.0.0")


async def gist_login() -> str:
    global _gist_token, _gist_token_expiry
    if _gist_token and time.time() < _gist_token_expiry - 300:
        return _gist_token
    if not GIST_USERNAME or not GIST_PASSWORD:
        return ""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{GIST_BASE_URL}/api/auth/login",
                         json={"identifier": GIST_USERNAME, "password": GIST_PASSWORD})
        if r.status_code != 200:
            raise RuntimeError(f"Gist login: {r.status_code}")
        d = r.json()
        _gist_token = d["token"]
        _gist_token_expiry = time.time() + 29 * 24 * 3600
        logger.info("Gist login OK")
        return _gist_token


def _hdr() -> dict:
    return {"Authorization": f"Bearer {_gist_token or ''}"}


# ══════════════════════════════════════════════════════════════
#  Gist API
# ══════════════════════════════════════════════════════════════

async def gist_refresh() -> None:
    """Fire-and-forget: trigger Gist refresh, don't wait for result."""
    try:
        await gist_login()
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{GIST_BASE_URL}/api/feeds/refresh", headers=_hdr())
            logger.info("Gist refresh triggered: %s", r.status_code)
    except Exception as e:
        logger.warning("Gist refresh skipped: %s", e)


async def gist_get_entries(feed_id: str = "", limit: int = 200) -> list[dict]:
    await gist_login()
    params = {"limit": limit}
    if feed_id:
        params["feedId"] = feed_id
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{GIST_BASE_URL}/api/entries", headers=_hdr(), params=params)
        if r.status_code != 200:
            return []
        return r.json().get("entries", [])


async def gist_find_entry(url: str) -> Optional[dict]:
    entries = await gist_get_entries(GIST_FEED_ID, 200)
    url = url.rstrip("/")
    for e in entries:
        eu = (e.get("url") or "").rstrip("/")
        if eu == url or eu.replace("https://", "http://") == url.replace("https://", "http://"):
            return e
    return None


async def gist_get_entry(entry_id: str) -> Optional[dict]:
    await gist_login()
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{GIST_BASE_URL}/api/entries/{entry_id}", headers=_hdr())
        return r.json() if r.status_code == 200 else None


async def gist_summarize(entry_id: str, content: str, title: str) -> str:
    """Call Gist AI summarize. Returns cached result instantly or consumes SSE."""
    await gist_login()
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post(f"{GIST_BASE_URL}/api/ai/summarize", headers=_hdr(), json={
            "entryId": entry_id, "content": content, "title": title, "isReadability": False,
        })
        ct = r.headers.get("Content-Type", "")
        if "application/json" in ct:
            s = r.json().get("summary", "")
            logger.info("Summarize cache hit #%s (%d chars)", entry_id, len(s))
            return s[:MAX_SUMMARY_CHARS]
        chunks = []
        async for chunk in r.aiter_bytes():
            try:
                chunks.append(chunk.decode("utf-8"))
            except Exception:
                pass
        s = "".join(chunks).strip()
        logger.info("Summarize stream done #%s (%d chars)", entry_id, len(s))
        return s[:MAX_SUMMARY_CHARS]


async def gist_translate(entry_id: str, content: str, title: str) -> bool:
    """Trigger Gist AI translate. Drains SSE to populate cache."""
    await gist_login()
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{GIST_BASE_URL}/api/ai/translate", headers=_hdr(), json={
            "entryId": entry_id, "content": content, "title": title, "isReadability": False,
        })
        ct = r.headers.get("Content-Type", "")
        if "application/json" in ct:
            logger.info("Translate cache hit #%s", entry_id)
            return True
        if "text/event-stream" in ct:
            logger.info("Translate SSE #%s...", entry_id)
            async for _ in r.aiter_lines():
                pass
            logger.info("Translate done #%s", entry_id)
            return True
        return False


# ══════════════════════════════════════════════════════════════
#  Discord
# ══════════════════════════════════════════════════════════════

def gist_entry_url(entry: dict) -> str:
    """Build Gist URL for Discord users: /feed/{feedId}/{entryId}?type=article"""
    fid = entry.get("feedId", "")
    eid = entry.get("id", "")
    return f"{GIST_PUBLIC_URL}/feed/{fid}/{eid}?type=article"


def build_embed(feed_name: str, title_en: str, summary_en: str,
                article_url: str, gist_url: str, *, test: bool = False) -> dict:
    # Discord limits: title 256, description 4096, field value 1024
    # Note: embed "url" must be publicly reachable — use original URL, not internal Gist
    return {
        "title": (("🧪 [TEST] " if test else "") + title_en)[:256],
        "url": article_url,
        "description": summary_en[:4096],
        "color": 0xED5B2D,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "footer": {"text": f"via {feed_name} · WeCord"},
        "fields": [
            {"name": "Read Full Translation",
             "value": f"[Open in Gist]({gist_url})" if gist_url else article_url,
             "inline": False},
        ] + ([{"name": "Mode", "value": "🧪 Test", "inline": True}] if test else []),
    }


async def send_discord(embeds: list[dict]) -> None:
    payload = {"embeds": embeds}
    headers = {"Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(DISCORD_WEBHOOK_URL, json=payload, headers=headers)
        if r.status_code == 204:
            logger.info("Discord OK (%d)", len(embeds))
        else:
            logger.error("Discord fail: %s", r.status_code)
            logger.error("Payload: %s", json.dumps(payload, ensure_ascii=False)[:800])


# ══════════════════════════════════════════════════════════════
#  Core
# ══════════════════════════════════════════════════════════════

async def process_one(title_cn: str, summary_cn: str, article_url: str,
                      gist_entry: dict, *, test: bool = False) -> dict:
    """Process one article: summarize, translate, return embed."""
    eid = gist_entry["id"]
    gurl = gist_entry_url(gist_entry)

    # Get full content
    full = await gist_get_entry(eid)
    content = (full or {}).get("content") or summary_cn

    # Summarize via Gist AI
    try:
        summary_en = await gist_summarize(eid, content, title_cn)
        logger.info("  summary: %d chars", len(summary_en))
    except Exception as e:
        logger.error("  summarize error: %s", e)
        summary_en = summary_cn[:MAX_SUMMARY_CHARS]

    # Translate (best-effort, drains SSE to populate cache)
    try:
        await gist_translate(eid, content, title_cn)
    except Exception as e:
        logger.warning("  translate error: %s", e)

    return build_embed(feed_name="", title_en=title_cn,
                       summary_en=summary_en,
                       article_url=article_url, gist_url=gurl, test=test)


async def process_articles(articles: list[dict], feed_name: str, *,
                           test: bool = False) -> dict:
    logs, embeds = [], []
    for i, a in enumerate(articles):
        t = a.get("title", "?")
        d = a.get("description", "")
        u = a.get("url", "")
        logger.info("[%d/%d] %s", i + 1, len(articles), t[:60])

        # Look up Gist entry by URL
        ge = await gist_find_entry(u)
        if not ge:
            # Maybe Gist hasn't synced yet — trigger refresh (best-effort)
            await gist_refresh()
            logs.append(f"Not found in Gist: {t[:30]}…")
            embeds.append(build_embed(
                feed_name, t, d[:MAX_SUMMARY_CHARS], u, "", test=test))
            continue

        logs.append(f"Gist #{ge['id']}")
        embeds.append(await process_one(t, d, u, ge, test=test))

    if embeds:
        await send_discord(embeds)
    return {"status": "ok", "sent": len(embeds), "logs": logs}


# ══════════════════════════════════════════════════════════════
#  Endpoints
# ══════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    return {"status": "ok", "gist_token": bool(_gist_token)}


@app.post("/webhook")
async def webhook(request: Request):
    try:
        p = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")
    logger.info("Webhook: %s", json.dumps(p, ensure_ascii=False)[:500])
    feed = p.get("feed", {})
    return JSONResponse(await process_articles(
        p.get("articles", []), feed.get("name", "")))


@app.post("/test")
async def test():
    """
    Fetch real entries from Gist (via API), run full summarize + translate +
    Discord pipeline. Uses Gist's existing AI cache — no extra token cost
    for already-translated articles.
    """
    await gist_login()
    entries = await gist_get_entries(GIST_FEED_ID, 3)
    if not entries:
        return JSONResponse({"error": "No entries found in Gist. "
                             "Make sure GIST_FEED_ID is correct and Gist has synced RSS."})

    # Convert Gist entries to article format expected by process_articles
    articles = []
    for e in entries:
        articles.append({
            "title": e.get("title") or "(no title)",
            "description": (e.get("content") or "")[:500],
            "url": e.get("url") or "",
        })

    logger.info("TEST: %d real entries from Gist feed %s", len(articles), GIST_FEED_ID or "all")
    result = await process_articles(articles, "Gist Test", test=True)
    return JSONResponse({"test": True, "source": "gist", **result})