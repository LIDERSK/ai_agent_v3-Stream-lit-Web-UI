"""📖 Reading files from workspace/ (agent chats)."""
import hashlib
import re

from core import workspace
from core.skills import Param, Skill, Tool, ToolError


def _list(args, body, ctx):
    files = workspace.list_tree(by_mtime=False)
    return "\n".join(files) if files else "(workspace je prázdny)"


NO_CHANGE = "[BEZ ZMENY]"      # the agent loop treats a result starting with this as "no progress"


CHUNK_CHARS = 4800        # one read_file answer; bigger files are read in parts (start / end)


def _int(v) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return 0


def _numbered(lines: list[str], first: int) -> str:
    return "\n".join(f"{first + i:>4}│ {l}" for i, l in enumerate(lines))


def _uploaded_zips() -> list[str]:
    return [f for f in workspace.list_tree(by_mtime=False) if f.startswith(workspace.UPLOAD_DIR + "/") and f.lower().endswith(".zip")][:5]


def _from_uploaded_zip(path: str):
    """Text of `path` from an uploaded ZIP that contains such a file (None when there is none)."""
    from core import zipwork
    for z in _uploaded_zips():
        try:
            return zipwork.read_member(z, path)
        except zipwork.ZipProblem:
            continue
    return None


def _zip_hint(path: str) -> str:
    zips = _uploaded_zips()
    return (f" Nahrané archívy: {', '.join(zips)} – obsah vidíš cez zip_list, súbory čítaš cez zip_read." if zips else "")


def _read(args, body, ctx):
    path = args.get("path", "")
    start, end = _int(args.get("start")), _int(args.get("end"))
    if path.lower().startswith(("http://", "https://")):
        raise ToolError(f'read_file číta len súbory vo workspace. Webovú stránku načítaj nástrojom fetch_url url="{path}".')
    try:
        text = workspace.read_full(path)
    except workspace.WorkspaceError as e:
        text = _from_uploaded_zip(path)                        # "ai_agent_v3/core/x.py" lives inside the uploaded ZIP
        if text is None:
            raise ToolError(str(e) + _zip_hint(path))
        path = f"{path} (z nahratého archívu)"
    lines = text.split("\n")
    total = len(lines)
    ranged = bool(start or end)
    if ranged or len(text) > CHUNK_CHARS:                      # numbered part of the file
        a = max(1, start or 1)
        b = min(total, end or total)
        if a > total:
            raise ToolError(f"Súbor {path} má len {total} riadkov.")
        picked, size = [], 0
        for l in lines[a - 1:b]:                               # stop at the size of one answer
            if picked and size + len(l) + 7 > CHUNK_CHARS:
                break
            picked.append(l)
            size += len(l) + 7
        b = a + len(picked) - 1
        text = (f"[{path}: riadky {a}–{b} z {total}; čísla pred │ nie sú súčasť kódu – pri edit_file ich nekopíruj]\n"
                + _numbered(picked, a)
                + (f"\n[ďalej: read_file path=\"{path}\" start={b + 1}]" if b < total and not end else ""))
    key = f"{path}#{start}-{end}"
    digest = hashlib.md5(text.encode("utf-8", "ignore")).hexdigest()
    if ctx.read_hashes.get(key) == digest:
        return (f"{NO_CHANGE} Súbor {path} sa od posledného čítania nezmenil – jeho obsah už máš vyššie v rozhovore. "
                "Nečítaj ho znova: pokračuj ďalším krokom, alebo ak je všetko hotové, odpovedz používateľovi.")
    ctx.read_hashes[key] = digest
    return text


def _search(args, body, ctx):
    query = (args.get("query") or body or "").strip()
    if not query:
        raise ToolError("search_files potrebuje query=\"hľadaný text\".")
    only = (args.get("path") or "").strip().replace("\\", "/").strip("/")
    try:
        rx = re.compile(query[3:] if query.lower().startswith("re:") else re.escape(query), re.I)
    except re.error as e:
        raise ToolError(f"Neplatný regulárny výraz: {e}")
    hits, files_hit = [], 0
    for rel in workspace.list_tree(by_mtime=False):
        if only and not (rel == only or rel.startswith(only + "/")):
            continue
        try:
            text = workspace.read_full(rel)
        except workspace.WorkspaceError:
            continue                                           # binary / unreadable
        found = [(i, l) for i, l in enumerate(text.split("\n"), 1) if rx.search(l)]
        if found:
            files_hit += 1
            hits += [f"{rel}:{i}: {l.strip()[:140]}" for i, l in found[:10]]
        if len(hits) >= 40:
            break
    if not hits:
        return f"Nič sa nenašlo pre „{query}“."
    return f"Nájdené v {files_hit} súbor(och):\n" + "\n".join(hits[:40])


def _code_map(args, body, ctx):
    from core import project
    return project.code_map(args.get("path", ""))[:6000]


SKILL = Skill(
    id="fs_read", icon="📖", name="Čítanie súborov", order=10, scope="agent",
    short="Agent vidí a číta súbory vo workspace/",
    description="Agent môže zobraziť zoznam súborov a prečítať ich obsah. Prístup je obmedzený "
                "na priečinok workspace/.",
    tools=(
        Tool("list_files", "bez argumentov – vypíše všetky súbory vo workspace",
             '<tool name="list_files"/>', _list),
        Tool("read_file", 'path="relatívna/cesta.py" [start="1" end="80"] – vráti obsah súboru; veľký súbor čítaj po '
                          'častiach cez start/end (riadky sa očíslujú)',
             '<tool name="read_file" path="app.py" start="40" end="90"/>', _read,
             params=(Param("path", "relatívna cesta k súboru vo workspace/"),
                     Param("start", "prvý riadok (od 1)", required=False),
                     Param("end", "posledný riadok", required=False))),
        Tool("code_map", '[path="priecinok"] – prehľad zdrojových súborov: triedy a funkcie s číslami riadkov. Použi PRED '
                         'úpravou cudzieho projektu, aby si našiel správne miesto bez čítania všetkých súborov',
             '<tool name="code_map" path="todo_aplikacia"/>', _code_map,
             params=(Param("path", "priečinok alebo súbor (bez parametra celý workspace)", required=False),)),
        Tool("search_files", 'query="hľadaný text" [path="priecinok"] – nájde riadky s textom (alebo regex po "re:") vo všetkých '
                             'súboroch a vráti súbor:riadok; použi pred úpravou veľkého súboru',
             '<tool name="search_files" query="def vypocitaj"/>', _search,
             params=(Param("query", "hľadaný text (alebo re:regex)"),
                     Param("path", "obmedziť na priečinok / súbor", required=False))),
    ),
)
