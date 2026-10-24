"""Switch the local Ollama completely off / on again (frees VRAM + RAM). No Streamlit imports here."""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import threading
import time
from urllib.parse import urlparse

IS_WIN = os.name == "nt"
# Windows: tray app first (otherwise it restarts the server), then the server, then its model runners.
WIN_PROCESSES = ("ollama app.exe", "ollama.exe", "ollama_llama_server.exe", "llama-server.exe")


def _local_addresses() -> set[str]:
    addrs = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
    try:
        addrs.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    try:                                                   # the address used for the LAN (no packet is sent)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            addrs.add(s.getsockname()[0])
    except OSError:
        pass
    return addrs


def is_local(url: str) -> bool:
    """Does this Ollama URL point at the PC the app runs on? (only then can the app stop its processes)"""
    host = urlparse(url).hostname or ""
    return host.lower() in _local_addresses()


def _run(cmd: list[str]) -> int:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=20,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).returncode
    except Exception:
        return -1


def stop_ollama_local() -> str:
    """Kill Ollama and every model runner on this PC. Returns a short human-readable result."""
    if IS_WIN:
        stopped = [n for n in WIN_PROCESSES if _run(["taskkill", "/F", "/T", "/IM", n]) == 0]
    else:
        if shutil.which("systemctl"):
            _run(["systemctl", "stop", "ollama"])
        stopped = [n for n in ("ollama", "ollama_llama_server", "llama-server") if _run(["pkill", "-f", n]) == 0]
    time.sleep(1)
    return ("Zastavené procesy: " + ", ".join(stopped)) if stopped else "Ollama už nebežala."


def start_ollama_local() -> bool:
    """Start `ollama serve` hidden and independent of the app. Returns False when `ollama` is not found.

    Windows: CREATE_NO_WINDOW only. DETACHED_PROCESS would leave the server without a console, and then every
    model runner it launches opens its own black cmd window (that was the 'cmd flashes several times' bug)."""
    exe = shutil.which("ollama")
    if not exe:
        return False
    kw: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if IS_WIN:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0                                    # SW_HIDE
        kw.update(creationflags=0x08000000 | 0x00000200, startupinfo=si)   # NO_WINDOW | NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    subprocess.Popen([exe, "serve"], **kw)
    return True


def _kill_self() -> None:
    """End this app and every child process of it (code run by the agent, ...)."""
    if IS_WIN:
        try:
            subprocess.Popen(["taskkill", "/F", "/T", "/PID", str(os.getpid())],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            time.sleep(1)
        except Exception:
            pass
    os._exit(0)


def exit_app_soon(delay: float = 3.0) -> None:
    """Stop the web interface + the agent after `delay` s (time for the page to draw its goodbye message)."""
    t = threading.Timer(delay, _kill_self)
    t.daemon = True
    t.start()
