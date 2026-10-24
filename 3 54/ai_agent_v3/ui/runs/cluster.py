"""Cluster mode (normal chat): both PCs work on the message together, every stage shown live."""
from __future__ import annotations

import time

import streamlit as st

from core import models
from core.cluster import run_cluster
from core.prompts import _with_attachments, history_text
from ui.live import wait_text,  REDRAW_EVERY, render_stream
from ui.runs import common


def run(settings, msgs: list[dict], user_msg: dict) -> None:
    ss = st.session_state
    goal = _with_attachments(user_msg)
    team = models.cluster_team()
    pcs = " + ".join(dict.fromkeys(pc for pc, _ in team.values()))
    common.stop_button()
    base_meta = {"node": pcs, "model": "klaster", "cluster": True,
                 "tier": settings.tier, "temperature": settings.temperature}
    trace: list[dict] = []
    partial = common.new_partial(base_meta, trace)

    final, error, buf, last = "", None, "", 0.0
    status = slot = answer_slot = None
    in_final = False
    t0 = time.perf_counter()
    for ev in run_cluster(goal, settings.temperature,
                      context=history_text(msgs[:-1])):
        t = ev["type"]
        if t == "info":
            st.caption("🤝 " + ev["text"])
        elif t == "wait":
            target_slot = answer_slot if in_final else slot
            if target_slot is not None and not buf:
                target_slot.caption(wait_text(ev))
        elif t == "stage_start":
            buf, in_final = "", ev["final"]
            if in_final:
                answer_slot = st.empty()
                answer_slot.caption("⏳ " + ev["title"])
            else:
                status = st.status(ev["title"], expanded=True)
                slot = status.empty()
        elif t == "chunk":
            buf += ev["text"]
            now = time.perf_counter()
            if now - last > REDRAW_EVERY:
                last = now
                render_stream(answer_slot if in_final else slot, buf)
            if in_final:
                partial["content"] = buf
        elif t == "stage_end":
            if ev["final"]:
                answer_slot.markdown(ev["text"])
            else:
                slot.markdown(ev["text"])
                status.update(state="complete", expanded=False)
                trace.append({"kind": "stage", "title": ev["title"], "text": ev["text"]})
        elif t == "final":
            final = ev["text"]
        elif t == "error":
            error = ev["text"]

    if error and not (final or trace):
        ss.partial = None
        st.error(error)
        return
    meta = {**base_meta, "total_s": round(time.perf_counter() - t0, 2)}
    if error:
        meta.update(stopped=True, error=error)
    common.finish(settings, final or "_(klaster nevrátil finálnu verziu)_", trace=trace, meta=meta)
