"""Hot topic scrapers for Chinese platforms."""

import logging
from dataclasses import dataclass
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}


@dataclass
class HotTopic:
    """A single hot topic from a platform."""

    title: str
    url: str | None = None
    source: str = ""
    rank: int = 0
    heat: str = ""


async def _scrape_weibo(client: httpx.AsyncClient) -> list[HotTopic]:
    """Scrape Weibo hot search (微博热搜)."""
    resp = await client.get(
        "https://weibo.com/ajax/side/hotSearch",
        headers={**HEADERS, "Referer": "https://weibo.com/"},
    )
    resp.raise_for_status()
    data = resp.json()
    topics = []
    for i, item in enumerate(data.get("data", {}).get("realtime", [])[:30]):
        word = item.get("word", "")
        if not word:
            continue
        topics.append(HotTopic(
            title=word,
            url=f"https://s.weibo.com/weibo?q={quote(word)}",
            source="weibo",
            rank=i + 1,
            heat=str(item.get("num", "")),
        ))
    return topics


async def _scrape_baidu(client: httpx.AsyncClient) -> list[HotTopic]:
    """Scrape Baidu hot search (百度热搜)."""
    resp = await client.get(
        "https://top.baidu.com/api/board?platform=wise&tab=realtime",
        headers=HEADERS,
    )
    resp.raise_for_status()
    data = resp.json()
    topics = []
    cards = data.get("data", {}).get("cards", [])
    if not cards:
        return topics
    # Baidu nests content: cards[0].content[0].content
    inner = cards[0].get("content", [])
    if not inner:
        return topics
    items = inner
    if isinstance(inner[0], dict) and "content" in inner[0]:
        items = inner[0].get("content", [])
    for i, item in enumerate(items[:30]):
        word = item.get("word", "") or item.get("query", "")
        if not word:
            continue
        topics.append(HotTopic(
            title=word,
            url=item.get("url") or f"https://www.baidu.com/s?wd={quote(word)}",
            source="baidu",
            rank=i + 1,
            heat=str(item.get("hotScore", "")),
        ))
    return topics


async def _scrape_toutiao(client: httpx.AsyncClient) -> list[HotTopic]:
    """Scrape Toutiao hot board (头条热榜)."""
    resp = await client.get(
        "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc",
        headers=HEADERS,
    )
    resp.raise_for_status()
    data = resp.json()
    topics = []
    for i, item in enumerate(data.get("data", [])[:30]):
        title = item.get("Title", "")
        if not title:
            continue
        topics.append(HotTopic(
            title=title,
            url=item.get("Url"),
            source="toutiao",
            rank=i + 1,
            heat=str(item.get("HotValue", "")),
        ))
    return topics


# --- Registry ---

SCRAPERS: dict[str, callable] = {
    "weibo": _scrape_weibo,
    "baidu": _scrape_baidu,
    "toutiao": _scrape_toutiao,
}

SOURCE_NAMES: dict[str, str] = {
    "weibo": "微博热搜",
    "baidu": "百度热搜",
    "toutiao": "头条热榜",
}


async def scrape_hotlists(
    sources: list[str] | None = None,
    timeout: float = 15.0,
) -> dict[str, list[HotTopic]]:
    """Scrape hot topics from specified sources (default: all).

    Returns a dict of {source_key: [HotTopic, ...]}.
    Failed sources are logged and returned as empty lists.
    """
    if sources is None:
        sources = list(SCRAPERS.keys())

    results: dict[str, list[HotTopic]] = {}
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for source_key in sources:
            scraper_fn = SCRAPERS.get(source_key)
            if not scraper_fn:
                logger.warning(f"Unknown hotlist source: {source_key}")
                continue
            try:
                results[source_key] = await scraper_fn(client)
                logger.info(f"Scraped {len(results[source_key])} topics from {source_key}")
            except Exception as e:
                logger.error(f"Failed to scrape {source_key}: {e}")
                results[source_key] = []

    return results
