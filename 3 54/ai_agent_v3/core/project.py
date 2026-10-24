"""Project memory + code map for the agent (no Streamlit).

  AGENTS.md   short notes of the project (purpose, files, how to run, style rules). Written by the agent / the user,
              injected into the agent's prompt at every task -> small features without re-discovering the project.
  code_map    classes / functions with line numbers per file: a small model finds the right place without reading
              every file.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from core import workspace

NOTES_NAME = "AGENTS.md"
NOTES_MAX = 2500
MAP_SUFFIX = {".py", ".js", ".mjs", ".ts", ".c", ".cpp", ".h", ".java", ".go", ".rs"}
SKIP_DIRS = {"__pycache__", "node_modules", ".git", ".venv", "venv", workspace.UPLOAD_DIR}
MAX_FILES = 120
_JS = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:function\s*\*?\s*(\w+)|class\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>)")
_C = re.compile(r"^[A-Za-z_][\w\s\*:<>,]*?\b(\w+)\s*\([^;]*\)\s*(?:const)?\s*\{?\s*$")


def find_notes() -> tuple[str, str]:
    """(relative path, text) of the most recently changed AGENTS.md in workspace/ or in a project folder."""
    root = workspace.WORKSPACE_DIR
    try:
        found = [root / NOTES_NAME] + [d / NOTES_NAME for d in root.iterdir()
                                        if d.is_dir() and not d.name.startswith(".") and d.name != workspace.UPLOAD_DIR]
    except OSError:
        return "", ""
    found = [p for p in found if p.is_file()]
    if not found:
        return "", ""
    p = max(found, key=lambda x: x.stat().st_mtime)
    try:
        return p.relative_to(root).as_posix(), p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", ""


def project_notes() -> str:
    rel, text = find_notes()
    if not text.strip():
        return ""
    cut = text.strip()[:NOTES_MAX] + ("\n[… skrátené, celé v " + rel + "]" if len(text.strip()) > NOTES_MAX else "")
    return f"\n\nPAMÄŤ PROJEKTU ({rel}) – dodržiavaj ju:\n{cut}"


# ----------------------------------------------------------------- code map
def _args(node: ast.AST) -> str:
    a = node.args
    names = [x.arg for x in [*a.posonlyargs, *a.args] if x.arg not in ("self", "cls")]
    if a.vararg:
        names.append("*" + a.vararg.arg)
    names += [x.arg for x in a.kwonlyargs]
    if a.kwarg:
        names.append("**" + a.kwarg.arg)
    s = ", ".join(names)
    return s if len(s) <= 60 else s[:57] + "..."


def _py_outline(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return [f"  ⚠ syntaktická chyba, riadok {e.lineno}: {e.msg}"]
    out = []
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(f"  def {n.name}({_args(n)})  :{n.lineno}")
        elif isinstance(n, ast.ClassDef):
            methods = [f"{m.name}:{m.lineno}" for m in n.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
            out.append(f"  class {n.name}  :{n.lineno}" + (f"  → {', '.join(methods)}" if methods else ""))
    return out


def _regex_outline(text: str, rx: re.Pattern) -> list[str]:
    out = []
    for i, line in enumerate(text.split("\n"), 1):
        m = rx.match(line)
        if m:
            name = next((g for g in m.groups() if g), "")
            if name and name not in ("if", "for", "while", "switch", "return", "else"):
                out.append(f"  {name}  :{i}")
    return out


def code_map(rel: str = "", max_chars: int = 6000) -> str:
    try:
        base = workspace.safe_path(rel) if rel else workspace.WORKSPACE_DIR
    except workspace.WorkspaceError as e:
        return str(e)
    if not base.exists():
        return f"'{rel}' neexistuje. Použi list_files."
    files = [base] if base.is_file() else sorted(
        p for p in base.rglob("*")
        if p.is_file() and p.suffix.lower() in MAP_SUFFIX
        and not any(part in SKIP_DIRS or part.startswith(".") for part in p.relative_to(base).parts[:-1]))
    if not files:
        return "Nenašiel som žiadne zdrojové súbory (.py .js .ts .c .cpp .h .java .go .rs)."
    root = workspace.WORKSPACE_DIR.resolve()
    lines, used = [], 0
    for p in files[:MAX_FILES]:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        ext = p.suffix.lower()
        outline = (_py_outline(text) if ext == ".py" else
                   _regex_outline(text, _JS) if ext in (".js", ".mjs", ".ts") else
                   _regex_outline(text, _C))
        head = f"{p.resolve().relative_to(root).as_posix()} ({len(text.splitlines())} r)"
        block = "\n".join([head, *outline[:60]])
        if used + len(block) > max_chars:
            lines.append(f"… ďalšie súbory vynechané (zúž hľadanie: code_map path=\"priecinok\")")
            break
        lines.append(block)
        used += len(block) + 1
    if len(files) > MAX_FILES:
        lines.append(f"… a ďalších {len(files) - MAX_FILES} súborov")
    return "\n".join(lines)
