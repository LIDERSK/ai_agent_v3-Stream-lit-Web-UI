"""📚 Knowledge about this app: patch notes + map of functions / architecture / model reasoning (PATCH_NOTES_A_MAPA.md)."""
from core import appdocs
from core.skills import Param, Skill, Tool, ToolError

CHUNK = 5200


def _int(v) -> int:
    try:
        return max(0, int(str(v).strip()))
    except (TypeError, ValueError):
        return 0


def _cut(text: str, start: int, topic: str) -> str:
    lines = text.split("\n")
    a = max(1, start or 1)
    out, size = [], 0
    for l in lines[a - 1:]:
        if out and size + len(l) + 1 > CHUNK:
            break
        out.append(l)
        size += len(l) + 1
    b = a + len(out) - 1
    return "\n".join(out) + (f"\n[ďalej: app_info topic=\"{topic}\" start={b + 1}]" if b < len(lines) else "")


def _info(args, body, ctx):
    topic = (args.get("topic") or "").strip()
    query = (args.get("query") or "").strip()
    if query:
        hits = appdocs.search(query)
        if not hits:
            raise ToolError(f"V dokumente o aplikácii sa nenašlo „{query}“. Skús app_info bez argumentov (obsah).")
        return "Nájdené (sekcia, riadok):\n" + hits
    if not topic:
        return appdocs.toc()
    found = appdocs.find(topic)
    if not found:
        raise ToolError(f"Téma „{topic}“ neexistuje.\n" + appdocs.toc())
    if len(found) > 1:
        return ("Téme zodpovedá viac častí – vyber jednu:\n" + "\n".join(f"- {s.title}" for s in found)
                + "\n(napr. app_info topic=\"" + found[0].title.split()[0].lower() + "\")")
    return _cut(found[0].text, _int(args.get("start")), topic)


SKILL = Skill(
    id="app_docs", icon="📚", name="Znalosť o aplikácii", order=7, scope="agent",
    short="Agent vie, ako je táto aplikácia postavená a čo sa menilo",
    description="Agent si môže prečítať dokument PATCH_NOTES_A_MAPA.md: patch notes všetkých verzií, mapu súborov a funkcií, "
                "architektúru, ako sa model rozhoduje (myslenie, volanie nástrojov, ochrany pred cyklením) a ako sa pridáva "
                "skill. Hodí sa, keď má agent upravovať samotnú aplikáciu alebo odpovedať, ako niečo funguje.",
    tools=(
        Tool("app_info", '[topic="mapa"] [query="text"] – dokumentácia aplikácie: bez argumentov obsah, topic časť, query hľadanie',
             '<tool name="app_info" topic="myslenie"/>', _info,
             params=(Param("topic", "časť dokumentu (časť názvu stačí)", required=False),
                     Param("query", "hľadaný text vo všetkých častiach", required=False),
                     Param("start", "prvý riadok pri dlhej časti", required=False))),
    ),
)
