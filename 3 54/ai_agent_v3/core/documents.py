"""Text of .docx / .xlsx / .pptx (stdlib only: they are ZIPs of XML) and .pdf (needs `pip install pypdf`)."""
from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET

from core import workspace
from core.zipwork import MAX_ONE, ZipProblem

DOC_EXT = ("pdf", "docx", "xlsx", "pptx")
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _xml(z: zipfile.ZipFile, name: str):
    return ET.fromstring(z.read(name))


def _docx(z) -> str:
    root = _xml(z, "word/document.xml")
    paras = ["".join(t.text or "" for t in p.iter(f"{_W}t")) for p in root.iter(f"{_W}p")]
    return "\n".join(p for p in paras if p.strip())


def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref or "A").group(0):
        n = n * 26 + ord(ch) - 64
    return n


def _xlsx(z) -> str:
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        shared = ["".join(t.text or "" for t in si.iter(f"{_S}t")) for si in _xml(z, "xl/sharedStrings.xml").iter(f"{_S}si")]
    names = re.findall(r'<sheet [^>]*name="([^"]+)"', z.read("xl/workbook.xml").decode("utf-8", "replace"))
    sheets = sorted(n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
    sheets.sort(key=lambda n: int(re.search(r"(\d+)\.xml", n).group(1)))
    out = []
    for idx, sheet in enumerate(sheets):
        out.append(f"=== list: {names[idx] if idx < len(names) else idx + 1} ===")
        for row in _xml(z, sheet).iter(f"{_S}row"):
            cells = {}
            for c in row.iter(f"{_S}c"):
                v = c.find(f"{_S}v")
                if c.get("t") == "inlineStr":
                    val = "".join(t.text or "" for t in c.iter(f"{_S}t"))
                elif v is None:
                    continue
                elif c.get("t") == "s":
                    val = shared[int(v.text)] if (v.text or "").isdigit() and int(v.text) < len(shared) else ""
                else:
                    val = v.text or ""
                cells[_col(c.get("r"))] = val
            if cells:
                out.append("\t".join(cells.get(i, "") for i in range(1, max(cells) + 1)))
    return "\n".join(out)


def _pptx(z) -> str:
    slides = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                    key=lambda n: int(re.search(r"(\d+)\.xml", n).group(1)))
    out = []
    for k, name in enumerate(slides, 1):
        texts = [t.text for t in _xml(z, name).iter(f"{_A}t") if t.text and t.text.strip()]
        out.append(f"=== snímka {k} ===\n" + "\n".join(texts))
    return "\n\n".join(out)


def _pdf(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ZipProblem("Na čítanie PDF chýba balík pypdf (pip install pypdf).")
    try:
        pages = PdfReader(io.BytesIO(raw)).pages
        out = [f"=== strana {i} ===\n{(p.extract_text() or '').strip()}" for i, p in enumerate(pages, 1)]
    except Exception as e:
        raise ZipProblem(f"PDF sa nedá prečítať: {type(e).__name__}: {e}")
    text = "\n\n".join(out)
    if not re.sub(r"=== strana \d+ ===|\s", "", text):
        raise ZipProblem("PDF nemá textovú vrstvu (asi sken) – text z neho nevyčítam.")
    return text


def read_document_bytes(name: str, raw: bytes) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext == "pdf":
        return _pdf(raw)
    if ext not in DOC_EXT:
        raise ZipProblem(f"Formát .{ext} nepoznám (podporované: {', '.join(DOC_EXT)}).")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            return {"docx": _docx, "xlsx": _xlsx, "pptx": _pptx}[ext](z)
    except zipfile.BadZipFile:
        raise ZipProblem(f"'{name}' je poškodený alebo to nie je platný .{ext}.")
    except (KeyError, ET.ParseError) as e:
        raise ZipProblem(f"'{name}' má neočakávanú štruktúru ({type(e).__name__}).")


def read_document(rel: str) -> str:
    try:
        p = workspace.safe_path(rel)
    except workspace.WorkspaceError as e:
        raise ZipProblem(str(e))
    if not p.is_file():
        raise ZipProblem(f"Súbor '{rel}' neexistuje. Použi list_files.")
    if p.stat().st_size > MAX_ONE:
        raise ZipProblem(f"Súbor má príliš veľa dát (max {MAX_ONE // 1024 // 1024} MB).")
    return read_document_bytes(p.name, p.read_bytes())
