"""The Deep Research card: title, plan with step status, progress, notes and sources.

One function draws it live (while the research runs) and from history (finished / stopped / waiting for the start).
`r` is a plain dict (it is saved with the message):
    title, question, state: planning | researching | draft | done | error, status (live text), elapsed (s),
    effort (e.g. "Medium"), steps: [{title, query, status: pending|active|done, notes, sources, warn, kind}],
    sources: [{n, title, url}]
"""
from __future__ import annotations

import streamlit as st

MARK = {"pending": "○", "active": "◔", "done": "✔"}


def _line(step: dict, stopped: bool) -> str:
    status = step.get("status", "pending")
    mark = "⚠️" if step.get("warn") else MARK.get(status, "○")
    if stopped and status == "active":
        mark = "⏹"
    text = f"{mark}  {step['title']}"
    if status == "active" and not stopped:
        return f"**{text}**"
    if status == "pending":
        return f":gray[{text}]"
    return text


def _edit_form(r: dict, key: str, on_start, label: str) -> None:
    titles = [s["title"] for s in r["steps"] if s.get("kind") != "final"]
    text = st.text_area("Kroky výskumu (jeden riadok = jeden krok)", value="\n".join(titles), key=f"{key}_steps",
                        height=min(280, 60 + 32 * len(titles)))
    extra = st.text_input("Doplňujúca požiadavka (voliteľné)", key=f"{key}_extra",
                          placeholder="napr. zameraj sa na ceny a dostupnosť na Slovensku")
    if st.button(label, key=f"{key}_go", type="primary"):
        on_start(text, extra)


def render(r: dict, *, key: str, live: bool = False, on_start=None) -> None:
    state = r.get("state", "done")
    stopped = (not live) and state in ("planning", "researching")
    steps = r.get("steps", [])
    done = sum(1 for s in steps if s.get("status") == "done")
    with st.container(border=True):
        c_title, c_upd = st.columns([5, 1.7], vertical_alignment="center")
        c_title.markdown(f"**🔬 {r.get('title') or 'Deep Research'}**")
        if not live and on_start and state != "draft" and steps:
            with c_upd.popover("✏️ Update", use_container_width=True,
                               help="Uprav kroky výskumu a spusti ho znova"):
                _edit_form(r, key, on_start, "🔄 Spustiť výskum znova")
        if state == "draft" and on_start and not live:
            st.caption("📝 Plán výskumu je pripravený. Skontroluj ho, uprav kroky a spusti výskum.")
            _edit_form(r, key, on_start, "▶ Spustiť výskum")
        elif steps:
            st.markdown("\n\n".join(_line(s, stopped) for s in steps))
        elif live:
            st.caption(r.get("status") or "🧭 Plánujem výskum…")
        if live:
            total = max(1, len(steps))
            elapsed = int(r.get("elapsed", 0))
            st.progress(min(1.0, done / total) if steps else 0.0,
                        text=f"Researching… {elapsed} s · {r.get('status') or ''}".strip(" ·"))
        elif state == "done":
            st.caption(f"⏱ Pracoval som {r.get('elapsed', 0):.0f} s · 📚 {len(r.get('sources', []))} zdrojov"
                       + (f" · 🧠 {r['effort']}" if r.get("effort") else ""))
        elif stopped:
            st.caption(f"⏹ Výskum bol zastavený – hotových {done} z {len(steps)} krokov (poznámky nižšie).")
        elif state == "error":
            st.caption("⚠️ Výskum sa nepodaril.")
        notes = [(i, s) for i, s in enumerate(steps, 1) if s.get("notes")]
        if not live and (notes or r.get("sources")):
            with st.expander(f"📚 Poznámky a zdroje ({len(r.get('sources', []))})"):
                for i, s in notes:
                    st.markdown(f"**{i}. {s['title']}**\n\n{s['notes']}")
                if r.get("sources"):
                    st.markdown("**Zdroje**\n\n" + "\n".join(
                        f"{x['n']}. [{x['title'] or x['url']}]({x['url']})" for x in r["sources"]))
