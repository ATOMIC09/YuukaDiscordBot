"""
utils/web_search.py
Async Tavily web search helper with in-memory TTL cache.

Cache design — "book with table of contents":
  - The ENTIRE Tavily response is stored losslessly on first call (1 credit).
  - Default call → LLM receives a compact TOC: snippets, favicons, per-result
    image previews, and the full top-level image list with URLs.
  - Follow-up with result_index=N → LLM receives full raw_content + all per-result
    images (url, description, description_source, score) of that result (0 credits).
  - Images have their URLs in the TOC, so the LLM can cite them with no extra call.

Cache structure:
  _cache[normalized_query] = {
      "ts": float,    # time.monotonic() of fetch
      "data": dict    # complete raw Tavily response — nothing dropped:
                      #   query, answer, follow_up_questions, images (top-level),
                      #   results[].{url, title, content, score, raw_content,
                      #             images[].{url, description, description_source, score},
                      #             favicon},
                      #   response_time, usage, request_id
  }
"""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

from bot.config import config
from bot.logger import logger

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tavily")

# In-memory cache
_cache: dict[str, dict] = {}

_RAW_CONTENT_LIMIT = 5000  # chars — cap for detail requests (single result)


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _normalize(query: str) -> str:
    return query.lower().strip()


def _get_cached(query: str) -> dict | None:
    """Return the cached data dict if fresh, else None."""
    key = _normalize(query)
    entry = _cache.get(key)
    if entry is None:
        return None
    age_minutes = (time.monotonic() - entry["ts"]) / 60
    if age_minutes > config.search_cache_ttl_minutes:
        logger.debug(f"[SEARCH] Cache expired for '{query}' (age={age_minutes:.1f} min)")
        del _cache[key]
        return None
    logger.info(
        f"[SEARCH] 💾 Cache hit for '{query}' "
        f"(age={age_minutes:.1f} min, TTL={config.search_cache_ttl_minutes} min)"
    )
    return entry["data"]


def _store_cache(query: str, data: dict) -> None:
    key = _normalize(query)
    _cache[key] = {"ts": time.monotonic(), "data": data}
    n_results = len(data.get("results", []))
    n_images = len(data.get("images", []))
    logger.debug(
        f"[SEARCH] Cached '{query}': {n_results} results, {n_images} images "
        f"(TTL={config.search_cache_ttl_minutes} min)"
    )


# ── Tavily API call ───────────────────────────────────────────────────────────

def _sync_search(query: str, max_results: int) -> dict:
    """
    Blocking Tavily call — runs in a thread to avoid blocking the event loop.
    Stores the COMPLETE Tavily response losslessly (no field dropping).
    All fields — per-result images, favicon, answer, usage, etc. — are preserved.
    """
    from tavily import TavilyClient  # lazy import

    client = TavilyClient(api_key=config.tavily_api_key)
    response = client.search(
        query=query,
        search_depth="basic",
        max_results=max_results,
        include_images=True,
        include_image_descriptions=True,
        include_favicon=True,
        include_raw_content="markdown",
        include_usage=True,
    )

    credits_used = response.get("usage", {}).get("credits", "?")
    logger.info(f"[SEARCH] Tavily reported {credits_used} credit(s) used for this call")

    return response


# ── Formatting: what the LLM actually sees ────────────────────────────────────

def _format_toc(data: dict) -> str:
    """
    Table of contents view — sent on a normal web_search call.
    Exposes all top-level fields: answer, results (with favicon, per-result images),
    and top-level images. The LLM can cite URLs/images directly from this view.
    """
    lines: list[str] = [f'Web search results for: "{data.get("query", "")}"', ""]

    # Direct answer (Tavily sometimes provides one)
    if data.get("answer"):
        lines += ["── DIRECT ANSWER ──", data["answer"], ""]

    # Follow-up questions
    if data.get("follow_up_questions"):
        lines.append("── FOLLOW-UP QUESTIONS ──")
        for q in data["follow_up_questions"]:
            lines.append(f"  • {q}")
        lines.append("")

    results = data.get("results", [])
    lines.append(f"── RESULTS ({len(results)} found) ──")
    for i, r in enumerate(results):
        lines.append(f"[{i}] {r.get('title', '')}")
        lines.append(f"    URL    : {r.get('url', '')}")
        if r.get("favicon"):
            lines.append(f"    Favicon: {r['favicon']}")
        lines.append(f"    Score  : {round(r.get('score', 0), 4)}")
        snippet = (r.get("content") or "").strip()
        if snippet:
            lines.append(f"    Snippet: {snippet}")
        # Per-result images — show count + first image as preview
        r_images = r.get("images", [])
        if r_images:
            lines.append(f"    Images : {len(r_images)} image(s) in this result")
            first = r_images[0]
            lines.append(f"             [0] {first.get('url', '')}")
            if first.get("description"):
                lines.append(f"                 {first['description']}")
        lines.append("")

    # Top-level images (curated image results from the search)
    top_images = data.get("images", [])
    if top_images:
        lines.append(f"── TOP-LEVEL IMAGES ({len(top_images)} found) ──")
        for i, img in enumerate(top_images):
            lines.append(f"[img:{i}] {img.get('title', '')}")
            lines.append(f"    URL : {img.get('url', '')}")
            if img.get("description"):
                lines.append(f"    Desc: {img['description']}")
            lines.append("")

    lines.append(
        "To get full content + all images of a specific result: call web_search with result_index=N."
    )
    return "\n".join(lines)


def _format_result_detail(data: dict, index: int) -> str:
    """
    Full detail view for a specific result — returned when result_index is set.
    Includes: raw_content (truncated), all per-result images with description_source,
    favicon, and score.
    """
    results = data.get("results", [])
    if index < 0 or index >= len(results):
        return (
            f"result_index={index} is out of range. "
            f"There are {len(results)} results (0\u2013{len(results)-1})."
        )

    r = results[index]
    raw = (r.get("raw_content") or r.get("content") or "").strip()
    if len(raw) > _RAW_CONTENT_LIMIT:
        raw = raw[:_RAW_CONTENT_LIMIT] + "\n\u2026[truncated — content continues on the page]"

    lines = [
        f'Full detail for result [{index}]: {r.get("title", "")}',
        f'URL    : {r.get("url", "")}',
    ]
    if r.get("favicon"):
        lines.append(f'Favicon: {r["favicon"]}')
    lines.append(f'Score  : {round(r.get("score", 0), 4)}')

    # Per-result images (with description_source and image score)
    r_images = r.get("images", [])
    if r_images:
        lines += ["", f"Images from this page ({len(r_images)} total):"]
        for j, img in enumerate(r_images):
            lines.append(f"  [img:{j}] {img.get('url', '')}")
            if img.get("description"):
                lines.append(f"           Desc  : {img['description']}")
            if img.get("description_source"):
                lines.append(f"           Source: {img['description_source']}")
            img_score = img.get("score")
            if img_score is not None:
                lines.append(f"           Score : {img_score}")

    lines += ["", "── Full content ──", raw]
    return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────────────────

async def web_search(
    query: str,
    max_results: int = 5,
    result_index: int | None = None,
) -> str:
    """
    Search the web via Tavily with in-memory TTL caching.

    Args:
        query:        The search query (LLM-generated).
        max_results:  Max results to fetch (only applies on a cache miss).
        result_index: If set, return the full raw_content of that specific result
                      from the cache. Always costs 0 credits on a cache hit.

    Returns:
        A formatted string ready to be injected as a tool message for the LLM.
    """
    if not config.tavily_api_key:
        logger.warning("[SEARCH] TAVILY_API_KEY is not set — skipping web search.")
        return "Web search is not configured (no TAVILY_API_KEY)."

    cached = _get_cached(query)

    if cached is None:
        # Cache miss — call Tavily (costs 1 credit)
        logger.info(f"[SEARCH] 🔍 Tavily API call — query='{query}' max_results={max_results}")
        loop = asyncio.get_event_loop()
        try:
            cached = await loop.run_in_executor(_executor, _sync_search, query, max_results)
            n_results = len(cached.get("results", []))
            n_images = len(cached.get("images", []))
            logger.info(f"[SEARCH] ✅ Got {n_results} results + {n_images} images, cached.")
            _store_cache(query, cached)
        except Exception as exc:
            logger.error(f"[SEARCH] ❌ Tavily search failed: {exc}")
            return f"Web search failed: {exc}"

    if result_index is not None:
        logger.info(f"[SEARCH] 📖 Detail requested — result_index={result_index} (cache hit, 0 credits)")
        return _format_result_detail(cached, result_index)

    return _format_toc(cached)
