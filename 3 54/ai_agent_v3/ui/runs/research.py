"""Deep Research run (normal chat): plan card -> live steps -> report with sources."""
from __future__ import annotations

import time

import streamlit as st

from core import research, workspace
from core.ollama_client import OllamaError, get_capabilities
from core.prompts import _with_attachments, history_text
from core.router import RoutingError, resolve_target
from core.thinking import GPTOSS_TIERS, is_gptoss, plan_thinking, tier_for_model
from ui import research_card, research_options
from ui.live import REDRAW_EVERY, render_stream
from ui.runs import common


def _new_steps(plan_steps: list[dict]) -> list[dict]:
    steps = [{"title": s["title"], "query": s["query"], "status": "pending", "notes": "", "sources": [], "warn": False}
             for s in plan_steps]
    steps.append({"title": research.FINAL_STEP, "query": "", "kind": "final", "status": "pending", "notes": "",
                  "sources": [], "warn": False})
    return steps


def _save_report(title: str, report: str) -> str:
    """Deep Research in an agent chat: the report goes to workspace/ as a Markdown file (the agent can read it later)."""
    try:
        rel = workspace.unique_path(f"vyskum_{workspace.slugify(title) or 'sprava'}.md", report)
        workspace.write_text(rel, report)
        return rel
    except Exception:
        return ""


def run(settings, msgs: list[dict], user_msg: dict) -> None:
    ss = st.session_state
    try:
        target = resolve_target(settings.node, needs_vision=False)
    except RoutingError as e:
        st.error(str(e))
        return
    if target.warning:
        st.warning(target.warning)
    tier = tier_for_model(settings.tier, target.model)
    think_param, _hint = plan_thinking(tier, target.model, get_capabilities(target.url, target.model))
    opts = research_options.load()
    override = ss.pop("research_override", None)                  # set by "Update" / "Spustiť výskum"
    question = _with_attachments(user_msg)
    if override and override.get("extra"):
        question += "\n\nDoplnenie od používateľa: " + override["extra"]
    context = history_text(msgs[:-1])

    usage = research.Usage()
    r = {"question": question[:500], "title": "", "state": "planning", "status": "🧭 Plánujem výskum…", "steps": [],
         "sources": [], "started": time.time(), "elapsed": 0.0, "model": target.model,
         "effort": GPTOSS_TIERS.get(tier) if is_gptoss(target.model) else tier}
    common.stop_button()
    base_meta = {"node": target.node, "model": target.model, "tier": settings.tier,
                 "temperature": settings.temperature, "research": r}
    partial = common.new_partial(base_meta, [])                   # meta["research"] is the SAME dict -> a stop keeps it
    card_slot, report_slot = st.empty(), st.empty()
    live_key = f"live_{ss.chat_id}_{int(r['started'])}"
    last = {"draw": 0.0, "text": 0.0}

    def draw() -> None:
        r["elapsed"] = time.time() - r["started"]
        with card_slot.container():
            research_card.render(r, key=live_key, live=True)
        last["draw"] = time.perf_counter()

    def end(content: str, *, error: str = "", state: str = "done") -> None:
        r["state"], r["status"] = state, ""
        r["elapsed"] = time.time() - r["started"]
        meta = {**base_meta, "total_s": r["elapsed"], "research": r, **usage.meta()}
        if error:
            meta["error"] = error
        elif state == "done" and settings.mode == "agent" and "fs_write" in settings.enabled:
            saved = _save_report(r.get("title") or question, content)     # agent chat: the report is also a file
            if saved:
                meta["files"] = [saved]
        common.finish(settings, content, thinking=None, trace=[], meta=meta, autosave=False)

    draw()
    try:
        if override:
            plan = {"title": override.get("title") or "", "steps": override["steps"]}
            research.with_topic(plan, target.url, target.model, question, think_param, usage)
        else:
            plan = research.make_plan(target.url, target.model, question, n_steps=opts["steps"],
                                      temperature=min(0.4, settings.temperature), think=think_param, context=context,
                                      usage=usage)
        r["title"] = plan["title"] or question[:60]
        r["steps"] = _new_steps(plan["steps"])
        if opts["confirm"] and not override:                      # wait for the user: edit the plan, then start
            end("_Plán výskumu je pripravený – skontroluj kroky v karte a spusti výskum._", state="draft")
            return
        r["state"] = "researching"
        draw()
        report, error, buf = "", "", ""
        for ev in research.run_research(question, plan, url=target.url, model=target.model,
                                        temperature=min(0.5, settings.temperature), think=think_param,
                                        read_pages=opts["pages"], usage=usage):
            t = ev["type"]
            if t == "step_start":
                r["steps"][ev["i"]]["status"] = "active"
                r["status"] = f"🔎 {r['steps'][ev['i']]['title']}"
            elif t == "search":
                r["status"] = f"🔎 Hľadám: {ev['query']}" + ("" if ev["ok"] else f" – ⚠️ {ev['error']}")
            elif t == "source":
                r["sources"].append({"n": ev["n"], "title": ev["title"], "url": ev["url"]})
                r["steps"][ev["i"]]["sources"].append(ev["n"])
            elif t == "page":
                r["status"] = f"📄 Čítam stránku [{ev['n']}]"
            elif t == "step_done":
                step = r["steps"][ev["i"]]
                step.update(status="done", notes=ev["notes"], warn=ev.get("warn", False))
                r["status"] = "🧠 Zapisujem poznámky"
            elif t == "report_start":
                r["steps"][-1]["status"] = "active"
                r["status"] = "✍️ Píšem záverečnú správu"
            elif t == "chunk":
                if ev["phase"] == "report":
                    buf += ev["text"]
                    partial["content"] = buf
                    if time.perf_counter() - last["text"] > REDRAW_EVERY:
                        last["text"] = time.perf_counter()
                        render_stream(report_slot, buf)
                elif time.perf_counter() - last["draw"] > 1.0:    # keep the timer moving during long model calls
                    draw()
                continue
            elif t == "done":
                report = ev["report"]
            elif t == "error":
                error = ev["text"]
            draw()
        report_slot.empty()
        if error:
            end(report or "_(výskum sa nepodaril – dôvod je v upozornení nižšie)_", error=error, state="error")
        else:
            r["steps"][-1]["status"] = "done"
            end(report)
    except OllamaError as e:
        end("_(výskum sa nepodaril – dôvod je v upozornení nižšie)_", error=str(e), state="error")
