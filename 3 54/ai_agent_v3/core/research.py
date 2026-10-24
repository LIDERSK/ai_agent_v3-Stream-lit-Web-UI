"""Deep Research: question -> plan -> (search + read pages + notes) per step -> report with numbered sources.

    make_plan(...)      one model call -> {"title", "steps": [{"title", "query"}]}      (the user may edit it)
    run_research(...)   generator of events, see below

Honesty rules: the report may only use what the notes (= what the web search / pages really returned) say. When the
web search does not work, there is NO report invented from the model's memory - the user gets the error instead.
The list of sources at the end is added by code from real URLs, never written by the model. No Streamlit here.

Events of run_research:
    step_start {i}                          search {i, query, ok, error, count}
    source {i, n, title, url}               page {i, n, url, chars}
    step_done {i, notes, warn}              report_start {}
    chunk {phase, text}                     done {report, sources}
    error {text}
"""
from __future__ import annotations

import ipaddress
import json
import re
import socket
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urlparse

import requests

from config import (RESEARCH_DEFAULT_STEPS, RESEARCH_FETCH_TIMEOUT, RESEARCH_MAX_STEPS, RESEARCH_PAGE_CHARS,
                    RESEARCH_PAGES, RESEARCH_PROMPT_CHARS, RESEARCH_RESULTS)
from core import web_search
from core.loopguard import trim_repetition
from core.ollama_client import stream_chat

FINAL_STEP = "Zhrnúť zistenia do správy so zdrojmi"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LocalResearchAgent/1.0)", "Accept-Language": "sk,en;q=0.8"}
MAX_PAGE_BYTES = 1_500_000


# ----------------------------------------------------------------- reading a web page
class _PageText(HTMLParser):
    SKIP = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "iframe"}
    KEEP = {"p", "li", "h1", "h2", "h3", "h4", "td", "th", "blockquote", "pre", "dd", "dt"}

    def __init__(self):
        super().__init__()
        self.parts, self._skip, self._keep, self._buf = [], 0, 0, []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.KEEP:
            self._keep += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.KEEP:
            self._keep = max(0, self._keep - 1)
            line = " ".join("".join(self._buf).split())
            self._buf = []
            if len(line) >= 25:                              # skip menu crumbs and one-word fragments
                self.parts.append(line)

    def handle_data(self, data):
        if not self._skip and self._keep:
            self._buf.append(data)


def _public_host(host: str) -> bool:
    """Do not let a search result send us to this PC or the home network."""
    if not host or host.lower() in ("localhost",) or host.lower().endswith((".local", ".internal")):
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return False
    return True


def fetch_page(url: str, max_chars: int = RESEARCH_PAGE_CHARS) -> str:
    """Readable text of a web page ("" on any problem - a page that cannot be read is simply skipped)."""
    try:
        u = urlparse(url)
        if u.scheme not in ("http", "https") or not _public_host(u.hostname or ""):
            return ""
        r = requests.get(url, headers=HEADERS, timeout=RESEARCH_FETCH_TIMEOUT, stream=True)
        if r.status_code != 200 or "html" not in r.headers.get("content-type", "").lower():
            return ""
        raw = b""
        for chunk in r.iter_content(65536):
            raw += chunk
            if len(raw) > MAX_PAGE_BYTES:
                break
        parser = _PageText()
        parser.feed(raw.decode(r.encoding or "utf-8", "replace"))
        return " ".join(parser.parts)[:max_chars]
    except Exception:
        return ""


# ----------------------------------------------------------------- model calls
class Usage:
    """Tokens of ALL model calls of one research (plan, notes, report) -> the footer under the answer."""

    def __init__(self) -> None:
        self.prompt = self.completion = 0
        self.eval_s = 0.0

    def add(self, stats: dict | None) -> None:
        st = stats or {}
        c = st.get("completion_tokens") or 0
        self.prompt += st.get("prompt_tokens") or 0
        self.completion += c
        if c and st.get("tok_per_s"):
            self.eval_s += c / st["tok_per_s"]

    def meta(self) -> dict:
        if not self.completion:
            return {}
        out = {"prompt_tokens": self.prompt, "completion_tokens": self.completion}
        if self.eval_s:
            out["tok_per_s"] = round(self.completion / self.eval_s, 1)
        return out


def _lower(think, model: str):
    """Thinking for the retry after an empty answer (the reasoning used up the whole turn)."""
    if model.lower().startswith("gpt-oss"):
        return "low"
    return False if think else think


def _llm(url: str, model: str, prompt: str, temperature: float, think, phase: str, usage: Usage | None = None):
    """Generator: yields {"type": "chunk", phase, text}; returns the full answer. One retry if the answer is empty."""
    messages = [{"role": "user", "content": prompt}]
    text = ""
    for attempt in (0, 1):
        text = ""
        for ev in stream_chat(url, model, messages, temperature, think=think if attempt == 0 else _lower(think, model)):
            if ev["type"] == "content":
                text += ev["text"]
                yield {"type": "chunk", "phase": phase, "text": ev["text"]}
            elif ev["type"] == "done" and usage is not None:
                usage.add(ev.get("stats"))
        if text.strip():
            break
    return trim_repetition(text).strip()


# ----------------------------------------------------------------- plan
PLAN_PROMPT = (
    "Dnes je {today}. Si výskumný asistent. Rozlož otázku používateľa na {n} krokov webového výskumu "
    "(každý krok = jedna téma, ktorú treba vyhľadať na webe). Odpovedz IBA JSON objektom bez ďalšieho textu:\n"
    '{{"title": "krátky názov výskumu (max 8 slov)", "steps": [{{"title": "čo zistiť v tomto kroku", '
    '"query": "dobrý vyhľadávací dotaz do webového vyhľadávača"}}]}}\n'
    "Názvy krokov píš v jazyku otázky. Záverečnú správu NEPRIDÁVAJ ako krok – napíše sa automaticky.\n"
    "{context}Otázka: {question}"
).replace("\\\n", "\n")


# ----------------------------------------------------------------- long input -> short topic (+ instructions)
TOPIC_RE = re.compile(r"(?im)^\W*(?:user\s+(?:question|query|request)|research\s+(?:topic|question)|question|topic|"
                      r"otázka|téma|zadanie|úloha|dotaz)\s*[:：]\s*(.+)$")
SHORT_CHARS, SHORT_LINES = 300, 2


def _topic_prompt(text: str) -> str:
    return ("Nižšie je dlhší text od používateľa. Môže obsahovať pokyny, ako má asistent pracovať, a niekedy aj "
            "konkrétnu tému alebo otázku. Napíš JEDNU vetu (max 25 slov) – tému, ktorú treba vyhľadať na webe. "
            "Ak text žiadnu konkrétnu tému nemá, napíš o čom pokyny sú. Nič iné nepíš.\n\nTEXT:\n" + text[:6000])


def split_question(url: str, model: str, question: str, think=None, usage=None) -> tuple[str, str]:
    """(topic, instructions). A short question IS the topic. A long pasted text (rules for the mode, a whole brief...)
    is reduced to a one-sentence topic; the text itself is kept as `instructions` for the report - it must never
    become a search query."""
    q = (question or "").strip()
    if len(q) <= SHORT_CHARS and q.count("\n") <= SHORT_LINES:
        return q, ""
    found = TOPIC_RE.findall(q)
    if found:
        return web_search.clean_query(found[-1]), q
    topic = ""
    try:
        gen = _llm(url, model, _topic_prompt(q), 0.2, _lower(think, model), "topic", usage)
        try:
            while True:
                next(gen)
        except StopIteration as stop:
            topic = (stop.value or "").strip().splitlines()[0] if (stop.value or "").strip() else ""
    except Exception:
        topic = ""
    topic = web_search.clean_query(topic)
    if len(topic) < 8:                                           # model gave nothing usable: last line is usually the ask
        lines = [l.strip() for l in q.splitlines() if l.strip()]
        topic = web_search.clean_query(lines[-1] if lines and len(lines[-1]) <= 300 else q)
    return topic, q


def with_topic(plan: dict, url: str, model: str, question: str, think=None, usage=None) -> dict:
    """Adds plan["topic"] / plan["instructions"] when missing (a plan edited by the user has none)."""
    if "topic" not in plan:
        plan["topic"], plan["instructions"] = split_question(url, model, question, think, usage)
    return plan


def _clip(s, n: int) -> str:
    return " ".join(str(s or "").split())[:n]


def parse_plan(text: str, question: str, n: int) -> dict:
    """Plan from the model's answer: JSON object / JSON list / numbered lines; falls back to a generic plan."""
    title, steps = "", []
    data = None
    for pattern in (r"\{.*\}", r"\[.*\]"):
        m = re.search(pattern, text, re.S)
        if m:
            try:
                data = json.loads(m.group(0))
                break
            except ValueError:
                continue
    if isinstance(data, dict):
        title = _clip(data.get("title"), 80)
        data = data.get("steps") or data.get("plan") or []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                t = _clip(item.get("title") or item.get("step") or item.get("name") or item.get("query"), 140)
                q = _clip(item.get("query") or item.get("search") or t, 160)
            else:
                t = q = _clip(item, 160)
            if t:
                steps.append({"title": t, "query": q or t})
    if not steps:                                                # numbered / bulleted lines
        for line in text.splitlines():
            mm = re.match(r"\s*(?:\d+[.)]|[-*•])\s+(.{6,})", line)
            if mm:
                t = _clip(mm.group(1), 140)
                steps.append({"title": t, "query": t})
    if not steps:
        year = datetime.now().year
        steps = [{"title": "Zistiť základné fakty a kontext", "query": question},
                 {"title": "Nájsť konkrétne možnosti a ich porovnanie", "query": f"{question} comparison"},
                 {"title": "Overiť aktuálne informácie a obmedzenia", "query": f"{question} {year}"}]
    return {"title": title or _clip(question, 60), "steps": steps[:n]}


def _plan_text(url, model, question, n, temperature, think, context, usage=None) -> str:
    prompt = PLAN_PROMPT.format(today=datetime.now().strftime("%d.%m.%Y"), n=n, question=question,
                                context=(f"Predchádzajúci rozhovor (pre kontext): {context[-1200:]}\n" if context else ""))
    gen = _llm(url, model, prompt, temperature, think, "plan", usage)
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        return stop.value or ""


def make_plan(url: str, model: str, question: str, *, n_steps: int = RESEARCH_DEFAULT_STEPS,
              temperature: float = 0.3, think=None, context: str = "", usage: Usage | None = None) -> dict:
    n = max(2, min(RESEARCH_MAX_STEPS, int(n_steps)))
    topic, instructions = split_question(url, model, question, think, usage)
    plan = parse_plan(_plan_text(url, model, topic, n, temperature, think, context, usage), topic, n)
    plan["topic"], plan["instructions"] = topic, instructions[:2500]
    return plan


# ----------------------------------------------------------------- notes + report
NOTES_PROMPT = (
    "Otázka používateľa: {question}\nAktuálny krok výskumu: {step}\n\n"
    "Nižšie sú výsledky webového vyhľadávania a úryvky stránok, každý so značkou [n]. Napíš 3 až 6 stručných "
    "faktických bodov k tomuto kroku. ZA KAŽDÉ tvrdenie dopíš značku zdroja, napr. [2]. Použi LEN informácie zo "
    "zdrojov (nie z pamäte); ak zdroje k téme nič užitočné nehovoria, napíš to. Konkrétne čísla a názvy uvádzaj "
    "presne tak, ako sú v zdroji. Odpovedz v jazyku otázky.\n\nZDROJE:\n{sources}"
)
REPORT_PROMPT = (
    "Dnes je {today}. Napíš výskumnú správu, ktorá odpovedá na otázku používateľa. Použi IBA poznámky nižšie "
    "(sú z webu) a ku každému faktu dopíš značku zdroja [n]. Štruktúra: 2 – 3 vety zhrnutia, potom sekcie s "
    "nadpismi (##), nakoniec praktické odporúčanie. Ak poznámky niečo nepodporujú alebo si protirečia, povedz to "
    "otvorene – nič nedomýšľaj. Zoznam zdrojov NEPÍŠ (pridá sa automaticky). Odpovedz v jazyku otázky.\n\n"
    "{instructions}OTÁZKA: {question}\n\nPOZNÁMKY:\n{notes}"
)


def _source_block(n: int, r: dict, page: str) -> str:
    return f"[{n}] {r['title']}\n{r['body']}" + (f"\nÚryvok stránky: {page}" if page else "")


def _sources_md(report: str, sources: list[dict]) -> str:
    used = sorted({int(x) for x in re.findall(r"\[(\d{1,3})\]", report)})
    chosen = [s for s in sources if s["n"] in used] or sources[:12]
    return "\n\n---\n**Zdroje**\n" + "\n".join(f"{s['n']}. [{s['title'] or s['url']}]({s['url']})" for s in chosen)


def run_research(question: str, plan: dict, *, url: str, model: str, temperature: float = 0.3, think=None,
                 read_pages: bool = True, usage: Usage | None = None):
    """Generator, see the module docstring. `plan` = {"title", "steps": [{"title", "query"}]}."""
    steps = plan["steps"]
    topic = plan.get("topic") or question                         # the short topic, never a pasted brief
    instructions = (plan.get("instructions") or "").strip()
    sources: list[dict] = []                                      # global numbering across the whole research
    by_url: dict[str, int] = {}
    notes_all: list[tuple[str, str]] = []
    any_web = False
    last_error = ""
    for i, step in enumerate(steps):
        yield {"type": "step_start", "i": i}
        res = web_search.search(step["query"], RESEARCH_RESULTS)
        yield {"type": "search", "i": i, "query": step["query"], "ok": res.ok, "error": res.error,
               "count": len(res.results)}
        if not res.ok:
            last_error = res.error
            yield {"type": "step_done", "i": i, "warn": True,
                   "notes": f"Vyhľadávanie „{step['query']}“ nevrátilo nič použiteľné ({res.error})."}
            notes_all.append((step["title"], "(k tomuto kroku sa nepodarilo nájsť žiadne zdroje)"))
            continue
        any_web = True
        blocks, budget = [], RESEARCH_PROMPT_CHARS
        for k, r in enumerate(res.results):
            if r["url"] not in by_url:
                by_url[r["url"]] = len(sources) + 1
                sources.append({"n": by_url[r["url"]], "title": r["title"], "url": r["url"]})
                yield {"type": "source", "i": i, "n": by_url[r["url"]], "title": r["title"], "url": r["url"]}
            n = by_url[r["url"]]
            page = ""
            if read_pages and k < RESEARCH_PAGES:
                page = fetch_page(r["url"])
                if page:
                    yield {"type": "page", "i": i, "n": n, "url": r["url"], "chars": len(page)}
            block = _source_block(n, r, page)[:max(600, budget // max(1, len(res.results) - k))]
            blocks.append(block)
            budget -= len(block)
        prompt = NOTES_PROMPT.format(question=topic, step=step["title"], sources="\n\n".join(blocks))
        notes = yield from _llm(url, model, prompt, temperature, think, "notes", usage)
        notes = notes or "(model nevrátil poznámky k tomuto kroku)"
        notes_all.append((step["title"], notes))
        yield {"type": "step_done", "i": i, "notes": notes, "warn": False}

    if not any_web:                                               # never write a report from memory
        yield {"type": "error", "text": (
            "Webové vyhľadávanie nefungovalo, preto výskum nemá z čoho vychádzať a správu som nevymýšľal. "
            f"Dôvod: {last_error or 'neznámy'}. Skontroluj internet / balík `ddgs` (pip install -U ddgs) a skús znova.")}
        return
    yield {"type": "report_start"}
    notes_text = "\n\n".join(f"### {t}\n{n}" for t, n in notes_all)[:RESEARCH_PROMPT_CHARS * 2]
    guide = (f"POKYNY POUŽÍVATEĽA K FORME A ŠTÝLU (dodrž ich, pokiaľ neodporujú pravidlám o zdrojoch a o nevymýšľaní):\n"
             f"{instructions[:2500]}\n\n") if instructions else ""
    prompt = REPORT_PROMPT.format(today=datetime.now().strftime("%d.%m.%Y"), question=topic, notes=notes_text,
                                  instructions=guide)
    report = yield from _llm(url, model, prompt, temperature, think, "report", usage)
    if not report:
        yield {"type": "error", "text": "Model nevrátil záverečnú správu. Poznámky ku krokom nájdeš v karte výskumu."}
        return
    report += _sources_md(report, sources)
    yield {"type": "done", "report": report, "sources": sources}
