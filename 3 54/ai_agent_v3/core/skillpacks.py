"""Skill packs = instruction skills in the common "SKILL.md" format (Claude / Codex style agent skills).

A pack is a folder in skill_packs/<id>/:
    SKILL.md        frontmatter (name, description) + instructions in Markdown
    scripts/ references/ assets/   optional bundled files (anything inside the folder)
    skillpack.json  our own metadata (source, original format, translation notes, warnings)

Packs are NOT Python code. They are loaded the way commercial agents do it ("progressive disclosure"):
  1. the agent prompt lists only name + description of every enabled pack (cheap),
  2. when a task fits, the agent calls skill_use and gets the full instructions,
  3. bundled files are read on demand (skill_file); scripts are staged into workspace/skills/<id>/ so run_code can run them.

This module also IMPORTS and TRANSLATES packs from the internet / other tools into this format:
  - SKILL.md folders, ZIPs (also whole repositories with many skills) and *.skill files (= ZIP)
  - a single SKILL.md / .md file, or pasted text
  - Cursor rules (*.mdc: description, globs, alwaysApply) and Claude Code commands / agents (*.md with
    frontmatter: description, allowed-tools, model ...)
  - http(s) URLs (GitHub "blob" links are turned into raw links, repositories into their ZIP)
Foreign tool names in the text (Bash, Read, Edit, Grep, WebFetch ...) are mapped to our tools when the pack is loaded.
No Streamlit imports here.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import time
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from config import (SKILLPACK_DOWNLOAD_MAX, SKILLPACK_FILE_MAX, SKILLPACK_MAX_BYTES, SKILLPACK_MAX_FILES,
                    SKILLPACK_PROMPT_CHARS, SKILLPACKS_DIR, WORKSPACE_DIR)
from core import settings_store
from core.fileio import atomic_write_text

SKILL_FILE = "SKILL.md"
META_FILE = "skillpack.json"
STAGE_DIR = "skills"                       # workspace/skills/<id>/  (scripts staged for run_code)
NAME_MAX, DESC_MAX = 64, 1024
TEXT_SUFFIX = {".md", ".txt", ".py", ".js", ".json", ".yml", ".yaml", ".csv", ".html", ".css", ".sh", ".bat", ".ps1",
               ".toml", ".ini", ".xml", ".sql", ".ts", ".c", ".cpp", ".h", ".rst", ".mdc", ".cfg", ".tsv", ".svg"}
SKIP_NAMES = {".git", ".github", "__pycache__", ".DS_Store", "node_modules", "__MACOSX", ".idea", ".vscode"}


class PackError(Exception):
    """Readable reason why a pack could not be read / installed."""


# ----------------------------------------------------------------- tool-name translation (foreign -> ours)
# Commercial skills talk about THEIR tool names. When a pack is loaded we add a short table for exactly those
# names that appear in its text, so a small local model knows what to call.
TOOL_MAP = (
    (r"\bBash\b|\bshell command\b", "run_code (spustí súbor z workspace/) – voľný príkazový riadok nie je dostupný"),
    (r"\bRead\b(?= tool| the file|\()|\bView\b(?= tool)|\bcat\b(?= the file)", "read_file"),
    (r"\bWrite\b(?= tool| the file|\()|\bCreate File\b", "write_file"),
    (r"\bEdit\b(?= tool|\()|\bMultiEdit\b|\bstr_replace\b", "edit_file"),
    (r"\bGrep\b|\bripgrep\b", "search_files"),
    (r"\bGlob\b|\bLS\b(?= tool)|\bListDir\b", "list_files"),
    (r"\bWebFetch\b|\bfetch_url\b|\bweb_fetch\b", "fetch_url"),
    (r"\bWebSearch\b|\bweb_search\b", "web_search"),
    (r"\bTodoWrite\b|\bTodoRead\b", "plan_set / plan_done"),
    (r"\bTask\b(?= tool)|\bsubagents?\b", "(podagenti nie sú k dispozícii – rob úlohu sám, krok za krokom)"),
)
TOOL_NAMES = {   # the label shown in the table (kept apart so the regex above stays readable)
    0: "Bash", 1: "Read", 2: "Write", 3: "Edit", 4: "Grep", 5: "Glob", 6: "WebFetch", 7: "WebSearch",
    8: "TodoWrite", 9: "Task / subagent"}
RISKY = re.compile(r"curl[^\n]*\|\s*(?:ba)?sh|wget[^\n]*\|\s*(?:ba)?sh|rm\s+-rf\s+[/~]|Invoke-Expression|\biex\b\s*\(|"
                   r"eval\(|base64\s+-d|chmod\s+\+x|sudo\s", re.I)
INJECTION = re.compile(r"ignore (?:all |any )?(?:previous|prior|above) instructions|disregard (?:the )?(?:system|previous)|"
                       r"ignoruj (?:všetky )?(?:predchádzajúce|predošlé) (?:pokyny|inštrukcie)", re.I)


# ----------------------------------------------------------------- data
@dataclass
class Pack:
    id: str
    name: str
    description: str
    body: str                                  # SKILL.md without the frontmatter
    path: object = None                        # folder
    meta: dict = field(default_factory=dict)
    files: list = field(default_factory=list)  # bundled files (relative, without SKILL.md / skillpack.json)

    @property
    def source(self) -> str:
        return self.meta.get("source", "builtin")

    @property
    def triggers(self) -> list:
        return list(self.meta.get("triggers", []))

    @property
    def warnings(self) -> list:
        return list(self.meta.get("warnings", []))

    @property
    def scripts(self) -> list:
        return [f for f in self.files if f.startswith("scripts/") or f.rsplit(".", 1)[-1].lower() in ("py", "js", "sh", "bat", "ps1")]


# ----------------------------------------------------------------- small text helpers
def slugify(text: str, max_len: int = NAME_MAX) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:max_len].strip("-") or "skill"


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", (text or "").lower()).encode("ascii", "ignore").decode()


def _scalar(v: str):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    if v.startswith("[") and v.endswith("]"):
        return [x.strip().strip("\"'") for x in v[1:-1].split(",") if x.strip()]
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    return v


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """(frontmatter dict, body). Understands `key: value`, quoted values, `>` / `|` blocks, `[a, b]` and `- item` lists.
    No YAML library needed; anything it can't read is skipped instead of failing the import."""
    text = (text or "").lstrip("\ufeff")
    m = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", text, re.S)
    if not m:
        return {}, text
    meta: dict = {}
    lines = m.group(1).splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        km = re.match(r"^([A-Za-z0-9_.\- ]+?)\s*:\s*(.*)$", line)
        if not km or line.startswith((" ", "\t", "#", "-")):
            i += 1
            continue
        key, val = km.group(1).strip().lower(), km.group(2).strip()
        i += 1
        if val in (">", "|", ">-", "|-", ">+", "|+"):
            block = []
            while i < len(lines) and (not lines[i].strip() or lines[i].startswith((" ", "\t"))):
                block.append(lines[i].strip())
                i += 1
            meta[key] = (" " if val.startswith(">") else "\n").join(b for b in block if b or val.startswith("|")).strip()
        elif val == "":
            items = []
            while i < len(lines) and (not lines[i].strip() or lines[i].lstrip().startswith("-") or lines[i].startswith((" ", "\t"))):
                s = lines[i].strip()
                if s.startswith("-"):
                    items.append(_scalar(s[1:]))
                elif s and ":" in s:                       # nested mapping (metadata:) -> keep as flat text
                    items.append(s)
                i += 1
            meta[key] = items if items else ""
        else:
            meta[key] = _scalar(val)
    return meta, text[m.end():]


def dump_frontmatter(meta: dict, body: str) -> str:
    def q(v: str) -> str:
        return json.dumps(v, ensure_ascii=False)
    head = ["---", f"name: {q(meta['name'])}", f"description: {q(meta['description'])}"]
    head.append("---")
    return "\n".join(head) + "\n\n" + body.strip() + "\n"


def _first_paragraph(body: str) -> str:
    """First real paragraph of a Markdown text (headings, code blocks, tables and rules are skipped)."""
    for block in re.split(r"\n\s*\n", body.strip()):
        lines = [l for l in block.strip().splitlines()]
        while lines and lines[0].lstrip().startswith("#"):          # a heading directly above the text
            lines.pop(0)
        b = " ".join(l.strip() for l in lines).strip()
        if b and not b.startswith(("```", "|", "---", "===")):
            return re.sub(r"\s+", " ", b)[:DESC_MAX]
    return ""


def _title(body: str) -> str:
    m = re.search(r"^#\s+(.+)$", body, re.M)
    return m.group(1).strip() if m else ""


def _keywords(text: str) -> set:
    stop = {"a", "i", "o", "u", "v", "s", "k", "na", "do", "po", "pre", "ako", "the", "and", "for", "with", "use", "when",
            "this", "that", "from", "you", "your", "are", "can", "not", "all", "any", "ked", "ktory", "ktora", "ktore",
            "alebo", "tiez", "ma", "je", "sa", "si", "to", "ten", "pri", "pouzi", "pouzivaj", "files", "file", "skill"}
    return {w for w in re.findall(r"[a-z0-9]{3,}", _fold(text)) if w not in stop}


# ----------------------------------------------------------------- reading installed packs
def _read_meta(folder) -> dict:
    try:
        return json.loads((folder / META_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _bundled(folder) -> list[str]:
    out = []
    for p in sorted(folder.rglob("*")):
        if p.is_file() and p.name not in (SKILL_FILE, META_FILE) and not any(part in SKIP_NAMES for part in p.relative_to(folder).parts):
            out.append(p.relative_to(folder).as_posix())
    return out


def _load_folder(folder) -> Pack | None:
    f = folder / SKILL_FILE
    try:
        text = f.read_text(encoding="utf-8")
    except OSError:
        return None
    fm, body = parse_frontmatter(text)
    pid = folder.name
    name = str(fm.get("name") or pid)
    desc = str(fm.get("description") or _first_paragraph(body))
    return Pack(pid, name, desc, body.strip(), folder, _read_meta(folder), _bundled(folder))


def list_packs() -> list[Pack]:
    """All installed packs (built-in first, then imported), read fresh from disk - no restart needed."""
    packs = []
    if SKILLPACKS_DIR.is_dir():
        for d in sorted(SKILLPACKS_DIR.iterdir()):
            if d.is_dir() and not d.name.startswith("."):
                p = _load_folder(d)
                if p:
                    packs.append(p)
    return sorted(packs, key=lambda p: (p.source != "builtin", p.id))


def get_pack(pid: str) -> Pack | None:
    pid = slugify(pid or "")
    for p in list_packs():
        if p.id == pid or slugify(p.name) == pid:
            return p
    return None


def find_pack(query: str) -> Pack | None:
    """Exact id / name first, then a unique partial match - small models often write the name a bit differently."""
    q = (query or "").strip()
    if not q:
        return None
    exact = get_pack(q)
    if exact:
        return exact
    qs = slugify(q)
    hits = [p for p in list_packs() if qs in p.id or p.id in qs or qs in slugify(p.name)]
    return hits[0] if len(hits) == 1 else None


# ----------------------------------------------------------------- enabled state
def is_enabled(pid: str, default: bool = True) -> bool:
    return bool(settings_store.get("skillpacks", {}).get(pid, default))


def set_enabled(pid: str, value: bool) -> None:
    saved = dict(settings_store.get("skillpacks", {}))
    saved[pid] = bool(value)
    settings_store.put("skillpacks", saved)


def enabled_packs() -> list[Pack]:
    return [p for p in list_packs() if is_enabled(p.id, p.meta.get("default_enabled", True))]


# ----------------------------------------------------------------- matching a task to packs
def score(task: str, pack: Pack) -> float:
    t = _keywords(task)
    if not t:
        return 0.0
    name_kw = _keywords(pack.name + " " + pack.id.replace("-", " "))
    desc_kw = _keywords(pack.description)
    trig = _keywords(" ".join(pack.triggers))
    return 3.0 * len(t & trig) + 2.0 * len(t & name_kw) + 1.0 * len(t & desc_kw)


def suggest(task: str, limit: int = 2, min_score: float = 2.0) -> list[Pack]:
    ranked = sorted(((score(task, p), p) for p in enabled_packs()), key=lambda x: -x[0])
    return [p for s, p in ranked if s >= min_score][:limit]


def _short(text: str, n: int) -> str:
    """Cut at a word boundary (the agent prompt must stay small: the local model has a small context window)."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def prompt_section(task: str = "") -> str:
    """The block for the agent's system prompt: enabled packs (id + a few words) and a hint for the best match."""
    packs = enabled_packs()
    if not packs:
        return ""
    lines, used = [], 0
    for p in packs:
        line = f"- {p.id}: {_short(p.description.split('. ')[0], 70)}"
        if used + len(line) > SKILLPACK_PROMPT_CHARS:
            lines.append(f"- … a ďalších {len(packs) - len(lines)} (skill_list)")
            break
        lines.append(line)
        used += len(line) + 1
    out = ("\n\nBALÍKY SKILLOV: ak úloha sedí, najprv skill_use skill=\"<id>\" a riaď sa postupom.\n" + "\n".join(lines))
    best = suggest(task)
    if best:
        out += "\nPRE TÚTO ÚLOHU SEDÍ: " + ", ".join(p.id for p in best) + " → skill_use."
    return out


# ----------------------------------------------------------------- loading for the agent
def tool_notes(body: str) -> str:
    """Table 'foreign tool name -> our tool' for the names that really occur in this pack's text."""
    rows = [f"{TOOL_NAMES[i]} → {ours}" for i, (rx, ours) in enumerate(TOOL_MAP) if re.search(rx, body)]
    return ("[PREKLAD NÁSTROJOV – v texte nižšie čítaj: " + "; ".join(rows) + "]\n") if rows else ""


def render_for_agent(pack: Pack) -> str:
    head = f"# Skill: {pack.name} ({pack.id})\n{pack.description}\n"
    notes = tool_notes(pack.body)
    files = ""
    if pack.files:
        shown = ", ".join(pack.files[:15]) + (f" … (+{len(pack.files) - 15})" if len(pack.files) > 15 else "")
        files = f"\n[PRILOŽENÉ SÚBORY: {shown} – čítaj ich cez skill_file skill=\"{pack.id}\" path=\"…\"]"
    return f"{head}{notes}\n{pack.body}{files}"


def read_bundled(pack: Pack, rel: str) -> str:
    rel = (rel or "").replace("\\", "/").strip().lstrip("/")
    if rel in ("", SKILL_FILE):
        return pack.body
    if ".." in PurePosixPath(rel).parts or rel not in pack.files:
        raise PackError(f"Súbor '{rel}' v balíku {pack.id} neexistuje. Súbory: {', '.join(pack.files[:20]) or 'žiadne'}")
    p = (pack.path / rel).resolve()
    if pack.path.resolve() not in p.parents:
        raise PackError("Cesta mimo balíka.")
    if p.suffix.lower() not in TEXT_SUFFIX:
        raise PackError(f"{rel} nie je textový súbor ({p.stat().st_size} B).")
    return p.read_text(encoding="utf-8", errors="replace")


def stage_scripts(pack: Pack) -> list[str]:
    """Copy the pack's bundled files into workspace/skills/<id>/ so run_code can execute them. Returns workspace paths."""
    out = []
    for rel in pack.files:
        src = pack.path / rel
        if src.suffix.lower() not in TEXT_SUFFIX and not rel.startswith("scripts/"):
            continue
        dst = WORKSPACE_DIR / STAGE_DIR / pack.id / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists() or dst.read_bytes() != src.read_bytes():
                shutil.copyfile(src, dst)
        except OSError:
            continue
        out.append(f"{STAGE_DIR}/{pack.id}/{rel}")
    return out


def stage_dir(pack: Pack) -> str:
    """Workspace folder where a script of the pack runs (run_code uses it as the working directory)."""
    first = next((f for f in pack.scripts if "/" in f), None)
    sub = first.rsplit("/", 1)[0] if first else ""
    return f"{STAGE_DIR}/{pack.id}" + (f"/{sub}" if sub else "")


def stage_inputs(pack: Pack, rels: list[str], max_bytes: int = 20_000_000) -> list[tuple[str, str]]:
    """Copy data files from workspace/ next to the pack's scripts. run_code runs a throw-away copy of the top folder
    of the script (skills/), so a file that lives elsewhere (e.g. nahrate/data.csv) must be copied there first. Returns [(source, copy)]."""
    from core import workspace
    out = []
    for rel in rels:
        rel = rel.strip()
        if not rel:
            continue
        try:
            src = workspace.safe_path(rel)
        except workspace.WorkspaceError as e:
            raise PackError(str(e))
        if not src.is_file():
            raise PackError(f"Súbor '{rel}' vo workspace/ neexistuje (zoznam: list_files).")
        if src.stat().st_size > max_bytes:
            raise PackError(f"Súbor '{rel}' je príliš veľký ({src.stat().st_size // 1_000_000} MB).")
        if src.name in pack.files or src.name.startswith("."):
            raise PackError(f"Názov '{src.name}' je v balíku už obsadený – premenuj súbor (rename_file).")
        dst_rel = f"{stage_dir(pack)}/{src.name}"
        dst = WORKSPACE_DIR / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        out.append((rel, dst_rel))
    return out


# ----------------------------------------------------------------- importing / translating
@dataclass
class Imported:
    pack_id: str
    name: str
    notes: list = field(default_factory=list)      # what was translated / changed
    warnings: list = field(default_factory=list)   # what the user should look at
    replaced: bool = False


def _safe_rel(name: str) -> str | None:
    n = name.replace("\\", "/").lstrip("/")
    parts = PurePosixPath(n).parts
    if not parts or ".." in parts or re.match(r"^[A-Za-z]:", parts[0]) or any(p in SKIP_NAMES for p in parts):
        return None
    return "/".join(parts)


def _decode(data: bytes) -> str:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", "replace")
    for enc in ("utf-8-sig", "cp1250", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeError:
            continue
    return data.decode("utf-8", "replace")


def translate(text: str, fallback_name: str = "", origin: str = "") -> tuple[dict, str, list, str]:
    """Foreign skill text -> (frontmatter {name, description, triggers...}, body, notes, detected format)."""
    fm, body = parse_frontmatter(text)
    notes: list = []
    fmt = "SKILL.md"
    if any(k in fm for k in ("globs", "alwaysapply")):
        fmt = "Cursor rule (.mdc)"
        extra = []
        if fm.get("globs"):
            g = fm["globs"] if isinstance(fm["globs"], str) else ", ".join(fm["globs"])
            extra.append(f"Platí pre súbory: {g}.")
        if fm.get("alwaysapply") is True:
            extra.append("Pôvodne sa používalo vždy – použi to pri každej súvisiacej úlohe.")
        if extra:
            body = " ".join(extra) + "\n\n" + body.lstrip()
        notes.append("Cursor pravidlo prevedené na skill (globs / alwaysApply pridané do textu).")
    elif any(k in fm for k in ("allowed-tools", "allowed_tools", "tools", "argument-hint", "model")) and "name" not in fm:
        fmt = "Claude Code príkaz / agent (.md)"
        notes.append("Príkaz / agent z iného nástroja prevedený na skill.")
    elif not fm:
        fmt = "obyčajný Markdown"
        notes.append("Súbor nemal hlavičku (frontmatter) – názov a popis boli odvodené z textu.")
    name = str(fm.get("name") or _title(body) or fallback_name or "skill").strip()
    desc = str(fm.get("description") or "").strip()
    if not desc:
        desc = _first_paragraph(body)
        notes.append("Chýbal popis – použil som prvý odsek textu.")
    if len(desc) > DESC_MAX:
        desc = desc[:DESC_MAX - 1] + "…"
        notes.append(f"Popis skrátený na {DESC_MAX} znakov.")
    out = {"name": name[:NAME_MAX * 2], "description": desc}
    triggers = fm.get("triggers") or fm.get("keywords") or fm.get("tags") or []
    out["triggers"] = [str(t) for t in (triggers if isinstance(triggers, list) else [triggers])][:20]
    for k in ("license", "version", "author", "allowed-tools", "allowed_tools", "model", "compatibility"):
        if k in fm:
            out.setdefault("original", {})[k] = fm[k]
    if "allowed-tools" in fm or "allowed_tools" in fm:
        notes.append("Zoznam povolených nástrojov z originálu sa nepoužíva – dostupné sú tvoje zapnuté skills.")
    return out, body.strip(), notes, fmt


def _check_text(name: str, text: str, warnings: list) -> None:
    if RISKY.search(text):
        warnings.append(f"{name}: obsahuje rizikový príkaz (curl | sh, rm -rf, sudo …) – skontroluj ho.")
    if INJECTION.search(text):
        warnings.append(f"{name}: obsahuje text typu „ignoruj predchádzajúce pokyny“ – skontroluj, či je balík dôveryhodný.")


def _install(files: dict[str, bytes], skill_text: str, fallback_name: str, source: str, origin: str,
             overwrite: bool = True, skipped: list | None = None) -> Imported:
    fm, body, notes, fmt = translate(skill_text, fallback_name, origin)
    pid = slugify(fm["name"])
    folder = SKILLPACKS_DIR / pid
    replaced = folder.exists()
    if replaced and not overwrite:
        raise PackError(f"Balík '{pid}' už existuje.")
    warnings: list = [f"{rel}: príliš veľký súbor – vynechaný." for rel in (skipped or [])]
    _check_text(SKILL_FILE, skill_text, warnings)
    total = len(skill_text.encode("utf-8"))
    kept: dict[str, bytes] = {}
    for rel, data in files.items():
        if len(data) > SKILLPACK_FILE_MAX:
            warnings.append(f"{rel}: príliš veľký súbor ({len(data) // 1024} kB) – vynechaný.")
            continue
        total += len(data)
        if len(kept) >= SKILLPACK_MAX_FILES or total > SKILLPACK_MAX_BYTES:
            warnings.append("Balík je príliš veľký – zvyšok súborov vynechaný.")
            break
        if rel.rsplit(".", 1)[-1].lower() in ("exe", "dll", "so", "dylib", "msi", "com", "scr"):
            warnings.append(f"{rel}: spustiteľný binárny súbor – vynechaný.")
            continue
        kept[rel] = data
        if PurePosixPath(rel).suffix.lower() in TEXT_SUFFIX:
            _check_text(rel, _decode(data), warnings)
    if any(r.startswith("scripts/") or r.endswith((".py", ".sh", ".js", ".bat", ".ps1")) for r in kept):
        notes.append("Obsahuje skripty – agent ich spustí cez run_code (v sandboxe) po skill_use.")
    body = body or fm["description"]
    meta = {"source": source, "origin": origin, "format": fmt, "imported_at": time.strftime("%Y-%m-%d %H:%M"),
            "notes": notes, "warnings": warnings, "triggers": fm["triggers"], "original": fm.get("original", {}),
            "default_enabled": not warnings}
    tmp = SKILLPACKS_DIR / f".tmp-{pid}-{int(time.time() * 1000)}"
    try:
        tmp.mkdir(parents=True)
        atomic_write_text(tmp / SKILL_FILE, dump_frontmatter({"name": fm["name"], "description": fm["description"]}, body))
        for rel, data in kept.items():
            dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
        atomic_write_text(tmp / META_FILE, json.dumps(meta, ensure_ascii=False, indent=2))
        if folder.exists():
            shutil.rmtree(folder)
        tmp.rename(folder)
    except OSError as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise PackError(f"Balík sa nepodarilo uložiť: {e}")
    if warnings:
        set_enabled(pid, False)                      # suspicious content: off until the user looks at it and switches it on
    elif not replaced:
        set_enabled(pid, True)
    return Imported(pid, fm["name"], notes, warnings, replaced)


def _is_skill_name(rel: str) -> bool:
    return rel.rsplit("/", 1)[-1].lower() == "skill.md"


def import_zip(data: bytes, source_name: str = "", origin: str = "") -> list[Imported]:
    """ZIP / .skill: one skill, or a repository with many skill folders (every folder with SKILL.md)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise PackError("Súbor nie je platný ZIP.")
    entries: dict[str, zipfile.ZipInfo] = {}
    declared = 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        rel = _safe_rel(info.filename)
        if rel is None:
            continue
        declared += info.file_size
        entries[rel] = info
    if declared > SKILLPACK_DOWNLOAD_MAX * 4:
        raise PackError("ZIP je po rozbalení príliš veľký.")
    roots = sorted({rel.rsplit("/", 1)[0] if "/" in rel else "" for rel in entries if _is_skill_name(rel)},
                   key=lambda r: r.count("/"))
    roots = [r for r in roots if not any(r != o and r.startswith(o + "/") and o for o in roots)]   # outermost only
    if not roots:
        md = [r for r in entries if r.lower().endswith((".md", ".mdc")) and r.count("/") <= 1]
        if len(md) == 1:
            return [import_text(_decode(zf.read(entries[md[0]])), md[0].rsplit("/", 1)[-1], source="import", origin=origin or source_name)]
        raise PackError("V ZIPe som nenašiel žiadny súbor SKILL.md.")
    results = []
    for root in roots:
        prefix = root + "/" if root else ""
        files, skill_text, skipped = {}, "", []
        for rel, info in entries.items():
            if not rel.startswith(prefix):
                continue
            inner = rel[len(prefix):]
            if root == "" and any(rel.startswith(o + "/") for o in roots if o):
                continue
            if inner == META_FILE:
                continue
            with zf.open(info) as fh:                     # bounded read: a lying ZIP header cannot blow up memory
                blob = fh.read(SKILLPACK_FILE_MAX + 1)
            if len(blob) > SKILLPACK_FILE_MAX and inner.lower() != "skill.md":
                skipped.append(inner)
            elif inner.lower() == "skill.md":
                skill_text = _decode(blob)
            else:
                files[inner] = blob
        fallback = root.rsplit("/", 1)[-1] if root else (source_name.rsplit(".", 1)[0] if source_name else "skill")
        results.append(_install(files, skill_text, fallback, "import", origin or source_name, skipped=skipped))
    return results


def import_text(text: str, filename: str = "", source: str = "import", origin: str = "") -> Imported:
    if not (text or "").strip():
        raise PackError("Prázdny text.")
    fallback = filename.rsplit(".", 1)[0] if filename and filename.lower() not in ("skill.md",) else ""
    return _install({}, text, fallback, source, origin or filename or "vložený text")


def import_file(name: str, data: bytes) -> list[Imported]:
    """Dispatch by what was dropped: ZIP / .skill, or a text file (SKILL.md, .md, .mdc, .txt)."""
    low = name.lower()
    if low.endswith((".zip", ".skill")) or data[:4] == b"PK\x03\x04":
        return import_zip(data, name)
    if low.endswith((".md", ".mdc", ".txt", ".markdown")):
        return [import_text(_decode(data), name)]
    if low.endswith((".py",)):
        raise PackError("Python súbor sa neinštaluje automaticky (spustil by sa pri štarte). Skopíruj ho ručne do core/skills/.")
    raise PackError(f"Nepodporovaný súbor {name}. Použi SKILL.md, .md, .mdc, ZIP alebo .skill.")


_GH_BLOB = re.compile(r"^https?://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)$")
_GH_REPO = re.compile(r"^https?://github\.com/([^/]+)/([^/#?]+?)(?:\.git)?/?(?:tree/([^/]+)(?:/.*)?)?$")
_GIST = re.compile(r"^https?://gist\.github\.com/([^/]+)/([0-9a-f]+)/?$")


def resolve_url(url: str) -> str:
    """Browser link -> a link that returns the file itself."""
    url = (url or "").strip()
    m = _GH_BLOB.match(url)
    if m:
        return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}/{m.group(4)}"
    m = _GIST.match(url)
    if m:
        return f"https://gist.githubusercontent.com/{m.group(1)}/{m.group(2)}/raw"
    m = _GH_REPO.match(url)
    if m:
        return f"https://github.com/{m.group(1)}/{m.group(2)}/archive/{m.group(3) or 'HEAD'}.zip"
    return url


def import_url(url: str) -> list[Imported]:
    import requests
    from core.research import _public_host
    from urllib.parse import urlparse
    real = resolve_url(url)
    u = urlparse(real)
    if u.scheme not in ("http", "https") or not _public_host(u.hostname or ""):
        raise PackError("Povolené sú len verejné http(s) adresy.")
    try:
        with requests.get(real, timeout=20, stream=True, headers={"User-Agent": "ai-agent-skill-import"}) as r:
            r.raise_for_status()
            chunks, size = [], 0
            for chunk in r.iter_content(65536):
                size += len(chunk)
                if size > SKILLPACK_DOWNLOAD_MAX:
                    raise PackError("Súbor je príliš veľký.")
                chunks.append(chunk)
    except requests.RequestException as e:
        raise PackError(f"Stiahnutie zlyhalo: {e}")
    data = b"".join(chunks)
    name = (urlparse(real).path.rsplit("/", 1)[-1] or "skill") if not real.endswith(".zip") else "repo.zip"
    if data[:4] == b"PK\x03\x04":
        return import_zip(data, name, origin=url)
    results = import_file(name if "." in name else name + ".md", data)
    for r in results:                                   # remember where it came from
        folder = SKILLPACKS_DIR / r.pack_id
        meta = _read_meta(folder)
        meta["origin"] = url
        try:
            atomic_write_text(folder / META_FILE, json.dumps(meta, ensure_ascii=False, indent=2))
        except OSError:
            pass
    return results


def remove_pack(pid: str) -> bool:
    folder = SKILLPACKS_DIR / slugify(pid)
    if not folder.is_dir() or SKILLPACKS_DIR.resolve() not in folder.resolve().parents:
        return False
    shutil.rmtree(folder, ignore_errors=True)
    saved = dict(settings_store.get("skillpacks", {}))
    if pid in saved:
        saved.pop(pid)
        settings_store.put("skillpacks", saved)
    return True


def export_zip(pid: str) -> bytes:
    """A pack as a standard ZIP (SKILL.md at the top of a folder named after the pack) - shareable with other tools."""
    pack = get_pack(pid)
    if not pack:
        raise PackError("Balík neexistuje.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(pack.path / SKILL_FILE, f"{pack.id}/{SKILL_FILE}")
        for rel in pack.files:
            z.write(pack.path / rel, f"{pack.id}/{rel}")
    return buf.getvalue()
