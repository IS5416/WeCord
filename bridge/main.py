"""
WeCord Bridge — 微信公众号 → Discord 桥接服务

接收 we-mp-rss webhook → DeepSeek AI 摘要 → Discord Embed 卡片
预翻译：通过 Gist API 触发翻译并消费 SSE 流以写入缓存
"""
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("wecord-bridge")

# ── Config ───────────────────────────────────────────────────
DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
DEEPSEEK_API_KEY = os.environ["DEEPSEEK_API_KEY"]
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
GIST_BASE_URL = os.environ.get("GIST_BASE_URL", "http://gist:8080")
GIST_USERNAME = os.environ.get("GIST_USERNAME", "")
GIST_PASSWORD = os.environ.get("GIST_PASSWORD", "")
GIST_FEED_ID = os.environ.get("GIST_FEED_ID", "")
MAX_SUMMARY_CHARS = int(os.environ.get("MAX_SUMMARY_CHARS", "300"))

_gist_token: Optional[str] = None
_gist_token_expiry: float = 0.0

app = FastAPI(title="WeCord Bridge", version="1.0.0")


# ══════════════════════════════════════════════════════════════
#  Gist helpers
# ══════════════════════════════════════════════════════════════

async def gist_login() -> str:
    global _gist_token, _gist_token_expiry
    if _gist_token and time.time() < _gist_token_expiry - 300:
        return _gist_token
    if not GIST_USERNAME or not GIST_PASSWORD:
        return ""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{GIST_BASE_URL}/api/auth/login",
            json={"identifier": GIST_USERNAME, "password": GIST_PASSWORD},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Gist login failed: {resp.status_code}")
        data = resp.json()
        _gist_token = data["token"]
        _gist_token_expiry = time.time() + 29 * 24 * 3600
        logger.info("Gist login OK")
        return _gist_token


async def gist_find_entry_by_url(article_url: str) -> Optional[dict]:
    token = await gist_login()
    if not token:
        return None
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=15) as client:
        params = {"limit": 50}
        if GIST_FEED_ID:
            params["feedId"] = GIST_FEED_ID
        resp = await client.get(f"{GIST_BASE_URL}/api/entries", headers=headers, params=params)
        if resp.status_code != 200:
            return None
        for entry in resp.json().get("entries", []):
            if entry.get("url") == article_url:
                return entry
    return None


async def gist_get_entry(entry_id: str) -> Optional[dict]:
    """Fetch full entry by ID (includes content field)."""
    token = await gist_login()
    if not token:
        return None
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{GIST_BASE_URL}/api/entries/{entry_id}", headers=headers)
        if resp.status_code != 200:
            return None
        return resp.json()


async def gist_pre_translate(entry_id: str, content: str, title: str) -> bool:
    """
    Trigger Gist AI translation and consume the SSE stream.
    The translation handler now auto-saves to cache on completion.
    Returns True if a cache hit, False if stream was consumed.
    """
    token = await gist_login()
    if not token:
        return False

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {
        "entryId": entry_id,
        "content": content,
        "title": title,
        "isReadability": False,
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{GIST_BASE_URL}/api/ai/translate", headers=headers, json=body,
        )

        content_type = resp.headers.get("Content-Type", "")

        # Cache hit → JSON response
        if "application/json" in content_type:
            data = resp.json()
            if data.get("cached"):
                logger.info("Gist translate: cache hit for entry %s", entry_id)
                return True

        # SSE stream → consume until done
        if "text/event-stream" in content_type:
            logger.info("Gist translate: consuming SSE stream for entry %s", entry_id)
            async for _ in resp.aiter_lines():
                pass  # just drain the stream; handler saves to cache on completion
            logger.info("Gist translate: stream done for entry %s", entry_id)
            return True

        logger.warning("Gist translate: unexpected content-type %s", content_type)
        return False


# ══════════════════════════════════════════════════════════════
#  DeepSeek AI
# ══════════════════════════════════════════════════════════════

TRANSLATE_PROMPT = """You are a professional translator and summariser. 
Given a Chinese article title and content, do the following:

1. Translate the title to natural English.
2. Write a concise English summary (2-4 sentences, max {max_chars} characters).
3. Output ONLY valid JSON in this exact format, with no extra text:
{{"title_en": "...", "summary_en": "..."}}
"""


async def translate_and_summarize(title_cn: str, description_cn: str) -> dict:
    prompt = TRANSLATE_PROMPT.format(max_chars=MAX_SUMMARY_CHARS)
    user_message = f"Title: {title_cn}\n\nContent: {description_cn}"
    body = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.3,
        "max_tokens": 600,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json=body,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"DeepSeek API error: {resp.status_code}")
        content = resp.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = "\n".join(content.split("\n")[1:-1])
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"title_en": title_cn, "summary_en": description_cn[:MAX_SUMMARY_CHARS]}


# ══════════════════════════════════════════════════════════════
#  Discord embed
# ══════════════════════════════════════════════════════════════

def build_discord_embed(
    feed_name: str, title_en: str, summary_en: str,
    article_url: str, gist_entry: Optional[dict],
    pic_url: Optional[str], publish_time: Optional[str],
    *, test_mode: bool = False, translating: bool = False,
) -> dict:
    prefix = "🧪 [TEST] " if test_mode else ""
    embed = {
        "title": prefix + title_en,
        "url": article_url,
        "description": summary_en,
        "color": 0xED5B2D,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": f"via {feed_name} · WeCord Bridge"},
    }
    if pic_url:
        embed["thumbnail"] = {"url": pic_url}

    fields = []
    if gist_entry:
        entry_id = gist_entry["id"]
        status = "⏳ Translating…" if translating else "📖 English Translation Ready"
        fields.append({
            "name": status,
            "value": f"[Read on Gist]({GIST_BASE_URL}/#/entries/{entry_id})",
            "inline": False,
        })
    if publish_time:
        try:
            pt = datetime.fromisoformat(publish_time.replace("Z", "+00:00"))
            fields.append({"name": "Published", "value": f"<t:{int(pt.timestamp())}:R>", "inline": True})
        except (ValueError, TypeError):
            pass
    if test_mode:
        fields.append({"name": "Mode", "value": "🧪 End-to-End Test", "inline": True})
    if fields:
        embed["fields"] = fields
    return embed


async def send_discord(embeds: list[dict]) -> None:
    payload = {"embeds": embeds}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(DISCORD_WEBHOOK_URL, json=payload)
        if resp.status_code == 204:
            logger.info("Discord OK (%d embeds)", len(embeds))
        else:
            logger.error("Discord failed: %s %s", resp.status_code, resp.text[:300])


# ══════════════════════════════════════════════════════════════
#  Core processor
# ══════════════════════════════════════════════════════════════

async def process_articles(
    articles: list[dict], feed_name: str, *, test_mode: bool = False,
) -> dict:
    logs, embeds = [], []
    for idx, article in enumerate(articles):
        title_cn = article.get("title", "Untitled")
        desc_cn = article.get("description", "")
        article_url = article.get("url", "")
        pic_url = article.get("pic_url", "")
        publish_time = article.get("publish_time", "")
        step = f"[{idx + 1}/{len(articles)}]"
        logger.info("%s Processing: %s", step, title_cn[:80])

        # 1. DeepSeek summary
        try:
            result = await translate_and_summarize(title_cn, desc_cn)
            title_en = result.get("title_en", title_cn)
            summary_en = result.get("summary_en", desc_cn[:MAX_SUMMARY_CHARS])
            logs.append(f"OK: {title_cn[:30]}... -> {title_en[:50]}...")
        except Exception as e:
            logger.error("DeepSeek: %s", e)
            title_en, summary_en = title_cn, f"[Error: {e}]"
            logs.append(f"FAIL: {e}")

        # 2. Gist lookup + pre-translate
        gist_entry = None
        translating = False
        try:
            if article_url:
                gist_entry = await gist_find_entry_by_url(article_url)
                if gist_entry:
                    eid = gist_entry["id"]
                    logs.append(f"Gist: #{eid}")
                    # Fetch full content & trigger translation
                    full = await gist_get_entry(eid)
                    content = (full or {}).get("content") or gist_entry.get("content", "")
                    if content:
                        logs.append(f"Pre-translating #{eid}…")
                        translating = True
                        try:
                            await gist_pre_translate(eid, content, title_cn)
                            translating = False
                            logs.append(f"Pre-translate done #{eid}")
                        except Exception as e:
                            logs.append(f"Pre-translate failed: {e}")
                else:
                    logs.append("Gist: not found (ok)")
        except Exception as e:
            logs.append(f"Gist error: {e}")

        # 3. Discord embed
        embeds.append(build_discord_embed(
            feed_name, title_en, summary_en, article_url, gist_entry,
            pic_url, publish_time, test_mode=test_mode, translating=translating,
        ))

    if embeds:
        await send_discord(embeds)
        logs.append(f"Sent {len(embeds)} embed(s)")
    return {"status": "ok", "sent": len(embeds), "logs": logs}


# ══════════════════════════════════════════════════════════════
#  Endpoints
# ══════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    logger.info("Webhook: %s", json.dumps(payload, ensure_ascii=False)[:500])
    feed = payload.get("feed", {})
    feed_name = feed.get("name", feed.get("mp_name", "Unknown"))
    articles = payload.get("articles", [])
    if not articles:
        return JSONResponse({"status": "no_articles"})
    return JSONResponse(await process_articles(articles, feed_name))


MOCK_ARTICLES = [
    {
        "id": "test-001", "mp_id": "test_mp_123",
        "title": "深度解析：2026年AI在医疗领域的五大突破性应用",
        "url": "https://mp.weixin.qq.com/s/test-001", "pic_url": "",
        "description": "从影像诊断到药物研发，AI正在重塑医疗行业。AI辅助癌症早期筛查准确率突破98%，智能药物分子设计将研发周期缩短60%，个性化基因治疗方案让罕见病治疗成为可能，手术机器人实现亚毫米级精准操作。",
        "publish_time": "2026-06-01 10:00:00",
    },
    {
        "id": "test-002", "mp_id": "test_mp_123",
        "title": "从零搭建个人AI知识库：RAG技术实战指南",
        "url": "https://mp.weixin.qq.com/s/test-002", "pic_url": "",
        "description": "RAG（检索增强生成）是当前大模型应用最热门架构之一。本文从ChromaDB向量数据库到LangChain集成，再到DeepSeek大模型对接，手把手教你搭建专属AI知识库助手。",
        "publish_time": "2026-06-01 09:30:00",
    },
]


@app.post("/test")
async def test_e2e():
    logger.info("TEST: %d mock articles", len(MOCK_ARTICLES))
    result = await process_articles(MOCK_ARTICLES, "Test Feed", test_mode=True)
    return JSONResponse({"test": True, "articles": len(MOCK_ARTICLES), **result})
