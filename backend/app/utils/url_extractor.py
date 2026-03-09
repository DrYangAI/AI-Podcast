"""URL content extraction utility - extracts article text from web pages."""

import logging
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class ExtractedArticle:
    title: str
    content: str
    url: str


async def extract_article(url: str) -> ExtractedArticle:
    """Extract article title and content from a URL."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AIPodcast/1.0)"},
        )
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Extract title
    title = ""
    if soup.title:
        title = soup.title.get_text(strip=True)
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"]

    # Remove unwanted elements
    for tag in soup.find_all(["script", "style", "nav", "header", "footer",
                               "aside", "iframe", "noscript", "form"]):
        tag.decompose()

    # Try to find main content container
    content_el = None
    for selector in ["article", "[role='main']", ".article-content",
                      ".post-content", ".entry-content", "#content", "main"]:
        content_el = soup.select_one(selector)
        if content_el:
            break

    if not content_el:
        content_el = soup.body or soup

    # Extract paragraphs
    paragraphs = []
    for p in content_el.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6"]):
        text = p.get_text(strip=True)
        if len(text) > 20:  # Filter short noise
            if p.name.startswith("h"):
                paragraphs.append(f"\n## {text}\n")
            else:
                paragraphs.append(text)

    content = "\n\n".join(paragraphs)

    if not content:
        # Fallback: get all text from body
        content = content_el.get_text(separator="\n", strip=True)

    return ExtractedArticle(title=title, content=content, url=url)
