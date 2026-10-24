"""✍️ Creating / editing files in workspace/ (agent tool + automatic saving of code in normal chats)."""
from core import editing, workspace
from core.skills import Param, Skill, Tool, ToolError


def _existing(path: str) -> str | None:
    try:
        p = workspace.safe_path(path)
        return workspace.read_full(path) if p.is_file() else None
    except workspace.WorkspaceError:
        return None


SMALL_REWRITE_MIN_LINES = 30     # an existing file this long ...
SMALL_REWRITE_SHARE = 0.4        # ... that changes by less than this share must be changed with edit_file


def _guard_rewrite(path: str, old: str, body: str, ctx) -> None:
    """write_file over an EXISTING file: it must have been read, and a small change must go through edit_file
    (rewriting a whole file for a small change is how code silently drifts / loses parts)."""
    if body == old:
        return
    if not ctx.has_read(path) and path not in ctx.written and path not in ctx.warned_unread:
        ctx.warned_unread.add(path)
        raise ToolError(f"Súbor {path} už existuje a ešte si ho v tejto úlohe nečítal. Najprv ho prečítaj (read_file), "
                        "nech nezmeníš to, čo nevidíš, a zmenu urob cez edit_file. (Toto upozornenie je jednorazové.)")
    n = len(old.splitlines())
    if n >= SMALL_REWRITE_MIN_LINES and editing.changed_share(old, body) < SMALL_REWRITE_SHARE:
        added, removed, _ = editing.diff_summary(old, body)
        raise ToolError(f"Súbor {path} má {n} riadkov a tvoja verzia mení len +{added} / -{removed} riadkov. Na takú zmenu "
                        "NEPREPISUJ celý súbor – použi edit_file (SEARCH/REPLACE len pre zmenené miesto). "
                        "Ak ho naozaj chceš nahradiť celý, pridaj overwrite=\"true\".")


def _write(args, body, ctx):
    path = args.get("path", "")
    if not body.strip():                                       # content given as an argument instead of the tag body
        body = str(args.get("content") or args.get("text") or args.get("contents") or "")
    if not body.strip():
        raise ToolError("write_file potrebuje obsah súboru medzi <tool ...> a </tool>.")
    try:
        workspace.check_meaningful_name(path)
        path = workspace.clean_rel_path(path)
        old = _existing(path)
        overwrite = str(args.get("overwrite", "")).lower() in ("1", "true", "yes", "ano", "áno")
        if old is not None and not overwrite and editing.shrinks_file(old, body):
            raise ToolError(
                f"Súbor {path} má {len(old.splitlines())} riadkov a ty by si ho prepísal kódom s {len(body.splitlines())} riadkami – "
                "stratilo by sa väčšina súboru (vyzerá to, že si napísal len časť). NEPREPISUJ ho: zmenu urob nástrojom "
                "edit_file (SEARCH/REPLACE). Ak ho naozaj chceš nahradiť skráteným obsahom, pridaj overwrite=\"true\".")
        if old is not None and not overwrite:
            _guard_rewrite(path, old, body, ctx)
        err = editing.syntax_error(path, body)
        if err and old is not None and not editing.syntax_error(path, old):
            raise ToolError(f"Zápis sa NEVYKONAL, súbor {path} je nezmenený: nový obsah má syntaktickú chybu ({err}). "
                            "Oprav ju a zapíš znova (pri malej zmene radšej edit_file).")
        ctx.originals.setdefault(path, old)
        changed = workspace.write_text(path, body)
    except workspace.WorkspaceError as e:
        raise ToolError(str(e))
    ctx.mark_written(path)
    msg = f"Súbor {path} {'uložený' if changed else 'už mal rovnaký obsah'} ({len(body)} znakov)."
    if err:                                                      # a NEW file with a syntax error: saved, but say so
        msg += f"\n[SYNTAX] {path} má syntaktickú chybu ({err}) – oprav ju hneď (edit_file) a až potom pokračuj."
    if old is not None and changed and len(old.splitlines()) >= 30 and editing.changed_share(old, body) < 0.4:
        msg += (f"\n[TIP] Prepísal si celý existujúci súbor kvôli malej zmene. Ďalšie malé úpravy rob cez edit_file "
                "(SEARCH/REPLACE) – je to rýchlejšie a nehrozí, že niečo vypadne.")
    return msg


def _edit(args, body, ctx):
    path = args.get("path", "")
    blocks = editing.parse_blocks(body)
    if not blocks:                                               # single replacement given as attributes
        old = next((args[k] for k in ("old", "old_str", "old_text", "search", "find") if k in args), None)
        new = next((args[k] for k in ("new", "new_str", "new_text", "replace", "replacement") if k in args), None)
        if old is not None and new is not None:
            blocks = [(old, new)]
    if not blocks:
        raise ToolError("edit_file potrebuje aspoň jeden blok SEARCH/REPLACE. " + editing.FORMAT_HELP)
    try:
        path = workspace.clean_rel_path(path)
        text = _existing(path)
        if text is None:
            if all(not o.strip() for o, _ in blocks):            # empty SEARCH on a missing file = create it
                workspace.check_meaningful_name(path)
                text = ""
            else:
                raise ToolError(f"Súbor '{path}' neexistuje – na nový súbor použi write_file (alebo list_files).")
        new_text, errors = editing.apply_blocks(text, blocks)
        if errors:
            raise ToolError("Úprava sa NEVYKONALA, súbor je nezmenený:\n- " + "\n- ".join(errors))
        err = editing.syntax_error(path, new_text)
        if err and text and not editing.syntax_error(path, text):
            raise ToolError(f"Úprava sa NEULOŽILA, súbor {path} je nezmenený: po nej by mal syntaktickú chybu ({err}). "
                            "Skontroluj zátvorky / odsadenie v bloku REPLACE a skús znova.")
        ctx.originals.setdefault(path, None if _existing(path) is None else text)
        changed = workspace.write_text(path, new_text)
    except workspace.WorkspaceError as e:
        raise ToolError(str(e))
    ctx.mark_written(path)
    if not changed:
        return f"Súbor {path} sa nezmenil (nový text je rovnaký ako starý)."
    added, removed, diff = editing.diff_summary(text, new_text)
    return f"Súbor {path} upravený: {len(blocks)} blok(y), +{added} / -{removed} riadkov.\n{diff}"


def _rename(args, body, ctx):
    old, new = args.get("path", ""), args.get("to", "")
    try:
        new = workspace.rename_file(old, new)
    except workspace.WorkspaceError as e:
        raise ToolError(str(e))
    if old in ctx.written:
        ctx.written.remove(old)
    ctx.mark_written(new)
    return f"Súbor {old} premenovaný na {new}."


def _delete(args, body, ctx):
    path = args.get("path", "")
    try:
        workspace.delete_file(path)                              # a copy goes to .history first
    except workspace.WorkspaceError as e:
        raise ToolError(str(e))
    if path in ctx.written:
        ctx.written.remove(path)
    return f"Súbor {path} zmazaný (záloha je v .history)."


def _undo(args, body, ctx):
    """Back to the state before the agent's changes in this task (or to the newest backup in .history)."""
    try:
        path = workspace.clean_rel_path(args.get("path", ""))
        if path in ctx.originals:
            orig = ctx.originals.pop(path)
            if orig is None:                                     # the file was created during this task
                workspace.delete_file(path)
                if path in ctx.written:
                    ctx.written.remove(path)
                return f"Súbor {path} vznikol až počas tejto úlohy – zmazal som ho (záloha je v .history)."
            workspace.write_text(path, orig)
            ctx.mark_written(path)
            return f"Súbor {path} je vrátený do stavu spred tvojich zmien v tejto úlohe ({len(orig.splitlines())} riadkov)."
        name = workspace.safe_path(path).name
        backups = sorted(workspace.HISTORY_DIR.glob(f"{name}.*.bak"), key=lambda b: b.stat().st_mtime)
        backups = [b for b in backups if not b.name.endswith(".deleted.bak")]
        if not backups:
            raise ToolError(f"Pre {path} nemám čo vrátiť (žiadna zmena v tejto úlohe ani záloha v .history).")
        workspace.write_text(path, backups[-1].read_text(encoding="utf-8", errors="replace"))
        ctx.mark_written(path)
        return f"Súbor {path} vrátený z poslednej zálohy {backups[-1].name}."
    except workspace.WorkspaceError as e:
        raise ToolError(str(e))


SKILL = Skill(
    id="fs_write", icon="✍️", name="Vytváranie súborov", order=20,
    short="Zápis do workspace/ (so zálohou)",
    description="Agent môže vytvárať, upravovať po častiach (edit_file – SEARCH/REPLACE bez prepisovania celého súboru), "
                "prepisovať a premenovávať súbory vo workspace/ (starý obsah sa zálohuje do .history; zmena, ktorá by rozbila syntax "
                "Pythonu / JSONu, sa neuloží; malá zmena veľkého súboru ide len cez edit_file; undo_file vráti zmeny). Názvy musia súvisieť s témou, nie script.py / test.py. "
                "V normálnom chate sa podľa tohto prepínača automaticky ukladá kód z odpovedí.",
    tools=(
        Tool("write_file", 'path="priecinok_temy/nazov.py" + celý obsah súboru medzi značky (vytvorí / prepíše súbor)',
             '<tool name="write_file" path="todo_aplikacia/todo.py">\nprint("ahoj")\n</tool>', _write,
             params=(Param("path", "cesta vo workspace/, názov podľa témy, napr. todo_aplikacia/todo.py"),
                     Param("content", "celý obsah súboru"),
                     Param("overwrite", "true = nahradiť existujúci súbor aj výrazne kratším obsahom", required=False)),
             body="content"),
        Tool("edit_file", 'path="subor.py" + v tele jeden alebo viac blokov <<<<<<< SEARCH / presný starý text / ======= / '
                          'nový text / >>>>>>> REPLACE – zmení LEN tú časť existujúceho súboru (NEPREPISUJ celý súbor)',
             '<tool name="edit_file" path="todo_aplikacia/todo.py">\n<<<<<<< SEARCH\ndef pridaj(x):\n    return x\n=======\n'
             'def pridaj(x, y=0):\n    return x + y\n>>>>>>> REPLACE\n</tool>', _edit,
             params=(Param("path", "existujúci súbor vo workspace/"),
                     Param("changes", "bloky SEARCH/REPLACE: <<<<<<< SEARCH, presný starý text, =======, nový text, "
                                      ">>>>>>> REPLACE (viac blokov = viac zmien naraz)", required=False),
                     Param("old", "alternatíva pre jednoriadkovú zmenu: presný starý text", required=False),
                     Param("new", "alternatíva pre jednoriadkovú zmenu: nový text", required=False)),
             body="changes"),
        Tool("undo_file", 'path="subor.py" – vráti súbor do stavu spred TVOJICH zmien v tejto úlohe (použi, keď zmena niečo '
                          'pokazila a nevieš to hneď opraviť; súbor vytvorený v tejto úlohe sa zmaže)',
             '<tool name="undo_file" path="todo_aplikacia/todo.py"/>', _undo,
             params=(Param("path", "súbor vo workspace/"),)),
        Tool("delete_file", 'path="subor.py" – zmaže súbor (kópia sa uloží do .history); mazaj len keď o to používateľ žiada',
             '<tool name="delete_file" path="stary_skript.py"/>', _delete,
             params=(Param("path", "súbor vo workspace/"),)),
        Tool("rename_file", 'path="stary.py" to="novy_nazov_podla_temy.py" – premenuje súbor',
             '<tool name="rename_file" path="app.py" to="zaloha_priecinka.py"/>', _rename,
             params=(Param("path", "súčasná cesta súboru"), Param("to", "nový názov podľa témy"))),
    ),
)
