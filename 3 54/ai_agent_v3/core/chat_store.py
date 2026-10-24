"""Chat persistence: one JSON file per chat (atomic writes) + uploaded images."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from datetime import datetime

from config import BASE_DIR, CHAT_DIR, UPLOAD_DIR
from core.fileio import atomic_write_text


def _safe(chat_id: str) -> str:
    return re.sub(r"[^\w\-]", "", chat_id)


def _path(chat_id: str):
    return CHAT_DIR / f"{_safe(chat_id)}.json"


def new_chat_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:4]   # unique even within 1 s


def new_message_id() -> str:
    return uuid.uuid4().hex[:8]


def normalize(m: dict) -> dict:
    """Make old/foreign messages match the current schema."""
    m.setdefault("id", new_message_id())
    if "attachment" in m:                                   # old single-attachment format
        m["attachments"] = [m.pop("attachment")]
    m.setdefault("attachments", [])
    m.setdefault("images", [])
    m.setdefault("thinking", None)
    m.setdefault("meta", {})
    m.setdefault("trace", [])
    return m


def save_chat(chat_id: str, title: str, messages: list[dict], mode: str = "chat") -> None:
    if not messages:
        return
    data = {"id": chat_id, "title": title, "mode": mode, "messages": messages,
            "updated": datetime.now().isoformat(timespec="seconds")}
    path = _path(chat_id)
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))   # never leaves a half-written chat


def load_chat_full(chat_id: str) -> tuple[list[dict], str]:
    """(messages, mode)"""
    try:
        data = json.loads(_path(chat_id).read_text(encoding="utf-8"))
        return [normalize(m) for m in data.get("messages", [])], data.get("mode", "chat")
    except (OSError, json.JSONDecodeError):
        return [], "chat"


def load_chat(chat_id: str) -> list[dict]:
    return load_chat_full(chat_id)[0]


def list_chats() -> list[dict]:
    """Newest first: [{id, title, updated}]"""
    chats = []
    for p in CHAT_DIR.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            chats.append({"id": p.stem, "title": d.get("title") or "Bez názvu",
                          "updated": d.get("updated", ""), "mode": d.get("mode", "chat")})
        except (OSError, json.JSONDecodeError):
            continue                       # skip corrupted files
    chats.sort(key=lambda c: c["updated"] or c["id"], reverse=True)
    return chats


def delete_chat(chat_id: str) -> None:
    _path(chat_id).unlink(missing_ok=True)
    shutil.rmtree(UPLOAD_DIR / _safe(chat_id), ignore_errors=True)


def save_upload(chat_id: str, data: bytes, suffix: str = ".jpg") -> str:
    """Store an uploaded image, return its path relative to the project folder."""
    folder = UPLOAD_DIR / _safe(chat_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (hashlib.sha1(data).hexdigest()[:12] + suffix)
    path.write_bytes(data)
    return path.relative_to(BASE_DIR).as_posix()


def export_markdown(title: str, messages: list[dict]) -> str:
    out = [f"# {title}\n"]
    for m in messages:
        out.append(f"## {'🧑 Ty' if m['role'] == 'user' else '🤖 Agent'}\n")
        for step in m.get("trace", []):
            if step.get("kind") == "tool":
                out.append(f"> 🔧 `{step['name']}` {step.get('args', {})}\n")
            elif step.get("kind") in ("thinking", "stage"):
                title = step.get("title") or "🧠 Myšlienkový proces"
                out.append(f"<details><summary>{title}</summary>\n\n{step['text']}\n\n</details>\n")
        if m.get("thinking"):
            out.append("<details><summary>🧠 Myšlienkový proces</summary>\n\n"
                       f"{m['thinking']}\n\n</details>\n")
        out.append(m["content"] + "\n")
    return "\n".join(out)
