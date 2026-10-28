"""Full text: obtain the text a Summary is written from, with its provenance.

``obtain`` tries each source in order (HTML, then PDF), cuts the text to the budget, and falls
back to the abstract.
"""

import re
from dataclasses import dataclass
from html.parser import HTMLParser

import httpx
import pymupdf

from .store import Candidate


@dataclass(frozen=True)
class FullText:
    text: str
    source: str  # "html", "pdf" or "abstract"
    cut: bool = False  # True if the text was cut to fit the context window


_SKIP_TAGS = {"script", "style", "head", "nav", "footer", "button", "svg", "math"}
_SKIP_CLASSES = {"ltx_bibliography", "ltx_appendix", "ltx_pagination", "ltx_page_footer"}
_VOID_TAGS = {"br", "hr", "img", "input", "link", "meta", "wbr", "col", "area", "base", "source"}
_BLOCK_TAGS = {"p", "div", "section", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "br",
               "figcaption", "table", "ul", "ol", "article"}


class _BodyExtractor(HTMLParser):
    """Collect text, ignoring references, appendices, scripts and page chrome."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._stack: list[tuple[str, bool]] = []  # open elements: (tag, starts a skipped region)
        self._skipping = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _VOID_TAGS:
            if tag in _BLOCK_TAGS and not self._skipping:
                self.parts.append("\n")
            return
        classes = set((dict(attrs).get("class") or "").split())
        skip = tag in _SKIP_TAGS or bool(classes & _SKIP_CLASSES)
        self._stack.append((tag, skip))
        self._skipping += skip
        if tag in _BLOCK_TAGS and not self._skipping:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS or not any(open_tag == tag for open_tag, _ in self._stack):
            return
        # Close the matching element and any unclosed ones inside it (e.g. a bare <li>).
        while True:
            open_tag, skip = self._stack.pop()
            self._skipping -= skip
            if open_tag == tag:
                break
        if tag in _BLOCK_TAGS and not self._skipping:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skipping:
            self.parts.append(data)


def extract_body(html: str) -> str:
    """Body text of an arXiv HTML page, without references and appendices."""
    extractor = _BodyExtractor()
    extractor.feed(html)
    lines = (" ".join(line.split()) for line in "".join(extractor.parts).splitlines())
    return "\n".join(line for line in lines if line)


def _from_html(candidate: Candidate, client: httpx.Client) -> FullText | None:
    try:
        response = client.get(candidate.html_url)
    except httpx.TransportError:
        return None
    if response.status_code != 200:
        return None
    text = extract_body(response.text)
    return FullText(text=text, source="html") if text else None


_BACK_MATTER = re.compile(
    r"^(?:(?:\d+|[IVX]+)\.?\s+)?(?:references|bibliography|appendix|appendices)\b", re.IGNORECASE
)


def strip_back_matter(text: str) -> str:
    """Drop everything from the first References / Bibliography / Appendix heading line
    (ignoring any in the first fifth of the text, e.g. a table of contents)."""
    lines = text.splitlines()
    start = len(text) // 5
    offset = 0
    for index, line in enumerate(lines):
        if offset >= start and _BACK_MATTER.match(line.strip()):
            return "\n".join(lines[:index]).strip()
        offset += len(line) + 1
    return text


def extract_pdf_text(data: bytes) -> str:
    """Body text of a PDF without references and appendices; empty if it cannot be read."""
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            raw = "\n".join(page.get_text() for page in doc)
    except Exception:  # pymupdf raises its own error types for corrupt input
        return ""
    lines = (" ".join(line.split()) for line in raw.splitlines())
    return strip_back_matter("\n".join(line for line in lines if line))


def _from_pdf(candidate: Candidate, client: httpx.Client) -> FullText | None:
    try:
        response = client.get(candidate.pdf_url, follow_redirects=True)
    except httpx.TransportError:
        return None
    if response.status_code != 200:
        return None
    text = extract_pdf_text(response.content)
    return FullText(text=text, source="pdf") if text else None


SOURCES = [_from_html, _from_pdf]


def obtain(candidate: Candidate, client: httpx.Client, budget: int | None = None) -> FullText:
    """The best available text for a Candidate, cut to ``budget`` characters if given;
    the abstract if no full text can be had."""
    if budget is not None and budget <= 0:
        return FullText(text=candidate.abstract, source="abstract")
    for source in SOURCES:
        found = source(candidate, client)
        if found is not None:
            if budget is not None and len(found.text) > budget:
                return FullText(text=found.text[:budget].rstrip(), source=found.source, cut=True)
            return found
    return FullText(text=candidate.abstract, source="abstract")
