"""Tiny persistent key/value store (settings.json): skills on/off, chosen PC, thinking depth, ..."""
from __future__ import annotations

import json
import sys

from config import SETTINGS_PATH
from core.fileio import atomic_write_text

_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _cache = {}
    return _cache


def get(key: str, default=None):
    return _load().get(key, default)


def put(key: str, value) -> None:
    data = _load()
    data[key] = value
    try:
        atomic_write_text(SETTINGS_PATH, json.dumps(data, ensure_ascii=False, indent=2))
    except OSError as e:                      # a preference that could not be saved must never crash the app
        print(f"[settings] could not save {SETTINGS_PATH}: {e}", file=sys.stderr)
