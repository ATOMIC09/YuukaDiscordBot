"""
utils/web_search.py
Async Tavily web search helper with in-memory TTL cache.

Cache design — "book with table of contents":
  - The ENTIRE Tavily response is stored losslessly on first call (1 credit).
  - Default call → LLM receives a compact TOC: capped snippets and a few top-level
    image URLs it can cite with no extra call.
  - Follow-up with result_index=N → LLM receives the (capped) raw_content and the first
    images of that result (0 credits).
  - The system prompt only names the cached queries (`cached_queries`); the model reads
    one again by calling web_search with the same query, which is free. Pasting every
    cached TOC into every request cost far more than the searches saved.

Cache structure:
  _cache[normalized_query] = {
      "ts": float,    # time.monotonic() of fetch
      "data": dict    # complete raw Tavily response — nothing dropped:
                      #   query, answer, follow_up_questions, images (top-level),
                      #   results[].{url, title, content, score, raw_content,
                      #             images[].{url, description, description_source, score}},
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

# Everything below is prompt the model is billed for, and Thai costs about a token per
# character or two, so each cap is deliberate.
_RAW_CONTENT_LIMIT = 3000  # chars — cap for detail requests (single result)
_SNIPPET_LIMIT = 400  # chars — one result's snippet in the table of contents
_TOC_IMAGES = 3  # top-level images listed in the table of contents
_DETAIL_IMAGES = 5  # images listed for one result in the detail view
_NOTICE_QUERIES = 5  # earlier queries named in the system prompt


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


def cached_queries(limit: int = _NOTICE_QUERIES) -> list[str]:
    """The newest cached queries still inside the TTL, newest first."""
    now = time.monotonic()
    fresh = []
    for key, entry in list(_cache.items()):
        if (now - entry["ts"]) / 60 > config.search_cache_ttl_minutes:
            del _cache[key]
        else:
            fresh.append((entry["ts"], entry["data"].get("query") or key))
    fresh.sort(reverse=True)
    return [query for _, query in fresh[:limit]]


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
    Title, URL and a capped snippet per result, Tavily's direct answer when it has one,
    and a few top-level images the model can cite. Favicons, scores, follow-up questions
    and per-result images carry nothing the model uses, so they stay in the cache only.
    """
    lines: list[str] = [f'Web search results for: "{data.get("query", "")}"', ""]

    if data.get("answer"):
        lines += ["── DIRECT ANSWER ──", data["answer"], ""]

    results = data.get("results", [])
    lines.append(f"── RESULTS ({len(results)} found) ──")
    for i, r in enumerate(results):
        lines.append(f"[{i}] {r.get('title', '')}")
        lines.append(f"    URL    : {r.get('url', '')}")
        snippet = (r.get("content") or "").strip()
        if len(snippet) > _SNIPPET_LIMIT:
            snippet = snippet[:_SNIPPET_LIMIT] + "…"
        if snippet:
            lines.append(f"    Snippet: {snippet}")
        lines.append("")

    top_images = data.get("images", [])[:_TOC_IMAGES]
    if top_images:
        lines.append("── IMAGES ──")
        for i, img in enumerate(top_images):
            desc = f" — {img['description']}" if img.get("description") else ""
            lines.append(f"[img:{i}] {img.get('url', '')}{desc}")
        lines.append("")

    lines.append("Full content + images of one result: call web_search with result_index=N.")
    return "\n".join(lines)


def _format_result_detail(data: dict, index: int) -> str:
    """
    Full detail view for a specific result — returned when result_index is set.
    Includes: raw_content (truncated) and the first few images of that page.
    """
    results = data.get("results", [])
    if index < 0 or index >= len(results):
        return (
            f"result_index={index} is out of range. "
            f"There are {len(results)} results (0–{len(results)-1})."
        )

    r = results[index]
    raw = (r.get("raw_content") or r.get("content") or "").strip()
    if len(raw) > _RAW_CONTENT_LIMIT:
        raw = raw[:_RAW_CONTENT_LIMIT] + "\n…[truncated — content continues on the page]"

    lines = [
        f'Full detail for result [{index}]: {r.get("title", "")}',
        f'URL    : {r.get("url", "")}',
    ]

    r_images = r.get("images", [])[:_DETAIL_IMAGES]
    if r_images:
        lines += ["", "Images from this page:"]
        for j, img in enumerate(r_images):
            desc = f" — {img['description']}" if img.get("description") else ""
            lines.append(f"  [img:{j}] {img.get('url', '')}{desc}")

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
        out = _format_result_detail(cached, result_index)
    else:
        out = _format_toc(cached)

    return out
