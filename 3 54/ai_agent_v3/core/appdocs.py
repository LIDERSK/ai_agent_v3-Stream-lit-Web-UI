"""Reads PATCH_NOTES_A_MAPA.md (patch notes + map of this app) in sections, so the agent finds anything with one call.
No Streamlit imports here."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from config import APP_DOCS_PATH


@dataclass
class Section:
    title: str
    key: str
    text: str            # including the "## ..." line


def _fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def load(path=None) -> str:
    try:
        return (path or APP_DOCS_PATH).read_text(encoding="utf-8")
    except OSError:
        return ""


def sections(text: str | None = None) -> list[Section]:
    """Split at `## ` headings (a `# ` title and the intro before the first `##` form the section 'uvod')."""
    text = load() if text is None else text
    out: list[Section] = []
    cur_title, cur = "Úvod", []
    for line in text.splitlines():
        if line.startswith("## "):
            if "".join(cur).strip():
                out.append(Section(cur_title, _fold(cur_title), "\n".join(cur).strip()))
            cur_title, cur = line[3:].strip(), [line]
        else:
            cur.append(line)
    if "".join(cur).strip():
        out.append(Section(cur_title, _fold(cur_title), "\n".join(cur).strip()))
    return out


def toc(text: str | None = None) -> str:
    secs = sections(text)
    if not secs:
        return "Dokument PATCH_NOTES_A_MAPA.md sa nenašiel."
    lines = [f"- {s.title}  (topic=\"{s.key.split()[0] if s.key else ''}\", {len(s.text)} znakov)" for s in secs]
    return ("OBSAH dokumentu o aplikácii (patch notes + mapa). Konkrétnu časť získaš cez app_info topic=\"…\" "
            "(stačí časť názvu), hľadať vieš cez app_info query=\"text\":\n" + "\n".join(lines))


def find(topic: str, text: str | None = None) -> list[Section]:
    q = _fold(topic)
    if not q:
        return []
    secs = sections(text)
    exact = [s for s in secs if s.key == q]
    if exact:
        return exact
    starts = [s for s in secs if s.key.startswith(q) or q in s.key.split()]
    if starts:
        return starts
    words = q.split()
    return [s for s in secs if all(w in s.key for w in words)] or [s for s in secs if q in _fold(s.text)][:3]


def search(query: str, text: str | None = None, limit: int = 25) -> str:
    q = _fold(query)
    if not q:
        return ""
    hits = []
    for s in sections(text):
        for line in s.text.splitlines():
            if q in _fold(line):
                hits.append(f"[{s.title}] {line.strip()[:170]}")
                if len(hits) >= limit:
                    return "\n".join(hits)
    return "\n".join(hits)
