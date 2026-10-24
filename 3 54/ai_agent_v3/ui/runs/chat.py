"""Normal chat: one model answers (optional web search, thinking, images)."""
from __future__ import annotations

import re
import time

import streamlit as st

from config import OFF_TIER
from core.ollama_client import OllamaError, get_capabilities, stream_chat
from core.prompts import build_messages
from core.router import RoutingError, resolve_target
from core.thinking import plan_thinking, tier_for_model
from core.web_search import build_query, search, should_search
from ui.live import LiveTurn
from ui.runs import common


_FILE_ASK = re.compile(r"(vytvor|urob|spravi|sprav|ulož|uloz|zapíš|zapis|vygeneruj|napíš|napis)\w*[^.\n]{0,60}"
                       r"(súbor|subor|\.txt|\.py|\.md|\.html|\.json|\.csv)", re.I)
AGENT_HINT = ("\n\n> 💡 Súbor sa neuložil – **Normálny chat** ukladá len kód označený názvom súboru (a pri zapnutom zápise súborov). "
              "Súbor ti vytvorí **Agent chat** (zapni ho cez ＋ Nový chat → 🤖 Agent).")


def run(settings, msgs: list[dict], user_msg: dict) -> None:
    ss = st.session_state
    try:
        target = resolve_target(settings.node, needs_vision=bool(user_msg["images"]))
    except RoutingError as e:
        st.error(str(e))
        return
    if target.warning:
        st.warning(target.warning)

    web = None
    if "web_search" in settings.enabled and (settings.force_web or should_search(user_msg["content"])):
        with st.status("🔍 Prehľadávam web…", expanded=False) as status:
            web = search(build_query(user_msg["content"]))
            if web.ok:
                status.update(label=f"🔍 Web prehľadaný · {len(web.results)} výsledkov", state="complete")
            else:
                status.update(label="⚠️ Vyhľadávanie sa nepodarilo", state="error")
            st.caption(f"Hľadané: {web.query}")                      # so you can see WHAT was searched
            for r in web.results:
                st.markdown(f"- [{r['title'] or r['url']}]({r['url']})")
            if web.error:
                st.caption(web.error)
        if not web.ok:
            st.warning("🌐 Web sa nepodarilo prehľadať – odpoveď je len z pamäte modelu a môže byť zastaraná.")
    web_data = web.as_text() if web and web.ok else ""

    think_param, hint = plan_thinking(tier_for_model(settings.tier, target.model), target.model, get_capabilities(target.url, target.model))
    api_messages = build_messages(msgs, mode="chat", hint=hint, web_data=web_data,
                                  include_images=target.vision, custom=settings.custom_instructions)

    common.stop_button()
    turn = LiveTurn(settings.tier != OFF_TIER)
    base_meta = {"node": target.node, "model": target.model, "tier": settings.tier,
                 "temperature": settings.temperature, "web": bool(web_data),
                 "web_sources": web.sources() if web and web.ok else []}
    partial = common.new_partial(base_meta)
    t0, stats, error = time.perf_counter(), {}, None
    try:
        for ev in stream_chat(target.url, target.model, api_messages, settings.temperature, think=think_param):
            if ev["type"] == "done":
                stats = ev["stats"]
            else:
                turn.feed(ev)
                partial["content"], partial["thinking"] = turn.answer, turn.thinking
    except OllamaError as e:
        error = str(e)

    thinking, answer, think_s = turn.finish()
    if error and not (answer or thinking):
        ss.partial = None
        st.error(error)
        st.caption("Správa je uložená v chate – použi „↻ Skúsiť znova“.")
        return
    meta = {**base_meta, "total_s": round(time.perf_counter() - t0, 2),
            "think_s": round(think_s, 2) if think_s else None, **stats}
    if error:
        meta.update(stopped=True, error=error)
    ask_file = bool(answer and _FILE_ASK.search(user_msg.get("content") or ""))
    common.finish(settings, answer or "_(prázdna odpoveď)_", thinking=thinking or None, meta=meta,
                  no_file_hint=AGENT_HINT if ask_file else "")
