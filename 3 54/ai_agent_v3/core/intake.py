"""What the chat input hands us (text + dropped files) -> plain data. No Streamlit imports here.

`st.chat_input(accept_file="multiple")` returns an object with `.text` and `.files` (a dict-like in newer
Streamlit versions, a plain string when the widget has no file support). These helpers accept all shapes.
"""
from __future__ import annotations

from config import BINARY_TYPES, IMAGE_TYPES, TEXT_TYPES

ALL_TYPES = TEXT_TYPES + BINARY_TYPES + IMAGE_TYPES


def split_value(value) -> tuple[str, list]:
    """(text, files) from whatever st.chat_input returned (None / str / object with .text and .files / dict)."""
    if value is None:
        return "", []
    if isinstance(value, str):
        return value, []
    if isinstance(value, dict):
        text, files = value.get("text"), value.get("files")
    else:
        text, files = getattr(value, "text", None), getattr(value, "files", None)
    return (text or ""), list(files or [])


def extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in (name or "") else ""


def kind_of(name: str) -> str:
    """\"image\" | \"binary\" (zip / pdf / office) | \"text\"."""
    ext = extension(name)
    if ext in IMAGE_TYPES:
        return "image"
    if ext in BINARY_TYPES:
        return "binary"
    return "text"


def default_prompt(files: list) -> str:
    """A file dropped without any text still has to mean something - say what the user most likely wants."""
    kinds = {kind_of(getattr(f, "name", "")) for f in files}
    if kinds == {"image"}:
        return "Popíš, čo je na priloženom obrázku."
    if kinds == {"binary"}:
        return "Pozri sa na priložený súbor a stručne zhrň, čo obsahuje."
    return "Pozri sa na priložené súbory a stručne zhrň, čo obsahujú."


def dedupe(files: list) -> list:
    """The same file attached twice (＋ menu and drag & drop) is used once."""
    seen, out = set(), []
    for f in files:
        key = (getattr(f, "name", ""), getattr(f, "size", None))
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out
