"""Agent chat: the model works in a loop with tools (files, code, web, images, cluster)."""
from __future__ import annotations

import time

import streamlit as st

from config import AGENT_GPTOSS_THINK, AGENT_TIER_CAP, MAX_IMAGES, OFF_TIER, THINKING_TIERS
from core import plan as planlib
from core.agent import run_agent
from core.toolcalling import choose_protocol
from core.media import resolve_upload
from core.ollama_client import OllamaError, get_capabilities
from core.prompts import asks_to_run, build_messages, history_text
from core.router import RoutingError, resolve_target
from core.skills import ToolContext
from core.thinking import is_gptoss, plan_thinking, tier_for_model
from core.vision import describe_bytes
from ui.live import Step,  LiveTurn
from ui.runs import common

LANG = {"py": "python", "js": "javascript", "html": "html", "css": "css", "json": "json", "md": "markdown",
        "sh": "bash", "yml": "yaml", "yaml": "yaml", "sql": "sql", "ts": "typescript"}


def _label(name: str, args: dict) -> str:
    arg = args.get("path") or args.get("query") or ""
    return f"{name} {arg}".strip()


def _lang(args: dict) -> str | None:
    return LANG.get((args.get("path") or "").rsplit(".", 1)[-1].lower())


def _stage_view(slot):
    """Live view of cluster stages inside the tool box of the agent chat."""
    state = {"title": "", "buf": "", "done": [], "last": 0.0}

    def show(ev: dict) -> None:
        t = ev["type"]
        if t == "info":
            state["done"].append(f"🤝 {ev['text']}")
        elif t == "stage_start":
            state["title"], state["buf"] = ev["title"], ""
        elif t == "chunk":
            state["buf"] += ev["text"]
            if time.perf_counter() - state["last"] < 0.4:           # don't redraw on every token
                return
            state["last"] = time.perf_counter()
        elif t == "stage_end":
            state["done"].append(f"✅ {ev['title']}")
            state["title"], state["buf"] = "", ""
        else:
            return
        head = "\n\n".join(state["done"])
        if state["title"]:
            lines = state["buf"].splitlines()
            tail = "\n".join(lines[-12:])[-1200:].replace("```", "'" * 3)
            head += f"\n\n**⏳ {state['title']}** · {len(lines)} riadkov\n\n```text\n{tail}\n```"
        slot.markdown(head)

    return show


def run(settings, msgs: list[dict], user_msg: dict) -> None:
    ss = st.session_state
    try:
        target = resolve_target(settings.node, needs_vision=False)       # the "brain" is the coder model
    except RoutingError as e:
        st.error(str(e))
        return
    if target.warning:
        st.warning(target.warning)
    if "run_code" not in settings.enabled and asks_to_run(user_msg["content"]):
        st.warning("▶️ Zadanie chce kód otestovať, ale **Sandbox je vypnutý** – agent ho nespustí. "
                   "Zapni ho v ＋ → Schopnosti (alebo Prispôsobiť) a pošli správu znova.")
    caps = get_capabilities(target.url, target.model)
    tier, order = tier_for_model(settings.tier, target.model), list(THINKING_TIERS)
    if AGENT_TIER_CAP and not is_gptoss(target.model) and tier in order and AGENT_TIER_CAP in order and order.index(tier) > order.index(AGENT_TIER_CAP):
        tier = AGENT_TIER_CAP                      # deep thinking on every small tool step only makes the agent crawl
    think_param, hint = plan_thinking(tier, target.model, caps)
    if AGENT_GPTOSS_THINK and is_gptoss(target.model) and think_param in ("low", "medium"):
        think_param = AGENT_GPTOSS_THINK           # long reasoning before every tiny tool call = empty answers and stalls
    protocol = choose_protocol(target.url, target.model, caps)           # native tool calling or text tags

    trace: list[dict] = []
    note = ""
    if user_msg["images"] and "vision" in settings.enabled:              # images -> text description
        for i, rel in enumerate(user_msg["images"][:MAX_IMAGES], 1):
            with st.status(f"👁 Rozpoznávam obrázok {i}…", expanded=False) as s:
                try:
                    desc = describe_bytes(settings.node, resolve_upload(rel).read_bytes(), "")
                    s.update(label=f"👁 Obrázok {i} rozpoznaný", state="complete")
                except (RoutingError, OllamaError, OSError) as e:
                    desc = f"(obrázok sa nepodarilo rozpoznať: {e})"
                    s.update(label=f"👁 Obrázok {i} – chyba", state="error")
                st.markdown(desc)
            trace.append({"kind": "tool", "name": "describe_image", "args": {"path": rel}, "body": "",
                          "text": desc, "ok": not desc.startswith("(")})
            note += f"\n\n[Popis priloženého obrázka {i} od vision modelu: {desc}]"

    api_messages = build_messages(msgs, mode="agent", hint=hint, enabled=settings.enabled,
                                  custom=settings.custom_instructions, extra_user_note=note, protocol=protocol)
    common.stop_button()
    base_meta = {"node": target.node, "model": target.model, "tier": settings.tier,
                 "temperature": settings.temperature, "agent": True, "protocol": protocol.name}
    partial = common.new_partial(base_meta, trace)

    planning = "planning" in settings.enabled
    tool_ctx = ToolContext(node=settings.node, temperature=settings.temperature,
                           history=history_text(msgs[:-1]), chat_id=ss.chat_id,
                           plan=planlib.load(ss.chat_id) if planning else [])
    plan_slot = st.empty()                                               # live checklist at the top of the answer

    def show_plan() -> None:
        if tool_ctx.plan:
            done, total = planlib.progress(tool_ctx.plan)
            plan_slot.markdown(f"**📋 Plán · {done}/{total}**\n\n```text\n{planlib.render(tool_ctx.plan)}\n```")
    if planning and planlib.pending(tool_ctx.plan):
        show_plan()
    want_think = settings.tier != OFF_TIER
    turn, tool_box = None, None
    final, stop_note, stop_reason, error = "", "", "", None
    t0, think_total, ptok, ctok, tok_s, n_tools = time.perf_counter(), 0.0, 0, 0, None, 0
    proc = st.status("🧰 Postup agenta", expanded=False)               # ONE box: thinking + tool calls (open it to see them)
    try:
        for ev in run_agent(api_messages, url=target.url, model=target.model, think_param=think_param,
                            temperature=settings.temperature, enabled=settings.enabled,
                            ctx=tool_ctx, protocol=protocol):
            t = ev["type"]
            if t == "protocol":
                base_meta["protocol"] = ev["name"]
                if ev["reason"]:
                    trace.append({"kind": "text", "text": f"🔁 _{ev['reason']}_"})
                    with proc:
                        st.caption(f"🔁 {ev['reason']}")
            elif t == "plan":
                show_plan()
            elif t == "turn_start":
                with proc:
                    turn = LiveTurn(want_think, hide_tools=True, collapse_when_done=True, flat=True)
            elif t in ("thinking", "content", "wait"):
                turn.feed(ev)
                partial["content"], partial["thinking"] = turn.shown(), turn.thinking
            elif t == "done":
                s = ev["stats"]
                ptok += s.get("prompt_tokens") or 0
                ctok += s.get("completion_tokens") or 0
                tok_s = s.get("tok_per_s") or tok_s
            elif t == "turn_end":
                thinking, text, think_s = turn.finish()
                if thinking:
                    think_total += think_s or 0
                    trace.append({"kind": "thinking", "title": f"🧠 Myšlienkový proces · {think_s:.1f} s",
                                  "text": thinking})
                if ev["call"] is not None and text:
                    trace.append({"kind": "text", "text": text})
                partial["content"], partial["thinking"] = "", ""
            elif t == "tool_call":
                n_tools += 1
                tool_box = Step(proc, _label(ev['name'], ev['args']))
                with tool_box:
                    if ev["body"]:
                        st.code(ev["body"][:2500], language=_lang(ev["args"]))
                    live_slot = st.empty()
                tool_ctx.on_event = _stage_view(live_slot) if ev["name"] == "cluster_solve" else None
                if ev["name"] == "cluster_solve":
                    tool_box.update(expanded=True)
                call = ev
            elif t == "tool_result":
                failed = (not ev["ok"]) or (ev["text"].startswith("Exit code") and not ev["text"].startswith("Exit code 0"))
                tool_box.update(state="error" if failed else "complete", expanded=failed)   # ✗ + opened when a run failed
                with tool_box:
                    st.code(ev["text"][:3000], language="text")
                trace.append({"kind": "tool", "name": call["name"], "args": call["args"],
                              "body": call["body"][:4000], "text": ev["text"][:3000], "ok": ev["ok"]})
                partial["meta"]["files"] = list(tool_ctx.written)       # kept even if the run is interrupted
                if call["name"] in ("plan_set", "plan_done", "cluster_solve"):
                    show_plan()
            elif t == "nudge":
                trace.append({"kind": "text", "text": f"↪️ _{ev['text']}_"})
                with proc:
                    st.caption(f"↪️ {ev['text']}")
            elif t == "final":
                final = ev["text"]
            elif t == "stopped":
                stop_note = ev["detail"]
                stop_reason = ev["reason"]
    except OllamaError as e:
        error = str(e)
        if turn is not None:
            turn.finish()

    if stop_note:
        why = {"stuck": "Agent sa zasekol", "time": "Čas vypršal", "steps": "Bezpečnostný strop krokov"}.get(
            stop_reason, "Agent sa zastavil")
        final = ((final or "") + f"\n\n⚠️ **{why}.** {stop_note} Doterajšia práca zostala vo `workspace/`. "
                 "Napíš „pokračuj“ (alebo upresni zadanie) a agent naváže.").strip()
    if error and not (final or trace):
        ss.partial = None
        st.error(error)
        st.caption("Správa je uložená v chate – použi „↻ Skúsiť znova“.")
        return
    base_meta["files"] = list(tool_ctx.written)
    if tool_ctx.plan:
        base_meta["plan"] = [dict(x) for x in tool_ctx.plan]
        plan_slot.empty()                                                # the saved message shows it from now on
    meta = {**base_meta, "total_s": round(time.perf_counter() - t0, 2),
            "think_s": round(think_total, 2) or None, "prompt_tokens": ptok or None,
            "completion_tokens": ctok or None, "tok_per_s": tok_s, "tools": n_tools}
    if error:
        meta.update(stopped=True, error=error)
    common.finish(settings, final or "_(agent skončil bez textovej odpovede)_", trace=trace, meta=meta,
                  autosave=False)
