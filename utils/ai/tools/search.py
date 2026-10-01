"""
utils/ai/tools/search.py
Web search as a tool. Wraps `utils.web_search` (Tavily, cached).
"""

from __future__ import annotations

from langchain_core.tools import tool

from utils.web_search import web_search as _web_search


@tool
async def web_search(query: str, result_index: int | None = None) -> str:
    """Search the web for current or factual information you do not already know.

    Returns a table of contents of results. To read one result in full, call
    again with the same `query` and that result's `result_index`; that costs
    nothing extra. Results from earlier searches are listed under
    [CACHED SEARCH RESULTS] in your instructions.
    """
    return await _web_search(query, max_results=5, result_index=result_index)


def _status(args: dict) -> str:
    if args.get("result_index") is not None:
        return f"<a:AppleLoadingGIF:1052465926487953428> กำลังอ่านรายละเอียดของ: `{args.get('query', '')}`..."
    return f"<a:MagnifierGIF:1052563354910216252> ค้นหาข้อมูลบนเว็บ: `{args.get('query', '')}`..."


TOOLS = [web_search]
STATUS = {"web_search": _status}
