"""🗜️ ZIP archives and office documents in workspace/ (agent tools)."""
from config import TOOL_RESULT_MAX
from core import documents, workspace, zipwork
from core.skills import Param, Skill, Tool, ToolError

CHUNK = 4800
READ_LIMIT = 6        # files read one by one from the same archive before the agent is told to extract it


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except (zipwork.ZipProblem, workspace.WorkspaceError) as e:
        raise ToolError(str(e))


def _int(v) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return 0


def _list(args, body, ctx):
    return _guard(zipwork.list_zip, args.get("path", ""))[:TOOL_RESULT_MAX]


def _part(text: str, args, label: str, tool: str) -> str:
    """Numbered lines a..b of `text`, at most CHUNK characters (same convention as read_file)."""
    lines = text.split("\n")
    a, b = max(1, _int(args.get("start")) or 1), _int(args.get("end")) or len(lines)
    if a > len(lines):
        raise ToolError(f"{label} má len {len(lines)} riadkov.")
    picked, size = [], 0
    for l in lines[a - 1:b]:
        if picked and size + len(l) + 7 > CHUNK:
            break
        picked.append(l)
        size += len(l) + 7
    end = a + len(picked) - 1
    out = f"[{label}: riadky {a}–{end} z {len(lines)}]\n" + "\n".join(f"{a + i:>4}│ {l}" for i, l in enumerate(picked))
    if end < len(lines) and not _int(args.get("end")):
        out += f"\n[ďalej: {tool} … start={end + 1}]"
    return out


def _read(args, body, ctx):
    member = args.get("file", "")
    if not member:
        raise ToolError("zip_read potrebuje file=\"cesta/v/archíve.txt\" (zoznam získaš cez zip_list).")
    names = [m.strip() for m in member.split(",") if m.strip()][:6]
    key = f"zipreads:{args.get('path', '')}"                   # reading 45 files one by one is not progress
    done = ctx.read_hashes.get(key, 0)
    if done + len(names) > READ_LIMIT:
        raise ToolError(f"Z archívu si už prečítal {done} súborov po jednom. STAČÍ: zavolaj zip_extract path=\"{args.get('path', '')}\" "
                        "(rozbalí všetko naraz), potom súbory čítaj cez read_file / search_files, kód spusti cez run_code a uprav cez edit_file.")
    ctx.read_hashes[key] = done + len(names)
    if len(names) > 1:                                         # several files in one call
        cap = CHUNK // len(names)
        parts = []
        for n in names:
            txt = _guard(zipwork.read_member, args.get("path", ""), n, password=args.get("password", ""))
            parts.append(f"=== {n} ({len(txt.splitlines())} riadkov) ===\n" + txt[:cap] + ("\n[… skrátené, celý súbor: zip_read file=\"%s\" …]" % n if len(txt) > cap else ""))
        return "\n\n".join(parts)
    text = _guard(zipwork.read_member, args.get("path", ""), member, password=args.get("password", ""))
    return _part(text, args, f"{args.get('path')}::{member}", f'zip_read path="{args.get("path")}" file="{member}"')


def _extract(args, body, ctx):
    overwrite = str(args.get("overwrite", "")).lower() in ("1", "true", "yes", "ano", "áno")
    written, notes = _guard(zipwork.extract, args.get("path", ""), args.get("to", ""), only=args.get("file", ""),
                            overwrite=overwrite, password=args.get("password", ""))
    # NOT marked as "created files": an extracted archive is workspace content, not a deliverable (68 loose files
    # under the answer are just noise). Show the folders with counts, not every file.
    tops: dict[str, int] = {}
    for w in written:
        key = "/".join(w.split("/")[:2]) + "/" if w.count("/") >= 2 else w
        tops[key] = tops.get(key, 0) + 1
    head = f"Rozbalených {len(written)} súborov."
    shown = "\n".join(f"  {k} ({n} súborov)" if k.endswith("/") else f"  {k}" for k, n in list(tops.items())[:30])
    more = ("\nTeraz súbory čítaj cez read_file (alebo search_files); nevypisuj ich všetky." if written else "")
    return (head + ("\n" + shown if shown else "") + ("\n" + "\n".join(notes[:15]) if notes else "") + more)[:TOOL_RESULT_MAX]


def _search(args, body, ctx):
    q = (args.get("query") or body or "").strip()
    if not q:
        raise ToolError("zip_search potrebuje query=\"hľadaný text\".")
    return _guard(zipwork.search, args.get("path", ""), q, password=args.get("password", ""))[:TOOL_RESULT_MAX]


def _create(args, body, ctx):
    raw = args.get("files") or body or ""
    paths = [p.strip() for p in raw.replace(",", "\n").splitlines() if p.strip()]
    rel, n, size = _guard(zipwork.create, args.get("path", ""), paths or None)
    ctx.mark_written(rel)
    return f"Archív {rel} vytvorený: {n} súborov, {zipwork.human(size)}."


def _doc(args, body, ctx):
    text = _guard(documents.read_document, args.get("path", ""))
    return _part(text, args, args.get("path", ""), f'read_document path="{args.get("path")}"')


SKILL = Skill(
    id="zip_tools", icon="🗜️", name="ZIP a dokumenty", order=15, scope="agent",
    short="Otvára, číta a vytvára ZIP; číta PDF / Word / Excel / PowerPoint",
    description="Agent vie vypísať obsah ZIP archívu, prečítať súbory v ňom a hľadať v nich bez rozbalenia, archív bezpečne rozbaliť do workspace/ "
                "(ochrana pred cestami mimo priečinka a ZIP bombami) a vytvoriť nový ZIP z vybraných súborov alebo "
                "priečinkov. Vie aj prečítať text z .docx, .xlsx, .pptx a (s balíkom pypdf) z .pdf. "
                "ZIP môžeš do chatu aj nahrať cez ＋ – uloží sa do workspace/nahrate/.",
    tools=(
        Tool("zip_list", 'path="archiv.zip" – vypíše súbory v archíve (názvy, veľkosti)',
             '<tool name="zip_list" path="nahrate/projekt.zip"/>', _list,
             params=(Param("path", "ZIP súbor vo workspace/"),)),
        Tool("zip_read", 'path="archiv.zip" file="priecinok/subor.py" [start="1" end="80"] – prečíta textový súbor '
                         'priamo z archívu BEZ rozbalenia (viac súborov naraz: file="a.py,b.py", najviac 6)',
             '<tool name="zip_read" path="nahrate/projekt.zip" file="src/main.py"/>', _read,
             params=(Param("path", "ZIP súbor vo workspace/"), Param("file", "cesta súboru vnútri archívu"),
                     Param("start", "prvý riadok", required=False), Param("end", "posledný riadok", required=False),
                     Param("password", "heslo, ak je archív šifrovaný", required=False))),
        Tool("zip_search", 'path="archiv.zip" query="text" – nájde riadky s textom (alebo re:regex) vo všetkých textových '
                           'súboroch archívu BEZ rozbalenia',
             '<tool name="zip_search" path="nahrate/projekt.zip" query="def main"/>', _search,
             params=(Param("path", "ZIP súbor vo workspace/"), Param("query", "hľadaný text (alebo re:regex)"),
                     Param("password", "heslo, ak je archív šifrovaný", required=False))),
        Tool("zip_extract", 'path="archiv.zip" [to="priecinok"] [file="cast/archivu"] [overwrite="true"] – rozbalí archív do '
                            'workspace/. Použi HNEĎ, keď treba kód spustiť, otestovať, opraviť alebo vylepšiť, alebo keď chceš čítať viac než ~5 súborov; '
                            'na rýchle prezretie stačí zip_list + zip_search',
             '<tool name="zip_extract" path="nahrate/projekt.zip" to="projekt"/>', _extract,
             params=(Param("path", "ZIP súbor vo workspace/"),
                     Param("to", "cieľový priečinok (predvolene názov archívu)", required=False),
                     Param("file", "rozbaliť iba tento súbor / priečinok z archívu", required=False),
                     Param("overwrite", "true = prepísať existujúce súbory", required=False),
                     Param("password", "heslo, ak je archív šifrovaný", required=False))),
        Tool("zip_create", 'path="vysledok.zip" + v tele zoznam súborov / priečinkov (jeden na riadok; bez zoznamu sa '
                           'zabalí celý workspace okrem ZIP-ov) – vytvorí archív',
             '<tool name="zip_create" path="projekt_zaloha.zip">\nprojekt/main.py\nprojekt/data\n</tool>', _create,
             params=(Param("path", "názov nového ZIP súboru"),
                     Param("files", "súbory / priečinky na zabalenie, jeden na riadok", required=False)),
             body="files"),
        Tool("read_document", 'path="subor.docx" [start="1" end="80"] – prečíta text z .docx, .xlsx, .pptx alebo .pdf',
             '<tool name="read_document" path="nahrate/sprava.docx"/>', _doc,
             params=(Param("path", ".docx / .xlsx / .pptx / .pdf vo workspace/"),
                     Param("start", "prvý riadok", required=False), Param("end", "posledný riadok", required=False))),
    ),
)
