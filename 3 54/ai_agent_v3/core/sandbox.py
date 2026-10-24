"""Sandbox: lets the agent RUN what it writes - Python, C, C++, JavaScript and HTML.

How a run works
  1. The project folder of the file is copied to a throw-away directory (the workspace itself is never touched;
     a program that writes or deletes files only does so in the copy, compiled binaries live there too).
  2. The file is compiled (C / C++) and run with a time limit, an output-size limit and a minimal environment
     (no API keys / user variables).  A runaway process tree is killed.
  3. HTML is opened in a HEADLESS browser (Edge / Chrome / Chromium): console errors, missing local files and
     the visible text are reported and a screenshot is saved next to the file.
  4. The result is `Result(code, text, files)`; `text` is clipped to the interesting head and tail.

Isolation level  (config.SANDBOX_MODE)
  "local"  a clean copy + limits, but the program still runs as YOUR user on this PC (like any script you start).
  "docker" every run happens in a container with no network, 512 MB RAM, 1 CPU (needs Docker; not for HTML).
No Streamlit imports here.
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from config import (RUN_TIMEOUT, SANDBOX_COMPILE_TIMEOUT, SANDBOX_DOCKER_IMAGES, SANDBOX_MODE,
                    SANDBOX_OUTPUT_MAX_BYTES, WORKSPACE_DIR)
from core import workspace

LANGS = {".py": "python", ".c": "c", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
         ".js": "javascript", ".mjs": "javascript", ".html": "html", ".htm": "html"}
RUNNABLE = tuple(LANGS)
IS_WIN = os.name == "nt"
MAX_COPY_FILE = 5_000_000          # files bigger than this are not copied into the sandbox
CLIP_HEAD, CLIP_TAIL = 1200, 4200  # what is kept of a long output

SERVER_RE = re.compile(r"running on http|listening on|serving http|uvicorn running|server (?:started|running)", re.I)
MODULE_RE = re.compile(r"No module named '([\w.]+)'")


@dataclass
class Result:
    code: int
    text: str
    files: list = field(default_factory=list)      # workspace paths created by the run (e.g. a screenshot)


# ----------------------------------------------------------------- what is installed
def _which(*names: str) -> str | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def find_browser() -> str | None:
    found = _which("msedge", "microsoft-edge", "google-chrome", "google-chrome-stable", "chrome", "chromium",
                   "chromium-browser")
    if found:
        return found
    for base in filter(None, (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                              os.environ.get("LOCALAPPDATA"))):
        for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
            if (Path(base) / rel).is_file():
                return str(Path(base) / rel)
    return None


HINTS = {
    "c": "Nainštaluj kompilátor: Windows `winget install -e --id BrechtSanders.WinLibs.POSIX.UCRT` (gcc/g++), "
         "Linux `sudo apt install build-essential`, macOS `xcode-select --install`. Alebo zapni Docker režim.",
    "cpp": "Rovnako ako pri C (balík obsahuje aj g++).",
    "javascript": "Nainštaluj Node.js: `winget install -e --id OpenJS.NodeJS.LTS` (alebo nodejs.org).",
    "html": "Nainštaluj Microsoft Edge alebo Google Chrome (na Windowse býva Edge). Bez neho sa HTML len skontroluje "
            "staticky (štruktúra, chýbajúce súbory), JavaScript sa nespustí.",
}


def toolchains() -> dict[str, dict]:
    """{language: {ok, path, hint}} for what this PC can run right now."""
    cc, cxx, node, browser = (_which("gcc", "cc", "clang"), _which("g++", "c++", "clang++"), _which("node"),
                              find_browser())
    info = {"python": sys.executable, "c": cc, "cpp": cxx, "javascript": node, "html": browser}
    out = {lang: {"ok": bool(path), "path": path or "", "hint": "" if path else HINTS.get(lang, "")}
           for lang, path in info.items()}
    out["docker"] = {"ok": bool(_which("docker")), "path": _which("docker") or "",
                     "hint": "Voliteľné: izolované spúšťanie v kontajneri (config.SANDBOX_MODE = \"docker\")."}
    return out


def describe() -> str:
    lines = [f"Sandbox režim: {SANDBOX_MODE}. Spustiteľné súbory: " + ", ".join(RUNNABLE)]
    for lang, i in toolchains().items():
        lines.append(f"- {lang}: {'k dispozícii' if i['ok'] else 'CHÝBA'}" + (f" – {i['hint']}" if i["hint"] else ""))
    return "\n".join(lines)


# ----------------------------------------------------------------- running a process safely
def _env(cwd: Path | None = None) -> dict:
    keep = ("PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR", "HOME",
            "USERPROFILE", "LANG", "LC_ALL", "LOCALAPPDATA", "APPDATA", "ProgramFiles", "ProgramFiles(x86)")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
    if cwd is not None:                                  # staged project: `import core` must work from tests/ etc.
        roots = [str(a) for a in [cwd, *cwd.parents] if a.name.startswith("sbx_") and a.parent == Path(tempfile.gettempdir())]
        if roots:
            env["PYTHONPATH"] = os.pathsep.join([str(cwd), roots[0]])
    return env


def _kill(p: subprocess.Popen, container: str = "") -> None:
    try:
        if container:
            subprocess.run(["docker", "kill", container], capture_output=True, timeout=15)
        if IS_WIN:
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, timeout=15)
        else:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass
    try:
        p.wait(timeout=5)
    except Exception:
        pass


def _exec(cmd: list[str], cwd: Path, stdin_text: str, timeout: float, container: str = "") -> tuple[int, str, str, str]:
    """Run a command with limits. Returns (returncode, stdout, stderr, status) - status: ok | timeout | flood.
    Output goes to temp files (not pipes): no deadlocks, and a program that spams output is stopped."""
    kw = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if IS_WIN else {"start_new_session": True}
    with tempfile.TemporaryDirectory(prefix="sbx_io_") as d:
        d = Path(d)
        (d / "in").write_text(stdin_text or "", encoding="utf-8")
        status = "ok"
        with open(d / "in", "rb") as fin, open(d / "out", "wb") as fout, open(d / "err", "wb") as ferr:
            try:
                p = subprocess.Popen(cmd, cwd=cwd, stdin=fin, stdout=fout, stderr=ferr, env=_env(cwd), **kw)
            except OSError as e:
                return 127, "", f"Program sa nepodarilo spustiť: {e}", "ok"
            deadline = time.monotonic() + timeout
            while True:
                try:
                    p.wait(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if time.monotonic() > deadline:
                    status = "timeout"
                    break
                if (d / "out").stat().st_size + (d / "err").stat().st_size > SANDBOX_OUTPUT_MAX_BYTES:
                    status = "flood"
                    break
            if status != "ok":
                _kill(p, container)
        rd = lambda f: (d / f).read_bytes()[:SANDBOX_OUTPUT_MAX_BYTES].decode("utf-8", "replace")      # noqa: E731
        return (p.returncode if status == "ok" else 1), rd("out"), rd("err"), status


def _clip(text: str) -> str:
    text = text.strip()
    if len(text) <= CLIP_HEAD + CLIP_TAIL:
        return text
    return text[:CLIP_HEAD] + f"\n[... vynechaných {len(text) - CLIP_HEAD - CLIP_TAIL} znakov ...]\n" + text[-CLIP_TAIL:]


def run_tests(rel: str = "", timeout: float = RUN_TIMEOUT * 3) -> Result:
    """Run the project's unit tests (`python -m unittest discover`) in a throw-away copy of the project folder `rel`
    ("" = workspace root). Tests are looked up in tests/ (or the folder itself). Never raises."""
    try:
        base = workspace.safe_path(rel) if rel else WORKSPACE_DIR
    except workspace.WorkspaceError as e:
        return Result(1, str(e))
    if base.is_file():
        base = base.parent
    if not base.is_dir():
        return Result(1, f"Priečinok '{rel}' neexistuje. Použi list_files.")
    start = "tests" if (base / "tests").is_dir() else "."
    if not list((base / start).rglob("test*.py")):
        return Result(1, f"V '{rel or 'workspace'}' som nenašiel žiadne testy (súbory test*.py v tests/). "
                         "Napíš ich (unittest) a spusti run_tests znova.")
    tmp, staged = _stage(base / "__run_tests__.py")
    try:
        cwd = staged.parent
        if SANDBOX_MODE == "docker":
            inner = _quote(["python", "-X", "utf8", "-m", "unittest", "discover", "-s", start, "-t", ".", "-v"])
            return _finish(*_docker("python", cwd, inner, timeout, ""), timeout)
        return _finish(*_exec([sys.executable, "-X", "utf8", "-m", "unittest", "discover", "-s", start, "-t", ".", "-v"],
                              cwd, "", timeout), timeout)
    except Exception as e:
        return Result(1, f"Chyba sandboxu: {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ----------------------------------------------------------------- staging a copy of the project
MAX_STAGE_FILES = 3000
MAX_STAGE_BYTES = 80_000_000
_SKIP_DIRS = ("__pycache__", "node_modules", ".git", ".venv", "venv")


def _stage(src: Path) -> tuple[Path, Path]:
    """Copy the project of `src` into a temp dir. Returns (temp_dir, staged_path_of_src).
    A file in a project folder (workspace/proj/tests/x.py) stages the WHOLE project folder, so `import core` works;
    a file directly in workspace/ stages only its sibling files."""
    tmp = Path(tempfile.mkdtemp(prefix="sbx_"))
    ws = WORKSPACE_DIR.resolve()
    try:
        rel = src.resolve().relative_to(ws)
    except ValueError:
        rel = Path(src.name)
    root = ws / rel.parts[0] if len(rel.parts) > 1 else ws       # the top-level project folder
    top = root == ws
    count = size = 0
    for item in root.iterdir():
        if item.name.startswith(".") or item.name in _SKIP_DIRS:
            continue
        try:
            if item.is_file() and item.stat().st_size <= MAX_COPY_FILE:
                shutil.copy2(item, tmp / item.name)
            elif item.is_dir() and not top:
                for dp, dns, fns in os.walk(item):
                    dns[:] = [d for d in dns if not d.startswith(".") and d not in _SKIP_DIRS]
                    out = tmp / Path(dp).relative_to(root)
                    out.mkdir(parents=True, exist_ok=True)
                    for fn in fns:
                        fp = Path(dp) / fn
                        if count >= MAX_STAGE_FILES or size >= MAX_STAGE_BYTES:
                            break
                        if fn.startswith(".") or fp.stat().st_size > MAX_COPY_FILE:
                            continue
                        shutil.copy2(fp, out / fn)
                        count += 1
                        size += fp.stat().st_size
        except OSError:
            pass
    staged = tmp / Path(*rel.parts[1:]) if not top and len(rel.parts) > 1 else tmp / src.name
    return tmp, staged


# ----------------------------------------------------------------- per-language runners
def _argv(argv: str) -> list[str]:
    import shlex
    try:
        return shlex.split(argv or "", posix=not IS_WIN)
    except ValueError:
        return (argv or "").split()


def _finish(code: int, out: str, err: str, status: str, timeout: float, note: str = "") -> Result:
    """Common wording of a run's result."""
    text = out.strip()
    if err.strip():
        text += ("\n" if text else "") + "[stderr]\n" + err.strip()
    text = _clip(text) or "(bez výstupu)"
    if status == "timeout":
        if SERVER_RE.search(out + err):
            return Result(0, f"Server nastartoval bez chyby a bežal do zastavenia po {int(timeout)} s (štart je "
                             f"overený). Správanie endpointov otestuj skriptom (test_client() / requests).\n{text}")
        return Result(1, f"⏱️ Program bežal dlhšie ako {int(timeout)} s a bol zastavený (nekonečná slučka alebo "
                         f"čaká na vstup? Pre vstupy použi stdin).\nVýstup do zastavenia:\n{text}")
    if status == "flood":
        return Result(1, f"Program chrlil príliš veľa výstupu (nekonečný výpis?) a bol zastavený.\n{text}")
    m = MODULE_RE.search(err)
    if m and code != 0:
        text += (f"\n[poznámka] Knižnica '{m.group(1)}' nie je nainštalovaná v prostredí aplikácie "
                 f"(pip install {m.group(1).split('.')[0]}), alebo ju v kóde nepoužívaj.")
    return Result(code, (note + "\n" if note else "") + text)


def _docker(lang: str, work: Path, inner: str, timeout: float, stdin_text: str) -> tuple[int, str, str, str]:
    name = f"sbx_{uuid.uuid4().hex[:10]}"
    cmd = ["docker", "run", "--rm", "-i", "--name", name, "--network", "none", "--memory", "512m", "--cpus", "1",
           "--pids-limit", "256", "-v", f"{work}:/work", "-w", "/work", SANDBOX_DOCKER_IMAGES[lang], "sh", "-c", inner]
    return _exec(cmd, work, stdin_text, timeout, container=name)


def _quote(parts: list[str]) -> str:
    import shlex
    return " ".join(shlex.quote(x) for x in parts)


GUI_RE = re.compile(r"^\s*(?:import|from)\s+(?:tkinter|customtkinter|PyQt[56]|PySide[26]|pygame|wx|kivy)\b|\.mainloop\(",
                    re.M)


def _gui_ok(f: Path, res: Result, timeout: float) -> Result:
    """A GUI program never ends by itself: if it ran until the timeout without a traceback, its start worked."""
    try:
        src = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return res
    if res.code != 1 or "dlhšie ako" not in res.text or "Traceback" in res.text or not GUI_RE.search(src):
        return res
    return Result(0, f"GUI okno sa spustilo bez chyby a bežalo, kým ho sandbox po {int(timeout)} s zastavil "
                     f"(štart je overený; okno v sandboxe neklikneš). Nespúšťaj ho znova a oprav iba to, "
                     f"čo používateľ výslovne chce. Ďalšie testovanie robí používateľ – ty NEČAKAJ na žiadne testovanie, "
                     f"napíš mu teraz krátke zhrnutie (súbory a ako kalkulačku/aplikáciu spustí).")


GUI_TIMEOUT = 8        # a window that opened and stayed up for this long started fine - no need to wait 30 s


def _run_python(f: Path, stdin: str, argv: str, timeout: float) -> Result:
    try:
        gui = bool(GUI_RE.search(f.read_text(encoding="utf-8", errors="replace")))
    except OSError:
        gui = False
    t = min(timeout, GUI_TIMEOUT) if gui else timeout
    return _gui_ok(f, _run_python_raw(f, stdin, argv, t), t)


def _run_python_raw(f: Path, stdin: str, argv: str, timeout: float) -> Result:
    if SANDBOX_MODE == "docker":
        return _finish(*_docker("python", f.parent, _quote(["python", "-X", "utf8", "-u", f.name, *_argv(argv)]),
                                timeout, stdin), timeout)
    return _finish(*_exec([sys.executable, "-X", "utf8", "-u", f.name, *_argv(argv)], f.parent, stdin, timeout), timeout)


def _run_js(f: Path, stdin: str, argv: str, timeout: float) -> Result:
    if SANDBOX_MODE == "docker":
        return _finish(*_docker("javascript", f.parent, _quote(["node", f.name, *_argv(argv)]), timeout, stdin), timeout)
    node = _which("node")
    if not node:
        return Result(127, "Node.js nie je nainštalovaný.\n" + HINTS["javascript"])
    return _finish(*_exec([node, f.name, *_argv(argv)], f.parent, stdin, timeout), timeout)


def _run_native(lang: str, f: Path, stdin: str, argv: str, timeout: float) -> Result:
    """C / C++: compile this file + the other sources of the folder that have no main(), then run."""
    exts = (".c",) if lang == "c" else (".cpp", ".cc", ".cxx")
    sources = [f.name]
    for other in sorted(f.parent.iterdir()):
        if other.suffix.lower() in exts and other.name != f.name:
            try:
                if not re.search(r"\bmain\s*\(", other.read_text(encoding="utf-8", errors="ignore")):
                    sources.append(other.name)
            except OSError:
                pass
    flags = (["-std=c11"] if lang == "c" else ["-std=c++17"]) + ["-Wall", "-Wextra", "-O0"]
    exe = "prog.exe" if IS_WIN else "prog"
    if SANDBOX_MODE == "docker":
        compiler = "gcc" if lang == "c" else "g++"
        inner = (f"{compiler} {_quote(flags)} -o {exe} {_quote(sources)} -lm && ./{exe} {_quote(_argv(argv))}")
        return _finish(*_docker(lang, f.parent, inner, timeout + SANDBOX_COMPILE_TIMEOUT, stdin), timeout)
    compiler = _which("gcc", "cc", "clang") if lang == "c" else _which("g++", "c++", "clang++")
    if not compiler:
        return Result(127, f"Kompilátor pre {'C' if lang == 'c' else 'C++'} nie je nainštalovaný.\n" + HINTS[lang])
    code, out, err, status = _exec([compiler, *flags, "-o", exe, *sources, "-lm"], f.parent, "", SANDBOX_COMPILE_TIMEOUT)
    log = (out + err).strip()
    if status != "ok" or code != 0:
        return Result(1, "Kompilácia zlyhala:\n" + _clip(log or "(kompilátor nevypísal nič)"))
    note = f"[varovania kompilátora]\n{_clip(log)}" if log else ""
    res = _finish(*_exec([str(f.parent / exe), *_argv(argv)], f.parent, stdin, timeout), timeout, note)
    if res.code in (-11, 139, -6, 134, -8, 136):                         # signal exits on POSIX
        res.text += "\n[poznámka] Program spadol (segfault / abort / delenie nulou) – skontroluj indexy, ukazovatele a delenie."
    return res


class _HtmlCheck(HTMLParser):
    """Light static check: unclosed / stray tags and local files that do not exist."""
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, base: Path):
        super().__init__()
        self.base, self.stack, self.problems, self.text, self._skip = base, [], [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)
        if tag in ("script", "style"):
            self._skip += 1
        for k, v in attrs:
            if k in ("src", "href") and v and not re.match(r"(?:[a-z][a-z0-9+.-]*:|//|#)", v, re.I):
                if not (self.base / v.split("#")[0].split("?")[0]).exists():
                    self.problems.append(f"Chýba lokálny súbor: {v}")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if tag in self.VOID:
            return
        if tag in self.stack:
            while self.stack and self.stack[-1] != tag:
                self.problems.append(f"Neuzavretá značka <{self.stack.pop()}>")
            self.stack.pop()
        else:
            self.problems.append(f"Nadbytočná uzatváracia značka </{tag}>")

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.text.append(data.strip())


def _run_html(f: Path, work_rel: Path, src_rel_png: str, timeout: float) -> Result:
    html = f.read_text(encoding="utf-8", errors="replace")
    chk = _HtmlCheck(f.parent)
    chk.feed(html)
    problems = chk.problems + [f"Neuzavretá značka <{t}>" for t in chk.stack if t not in ("html", "body", "head", "p", "li")]
    if "<!doctype" not in html[:200].lower():
        problems.append("Chýba <!DOCTYPE html> (prehliadač prejde do quirks režimu).")
    browser = find_browser()
    files: list[str] = []
    console: list[str] = []
    visible = " ".join(chk.text)
    note = ""
    if browser:
        url = f.resolve().as_uri()
        prof = Path(tempfile.mkdtemp(prefix="sbx_prof_"))
        base = [browser, "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                f"--user-data-dir={prof}", "--enable-logging=stderr", "--v=0", "--virtual-time-budget=4000"]
        try:
            code, dom, err, status = _exec(base + ["--dump-dom", url], f.parent, "", timeout)
            for line in err.splitlines():
                if "CONSOLE" in line:
                    msg = re.sub(r"^\[[^\]]*\]\s*", "", line).strip()
                    console.append(msg[:300])
            if status == "ok" and dom.strip():
                d = _HtmlCheck(f.parent)
                d.feed(dom)
                visible = " ".join(d.text)
            png = f.parent / "nahlad.png"
            _exec(base + [f"--screenshot={png}", "--window-size=1280,800", url], f.parent, "", timeout)
            if png.is_file() and png.stat().st_size > 0:
                dest = workspace.safe_path(src_rel_png)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(png, dest)
                files.append(src_rel_png)
        finally:
            shutil.rmtree(prof, ignore_errors=True)
    else:
        note = "Prehliadač sa nenašiel – JavaScript sa nespustil, výsledok je len statická kontrola.\n" + HINTS["html"]
    errors = [c for c in console if re.search(r"error|uncaught|failed|refused|not defined", c, re.I)]
    lines = []
    if note:
        lines.append(note)
    if problems:
        lines.append("Problémy v HTML:\n- " + "\n- ".join(dict.fromkeys(problems)))
    if console:
        lines.append("Konzola prehliadača:\n- " + "\n- ".join(console[:15]))
    if browser and not console:
        lines.append("Konzola prehliadača: bez hlásení.")
    lines.append("Viditeľný text stránky: " + (_clip(visible)[:600] or "(prázdna stránka)"))
    if files:
        lines.append(f"Screenshot uložený: {files[0]} (obsah si môžeš nechať popísať cez describe_image).")
    return Result(1 if (errors or problems) else 0, "\n".join(lines), files)


# ----------------------------------------------------------------- public API
def run(rel: str, stdin: str = "", argv: str = "", timeout: float = RUN_TIMEOUT) -> Result:
    """Run / check the workspace file `rel` in a throw-away copy. Never raises."""
    try:
        src = workspace.safe_path(rel)
    except workspace.WorkspaceError as e:
        return Result(1, str(e))
    if not src.is_file():
        return Result(1, f"Súbor '{rel}' neexistuje.")
    lang = LANGS.get(src.suffix.lower())
    if not lang:
        return Result(1, f"Typ súboru '{src.suffix}' neviem spustiť. Podporované: {', '.join(RUNNABLE)}.")
    tmp, staged = _stage(src)
    try:
        if lang == "python":
            return _run_python(staged, stdin, argv, timeout)
        if lang == "javascript":
            return _run_js(staged, stdin, argv, timeout)
        if lang in ("c", "cpp"):
            return _run_native(lang, staged, stdin, argv, timeout)
        png = str(Path(rel).with_name(Path(rel).stem + "_nahlad.png")).replace("\\", "/")
        return _run_html(staged, tmp, png, timeout)
    except Exception as e:                                           # the sandbox must never crash the agent loop
        return Result(1, f"Chyba sandboxu: {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
