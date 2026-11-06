"""Save official pages of the UAE Government Portal (u.ae) as knowledge base text files.

Follows links under the sections below and writes each page with useful text to the output
folder, with its title and address at the top, as `UAE_Portal_<page>.txt`. It saves every page it
finds: choose the relevant ones before copying them to data/knowledge_base/raw, then run
`make refresh-kb`.

Usage: python scripts/fetch_portal_pages.py <output-folder> [--limit 220]
"""

import argparse
import re
import time
import urllib.request
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

BASE = "https://u.ae"
SECTIONS = (
    "/en/about-the-uae/strategies-initiatives-and-awards/strategies-plans-and-visions",
    "/en/about-the-uae/strategies-initiatives-and-awards/policies",
    "/en/about-the-uae/digital-uae",
    "/en/about-the-uae/human-rights-in-the-uae",
    "/en/about-the-uae/the-uae-government",
    "/en/about-the-uae/the-constitution",
)
LINK_RE = re.compile(r'href="(/en/about-the-uae/[a-z0-9\-/]+)"', re.IGNORECASE)
TITLE_RE = re.compile(r"<title>([^<|]+)")
MIN_TEXT_CHARS = 800
PAUSE_SECONDS = 0.5
BODY_START = "U.Ask"
BODY_ENDS = ("Updated on:", "Did you find this content useful?")


class TextExtractor(HTMLParser):
    """Collect a page's visible text, one block per line."""

    SKIPPED = frozenset({"script", "style", "nav", "footer", "noscript", "svg"})
    BLOCKS = frozenset({"p", "h1", "h2", "h3", "h4", "li", "br", "div", "tr"})

    def __init__(self) -> None:
        super().__init__()
        self.skipping = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        self.skipping += tag in self.SKIPPED
        if tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIPPED and self.skipping:
            self.skipping -= 1

    def handle_data(self, data: str) -> None:
        if not self.skipping:
            self.parts.append(data)


def fetch(path: str) -> str:
    request = urllib.request.Request(BASE + path, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def page_body(html: str) -> str:
    """The page's own text, between the portal's header and its feedback form."""
    extractor = TextExtractor()
    extractor.feed(html)
    lines = [" ".join(line.split()) for line in "".join(extractor.parts).split("\n")]
    lines = [line for line in lines if line]
    if BODY_START not in lines:
        return ""
    start = lines.index(BODY_START) + 1
    if start < len(lines) and " " not in lines[start]:
        start += 1  # The page's address, printed as a line
    ends = (i for i in range(start, len(lines)) if lines[i] in BODY_ENDS)
    return "\n".join(lines[start : next(ends, len(lines))])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("output", type=Path)
    parser.add_argument("--limit", type=int, default=220, help="pages to visit at most")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    visited: set[str] = set()
    texts: set[str] = set()
    queue = list(SECTIONS)
    saved = 0
    while queue and len(visited) < args.limit:
        path = queue.pop(0).lower().rstrip("/")
        if path in visited:
            continue
        visited.add(path)
        try:
            html = fetch(path)
        except OSError as exc:
            print(f"failed {path}: {exc}")
            continue
        time.sleep(PAUSE_SECONDS)
        for link in LINK_RE.findall(html):
            link = link.lower().rstrip("/")
            if link.startswith(SECTIONS) and link not in visited:
                queue.append(link)

        body = page_body(html)
        if len(body) < MIN_TEXT_CHARS or body in texts:
            continue
        texts.add(body)
        match = TITLE_RE.search(html)
        slug = path.rsplit("/", 1)[1]
        title = unescape(" ".join(match.group(1).split())) if match else slug
        name = "UAE_Portal_" + re.sub(r"[^a-z0-9]+", "_", slug)[:60] + ".txt"
        (args.output / name).write_text(
            f"{title}\n\nSource: {BASE}{path}\n\n{body}\n", encoding="utf-8"
        )
        saved += 1
    print(f"{len(visited)} pages visited, {saved} saved to {args.output}")


if __name__ == "__main__":
    main()
