"""Detects a model that got stuck repeating the same block of text (typical for small local models)."""
from __future__ import annotations

import re

# a block of 30-300 characters (starting with a visible character) repeated 4+ times in a row
_LOOP = re.compile(r"(\S.{29,299}?)\1{3,}", re.S)
# a SHORT phrase (8-30 chars) repeated 6+ times in a row, e.g. "We need to wait." x 20 (thinking loops)
_SHORT = re.compile(r"(\S.{7,29}?)\1{5,}", re.S)
# one short line (8+ visible characters) repeated 8+ times in a row
_LINE_LOOP = re.compile(r"(?m)^([^\n]*\S[^\n]{7,})\n(?:\1\n){7,}")
CHECK_EVERY = 300          # characters of new text between two checks
WINDOW = 2400              # only the tail is examined (keeps it cheap)


def _search(tail: str) -> re.Match | None:
    for rx in (_LOOP, _LINE_LOOP, _SHORT):
        for m in rx.finditer(tail):
            unit = m.group(1)
            if len(re.sub(r"\s", "", unit)) < 8:
                continue
            if rx is _SHORT and len(set(unit)) < 5:      # "=======" / "-----" dividers are not a loop
                continue
            return m
    return None


def find_loop(text: str) -> re.Match | None:
    return _search(text[-WINDOW:])


def trim_repetition(text: str) -> str:
    """Cut a repeated tail down to ONE copy of the repeated block (the rest was just looping)."""
    tail_len = min(len(text), 6000)
    tail, offset = text[-tail_len:], len(text) - tail_len
    m = _search(tail)
    if not m:
        return text
    return text[: offset + m.start() + len(m.group(1))].rstrip()
