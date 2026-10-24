"""Sound signal when a long task finishes (the app runs on your own PC, so the sound plays there)."""
from __future__ import annotations

import sys

from config import NOTIFY_DONE, NOTIFY_MIN_SECONDS


def task_done(seconds: float | None, ok: bool = True) -> None:
    if not NOTIFY_DONE or not seconds or seconds < NOTIFY_MIN_SECONDS:
        return
    try:
        if sys.platform.startswith("win"):
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK if ok else winsound.MB_ICONHAND)
        else:
            print("\a", end="", flush=True)
    except Exception:
        pass                                   # a notification must never break the app
