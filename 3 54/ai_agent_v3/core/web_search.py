"""DuckDuckGo web search.

Returns a structured WebResult so the UI can tell the TRUTH: did it work, what was searched, which sources
were found (and show them), instead of passing an error message to the model as if it were search results.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from config import WEB_TRIGGERS

_RECENT = re.compile(r"najnov|novink|aktuáln|dnes|teraz|latest|news|recent", re.I)


@dataclass
class WebResult:
    query: str
    results: list[dict] = field(default_factory=list)      # {title, body, url}
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.results) and not self.error

    def as_text(self) -> str:
        return "\n\n".join(f"[{i}] {r['title']}\n    {r['body']}\n    {r['url']}"
                           for i, r in enumerate(self.results, 1))

    def sources(self) -> list[dict]:
        return [{"title": r["title"], "url": r["url"]} for r in self.results]


def should_search(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in WEB_TRIGGERS)


def is_recency_question(text: str) -> bool:
    return bool(_RECENT.search(text))


def build_query(text: str) -> str:
    """User sentence -> search query. 'latest/news' questions get the current year so fresh pages win."""
    q = clean_query(text)
    if is_recency_question(q) and not re.search(r"\b20\d\d\b", q):
        q += f" {datetime.now().year}"
    return q


_URL = re.compile(r"https?://\S+")
_MD = re.compile(r"[#*`>|_~=\[\]{}<]+")
MAX_QUERY_CHARS = 150
MAX_QUERY_WORDS = 24


def clean_query(text: str) -> str:
    """Anything -> a short plain search query (a search engine rejects / DNS-fails on multi-page text)."""
    q = _MD.sub(" ", _URL.sub(" ", text or ""))
    q = re.sub(r"\s+", " ", q).strip(" ?!.,;:-—–")
    words = q.split()[:MAX_QUERY_WORDS]
    q = " ".join(words)
    if len(q) > MAX_QUERY_CHARS:
        q = q[:MAX_QUERY_CHARS].rsplit(" ", 1)[0]
    return q


def _ddgs_class():
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    return DDGS


# (kwargs for DDGS.text, in order). "wt-wt" is NOT a language: the Wikipedia backend of ddgs builds the host
# "wt.wikipedia.org" from it -> DNSError. A real region first; the plain DuckDuckGo backend as a fallback.
_ATTEMPTS = ({"region": "us-en"}, {"region": "us-en", "backend": "duckduckgo"}, {"backend": "duckduckgo"})


def _text(d, query: str, max_results: int, recent: bool) -> list:
    last: Exception | None = None
    for kw in _ATTEMPTS:
        try:
            raw: list = []
            if recent:                                           # prefer the last year, then anything
                raw = list(d.text(query, timelimit="y", max_results=max_results, **kw))
            if not raw:
                raw = list(d.text(query, max_results=max_results, **kw))
            if raw:
                return raw
        except TypeError:                                        # this ddgs version has no such argument
            continue
        except Exception as e:                                   # network, rate limit, blocked backend, ...
            last = e
    if last:
        raise last
    return []


def search(query: str, max_results: int = 6) -> WebResult:
    """Never raises. Check .ok / .error."""
    query = clean_query(query)
    if not query:
        return WebResult(query, error="Prázdny vyhľadávací dotaz.")
    try:
        DDGS = _ddgs_class()
    except ImportError:
        return WebResult(query, error="Chýba balík ddgs (pip install ddgs).")
    try:
        with DDGS() as d:
            raw = _text(d, query, max_results, is_recency_question(query))
    except Exception as e:
        err = f"{type(e).__name__}: {e}"[:300]
        if "DNS" in err or "resolve" in err.lower():
            err += " (DNS / internet – skontroluj pripojenie)"
        return WebResult(query, error=err)
    results = [{"title": (r.get("title") or "").strip(), "body": (r.get("body") or "").strip(),
                "url": r.get("href") or r.get("url") or ""} for r in raw]
    results = [r for r in results if r["title"] or r["body"]]
    return WebResult(query, results, "" if results else "Vyhľadávanie nevrátilo žiadne výsledky.")


def search_web(query: str, max_results: int = 5) -> str:
    """Text version (kept for compatibility)."""
    r = search(query, max_results)
    return r.as_text() if r.ok else f"(Vyhľadávanie zlyhalo: {r.error})"
