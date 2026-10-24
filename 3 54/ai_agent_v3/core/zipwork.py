"""ZIP archives inside workspace/: list, read one file, extract (zip-slip / zip-bomb safe), create. No Streamlit here."""
from __future__ import annotations

import io
import re
import stat
import zipfile
from pathlib import PurePosixPath

from core import workspace

MAX_ENTRIES = 1000                 # files in one archive we are willing to handle
MAX_TOTAL = 200 * 1024 * 1024      # uncompressed bytes of one extraction / creation
MAX_ONE = 50 * 1024 * 1024         # one file inside
MAX_RATIO = 200                    # uncompressed / compressed above this (and big) = zip bomb
PREVIEW_FILE_CHARS = 3000          # one file in the inline preview of an uploaded archive
PREVIEW_TOTAL_CHARS = 12000
TEXT_EXT = {"txt", "py", "md", "json", "csv", "js", "ts", "html", "css", "yml", "yaml", "log", "ini", "cfg", "toml",
            "xml", "bat", "sh", "sql", "java", "c", "cpp", "h", "go", "rs", "rst", "tsv", "env", "gitignore"}


class ZipProblem(Exception):
    """Readable reason why an archive cannot be handled."""


def human(n: int) -> str:
    for unit in ("B", "kB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


def _open(rel: str, data: bytes | None = None) -> zipfile.ZipFile:
    try:
        src = io.BytesIO(data) if data is not None else workspace.safe_path(rel)
        if data is None and not src.is_file():
            raise ZipProblem(f"Súbor '{rel}' neexistuje. Použi list_files.")
        z = zipfile.ZipFile(src)
    except workspace.WorkspaceError as e:
        raise ZipProblem(str(e))
    except zipfile.BadZipFile:
        raise ZipProblem(f"'{rel}' nie je platný ZIP súbor (alebo je poškodený).")
    if len(z.infolist()) > MAX_ENTRIES:
        raise ZipProblem(f"Archív má {len(z.infolist())} položiek (max {MAX_ENTRIES}).")
    return z


def _is_link(i: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(i.external_attr >> 16)


def clean_member(name: str) -> str | None:
    """Safe relative path of an archive member, or None when it must be skipped (absolute, '..', hidden history)."""
    n = (name or "").replace("\\", "/").strip()
    if not n or n.endswith("/") or n.startswith("/") or re.match(r"^[A-Za-z]:", n) or "\x00" in n:
        return None
    parts = [p for p in PurePosixPath(n).parts if p not in ("", ".")]
    if not parts or ".." in parts or ".history" in parts or parts[0] == "__MACOSX":
        return None
    return "/".join(parts)


def _files(z: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    return [i for i in z.infolist() if not i.is_dir() and not _is_link(i)]


def _check_size(files: list[zipfile.ZipInfo]) -> int:
    total = sum(i.file_size for i in files)
    packed = sum(i.compress_size for i in files) or 1
    if total > MAX_TOTAL:
        raise ZipProblem(f"Po rozbalení by archív mal {human(total)} (max {human(MAX_TOTAL)}).")
    if total > 20 * 1024 * 1024 and total / packed > MAX_RATIO:
        raise ZipProblem("Archív vyzerá ako ZIP bomba (extrémny pomer rozbalenia) – nerozbaľujem ho.")
    big = next((i for i in files if i.file_size > MAX_ONE), None)
    if big:
        raise ZipProblem(f"Súbor '{big.filename}' v archíve má {human(big.file_size)} (max {human(MAX_ONE)}).")
    return total


# ----------------------------------------------------------------- list
NOISE_RE = re.compile(r"(?:^|/)(?:\.history|__pycache__|\.plan|\.git|node_modules)/|\.(?:pyc|bak)$")


def list_zip(rel: str, data: bytes | None = None, limit: int = 200) -> str:
    with _open(rel, data) as z:
        infos = z.infolist()
        files = [i for i in infos if not i.is_dir()]
        total = sum(i.file_size for i in files)
        noise = [i for i in files if NOISE_RE.search(i.filename)]           # backups / caches: listed as one line
        shown = [i for i in files if not NOISE_RE.search(i.filename)]
        lines = [f"{rel}: {len(files)} súborov, spolu {human(total)} po rozbalení"
                 f" ({human(sum(i.compress_size for i in files))} zbalené)"]
        if noise:
            lines.append(f"  (skrytých {len(noise)} záložných / cache súborov: .history, __pycache__, *.pyc, *.bak – "
                         "prečítať sa dajú cez zip_read)")
        files = shown
        for i in sorted(files, key=lambda x: x.filename)[:limit]:
            mark = " 🔒" if i.flag_bits & 0x1 else ""
            skip = ("  [bude preskočený: symbolický odkaz]" if _is_link(i) else
                    "" if clean_member(i.filename) else "  [bude preskočený: nebezpečná cesta]")
            lines.append(f"  {i.filename}  ({human(i.file_size)}){mark}{skip}")
        if len(files) > limit:
            lines.append(f"  … a ďalších {len(files) - limit} súborov")
        if any(i.flag_bits & 0x1 for i in files):
            lines.append("🔒 = šifrované (na čítanie treba heslo: password=\"…\")")
        return "\n".join(lines)


# ----------------------------------------------------------------- read one member
def read_member(rel: str, member: str, *, password: str = "", data: bytes | None = None,
                max_bytes: int = 2_000_000) -> str:
    with _open(rel, data) as z:
        want = member.replace("\\", "/").lstrip("/")
        info = next((i for i in z.infolist() if i.filename == want), None) or \
            next((i for i in z.infolist() if i.filename.endswith("/" + want) or i.filename.lower() == want.lower()), None)
        if info is None or info.is_dir():
            near = [i.filename for i in z.infolist() if want.split("/")[-1].lower() in i.filename.lower()][:5]
            raise ZipProblem(f"V archíve nie je súbor '{member}'." + (f" Podobné: {', '.join(near)}" if near else
                                                                       " Použi zip_list."))
        if info.file_size > max_bytes:
            raise ZipProblem(f"'{info.filename}' má {human(info.file_size)} – na čítanie je príliš veľký, rozbaľ ho (zip_extract).")
        try:
            raw = z.read(info, pwd=password.encode() if password else None)
        except RuntimeError:
            raise ZipProblem(f"'{info.filename}' je šifrovaný – zadaj správne heslo (password=\"…\").")
        except (zipfile.BadZipFile, NotImplementedError) as e:
            raise ZipProblem(f"'{info.filename}' sa nedá prečítať: {e}")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ZipProblem(f"'{info.filename}' nie je textový súbor (UTF-8) – rozbaľ ho cez zip_extract.")


# ----------------------------------------------------------------- extract
def extract(rel: str, to: str = "", *, only: str = "", overwrite: bool = False, password: str = "") -> tuple[list[str], list[str]]:
    """Returns (written_paths, notes). Every member is checked against the workspace jail; existing files are kept
    unless overwrite=True; the real number of bytes written is capped (a lying header cannot fill the disk)."""
    stem = PurePosixPath(rel.replace("\\", "/")).stem
    dest = workspace.clean_rel_path(to) if to else workspace.clean_rel_path(stem) or "rozbalene"
    written, notes, budget = [], [], MAX_TOTAL
    with _open(rel) as z:
        files = _files(z)
        if only:
            files = [i for i in files if i.filename == only or i.filename.startswith(only.rstrip("/") + "/")]
            if not files:
                raise ZipProblem(f"V archíve nič nezodpovedá '{only}'. Použi zip_list.")
        _check_size(files)
        pwd = password.encode() if password else None
        names = [clean_member(i.filename) for i in z.infolist() if not i.is_dir() and not _is_link(i)]
        names = [n for n in names if n]
        tops = {n.split("/")[0] for n in names}
        strip = len(tops) == 1 and all("/" in n for n in names)      # one wrapper folder inside: do not nest it again
        if strip:
            notes.append(f"najvyšší priečinok archívu '{next(iter(tops))}/' som nezdvojil – súbory sú priamo v '{dest}/'")
        for i in files:
            member = clean_member(i.filename)
            if not member:
                notes.append(f"preskočené (nebezpečná cesta): {i.filename}")
                continue
            if strip and "/" in member:
                member = member.split("/", 1)[1]
            target = f"{dest}/{member}" if dest else member
            try:
                p = workspace.safe_path(target)
            except workspace.WorkspaceError as e:
                notes.append(f"preskočené ({e}): {i.filename}")
                continue
            if p.exists() and not overwrite:
                notes.append(f"už existuje, nezmenené: {target}")
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            try:
                with z.open(i, pwd=pwd) as src, open(p, "wb") as out:
                    while True:
                        chunk = src.read(1 << 16)
                        if not chunk:
                            break
                        budget -= len(chunk)
                        if budget < 0:
                            raise ZipProblem("Rozbalené dáta presiahli limit – rozbaľovanie zastavené.")
                        out.write(chunk)
            except RuntimeError:
                p.unlink(missing_ok=True)
                raise ZipProblem(f"Archív je šifrovaný – zadaj správne heslo (password=\"…\").")
            written.append(target)
    return written, notes


# ----------------------------------------------------------------- search inside (without extracting)
def search(rel: str, query: str, *, password: str = "", limit: int = 40) -> str:
    try:
        rx = re.compile(query[3:] if query.lower().startswith("re:") else re.escape(query), re.I)
    except re.error as e:
        raise ZipProblem(f"Neplatný regulárny výraz: {e}")
    hits, files_hit = [], 0
    with _open(rel) as z:
        for i in sorted(_files(z), key=lambda x: x.filename):
            ext = i.filename.rsplit(".", 1)[-1].lower() if "." in i.filename else ""
            if ext not in TEXT_EXT or i.file_size > 500_000 or i.flag_bits & 0x1 and not password:
                continue
            try:
                text = z.read(i, pwd=password.encode() if password else None).decode("utf-8")
            except (UnicodeDecodeError, RuntimeError, zipfile.BadZipFile):
                continue
            found = [(n, l) for n, l in enumerate(text.split("\n"), 1) if rx.search(l)]
            if found:
                files_hit += 1
                hits += [f"{i.filename}:{n}: {l.strip()[:140]}" for n, l in found[:8]]
            if len(hits) >= limit:
                break
    if not hits:
        return f"V archíve sa nenašlo „{query}“."
    return f"Nájdené v {files_hit} súbor(och) archívu:\n" + "\n".join(hits[:limit])


# ----------------------------------------------------------------- create
def create(rel: str, paths: list[str] | None = None) -> tuple[str, int, int]:
    """ZIP of workspace files / folders (None = everything except archives). Returns (path, file_count, size)."""
    rel = workspace.clean_rel_path(rel)
    if not rel.lower().endswith(".zip"):
        rel += ".zip"
    out = workspace.safe_path(rel)
    everything = workspace.list_tree(by_mtime=False)
    if paths:
        chosen: list[str] = []
        for raw in paths:
            r = workspace.clean_rel_path(raw)
            hit = [f for f in everything if f == r or f.startswith(r.rstrip("/") + "/")]
            if not hit:
                raise ZipProblem(f"'{raw}' vo workspace neexistuje. Použi list_files.")
            chosen += hit
    else:
        chosen = [f for f in everything if not f.lower().endswith(".zip")]
    chosen = [f for f in dict.fromkeys(chosen) if f != rel]
    if not chosen:
        raise ZipProblem("Nie je čo zabaliť.")
    if len(chosen) > MAX_ENTRIES:
        raise ZipProblem(f"Príliš veľa súborov ({len(chosen)}, max {MAX_ENTRIES}).")
    total = 0
    for f in chosen:
        total += workspace.safe_path(f).stat().st_size
    if total > MAX_TOTAL:
        raise ZipProblem(f"Súbory majú {human(total)} (max {human(MAX_TOTAL)}).")
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in chosen:
            z.write(workspace.safe_path(f), arcname=f)
    return rel, len(chosen), out.stat().st_size


# ----------------------------------------------------------------- inline preview of an uploaded archive
def preview(name: str, data: bytes) -> str:
    """Text for the prompt: the listing + the contents of small text files (so even a normal chat can 'read' a ZIP)."""
    try:
        text = list_zip(name, data, limit=80)
        with _open(name, data) as z:
            left = PREVIEW_TOTAL_CHARS
            for i in sorted(_files(z), key=lambda x: x.file_size):
                ext = i.filename.rsplit(".", 1)[-1].lower() if "." in i.filename else ""
                if left < 400 or i.flag_bits & 0x1 or ext not in TEXT_EXT or i.file_size > 200_000 or not clean_member(i.filename):
                    continue
                try:
                    body = z.read(i).decode("utf-8")
                except (UnicodeDecodeError, RuntimeError, zipfile.BadZipFile):
                    continue
                body = body[:min(PREVIEW_FILE_CHARS, left)]
                left -= len(body)
                text += f"\n\n--- {i.filename} ---\n{body}"
        return text
    except ZipProblem as e:
        return f"(ZIP sa nedá otvoriť: {e})"
