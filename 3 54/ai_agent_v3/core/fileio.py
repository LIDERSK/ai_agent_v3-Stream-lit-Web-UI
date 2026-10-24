"""Safe file writing that also works on Windows (where os.replace fails if something has the target open)."""
from __future__ import annotations

import os
import threading
import time
import uuid
from pathlib import Path

_lock = threading.Lock()


def atomic_write_text(path: Path, text: str, retries: int = 12) -> None:
    """Write via a unique temp file + replace. If Windows keeps refusing (antivirus, indexer, another
    Streamlit session holding the file), retry with a short back-off and finally write directly."""
    path = Path(path)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    with _lock:
        try:
            tmp.write_text(text, encoding="utf-8")
            for attempt in range(retries):
                try:
                    os.replace(tmp, path)
                    return
                except PermissionError:
                    time.sleep(0.05 * (attempt + 1))
            path.write_text(text, encoding="utf-8")          # last resort: not atomic, but never loses data
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
