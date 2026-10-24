"""Renders the conversation: header, bubbles, thinking/agent steps, metrics and action buttons."""
import streamlit as st

from config import MODES, SUGGESTIONS_AGENT, SUGGESTIONS_CHAT
from core import chat_store, skills
from core.media import resolve_upload
from config import RESEARCH_MAX_STEPS
from ui import delivery, research_card, state

LANG = {"py": "python", "js": "javascript", "html": "html", "css": "css", "json": "json", "md": "markdown",
        "sh": "bash", "yml": "yaml", "yaml": "yaml", "sql": "sql", "ts": "typescript"}


# ----------------------------------------------------------------- helpers
def format_meta(meta: dict) -> str:
    parts = []
    if meta.get("stopped"):
        parts.append("⏹ zastavené")
    if meta.get("node"):
        parts.append(f"{meta['node']} · {meta['model']}")
    if meta.get("total_s"):
        parts.append(f"⏱ {meta['total_s']:.1f} s")
    if meta.get("think_s"):
        parts.append(f"🧠 {meta['think_s']:.1f} s premýšľanie")
    if meta.get("tools"):
        parts.append(f"🔧 {meta['tools']}× nástroj")
    if meta.get("completion_tokens"):
        parts.append(f"🔢 {meta.get('prompt_tokens') or '?'} → {meta['completion_tokens']} tokenov")
    if meta.get("tok_per_s"):
        parts.append(f"⚡ {meta['tok_per_s']} tok/s")
    if meta.get("web"):
        parts.append("🌐 web")
    return " · ".join(parts)


def _actions(m: dict, index: int, *, can_edit=False, can_regen=False) -> None:
    ss = st.session_state
    with st.container(key=f"actions_{m['id']}"):
        cols = st.columns([1, 1, 1, 10], gap="small")
        with cols[0]:
            with st.popover("📋", help="Kopírovať (klikni na ikonu v rohu kódu)"):
                st.code(m["content"], language="markdown", wrap_lines=True)
        if can_edit and cols[1].button("✏️", key=f"edit_{m['id']}",
                                       help="Upraviť a poslať znova (zmaže nasledujúce správy)"):
            ss.editing_id = m["id"]
            st.rerun()
        if can_regen and cols[1].button("🔄", key=f"regen_{m['id']}", help="Generovať znova"):
            ss.messages = ss.messages[:index]
            ss.generate = True
            state.persist()
            st.rerun()


def _render_flat(step: dict) -> None:
    kind = step.get("kind")
    if kind == "thinking":
        st.caption(step.get("title", "🧠 Myšlienkový proces"))
        st.markdown(step["text"])
    elif kind == "text":
        st.markdown(step["text"])
    elif kind == "stage":
        st.caption(step["title"])
        st.markdown(step["text"])
    elif kind == "tool":
        arg = step["args"].get("path") or step["args"].get("query") or ""
        st.markdown(f"**{'✅' if step.get('ok') else '⚠️'} 🔧 {step['name']} {arg}**".strip())
        if step.get("body"):
            st.code(step["body"], language=LANG.get(arg.rsplit(".", 1)[-1].lower()))
        st.code(step["text"], language="text")
        st.divider()


def _render_trace(trace: list[dict], meta: dict | None = None) -> None:
    if meta and meta.get("agent") and trace:                 # agent run: ONE expander instead of dozens of boxes
        tools = sum(1 for s in trace if s.get("kind") == "tool")
        label = f"🧰 Postup agenta · {tools}× nástroj" + (f" · 🧠 {meta['think_s']:.0f} s" if meta.get("think_s") else "")
        with st.expander(label):
            for step in trace:
                _render_flat(step)
        return
    for step in trace:
        kind = step.get("kind")
        if kind == "thinking":
            with st.expander(step.get("title", "🧠 Myšlienkový proces")):
                st.markdown(step["text"])
        elif kind == "text":
            st.markdown(step["text"])
        elif kind == "stage":
            with st.expander(step["title"]):
                st.markdown(step["text"])
        elif kind == "tool":
            arg = step["args"].get("path") or step["args"].get("query") or ""
            with st.expander(f"{'✅' if step.get('ok') else '⚠️'} 🔧 {step['name']} {arg}".strip()):
                if step.get("body"):
                    st.code(step["body"], language=LANG.get(arg.rsplit(".", 1)[-1].lower()))
                st.code(step["text"], language="text")


# ----------------------------------------------------------------- messages
def _render_user(index: int, m: dict) -> None:
    ss = st.session_state
    with st.chat_message("user"):
        if ss.editing_id == m["id"]:
            new_text = st.text_area("Upraviť správu", value=m["content"], key=f"edit_text_{m['id']}",
                                    label_visibility="collapsed")
            save_col, cancel_col, _ = st.columns([3, 1.4, 5])
            if save_col.button("💾 Uložiť a regenerovať", key=f"save_{m['id']}", type="primary"):
                m["content"] = new_text.strip() or m["content"]
                ss.messages = ss.messages[:index + 1]
                ss.editing_id, ss.generate = None, True
                state.persist()
                st.rerun()
            if cancel_col.button("Zrušiť", key=f"cancel_{m['id']}"):
                ss.editing_id = None
                st.rerun()
            return
        paths = [str(resolve_upload(p)) for p in m["images"] if resolve_upload(p).exists()]
        if paths:
            st.image(paths, width=220)
        st.markdown(m["content"])
        for a in m["attachments"]:
            with st.expander(f"📎 {a['name']}"):
                st.code(a["text"][:20000])
        _actions(m, index, can_edit=not ss.generate)


def _research_restart(index: int, r: dict, steps_text: str, extra: str) -> None:
    """✏️ Update / ▶ Spustiť výskum: the edited steps become the plan of a fresh run of the same question."""
    ss = st.session_state
    titles = [l.strip(" -•\t") for l in steps_text.splitlines() if l.strip(" -•\t")]
    old = {s["title"]: s["query"] for s in r.get("steps", []) if s.get("kind") != "final"}
    steps = [{"title": t, "query": old.get(t, t)} for t in titles][:RESEARCH_MAX_STEPS]
    if not steps:
        st.toast("Plán je prázdny – napíš aspoň jeden krok.", icon="⚠️")
        return
    ss.research_override = {"steps": steps, "title": r.get("title", ""), "extra": (extra or "").strip()}
    ss.messages = ss.messages[:index]
    ss.generate = True
    state.persist()
    st.rerun()


def _render_assistant(index: int, m: dict, is_last: bool) -> None:
    meta = m.get("meta", {})
    with st.chat_message("assistant"):
        if m.get("trace"):
            _render_trace(m["trace"], meta)
        elif m.get("thinking"):
            label = "🧠 Myšlienkový proces" + (f" · {meta['think_s']:.1f} s" if meta.get("think_s") else "")
            with st.expander(label):
                st.markdown(m["thinking"])
        if meta.get("research"):
            research_card.render(meta["research"], key=f"rc_{m['id']}", live=False,
                                 on_start=lambda steps, extra, i=index, r=meta["research"]: _research_restart(i, r, steps, extra))
        st.markdown(m["content"])
        if meta.get("web_sources"):
            with st.expander(f"🌐 Zdroje z webu ({len(meta['web_sources'])})"):
                for src in meta["web_sources"]:
                    st.markdown(f"- [{src['title'] or src['url']}]({src['url']})")
        if meta.get("error"):
            st.warning(meta["error"])
        if meta.get("plan"):
            done = sum(1 for x in meta["plan"] if x["done"])
            with st.expander(f"📋 Plán · {done}/{len(meta['plan'])} hotovo"):
                st.markdown("\n".join(f"- {'☑' if x['done'] else '☐'} {x['text']}" for x in meta["plan"]))
        files = meta.get("files") or meta.get("saved_files")       # (saved_files = chats from older v3 builds)
        if files:
            topic = next((x["content"] for x in reversed(st.session_state.messages[:index]) if x["role"] == "user"), "")
            delivery.render_files(files, m["id"], topic)
        if caption := format_meta(meta):
            st.caption(caption)
        _actions(m, index, can_regen=is_last and not st.session_state.generate)


# ----------------------------------------------------------------- screens
def render_header(settings: state.Settings) -> None:
    ss = st.session_state
    icon, name, desc = MODES[ss.chat_mode]
    c_title, c_export, c_clear = st.columns([8, 1, 1], vertical_alignment="center")
    c_title.markdown(f"**{icon} {name}**  <span class='muted'>· {state.chat_title()}</span>",
                     unsafe_allow_html=True)
    if ss.messages:
        c_export.download_button("⬇", chat_store.export_markdown(state.chat_title(), ss.messages),
                                 file_name=f"chat_{ss.chat_id}.md", mime="text/markdown",
                                 key="export_chat", help="Exportovať chat (.md)")
        with c_clear.popover("🧹", help="Vymazať chat"):
            st.write("Vymazať všetky správy v tomto chate?")
            if st.button("Áno, vymazať", type="primary", key="confirm_clear"):
                state.clear_chat()
                st.rerun()
    if ss.chat_mode == "agent":
        tools = [f"{s.icon} {s.name}" for s in skills.SKILLS.values()
                 if s.id in settings.enabled and s.tools]
        st.caption("Nástroje agenta: " + (" · ".join(tools) if tools else "žiadne – zapni ich cez ＋"))


def _welcome() -> None:
    mode = st.session_state.chat_mode
    icon, name, desc = MODES[mode]
    st.markdown(f'<div class="hero"><h1>{icon} {name}</h1><p>{desc}<br>'
                'Dole cez <b>＋</b> zapneš schopnosti, vyberieš počítač a hĺbku myslenia.</p></div>',
                unsafe_allow_html=True)
    with st.container(key="welcome"):
        cols = st.columns(2)
        for i, text in enumerate(SUGGESTIONS_AGENT if mode == "agent" else SUGGESTIONS_CHAT):
            if cols[i % 2].button(text, key=f"sugg_{i}"):
                st.session_state.pending_prompt = text
                st.rerun()


def render_history() -> None:
    ss = st.session_state
    msgs = ss.messages
    if not msgs and not ss.generate:
        _welcome()
        return
    for i, m in enumerate(msgs):
        if m["role"] == "user":
            _render_user(i, m)
        else:
            _render_assistant(i, m, is_last=(i == len(msgs) - 1))
    if msgs and msgs[-1]["role"] == "user" and not ss.generate and ss.editing_id is None:
        if st.button("↻ Skúsiť znova", key="retry_last"):      # e.g. after a connection error
            ss.generate = True
            st.rerun()


def render_scroll_helpers() -> None:
    """Anchor at the end of the chat + floating 'scroll to bottom' button."""
    st.markdown('<div id="chat-bottom"></div>'
                '<a class="scroll-bottom" href="#chat-bottom" title="Na koniec chatu">⬇</a>',
                unsafe_allow_html=True)
