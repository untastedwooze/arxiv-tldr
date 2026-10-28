"""Full text: obtain the text a Summary is written from, with its provenance.

``obtain`` tries each source in order and falls back to the abstract. Ticket #5 adds a PDF
source (and cutting to fit the context window) by extending ``SOURCES`` and setting ``cut``.
"""

from dataclasses import dataclass
from html.parser import HTMLParser

import httpx

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
        self._stack: list[bool] = []  # per open element: does it start a skipped region?
        self._skipping = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _VOID_TAGS:
            if tag in _BLOCK_TAGS and not self._skipping:
                self.parts.append("\n")
            return
        classes = set((dict(attrs).get("class") or "").split())
        skip = tag in _SKIP_TAGS or bool(classes & _SKIP_CLASSES)
        self._stack.append(skip)
        self._skipping += skip
        if tag in _BLOCK_TAGS and not self._skipping:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS or not self._stack:
            return
        self._skipping -= self._stack.pop()
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


SOURCES = [_from_html]


def obtain(candidate: Candidate, client: httpx.Client) -> FullText:
    """The best available text for a Candidate; the abstract if no full text can be had."""
    for source in SOURCES:
        found = source(candidate, client)
        if found is not None:
            return found
    return FullText(text=candidate.abstract, source="abstract")
