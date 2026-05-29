"""URL content extraction utility - extracts article text from web pages."""

import logging
import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

logger = logging.getLogger(__name__)


@dataclass
class ExtractedArticle:
    title: str
    content: str
    url: str


def _get_text_density(element: Tag) -> float:
    """Calculate text-to-HTML ratio for an element (higher = more content-rich)."""
    text = element.get_text(strip=True)
    html = str(element)
    if not html:
        return 0
    return len(text) / len(html)


def _find_content_container(soup: BeautifulSoup) -> Tag:
    """Find the main content container using multiple strategies."""

    # Strategy 1: Common semantic selectors
    for selector in [
        "article",
        "[role='main']",
        ".article-content", ".article-body", ".article_content",
        ".post-content", ".post-body", ".post_content",
        ".entry-content", ".entry-body",
        ".rich_media_content",       # WeChat articles
        ".js_content",               # WeChat articles
        "#js_content",               # WeChat articles
        ".content-detail",
        ".detail-content",
        "#article-content",
        "#content",
        ".text-content",
        "main",
        ".main-content",
        "#main-content",
    ]:
        el = soup.select_one(selector)
        if el and len(el.get_text(strip=True)) > 100:
            return el

    # Strategy 2: Find the element with the most text content (text density approach)
    candidates = []
    for tag in soup.find_all(["div", "section", "article", "main"]):
        text = tag.get_text(strip=True)
        if len(text) < 200:
            continue
        # Penalize elements that are too high in the tree (like body wrappers)
        depth = len(list(tag.parents))
        density = _get_text_density(tag)
        # Score: prefer longer text with higher density and deeper nesting
        score = len(text) * density * (1 + depth * 0.1)
        candidates.append((score, tag))

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    # Fallback: body or root
    return soup.body or soup


def _extract_text_blocks(container: Tag) -> list[str]:
    """Extract meaningful text blocks from a container, handling various HTML structures."""
    blocks = []

    # First try: collect from <p>, headings, <li>, <blockquote>
    block_tags = container.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote"])
    for tag in block_tags:
        text = tag.get_text(strip=True)
        if not text or len(text) < 10:
            continue
        if tag.name.startswith("h"):
            blocks.append(f"\n{text}\n")
        else:
            blocks.append(text)

    # If we got enough content from block tags, use it
    if sum(len(b) for b in blocks) > 200:
        return blocks

    # Fallback: walk the tree and collect text from any leaf-level containers
    blocks = []
    for element in container.descendants:
        if isinstance(element, NavigableString):
            continue
        if not isinstance(element, Tag):
            continue
        # Skip non-content tags
        if element.name in ("script", "style", "nav", "header", "footer",
                            "aside", "iframe", "noscript", "form", "button",
                            "input", "select", "textarea", "img", "svg"):
            continue

        # Only process leaf-like elements (no nested block children)
        has_block_child = False
        for child in element.children:
            if isinstance(child, Tag) and child.name in (
                "div", "section", "article", "p", "ul", "ol", "table",
                "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"
            ):
                has_block_child = True
                break

        if has_block_child:
            continue

        text = element.get_text(strip=True)
        if text and len(text) >= 10:
            if element.name and element.name.startswith("h"):
                blocks.append(f"\n{text}\n")
            else:
                blocks.append(text)

    return blocks


async def extract_article(url: str) -> ExtractedArticle:
    """Extract article title and content from a URL."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            timeout=30,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            },
        )
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Extract title
    title = ""
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"]
    elif soup.title:
        title = soup.title.get_text(strip=True)

    # Also try h1
    if not title:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)

    # Remove unwanted elements
    for tag in soup.find_all(["script", "style", "nav", "header", "footer",
                               "aside", "iframe", "noscript", "form",
                               "button", "input", "select", "textarea"]):
        tag.decompose()

    # Remove common non-content elements by class/id patterns
    noise_patterns = re.compile(
        r"(comment|share|social|recommend|related|sidebar|widget|ad-|advertisement|"
        r"copyright|footer|breadcrumb|pagination|nav|menu)",
        re.I,
    )
    for tag in soup.find_all(True):
        classes = " ".join(tag.get("class", []))
        tag_id = tag.get("id", "")
        if noise_patterns.search(classes) or noise_patterns.search(tag_id):
            # Don't remove if it's a large content block
            if len(tag.get_text(strip=True)) < 200:
                tag.decompose()

    # Find main content container
    content_el = _find_content_container(soup)

    # Extract text blocks
    blocks = _extract_text_blocks(content_el)

    # Deduplicate consecutive blocks
    deduped = []
    for block in blocks:
        if not deduped or block != deduped[-1]:
            deduped.append(block)

    content = "\n\n".join(deduped)

    # Clean up excessive whitespace
    content = re.sub(r"\n{3,}", "\n\n", content)

    if not content or len(content) < 50:
        # Last resort fallback: get all text from body
        content = (soup.body or soup).get_text(separator="\n", strip=True)

    logger.info("Extracted %d chars from %s (title: %s)", len(content), url, title[:50])

    return ExtractedArticle(title=title, content=content, url=url)
