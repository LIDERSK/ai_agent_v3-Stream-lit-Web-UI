"""Workspace sandbox: path jail, file helpers, saving generated code, running scripts, self-heal.

Everything the agent (or the UI) may touch lives inside WORKSPACE_DIR. safe_path() is the only gate.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path

from config import (HISTORY_DIR, MAX_WRITE_CHARS, RUN_TIMEOUT, TOOL_RESULT_MAX, WORKSPACE_DIR,
                    ZIP_NAME_MAX)
from core.ollama_client import OllamaError, chat_once


class WorkspaceError(Exception):
    """Readable error for refused / failed file operations."""


# ----------------------------------------------------------------- sandbox
def safe_path(rel: str) -> Path:
    rel = (rel or "").strip().replace("\\", "/")
    if not rel:
        raise WorkspaceError("Chýba cesta k súboru.")
    if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel) or "\x00" in rel:
        raise WorkspaceError("Použi relatívnu cestu vo workspace/ (bez disku a bez / na začiatku).")
    root = WORKSPACE_DIR.resolve()
    p = (root / rel).resolve()
    if p != root and root not in p.parents:
        raise WorkspaceError("Prístup mimo priečinka workspace/ je zakázaný.")
    if ".history" in p.relative_to(root).parts:
        raise WorkspaceError("Priečinok .history je chránený.")
    return p


def list_tree(limit: int = 500, by_mtime: bool = True) -> list[str]:
    """Relative posix paths of all files in the workspace (hidden folders skipped)."""
    root = WORKSPACE_DIR.resolve()
    files = [p for p in root.rglob("*")
             if p.is_file() and not any(part.startswith(".") for part in p.relative_to(root).parts)]
    files.sort(key=(lambda p: -p.stat().st_mtime) if by_mtime else (lambda p: p.as_posix()))
    return [p.relative_to(root).as_posix() for p in files[:limit]]


def read_full(rel: str) -> str:
    """The whole file (no shortening) - for tools that cut / number the text themselves."""
    return read_text(rel, max_chars=10**9)


def read_text(rel: str, max_chars: int = TOOL_RESULT_MAX) -> str:
    p = safe_path(rel)
    if not p.is_file():
        raise WorkspaceError(f"Súbor '{rel}' neexistuje. Použi list_files.")
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        ext = p.suffix.lower()
        hint = (" Je to ZIP: použi zip_list / zip_read / zip_extract." if ext == ".zip" else
                " Na dokumenty použi read_document." if ext in (".pdf", ".docx", ".xlsx", ".pptx") else "")
        raise WorkspaceError(f"Súbor '{rel}' nie je textový (UTF-8).{hint}")
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n[... skrátené, súbor má {len(text)} znakov ...]"
    return text


def write_text(rel: str, content: str) -> bool:
    """Write a file (backup of the old version goes to .history). Returns False if unchanged."""
    if len(content) > MAX_WRITE_CHARS:
        raise WorkspaceError(f"Súbor je príliš veľký (max {MAX_WRITE_CHARS} znakov).")
    p = safe_path(rel)
    if p.exists():
        if p.is_dir():
            raise WorkspaceError(f"'{rel}' je priečinok.")
        if p.read_text(encoding="utf-8", errors="ignore") == content:
            return False
        shutil.copy2(p, HISTORY_DIR / f"{p.name}.{datetime.now():%Y%m%d_%H%M%S}.bak")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return True


UPLOAD_DIR = "nahrate"
MAX_UPLOAD = 100 * 1024 * 1024


def save_upload(name: str, data: bytes) -> str:
    """Binary upload (ZIP, PDF, Office) -> workspace/nahrate/<name>; never overwrites (name_2.ext ...)."""
    if len(data) > MAX_UPLOAD:
        raise WorkspaceError(f"Súbor má {len(data) // 1024 // 1024} MB (max {MAX_UPLOAD // 1024 // 1024} MB).")
    rel = clean_rel_path(f"{UPLOAD_DIR}/{Path(name).name}")
    stem, dot, ext = rel.rpartition(".")
    n = 1
    while safe_path(rel).exists():
        if safe_path(rel).read_bytes() == data:
            return rel                                           # the same file again
        n += 1
        rel = f"{stem}_{n}.{ext}" if dot else f"{rel}_{n}"
    p = safe_path(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return rel


def delete_file(rel: str) -> None:
    p = safe_path(rel)
    if not p.is_file():
        raise WorkspaceError(f"Súbor '{rel}' neexistuje.")
    shutil.copy2(p, HISTORY_DIR / f"{p.name}.{datetime.now():%Y%m%d_%H%M%S}.deleted.bak")
    p.unlink()


# ----------------------------------------------------------------- meaningful file names
GENERIC_STEMS = {"script", "scripts", "file", "files", "untitled", "new", "newfile", "output", "temp", "tmp",
                 "test", "tests", "code", "example", "sample", "foo", "bar", "data", "text", "document",
                 "doc", "soubor", "subor", "skript", "kod", "vystup", "poznamka"}
STOPWORDS = {"a", "i", "o", "u", "v", "s", "k", "na", "do", "po", "pre", "ako", "ktory", "ktora", "ktore",
             "ze", "aby", "mi", "ma", "je", "si", "sa", "to", "the", "an", "of", "for", "and", "with",
             "that", "me", "my", "please", "write", "make", "create", "napis", "napis", "vytvor", "urob",
             "spravi", "daj", "prosim", "chcem", "potrebujem", "jednoduchy", "jednoduchu", "jednoduche",
             "skript", "script", "program", "kod", "code", "subor", "file", "python", "pythone", "pythonu"}


def slugify(text: str, max_len: int = ZIP_NAME_MAX, words: int = 4) -> str:
    """'Napíš skript na zálohu priečinka' -> 'zaloha_priecinka' (ASCII, snake_case, topic words only)."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    toks = [t for t in re.findall(r"[a-z0-9]+", text) if t not in STOPWORDS and not t.isdigit()]
    return "_".join(toks[:words])[:max_len].strip("_")


def clean_rel_path(rel: str) -> str:
    """Normalise a path the model chose: no spaces / odd characters, keep folders and the extension."""
    rel = (rel or "").strip().strip("`'\"").replace("\\", "/")
    parts = []
    for part in [x for x in rel.split("/") if x not in ("", ".")]:
        stem, dot, ext = part.rpartition(".")
        if not dot:
            stem, ext = part, ""
        stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
        stem = re.sub(r"[^\w\-]+", "_", stem).strip("_")
        if not stem.isupper():                          # keep README / LICENSE, lowercase the rest
            stem = stem.lower()
        if part.startswith(".") and not stem:            # e.g. ".gitignore" - keep as is
            stem, ext = "", part[1:]
            parts.append("." + re.sub(r"[^\w\-]", "", ext))
            continue
        parts.append(f"{stem}.{ext.lower()}" if ext else stem)
    return "/".join(parts)


def check_meaningful_name(rel: str) -> None:
    """Refuse nameless top-level files like script.py / test.py / output_3.txt."""
    clean = clean_rel_path(rel)
    if not clean:
        raise WorkspaceError("Chýba názov súboru.")
    if "/" in clean:                                      # inside a project folder -> main.py etc. are fine
        return
    stem = clean.rsplit(".", 1)[0].lower()
    base = re.sub(r"[_\-]?\d+$", "", stem)               # test_1 / script2 -> test / script
    if stem in GENERIC_STEMS or base in GENERIC_STEMS or re.fullmatch(r"[\d_\-]+", stem):
        raise WorkspaceError(
            f"Názov '{rel}' je príliš všeobecný. Zvoľ názov podľa témy súboru (napr. 'zaloha_priecinka.py', "
            "'todo_aplikacia/main.py' alebo 'poznamky_python_verzia.md').")


def unique_path(rel: str, content: str | None = None) -> str:
    """If `rel` exists with different content, return 'name_2.ext', 'name_3.ext' ... (never overwrite by accident)."""
    p = safe_path(rel)
    if not p.exists() or (content is not None and p.read_text(encoding="utf-8", errors="ignore") == content):
        return rel
    stem, dot, ext = rel.rpartition(".")
    if not dot:
        stem, ext = rel, ""
    for n in range(2, 100):
        cand = f"{stem}_{n}{'.' + ext if ext else ''}"
        q = safe_path(cand)
        if not q.exists() or (content is not None and q.read_text(encoding="utf-8", errors="ignore") == content):
            return cand
    return rel


def suggest_filename(code: str, lang: str, topic: str = "") -> str:
    """Name for an unnamed code block: topic of the request, else main def/class, else first comment."""
    ext = EXT.get(lang, "txt")
    base = slugify(topic)
    if not base:
        m = re.search(r"^\s*(?:async\s+def|def|class|function|const|fn|func)\s+(\w+)", code, re.M)
        if m and m.group(1) not in ("main", "__init__"):
            base = slugify(m.group(1).replace("_", " "))
    if not base:
        m = re.search(r"<title>(.*?)</title>", code, re.I | re.S) or re.search(r"^\s*(?:#|//)\s*(.+)$", code, re.M)
        base = slugify(m.group(1)) if m else ""
    base = base or "kod"
    if base in GENERIC_STEMS:
        base += "_" + datetime.now().strftime("%d%m_%H%M")
    return f"{base}.{ext}"


# ----------------------------------------------------------------- saving model code (normal chat)
EXT = {"python": "py", "py": "py", "javascript": "js", "js": "js", "typescript": "ts",
       "html": "html", "css": "css", "json": "json", "yaml": "yml", "yml": "yml",
       "bash": "sh", "sh": "sh", "sql": "sql", "java": "java", "cpp": "cpp", "c": "c",
       "go": "go", "rust": "rs", "markdown": "md", "md": "md"}
SKIP_UNNAMED = {"", "text", "txt", "console", "output", "bash", "sh", "shell", "json", "markdown", "md"}
FILE_RE = re.compile(r"([\w\-./]+\.(?:py|js|ts|html|css|json|yml|yaml|sh|sql|java|cpp|c|go|rs|md|txt))")


def _find_filename(text: str, start: int, code: str):
    first = code.strip().splitlines()[0] if code.strip() else ""
    m = re.match(r"^\s*(?:#|//|<!--)\s*(?:file(?:name)?|súbor)\s*:\s*(\S+)", first, re.I)
    if m:
        return m.group(1).strip("`'\"")
    before = [l for l in text[max(0, start - 250):start].splitlines() if l.strip()]
    if before:
        found = FILE_RE.findall(before[-1])
        if found:
            return found[-1]
    return None


_EXT_LANGS = {"py": {"python", "py", ""}, "js": {"javascript", "js", ""}, "html": {"html", ""}, "c": {"c", ""},
              "cpp": {"cpp", "c++", ""}, "sh": {"bash", "sh", ""}, "json": {"json", ""}}
WANTED_RE = re.compile(r"(?<![\w/.-])([A-Za-z0-9_\-]+\.(?:py|js|html|css|c|cpp|h|json|sh|md|txt))\b")


BARE_NAME_RE = re.compile(r"^\s*[`'\"]?([\w\-]+\.(?:py|js|html|css|c|cpp|h|json|sh|md|txt))[`'\"]?\s*:?\s*$")


def strip_name_line(code: str) -> tuple[str, str | None]:
    """A code block whose FIRST line is only the file name (`server.py`) -> (code without it, that name)."""
    first, _, rest = code.partition("\n")
    m = BARE_NAME_RE.match(first)
    return (rest.lstrip("\n"), m.group(1)) if m and rest.strip() else (code, None)


def wanted_files(task: str) -> list[str]:
    """File names the user explicitly asked for ('... v súbore server.py ...')."""
    return list(dict.fromkeys(WANTED_RE.findall(task or "")))


def save_generated_code(text: str, topic: str = "", wanted: list[str] | None = None) -> list[str]:
    """Save every named / substantial code block to workspace/. Returns saved filenames.

    `topic` (usually the user's question) is used to give unnamed blocks a meaningful name.
    Several unnamed blocks of one answer get _2, _3 ... instead of overwriting each other.
    `wanted`: file names the user asked for. The biggest unnamed block of the right language becomes the first
    of them, the other unnamed blocks of that language are fragments of it and are NOT saved as extra files.
    """
    blocks = []
    for m in re.finditer(r"```([^\s`]*)[ \t]*\n(.*?)```", text, re.S):
        lang, code = m.group(1).lower(), m.group(2).rstrip() + "\n"
        name = _find_filename(text, m.start(), code)
        if re.fullmatch(r"[\w\-]+\.\w{1,5}", lang):                  # ```server.py  = the fence names the file
            name = name or m.group(1)
            lang = {"py": "python", "js": "javascript"}.get(lang.rsplit(".", 1)[-1], lang.rsplit(".", 1)[-1])
        code, inner = strip_name_line(code)               # "`server.py`" as the first line is not code
        name = name or inner
        blocks.append({"lang": lang, "code": code, "name": name})
    if wanted:
        target = wanted[0]
        langs = _EXT_LANGS.get(target.rsplit(".", 1)[-1].lower(), set())
        same = [b for b in blocks if not b["name"] and b["lang"] in langs]
        if same and not any(b["name"] == target for b in blocks):
            main = max(same, key=lambda b: len(b["code"]))
            main["name"] = target
            for b in same:
                if b is not main:
                    b["skip"] = True
    saved = []
    for b in blocks:
        if b.get("skip"):
            continue
        lang, code, name = b["lang"], b["code"], b["name"]
        if name:
            name = clean_rel_path(Path(name).name)       # flat names only
        else:
            if lang in SKIP_UNNAMED or len(code.splitlines()) < 4:
                continue                                  # snippet / command / output, not a file
            name = suggest_filename(code, lang, topic)
        try:
            name = unique_path(name, code) if name not in saved else unique_path(name)
            if write_text(name, code):
                saved.append(name)
        except WorkspaceError:
            continue
    return saved


def rename_file(old: str, new: str) -> str:
    """Rename / move a file inside the workspace (the backup of an overwritten target goes to .history)."""
    check_meaningful_name(new)
    src, new = safe_path(old), clean_rel_path(new)
    if not src.is_file():
        raise WorkspaceError(f"Súbor '{old}' neexistuje.")
    dst = safe_path(new)
    if dst.exists():
        raise WorkspaceError(f"Cieľ '{new}' už existuje.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return new


# ----------------------------------------------------------------- delivery: ZIP, open on this PC
def make_zip(rels: list[str] | None = None) -> bytes:
    """ZIP (in memory) of the given workspace files, or of everything when `rels` is None."""
    rels = list_tree(by_mtime=False) if rels is None else rels
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in rels:
            try:
                p = safe_path(rel)
            except WorkspaceError:
                continue
            if p.is_file():
                z.write(p, arcname=rel)
    return buf.getvalue()


def zip_name(rels: list[str], topic: str = "") -> str:
    """'zaloha_priecinka_2026-10-17.zip' - named after the topic or the common folder / first file."""
    base = slugify(topic) or ""
    if not base and rels:
        tops = {r.split("/")[0] for r in rels if "/" in r}
        base = next(iter(tops)) if len(tops) == 1 and all("/" in r for r in rels) else rels[0].rsplit(".", 1)[0]
        base = slugify(base.replace("_", " ")) or "workspace"
    return f"{base or 'workspace'}_{datetime.now():%Y-%m-%d}.zip"


def existing(rels: list[str]) -> list[str]:
    out = []
    for r in rels or []:
        try:
            if safe_path(r).is_file():
                out.append(r)
        except WorkspaceError:
            pass
    return out


def open_in_explorer(rel: str | None = None) -> str:
    """Open the workspace folder (or select one file) in the file manager of THIS computer."""
    target = safe_path(rel) if rel else WORKSPACE_DIR.resolve()
    try:
        if sys.platform.startswith("win"):
            if target.is_file():
                subprocess.Popen(["explorer", "/select,", str(target)])
            else:
                os.startfile(str(target))                 # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(target)] if target.is_file() else ["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target if target.is_dir() else target.parent)])
    except Exception as e:
        raise WorkspaceError(f"Priečinok sa nepodarilo otvoriť: {e}")
    return str(target)


# ----------------------------------------------------------------- running scripts
def list_scripts() -> list[str]:
    return [f for f in list_tree() if f.endswith(".py")]


def run_python(rel: str, stdin: str = "", timeout: int = RUN_TIMEOUT) -> tuple[int, str]:
    try:
        path = safe_path(rel)
    except WorkspaceError as e:
        return 1, str(e)
    if not path.is_file():
        return 1, f"Súbor '{rel}' neexistuje."
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    try:
        p = subprocess.run([sys.executable, str(path)], input=stdin or "", capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           cwd=path.parent, env=env,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (p.stdout or "") + (f"\n[stderr]\n{p.stderr}" if p.stderr else "")
        return p.returncode, out.strip() or "(bez výstupu)"
    except subprocess.TimeoutExpired:
        return 1, f"⏱️ Skript bežal dlhšie ako {timeout}s a bol zastavený."
    except Exception as e:
        return 1, f"Chyba pri spustení: {e}"


def run_script(rel: str, stdin: str = "", timeout: int = RUN_TIMEOUT) -> str:
    code, out = run_python(rel, stdin, timeout)
    return f"{'✅' if code == 0 else '❌'} Exit code {code}\n\n{out}"


def self_heal(rel: str, stdin: str, url: str, model: str, temperature: float = 0.2,
              max_attempts: int = 3) -> str:
    """Run -> on error ask the model for a fix -> back up + rewrite -> retry."""
    log = []
    for attempt in range(1, max_attempts + 1):
        code, out = run_python(rel, stdin)
        if code == 0:
            log.append(f"✅ Pokus {attempt}: skript beží bez chyby.\n{out}")
            break
        log.append(f"❌ Pokus {attempt}: chyba\n{out[-1200:]}")
        if attempt == max_attempts:
            break
        try:
            source = read_text(rel, max_chars=60000)
            prompt = ("Oprav tento Python skript. Vráť IBA kompletný opravený skript v jednom "
                      f"```python bloku, bez vysvetlenia.\n\nSKRIPT:\n```python\n{source}\n```\n\n"
                      f"CHYBA:\n{out[-2000:]}")
            answer = chat_once(url, model, [{"role": "user", "content": prompt}], temperature)
        except (OllamaError, WorkspaceError) as e:
            log.append(f"⚠️ {e}")
            break
        m = re.search(r"```(?:python|py)?\s*\n(.*?)```", answer, re.S)
        if not m:
            log.append(f"⚠️ Model nevrátil kód:\n{answer[:500]}")
            break
        write_text(rel, m.group(1).rstrip() + "\n")
        log.append("🔧 Model navrhol opravu, skúšam znova… (záloha je v workspace/.history)")
    return "\n\n".join(log)
