"""🧰 Skill packs: modular instruction skills (SKILL.md folders, also imported from the internet) - see core/skillpacks.py.

The prompt lists the enabled packs (name + description); the agent loads the full instructions on demand.
"""
import hashlib
import re

from core import skillpacks
from core.skills import Param, Skill, Tool, ToolError
from core.skills.fs_read import NO_CHANGE

CHUNK = 5200          # characters of one answer; the rest is read with start=


def _int(v) -> int:
    try:
        return max(0, int(str(v).strip()))
    except (TypeError, ValueError):
        return 0


def _pick(name: str) -> skillpacks.Pack:
    pack = skillpacks.find_pack(name)
    if not pack:
        names = ", ".join(p.id for p in skillpacks.enabled_packs()) or "žiadne"
        raise ToolError(f"Balík skillov '{name}' neexistuje. Dostupné: {names}.")
    if not skillpacks.is_enabled(pack.id, pack.meta.get("default_enabled", True)):
        raise ToolError(f"Balík '{pack.id}' je vypnutý – používateľ ho môže zapnúť v Prispôsobiť → Balíky skillov.")
    return pack


def _part(text: str, start: int, label: str, name: str, path: str) -> str:
    lines = text.split("\n")
    a = max(1, start or 1)
    out, size = [], 0
    for l in lines[a - 1:]:
        if out and size + len(l) + 1 > CHUNK:
            break
        out.append(l)
        size += len(l) + 1
    b = a + len(out) - 1
    more = (f"\n[ďalej: skill_file skill=\"{name}\" path=\"{path}\" start={b + 1}]" if b < len(lines) else "")
    return "\n".join(out) + more


def _list(args, body, ctx):
    packs = skillpacks.enabled_packs()
    if not packs:
        return "(žiadne zapnuté balíky skillov – používateľ ich pridá v Prispôsobiť → Balíky skillov)"
    return "\n".join(f"- {p.id}: {p.description[:200]}" + (f"  [súbory: {len(p.files)}]" if p.files else "") for p in packs)


def _use(args, body, ctx):
    pack = _pick(args.get("skill") or args.get("name") or body)
    copy = [c for c in re.split(r"[,;\n]", args.get("copy") or "") if c.strip()]
    key = f"skill:{pack.id}"
    text = skillpacks.render_for_agent(pack)
    digest = hashlib.md5(text.encode("utf-8", "ignore")).hexdigest()
    if ctx.read_hashes.get(key) == digest and not copy:
        return (f"{NO_CHANGE} Postup balíka {pack.id} už máš vyššie v rozhovore. Neotváraj ho znova – riaď sa ním a "
                "pokračuj ďalším krokom.")
    done = []
    if copy:                                               # a failed copy must not count as "already loaded"
        try:
            done = skillpacks.stage_inputs(pack, copy)
        except skillpacks.PackError as e:
            raise ToolError(str(e))
    staged = skillpacks.stage_scripts(pack) if pack.scripts else []
    if ctx.read_hashes.get(key) == digest:                 # postup už je v rozhovore: len potvrď kópie dát
        out = f"Postup balíka {pack.id} už máš vyššie."
    else:
        out = _part(text, 1, "", pack.id, "SKILL.md")
    ctx.read_hashes[key] = digest
    if done:
        out += "\n[KÓPIE DÁT: " + "; ".join(f"{a} → {b}" for a, b in done) + " – v skripte ich uvádzaj len názvom súboru.]"
    if staged:
        runner = next((f for f in staged if f.endswith(".py")), staged[0])
        out += (f"\n[SKRIPTY pripravené vo workspace/: {', '.join(staged[:8])}. Spusti: run_code path=\"{runner}\" "
                "args=\"názov_súboru_s_dátami\". Súbor, ktorý skript číta, musí byť skopírovaný vedľa neho (parameter copy).]")
    return out


def _file(args, body, ctx):
    pack = _pick(args.get("skill") or args.get("name") or "")
    rel = (args.get("path") or "").strip()
    try:
        text = skillpacks.read_bundled(pack, rel)
    except skillpacks.PackError as e:
        raise ToolError(str(e))
    if rel in ("", "SKILL.md"):
        text = skillpacks.render_for_agent(pack)
    return _part(text, _int(args.get("start")), "", pack.id, rel or "SKILL.md")


SKILL = Skill(
    id="skillpacks", icon="🧰", name="Balíky skillov", order=12, scope="agent",
    short="Postupy pre konkrétnu prácu (SKILL.md); dajú sa importovať z internetu",
    description="Modulárne inštrukčné skills v bežnom formáte SKILL.md (ako u komerčných AI asistentov). V prompte sú len "
                "názvy a popisy zapnutých balíkov; keď úloha niektorému zodpovedá, agent si načíta celý postup (skill_use), "
                "podľa potreby aj priložené súbory (skill_file) a skripty spustí cez run_code. Balíky pridáš pretiahnutím "
                "ZIPu / SKILL.md alebo odkazom v Prispôsobiť → Balíky skillov; cudzie formáty sa preložia automaticky.",
    tools=(
        Tool("skill_list", "bez argumentov – zapnuté balíky skillov",
             '<tool name="skill_list"/>', _list),
        Tool("skill_use", 'skill="id" [copy="nahrate/data.csv"] – načíta postup balíka; copy dá dátový súbor vedľa jeho skriptov',
             '<tool name="skill_use" skill="csv-analyza" copy="nahrate/data.csv"/>', _use,
             params=(Param("skill", "id balíka skillov zo zoznamu"),
                     Param("copy", "súbor(y) z workspace/, ktoré skripty balíka potrebujú (čiarkou)", required=False))),
        Tool("skill_file", 'skill="id" path="references/x.md" [start="1"] – súbor priložený k balíku / ďalšia časť SKILL.md',
             '<tool name="skill_file" skill="csv-analyza" path="references/postup.md"/>', _file,
             params=(Param("skill", "id balíka"), Param("path", "cesta súboru v balíku, napr. references/x.md"),
                     Param("start", "prvý riadok (od 1)", required=False))),
    ),
)
