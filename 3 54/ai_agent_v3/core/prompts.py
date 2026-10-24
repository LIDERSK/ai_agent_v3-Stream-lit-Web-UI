"""Builds the message list sent to the model (normal chat + agent chat)."""
import re

from datetime import datetime

from config import HISTORY_MESSAGES, MAX_IMAGES
from core.media import encode_b64
from core.skills import tools_for
from core.toolcalling import TextProtocol, ToolProtocol

SYSTEM_PROMPT = (
    "Si skúsený programátor a užitočný asistent. Odpovedaj v jazyku používateľa "
    "(predvolene po slovensky). Kód vždy vlož do blokov ``` s označením jazyka. "
    "Ak vytváraš súbor, pred blok napíš jeho názov v `spätných apostrofoch`. Názov musí vyjadrovať tému "
    "(napr. `zaloha_priecinka.py`), nie `script.py`."
)

AGENT_PROMPT = (
    "Si autonómny programátorský agent. S počítačom používateľa pracuješ VÝLUČNE cez nástroje, "
    "súbory sú v priečinku workspace/. Odpovedaj po slovensky.\n\n"
    "{tool_protocol}\n\n"
    "POSTUP: najprv zisti stav (napr. list_files, read_file), potom konaj a over výsledok. "
    "Pracuj samostatne, kým úloha nie je celá hotová – nepýtaj sa po každom kroku a nezastavuj sa "
    "predčasne. Ak niečo zlyhá, prečítaj chybu a skús iný postup, nikdy neopakuj rovnaké volanie.\n"
    "PRAVDIVOSŤ: súbor existuje IBA ak ho vytvoril nástroj write_file a vrátil OK. Nikdy netvrď, že si "
    "niečo vytvoril alebo spustil, ak si nástroj nezavolal. Do odpovede NIKDY nepíš hranaté "
    "technické značky ani zoznamy použitých nástrojov – výsledky nástrojov dodáva len systém.\n"
    "KAŽDÝ KROK: tesne pred volaním nástroja napíš JEDEN krátky riadok v tvare „Cieľ: …“ – čo robíš a prečo. "
    "Príklad: Cieľ: Zapíšem súbor s výpočtami, lebo menu z neho bude funkcie volať.\n"
    "OVERENIE: po vytvorení alebo úprave súboru výsledok over (spusti ho, ak môžeš, alebo ho prečítaj späť) "
    "a až potom napíš, že je hotovo.\n"
    "CHYBY: keď nástroj zlyhá alebo skript skončí chybou, najprv napíš PRÍČINU (prečo to zlyhalo) a až potom "
    "to oprav. Neopravuj naslepo.\n"
    "Keď je úloha hotová, odpovedz používateľovi stručným zhrnutím BEZ volania nástroja a vymenuj "
    "súbory, ktoré si vytvoril.\n\n"
    "NÁZVY SÚBOROV: názov musí jasne vyjadrovať tému (napr. zaloha_priecinka.py, nie script.py ani "
    "test1.py). Ak vytváraš viac súborov k jednej úlohe, daj ich do spoločného priečinka podľa témy "
    "(napr. todo_aplikacia/main.py, todo_aplikacia/README.md). Používaj malé písmená bez medzier "
    "a diakritiky, slová oddeľ podčiarkovníkom."
)
AGENT_NO_TOOLS = ("Si programátorský asistent v agent chate, ale používateľ nemá zapnuté žiadne nástroje. "
                  "Odpovedaj priamo a odporuč mu zapnúť potrebné skills cez tlačidlo ＋. Odpovedaj po slovensky.")

CLUSTER_RULE = (
    "\n\nKLASTER JE ZAPNUTÝ: pri každej úlohe, kde treba napísať alebo výrazne upraviť kód, najprv "
    "zavolaj nástroj cluster_solve (obe PC spolu navrhnú, napíšu a zrecenzujú kód a nástroj ho sám uloží "
    "do súborov). Potom výsledok over (read_file / run_code) a prípadne dolaď. Pri jednoduchých otázkach "
    "a čítaní súborov klaster nepoužívaj."
)

RUN_RULE = (
    "\n\nSANDBOX: kód z workspace/ vieš spustiť nástrojom run_code (Python, C, C++, JavaScript; HTML sa otvorí "
    "v headless prehliadači, nahlási chyby konzoly a uloží screenshot). Po napísaní kódu ho spusti a chyby oprav "
    "podľa výstupu. Ak chýba kompilátor alebo prehliadač, zavolaj sandbox_info a povedz to používateľovi. "
    "Programy s input()/scanf/menu spúšťaj so stdin. Server (Flask…) sa spustením len overí štart – endpointy "
    "otestuj skriptom (test_client()/requests)."
)

EDIT_RULE = (
    "\n\nÚPRAVY: EXISTUJÚCI súbor nikdy neprepisuj celý. Najprv nájdi miesto (search_files), prečítaj len potrebné "
    "riadky (read_file s start/end – veľké súbory sa čítajú po častiach) a zmenu urob nástrojom edit_file "
    "(blok SEARCH/REPLACE: presný pôvodný text → nový text; viac zmien = viac blokov). write_file použi na NOVÝ "
    "súbor alebo keď meníš väčšinu súboru. Text do SEARCH kopíruj presne z read_file bez čísel riadkov."
)

def project_rule(enabled) -> str:
    run = "run_code" in enabled
    return (
        "\n\nPRÁCA NA PROJEKTE (rob ako skúsený programátor, nie ako generátor kódu):\n"
        "1. Najprv pochop: pozri code_map a prečítaj len súbory, ktorých sa úloha týka. Ak existuje pamäť projektu "
        "(AGENTS.md), dodržiavaj ju.\n"
        "2. Jedna požiadavka = jeden malý krok. Zmeň LEN to, čo používateľ žiada. Nemeň názvy, štýl ani nesúvisiaci kód, "
        "nič nepresúvaj, nerefaktoruj, nepridávaj funkcie navyše.\n"
        + ("3. Po každej zmene over: spusti run_tests (ak má projekt testy) alebo run_code a oprav chyby. Ak zmena niečo "
           "pokazila a nevieš to hneď opraviť, vráť ju cez undo_file a skús menší krok.\n"
           if run else
           "3. Po každej zmene si súbor prečítaj späť a over, že sedí. Ak zmena niečo pokazila, vráť ju cez undo_file.\n")
        + "4. Novú aplikáciu stav po krokoch: najprv najmenšia kostra, ktorá sa spustí, potom po jednej funkcii, po každej over.\n"
        "5. Ak projekt nemá AGENTS.md, po prvom dokončenom kroku ho vytvor (5 – 10 riadkov: účel, súbory, ako spustiť, "
        "pravidlá štýlu); po väčšej zmene ho doplň.\n"
        "6. V odpovedi na konci povedz presne, čo si zmenil (súbor a funkcia) a čo si overil."
    )


TOOL_GUIDE = (
    "\n\nAKO FUNGUJÚ NÁSTROJE: jedno volanie = jeden nástroj; systém ho vykoná a vráti jeho SKUTOČNÝ výsledok, "
    "čo nevrátil, nevieš – nehádaj. Argumenty píš presne podľa príkladu, cesty sú relatívne k workspace/. "
    "Poradie: zisti → prečítaj len potrebné riadky → zmeň → over. Výsledok [BEZ ZMENY] = už to máš, choď ďalej. "
    "Rob len to, čo zadanie žiada (presný názov súboru, žiadne ďalšie)."
)

TOOL_TIPS = {      # one line per enabled skill that is NOT already explained by its own rule below
    "zip_tools": "ZIP: prezri zip_list/zip_search; ak treba kód testovať či meniť, HNEĎ zip_extract. PDF/Office: read_document.",
    "web_search": "Aktuálne veci: web_search, konkrétna stránka: fetch_url.",
}


ASKS_TO_RUN = re.compile(r"otestuj|testuj|spusti|spúšť|vyskúšaj|funkčnos|funkcnos|over\w* funk|\btesty?\b|\btest\b|\brun\b", re.I)


def asks_to_run(task: str) -> bool:
    """Does the user want the code tested / run? (Then a disabled Sandbox has to be said out loud.)"""
    return bool(ASKS_TO_RUN.search(task or ""))


SANDBOX_OFF_ASKED = (
    "\n\nPOUŽÍVATEĽ CHCE KÓD OTESTOVAŤ, ALE SPÚŠŤANIE JE VYPNUTÉ. Nevolaj run_code. Napíš kód aj testy, raz si ich prečítaj "
    "a v ZÁVEREČNEJ odpovedi výslovne napíš: „Kód som nespúšťal (Sandbox je vypnutý – zapni ho v ＋ → Schopnosti).“ "
    "a uveď príkaz, ktorým ho používateľ spustí sám. Netvrď, že je otestovaný."
)


def tool_guide(enabled) -> str:
    tips = " ".join(t for sid, t in TOOL_TIPS.items() if sid in enabled)
    return TOOL_GUIDE + ((" " + tips) if tips else "")


APPDOCS_RULE = (
    "\n\nO APLIKÁCII AI Agent (súbory, fungovanie, zmeny verzií) najprv zavolaj app_info."
)

NO_RUN_RULE = (
    "\n\nKÓD NEVIEŠ SPÚŠŤAŤ (nástroj run_code je vypnutý): do plánu nepíš kroky „spustiť“ ani „otestovať spustením“. "
    "Výsledok over len prečítaním súboru (každý súbor najviac raz) a v odpovedi povedz, že kód nebol spustený."
)

AGENT_THINK_STEP = (
    "\n\nPREMÝŠĽANIE V KAŽDOM KROKU: pred každým volaním nástroja napíš medzi <think> a </think> 2 – 4 vety: "
    "čo už vieš, čo urobíš teraz a prečo. Hneď potom (mimo značiek) zavolaj nástroj. "
    "Príklad: <think>Treba vytvoriť výpočty a menu. Najprv zapíšem súbor s funkciami.</think>"
)

PLAN_RULE = (
    "\n\nPLÁN: pri úlohe s 3 a viac krokmi najprv zavolaj plan_set (3 – 8 krátkych krokov, každý na jeden riadok). "
    "Po dokončení každého kroku zavolaj plan_done s jeho číslom. Aktuálny plán dostaneš po každom kroku v bloku "
    "[PLÁN]. Pri jednoduchej úlohe (1 – 2 kroky) plán nepíš. Neskonči, kým nie sú všetky kroky hotové. "
    "plan_done volaj až PO skutočnom vykonaní kroku. Súbor musí splniť VŠETKY požiadavky zadania naraz "
    "(nie len kostru) – ak zadanie spomína logovanie a ošetrenie chýb, patria už do prvého zápisu súboru."
)

MAX_ATTACH_CHARS = 24000
MAX_OLD_CHARS = 6000


AGENT_FILE_ATTACH_CHARS = 2000      # agent mode: a file stored in workspace/ is only introduced (the tools read it)
AGENT_TEXT_ATTACH_CHARS = 6000      # agent mode: a pasted / small text attachment


def _with_attachments(m: dict, agent: bool = False) -> str:
    """Message text + attachments. In AGENT mode attachments are kept SHORT: the whole prompt (system + task) must
    fit the context window, or Ollama silently cuts off the START of it (= the instructions) and the model
    answers 'the user has not specified a task'. The agent has tools to read the rest."""
    text = m["content"]
    for a in m.get("attachments", []):
        body = a["text"]
        limit = (AGENT_FILE_ATTACH_CHARS if a.get("path") else AGENT_TEXT_ATTACH_CHARS) if agent else MAX_ATTACH_CHARS
        if len(body) > limit:
            more = (" zvyšok prečítaj nástrojmi (zip_list / zip_read / read_file / read_document)" if agent else "")
            body = body[:limit] + f"\n[... skrátené ...{more}]"
        text += f"\n\n[Priložený súbor: {a['name']}]\n```\n{body}\n```"
    return text


def history_text(history: list[dict], max_chars: int = 6000) -> str:
    """Plain-text version of the earlier conversation (newest last), for components without a chat API."""
    lines = []
    for m in history[-HISTORY_MESSAGES:]:
        who = "Používateľ" if m["role"] == "user" else "Asistent"
        lines.append(f"{who}: {m['content'].strip()[:1500]}")
    text = "\n".join(lines)
    return text[-max_chars:]


LEAK_RE = re.compile(r"\[(?:Použité nástroje|VÝSLEDOK NÁSTROJA|KONIEC VÝSLEDKU|UPOZORNENIE|PLÁN|DIAGNÓZA)[^\]]*\]?", re.I)


def _strip_leaks(text: str) -> str:
    """Remove protocol markers a model may have copied into its answer (they are not real tool results)."""
    return LEAK_RE.sub("", text).strip()


def workspace_state(limit: int = 40) -> str:
    """The TRUE list of files in workspace/ - given to the agent so it never has to guess or invent.
    Uploads (nahrate/) are always listed first; a big extracted folder is summarised, so it cannot push them out."""
    from core import workspace
    files = workspace.list_tree()
    if not files:
        return "\n\nAKTUÁLNY STAV workspace/: je prázdny (žiadne súbory)."
    ups = [f for f in files if f.startswith(workspace.UPLOAD_DIR + "/")]
    rest = [f for f in files if f not in ups]
    if len(rest) > limit:                                      # summarise by top-level folder
        groups: dict[str, int] = {}
        for f in rest:
            key = f.split("/")[0] + "/" if "/" in f else f
            groups[key] = groups.get(key, 0) + 1
        rest = [f"{k} ({n} súborov)" if k.endswith("/") else k for k, n in list(groups.items())[:limit]]
    out = "\n\nAKTUÁLNY STAV workspace/ (skutočné súbory): "
    if ups:
        out += "NAHRATÉ POUŽÍVATEĽOM: " + ", ".join(ups[:20]) + ". | OSTATNÉ: "
    return out + (", ".join(rest) if rest else "(nič iné)")


UPLOAD_RULE = (
    "\n\nNAHRATÉ SÚBORY V TOMTO CHATE: {paths}. Keď používateľ povie „tento zip“ / „tento súbor“ / „priložený súbor“, "
    "myslí presne tieto súbory – nepýtaj sa ho na cestu. Na PREZRETIE ZIPu stačí zip_list a zip_search. Ak má úloha kód ZMENIŤ / vylepšiť / opraviť a vrátiť (napr. „pošli mi to ako zip“), ZIP HNEĎ ROZBAĽ jedným zip_extract, súbory čítaj a upravuj priamo (read_file / edit_file / write_file), over to run_code a na konci zabaľ výsledok cez zip_create a odovzdaj. Nečítaj súbory po jednom cez zip_read (45× čítanie nie je pokrok). Ak používateľ chce „použi internet“, použi web_search. Dokument (.pdf/.docx/.xlsx/.pptx) čítaj cez read_document."
)


def uploaded_paths(history: list[dict]) -> list[str]:
    seen: list[str] = []
    for m in history:
        for a in m.get("attachments", []) or []:
            if a.get("path") and a["path"] not in seen:
                seen.append(a["path"])
    return seen


def build_messages(history: list[dict], *, mode: str = "chat", hint: str = "", web_data: str = "",
                   include_images: bool = False, enabled=frozenset(), custom: str = "",
                   extra_user_note: str = "", protocol: ToolProtocol | None = None) -> list[dict]:
    """`history` must end with the user message we want answered."""
    if mode == "agent":
        proto = protocol or TextProtocol()
        system = (AGENT_PROMPT.format(tool_protocol=proto.system_section(enabled))
                  if tools_for(enabled) else AGENT_NO_TOOLS)
        if tools_for(enabled):
            system += tool_guide(enabled)
            system += workspace_state()
            if uploaded_paths(history):
                system += UPLOAD_RULE.format(paths=", ".join("workspace/" + p for p in uploaded_paths(history)))
        if "planning" in enabled:
            system += PLAN_RULE
        if "fs_write" in enabled:
            system += EDIT_RULE + project_rule(enabled)
        if tools_for(enabled):
            from core import project
            system += project.project_notes()
        if "skillpacks" in enabled:
            from core import skillpacks
            system += skillpacks.prompt_section(history[-1]["content"] if history else "")
        if "app_docs" in enabled:
            system += APPDOCS_RULE
        if "run_code" in enabled:
            system += RUN_RULE
        elif tools_for(enabled):
            system += NO_RUN_RULE
            if asks_to_run(history[-1]["content"] if history else ""):
                system += SANDBOX_OFF_ASKED
        if "cluster" in enabled:
            system += CLUSTER_RULE
        if "<think>" in hint:                      # model without native thinking -> keep it thinking every step
            system += AGENT_THINK_STEP
    else:
        system = SYSTEM_PROMPT
    system += (f"\n\nDnešný dátum: {datetime.now():%d. %m. %Y}. "
               "Tvoje vlastné znalosti môžu byť staršie než tento dátum.")
    if custom.strip():
        system += "\n\nVlastné inštrukcie používateľa:\n" + custom.strip()
    if hint:
        system += "\n\n" + hint
    if web_data:
        system += ("\n\nAKTUÁLNE VÝSLEDKY Z WEBU (sú novšie než tvoje znalosti). Pri otázkach na aktuálne "
                   "informácie vychádzaj z nich, nie z pamäte, a pri faktoch uveď zdroj (URL). Ak výsledky "
                   "na odpoveď nestačia, povedz to a nehádaj.\n" + web_data)

    window = history[-HISTORY_MESSAGES:]
    items = []
    for i, m in enumerate(window):
        text = _with_attachments(m, agent=(mode == "agent"))
        if m["role"] == "assistant" and mode == "agent":
            text = _strip_leaks(text)
        if i < len(window) - 1 and len(text) > MAX_OLD_CHARS:
            text = text[:MAX_OLD_CHARS] + "…"
        items.append({"role": m["role"], "content": text})
    if extra_user_note and items:
        items[-1]["content"] += extra_user_note

    if include_images:                                  # newest images first, capped
        left = MAX_IMAGES
        for item, m in reversed(list(zip(items, window))):
            imgs = m.get("images") or []
            if imgs and left > 0:
                take = imgs[-left:]
                item["images"] = [encode_b64(p) for p in take]
                left -= len(take)
    return [{"role": "system", "content": system}, *items]
