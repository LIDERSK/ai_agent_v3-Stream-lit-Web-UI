"""Small, safe edits of an EXISTING file instead of rewriting all of it.

A change is written as SEARCH/REPLACE blocks (the format models know from coding assistants):

    <<<<<<< SEARCH
    exact old text
    =======
    new text
    >>>>>>> REPLACE

Rules: every block is applied in order; ALL blocks must succeed or nothing is written. The old text must be
found exactly once (a unique match); lines are also matched when only the indentation / trailing spaces differ.
An empty SEARCH appends the new text to the end of the file. Pure functions, no Streamlit.
"""
from __future__ import annotations

import ast
import difflib
import json
import re

BLOCK_RE = re.compile(
    r"^[ \t]*<{3,9}[ \t]*SEARCH[ \t]*\n(?P<old>.*?)^[ \t]*={3,9}[ \t]*\n(?P<new>.*?)^[ \t]*>{3,9}[ \t]*REPLACE[ \t]*$",
    re.S | re.M | re.I)

FORMAT_HELP = ("Formát: v tele značky jeden alebo viac blokov\n<<<<<<< SEARCH\npresný pôvodný text\n=======\n"
               "nový text\n>>>>>>> REPLACE")

SHRINK_RATIO = 0.5       # write_file over an existing file that would lose more than half of its lines is refused
SHRINK_MIN_LINES = 30


def _chomp(s: str) -> str:
    return s[:-1] if s.endswith("\n") else s


def parse_blocks(body: str) -> list[tuple[str, str]]:
    """[(old, new), ...] from the SEARCH/REPLACE blocks in `body`."""
    return [(_chomp(m.group("old")), _chomp(m.group("new"))) for m in BLOCK_RE.finditer(body or "")]


def _indent(line: str) -> str:
    return line[:len(line) - len(line.lstrip())]


def _reindent(new_lines: list[str], old_indent: str, file_indent: str) -> list[str]:
    """The model copied the code with another indentation than the file has: shift the new text by the difference."""
    if old_indent == file_indent:
        return new_lines
    if file_indent.startswith(old_indent):                       # file is indented deeper
        extra = file_indent[len(old_indent):]
        return [(extra + l) if l.strip() else l for l in new_lines]
    if old_indent.startswith(file_indent):                       # file is indented less
        cut = len(old_indent) - len(file_indent)
        return [l[cut:] if l.strip() and l[:cut].strip() == "" else l for l in new_lines]
    return new_lines


def _fuzzy(text: str, old: str, new: str) -> tuple[str | None, str]:
    """Whitespace-tolerant line match. Returns (new_text, "") or (None, hint)."""
    tl = text.split("\n")
    ol = old.split("\n")
    while ol and not ol[-1].strip():
        ol.pop()
    while ol and not ol[0].strip():
        ol.pop(0)
    if not ol:
        return None, "Hľadaný text je prázdny."
    key = [l.strip() for l in ol]
    k = len(key)
    hits = [i for i in range(len(tl) - k + 1) if [l.strip() for l in tl[i:i + k]] == key]
    if len(hits) == 1:
        i = hits[0]
        repl = _reindent(new.split("\n"), _indent(ol[0]), _indent(tl[i]))
        return "\n".join(tl[:i] + repl + tl[i + k:]), ""
    if len(hits) > 1:
        return None, f"pôvodný text sa (po zanedbaní odsadenia) nachádza {len(hits)}× – pridaj viac okolitých riadkov."
    first = key[0]
    cands = [l.strip() for l in tl if l.strip()]
    near = difflib.get_close_matches(first, cands, n=1, cutoff=0.6)
    if near:
        idx = next(i for i, l in enumerate(tl) if l.strip() == near[0])
        return None, (f"pôvodný text som nenašiel. Najpodobnejší riadok je {idx + 1}: «{tl[idx].strip()[:100]}». "
                      f"Prečítaj si ho (read_file start={max(1, idx - 1)} end={idx + 12}) a skopíruj text PRESNE.")
    return None, "pôvodný text som v súbore nenašiel. Nájdi správne miesto cez search_files a skopíruj text PRESNE."


def apply_blocks(content: str, blocks: list[tuple[str, str]]) -> tuple[str, list[str]]:
    """Apply all blocks. Returns (new_content, errors); with any error the content is returned UNCHANGED."""
    text, errors = content, []
    for i, (old, new) in enumerate(blocks, 1):
        label = f"Blok {i}" if len(blocks) > 1 else "Úprava"
        if not old.strip():                                      # empty SEARCH = append
            sep = "" if (not text or text.endswith("\n")) else "\n"
            text = text + sep + new + ("\n" if new and not new.endswith("\n") else "")
            continue
        n = text.count(old)
        if n == 1:
            text = text.replace(old, new, 1)
        elif n > 1:
            errors.append(f"{label}: pôvodný text sa nachádza {n}× – pridaj viac okolitých riadkov, aby bol jednoznačný.")
        else:
            res, hint = _fuzzy(text, old, new)
            if res is None:
                errors.append(f"{label}: {hint}")
            else:
                text = res
    return (content if errors else text), errors


def diff_summary(old: str, new: str, limit: int = 60) -> tuple[int, int, str]:
    """(added, removed, compact unified diff) of two texts."""
    lines = list(difflib.unified_diff(old.split("\n"), new.split("\n"), "pred", "po", lineterm="", n=1))
    body = [l for l in lines if not l.startswith(("---", "+++"))]
    added = sum(1 for l in body if l.startswith("+"))
    removed = sum(1 for l in body if l.startswith("-"))
    shown = body[:limit]
    if len(body) > limit:
        shown.append(f"… (ďalších {len(body) - limit} riadkov diffu vynechaných)")
    return added, removed, "\n".join(shown)


def changed_share(old: str, new: str) -> float:
    """Share of the old file's lines that differ in the new one (0 = identical, 1 = nothing in common)."""
    a, b = old.split("\n"), new.split("\n")
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return 1.0 - sm.ratio()


def shrinks_file(old: str, new: str) -> bool:
    """A "rewrite" that throws away most of an existing file: almost always a model that wrote only a fragment."""
    a, b = len(old.split("\n")), len(new.split("\n"))
    return a >= SHRINK_MIN_LINES and b < a * SHRINK_RATIO


def syntax_error(path: str, text: str) -> str:
    """"" when the text is fine (or the type is not checked); otherwise a short reason with the line number."""
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    try:
        if ext == "py":
            ast.parse(text)
        elif ext == "json":
            json.loads(text)
    except SyntaxError as e:
        return f"riadok {e.lineno}: {e.msg}"
    except json.JSONDecodeError as e:
        return f"riadok {e.lineno}: {e.msg}"
    except ValueError as e:                                      # e.g. null bytes in the source
        return str(e)
    return ""
