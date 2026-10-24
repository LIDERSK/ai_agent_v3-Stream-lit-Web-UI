"""Two-PC collaboration: architect plans, programmer writes the first draft, reviewer checks + finishes.

Each role runs on the PC + model the user picked (models.cluster_team()).

run_cluster() is a generator so the UI can show every stage live. Events (dicts):
    info         {text}
    stage_start  {title, final}
    chunk        {text}                  (streamed text of the current stage)
    stage_end    {title, text, final}
    final        {text}
    error        {text}
"""
from __future__ import annotations

from config import CARRY_CHARS, CARRY_REF_CTX, CLUSTER_NUM_CTX, NODES, STAGE_MAX_TOKENS
from core import models
from core.loopguard import trim_repetition
from core.ollama_client import OllamaError, check_node, effective_ctx, stream_chat

FILE_HINT = ("Pred každý blok kódu napíš názov súboru v `spätných apostrofoch` (názov podľa témy). "
             "Každý súbor uveď PRESNE RAZ – nikdy nepíš ten istý kód dvakrát ani alternatívne verzie. "
             "Celý kód jedného súboru patrí do JEDNÉHO bloku – nikdy ho nedeľ na časti. "
             "Používaj IBA štandardnú knižnicu a knižnice, ktoré zadanie výslovne spomína (pri Flasku len Flask) – "
             "žiadne ďalšie pip balíky (napr. flask_cors, flask_sqlalchemy), nemusia byť nainštalované.")


_SCALE = [1.0]      # share of CARRY_REF_CTX that the current PC can really use


def _cap(text: str, limit: int) -> str:
    """Shorten text carried over into the next stage so the prompt always fits the context window."""
    limit = int(limit * _SCALE[0])
    if len(text) <= limit:
        return text
    return text[:limit] + "\n… (zvyšok skrátený)"


def _think_for(model: str, retry: bool = False):
    """gpt-oss cannot switch thinking off, only to "low"; a long reasoning eats the whole stage budget."""
    if model.lower().startswith("gpt-oss"):
        from core.thinking import selected_effort     # the Low / Medium / High button; a retry always goes down to low
        return "low" if retry else selected_effort()
    return False if retry else None


def run_cluster(goal: str, temperature: float = 0.4, context: str = ""):
    team = models.cluster_team()                                  # role -> (PC, model chosen by the user)
    online = {n: check_node(NODES[n].url)[0] for n in {pc for pc, _ in team.values()} | set(NODES)}
    if not any(online.values()):
        yield {"type": "error", "text": "Ani jeden počítač nie je dostupný."}
        return
    fallback_pc = next(n for n, ok in online.items() if ok)
    who: dict[str, tuple] = {}                                    # role -> (node, model)
    for role, (pc, chosen) in team.items():
        if not online[pc]:                                        # that PC is down -> an online one takes over
            yield {"type": "info", "text": f"⚠️ {pc} nie je dostupný – rolu „{role}“ preberá {fallback_pc}."}
            pc, chosen = fallback_pc, None
        model = models.resolve_role_model(pc, chosen)
        if not model:
            yield {"type": "error", "text": f"{pc}: nie je nainštalovaný žiadny textový model (`ollama pull <model>`)."}
            return
        if chosen and model != chosen:
            yield {"type": "info", "text": f"ℹ️ {pc}: model `{chosen}` nie je nainštalovaný, použijem `{model}`."}
        who[role] = (NODES[pc], model)
    labels = {"architect": "Architekt", "programmer": "Programátor", "reviewer": "Recenzent"}
    yield {"type": "info", "text": " · ".join(f"{labels[r]}: {who[r][0].name} ({who[r][1]})" for r in models.ROLES)}
    arch, prog, rev = who["architect"][0], who["programmer"][0], who["reviewer"][0]

    stages = [
        ("plan", f"🧠 1. Plán – {arch.name}", "architect", False,
         lambda r: ctx_block + f"Navrhni stručný plán (súbory, funkcie, kroky) pre úlohu:\n{goal}\nBez kódu, max 12 riadkov."),
        ("draft", f"💻 2. Prvá verzia – {prog.name}", "programmer", False,
         lambda r: ctx_block + f"Úloha: {goal}\n\nPlán:\n{_cap(r['plan'], CARRY_CHARS['plan'])}\n\nNapíš kompletný kód. {FILE_HINT}"),
        ("review", f"🔍 3. Recenzia – {rev.name}", "reviewer", False,
         lambda r: ctx_block + f"Cieľ: {goal}\n\nSprav stručné code review. Vypíš konkrétne chyby a čo opraviť "
                   f"(odrážky, max 10). Over najmä: je splnená KAŽDÁ požiadavka zo zadania; "
                   f"globálny handler výnimiek nesmie meniť HTTP chyby (404/405/400) na 500; neplatný vstup má vrátiť 4xx; "
                   f"v kóde nie je zastaraný ani nebezpečný konštrukt.\n\n{_cap(r['draft'], CARRY_CHARS['draft'])}"),
        ("final", f"✅ 4. Finálna verzia – {rev.name}", "reviewer", True,
         lambda r: ctx_block + f"Úloha: {goal}\n\nPôvodný kód:\n{_cap(r['draft'], CARRY_CHARS['draft'])}\n\nRecenzia:\n{_cap(r['review'], CARRY_CHARS['review'])}\n\n"
                   f"Vráť finálnu opravenú verziu kompletného kódu (každý súbor raz, bez opakovania a bez "
                   f"vysvetľovania navyše). {FILE_HINT}"),
    ]
    from core.workspace import wanted_files
    names = wanted_files(goal)
    if names:
        goal = goal + f"\n(Hlavný súbor sa MUSÍ volať presne {names[0]}.)"
    ctx_block = f"Predošlý rozhovor (pre kontext):\n{context}\n\n" if context.strip() else ""
    results: dict[str, str] = {}
    try:
        for key, title, role, is_final, make_prompt in stages:
            node, model = who[role]
            yield {"type": "stage_start", "title": title, "final": is_final}
            ctx = effective_ctx(node.url, model, CLUSTER_NUM_CTX)
            _SCALE[0] = min(1.0, ctx / CARRY_REF_CTX)
            if ctx < min(CLUSTER_NUM_CTX, CARRY_REF_CTX) and ctx < CLUSTER_NUM_CTX:
                yield {"type": "info", "text": f"ℹ️ {node.name}: okno kontextu {ctx} (menej VRAM) – prenášaný text sa skracuje."}
            prompt = make_prompt(results)
            room = max(512, ctx - len(prompt) // 3 - 200)       # prompt + answer must fit in the window
            text, stopped = "", None
            for attempt in (0, 1):
                text, stopped = "", None
                for ev in stream_chat(node.url, model, [{"role": "user", "content": prompt}], temperature,
                                      think=_think_for(model, attempt == 1),
                                      num_ctx=ctx, num_predict=min(STAGE_MAX_TOKENS[key], room)):
                    if ev["type"] == "content":
                        text += ev["text"]
                        yield {"type": "chunk", "text": ev["text"]}
                    elif ev["type"] == "wait":
                        yield ev
                    elif ev["type"] == "done":
                        stopped = ev["stats"].get("stopped")
                text = trim_repetition(text)                  # drop a looping tail, keep one copy
                if text.strip():
                    break
                if attempt == 0:                              # reasoning ate the budget: ask again with less thinking
                    yield {"type": "info", "text": f"↪️ {title}: model nevrátil text (len úvahu) – skúšam znova s kratším premýšľaním."}
            if stopped == "loop":
                yield {"type": "info", "text": f"⚠️ {title}: model sa začal opakovať – výstup som ukončil a opakovanie odstránil."}
            elif stopped == "length":
                yield {"type": "info", "text": f"⚠️ {title}: dosiahnutý limit dĺžky etapy – výstup môže byť neúplný."}
            if not text.strip() and is_final and results.get("draft", "").strip():
                yield {"type": "info", "text": "⚠️ Finálna etapa zostala prázdna – použijem prvú verziu kódu."}
                text = results["draft"]
            results[key] = text.strip()
            yield {"type": "stage_end", "title": title, "text": results[key], "final": is_final}
        yield {"type": "final", "text": results["final"]}
    except OllamaError as e:
        yield {"type": "error", "text": str(e)}
