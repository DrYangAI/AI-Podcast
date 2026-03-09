"""RSS feed parsing utility."""

from dataclasses import dataclass
from datetime import datetime

import feedparser


@dataclass
class FeedItem:
    title: str
    url: str
    summary: str
    published: datetime | None


async def parse_feed(url: str, max_items: int = 20) -> list[FeedItem]:
    """Parse an RSS/Atom feed and return items."""
    import httpx
    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=30)
        response.raise_for_status()

    feed = feedparser.parse(response.text)
    items = []
    for entry in feed.entries[:max_items]:
        published = None
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            published = datetime(*entry.published_parsed[:6])

        items.append(FeedItem(
            title=entry.get('title', ''),
            url=entry.get('link', ''),
            summary=entry.get('summary', '')[:500],
            published=published,
        ))

    return items
