"""
WeCord Bridge v2 — 全部 AI 通过 Gist，含真实文章测试端点
"""
import asyncio
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
WERSS_BASE_URL = os.environ.get("WERSS_BASE_URL", "http://we-mp-rss:8001")
WERSS_AK = os.environ.get("WERSS_AK", "")
WERSS_SK = os.environ.get("WERSS_SK", "")

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


async def gist_translate(entry_id: str, content: str, title: str, retries: int = 2) -> bool:
    """Trigger Gist AI translate with retry. Drains SSE to populate cache."""
    await gist_login()
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=300) as c:
                r = await c.post(f"{GIST_BASE_URL}/api/ai/translate", headers=_hdr(), json={
                    "entryId": entry_id, "content": content, "title": title,
                    "isReadability": False,
                })
                ct = r.headers.get("Content-Type", "")
                if "application/json" in ct:
                    logger.info("Translate cache hit #%s", entry_id)
                    return True
                if "text/event-stream" in ct:
                    logger.info("Translate SSE #%s (attempt %d)...", entry_id, attempt + 1)
                    async for _ in r.aiter_lines():
                        pass
                    logger.info("Translate done #%s", entry_id)
                    return True
                logger.warning("Translate unexpected ct=%s #%s", ct, entry_id)
        except Exception as e:
            logger.warning("Translate attempt %d failed #%s: %s", attempt + 1, entry_id, e)
            if attempt < retries:
                await asyncio.sleep(3)
    logger.error("Translate exhausted retries for #%s", entry_id)
    return False


# ══════════════════════════════════════════════════════════════
#  we-mp-rss helpers
# ══════════════════════════════════════════════════════════════

def _werss_auth() -> dict:
    if WERSS_AK and WERSS_SK:
        return {"Authorization": f"AK-SK {WERSS_AK}:{WERSS_SK}"}
    return {}


async def werss_find_article(url: str) -> Optional[dict]:
    """Search we-mp-rss for an article by URL."""
    if not WERSS_AK:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                f"{WERSS_BASE_URL}/api/v1/wx/articles",
                headers=_werss_auth(),
                params={"search": url, "limit": 1},
            )
            if r.status_code == 200:
                data = r.json()
                items = data.get("items") or data.get("data") or []
                for item in (items if isinstance(items, list) else [items]):
                    return item
    except Exception as e:
        logger.warning("werss search failed: %s", e)
    return None


async def werss_refresh_article(article_id: str) -> bool:
    """Trigger we-mp-rss to re-fetch article content. Waits for completion."""
    if not WERSS_AK:
        return False
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"{WERSS_BASE_URL}/api/v1/wx/articles/{article_id}/refresh",
                headers=_werss_auth(),
            )
            if r.status_code != 200:
                return False
            task = r.json().get("data", {})
            task_id = task.get("task_id") or task.get("id", "")
            if not task_id:
                return True  # no task id, assume done

        # Poll for completion (max 60s)
        for _ in range(12):
            await asyncio.sleep(5)
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(
                    f"{WERSS_BASE_URL}/api/v1/wx/articles/refresh/tasks/{task_id}",
                    headers=_werss_auth(),
                )
                if r.status_code == 200:
                    status = r.json().get("status", "")
                    if status in ("completed", "success", "done"):
                        return True
                    if status in ("failed", "error"):
                        return False
        return False
    except Exception as e:
        logger.warning("werss refresh failed: %s", e)
        return False


async def ensure_full_content(ge: dict) -> dict:
    """
    If Gist entry content is too short, trigger we-mp-rss refresh +
    Gist re-sync to get complete content.
    Returns the (possibly updated) entry dict.
    """
    content = ge.get("content") or ""
    if len(content) >= 50:
        return ge

    eid = ge["id"]
    url = ge.get("url", "")
    logger.info("Short content #%s (%d chars), attempting auto-fix...", eid, len(content))

    # 1. Find article in we-mp-rss and trigger refresh
    if WERSS_AK and url:
        article = await werss_find_article(url)
        if article:
            aid = article.get("id") or article.get("article_id", "")
            if aid:
                logger.info("  we-mp-rss refresh #%s...", aid)
                await werss_refresh_article(aid)

    # 2. Trigger Gist re-sync
    await gist_refresh()
    await asyncio.sleep(15)

    # 3. Re-fetch from Gist
    ge2 = await gist_get_entry(eid)
    if ge2 and len(ge2.get("content") or "") > len(content):
        logger.info("  content improved: %d → %d chars", len(content), len(ge2["content"]))
        return ge2

    logger.info("  content unchanged (%d chars)", len(content))
    return ge


# ══════════════════════════════════════════════════════════════
#  Discord
# ══════════════════════════════════════════════════════════════

def gist_entry_url(entry: dict) -> str:
    """Build Gist URL for Discord users: /feed/{feedId}/{entryId}?type=article"""
    fid = entry.get("feedId", "")
    eid = entry.get("id", "")
    return f"{GIST_PUBLIC_URL}/feed/{fid}/{eid}?type=article"


def build_embed(feed_name: str, title_en: str, summary_en: str,
                article_url: str, gist_url: str, *,
                test: bool = False, translating: bool = False) -> dict:
    if gist_url and translating:
        status = "⏳ English translation in progress (may take 1-3 min)"
    elif gist_url:
        status = "📖 English translation ready"
    else:
        status = "⚠️ Translation unavailable"
    return {
        "title": (("🧪 [TEST] " if test else "") + title_en)[:256],
        "url": article_url,
        "description": summary_en[:4096],
        "color": 0xED5B2D,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "footer": {"text": f"via {feed_name} · WeCord"},
        "fields": [
            {"name": status,
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
    """Process one article: ensure full content, summarize, translate, return embed."""
    eid = gist_entry["id"]

    # Ensure we have full content (auto-fix via we-mp-rss + Gist sync)
    gist_entry = await ensure_full_content(gist_entry)
    gurl = gist_entry_url(gist_entry)
    full = await gist_get_entry(eid)
    content = (full or {}).get("content") or summary_cn

    # Summarize via Gist AI
    try:
        summary_en = await gist_summarize(eid, content, title_cn)
        logger.info("  summary: %d chars", len(summary_en))
    except Exception as e:
        logger.error("  summarize error: %s", e)
        summary_en = summary_cn[:MAX_SUMMARY_CHARS]

    # Translate — wait for completion so cache is ready before Discord push
    ok = False
    try:
        ok = await gist_translate(eid, content, title_cn)
    except Exception as e:
        logger.warning("  translate error: %s", e)

    return build_embed(feed_name="", title_en=title_cn,
                       summary_en=summary_en,
                       article_url=article_url, gist_url=gurl, test=test,
                       translating=not ok)


async def process_articles(articles: list[dict], feed_name: str, *,
                           test: bool = False) -> dict:
    logs, embeds = [], []
    for i, a in enumerate(articles):
        t = a.get("title", "?")
        d = a.get("description", "")
        u = a.get("url", "")
        logger.info("[%d/%d] %s", i + 1, len(articles), t[:60])

        # Look up Gist entry by URL — retry if Gist hasn't synced yet
        ge = await gist_find_entry(u)
        if not ge:
            await gist_refresh()
            for attempt in range(3):  # wait up to ~30s for Gist to finish refresh
                logger.info("  waiting for Gist to sync (attempt %d)…", attempt + 1)
                await asyncio.sleep(10)
                ge = await gist_find_entry(u)
                if ge:
                    break
        if not ge:
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


@app.get("/diag/{entry_id}")
async def diag(entry_id: str):
    """Diagnose: show entry content length and preview."""
    await gist_login()
    ge = await gist_get_entry(entry_id)
    if not ge:
        return JSONResponse({"error": "not found"}, status_code=404)
    content = ge.get("content") or ""
    return JSONResponse({
        "id": entry_id,
        "title": ge.get("title"),
        "url": ge.get("url"),
        "content_len": len(content),
        "content_preview": content[:300],
        "feed_id": ge.get("feedId"),
    })


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


@app.post("/push/latest")
async def push_latest_one():
    return await push_latest(n=1)


@app.post("/push/latest/{n}")
async def push_latest(n: int = 1):
    """Push the latest N entries from Gist. n=1 pushes the newest."""
    await gist_login()
    entries = await gist_get_entries(GIST_FEED_ID, max(n, 1))
    if not entries:
        return JSONResponse({"error": "No entries in Gist"}, status_code=404)
    results = []
    for e in entries[:n]:
        results.append(await _push_entry(e["id"]))
    return JSONResponse({"pushed": len(results), "results": results})


@app.post("/push/{entry_id}")
async def push(entry_id: str):
    """Push a single Gist entry to Discord (no test prefix)."""
    return JSONResponse(await _push_entry(entry_id))


@app.post("/retranslate/{entry_id}")
async def retranslate(entry_id: str):
    """Force re-translate: delete old cache, then warm Gist cache fresh."""
    await gist_login()
    ge = await gist_get_entry(entry_id)
    if not ge:
        return JSONResponse({"error": f"Entry {entry_id} not found"}, status_code=404)
    content = (ge.get("content") or "")
    title = ge.get("title") or ""

    # Delete stale cache first
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.delete(f"{GIST_BASE_URL}/api/ai/translations/{entry_id}", headers=_hdr())
            logger.info("Retranslate: deleted old cache #%s → %s", entry_id, r.status_code)
    except Exception as e:
        logger.warning("Retranslate: delete failed (continuing): %s", e)

    logger.info("RETRANSLATE: #%s (%d chars)", entry_id, len(content))
    ok = await gist_translate(entry_id, content, title)
    return JSONResponse({"entry_id": entry_id, "cached": ok})


async def _push_entry(entry_id: str) -> dict:
    """Internal: fetch and push one entry (auto-fixes short content)."""
    ge = await gist_get_entry(entry_id)
    if not ge:
        return {"error": f"Entry {entry_id} not found"}
    t = ge.get("title") or "(no title)"
    content = ge.get("content") or ""
    d = content[:500]
    u = ge.get("url") or ""
    logger.info("PUSH: #%s %s (%d chars)", entry_id, t[:60], len(content))
    embed = await process_one(t, d, u, ge, test=False)
    await send_discord([embed])
    return {"status": "sent", "entry_id": entry_id, "title": t,
            "content_len": len(content)}


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