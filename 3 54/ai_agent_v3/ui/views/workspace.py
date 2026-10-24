"""Workspace page (like Claude's Artifacts + Code): browse, edit, download, run and fix the files."""
import streamlit as st

from config import NODES, WORKSPACE_DIR
from core import workspace
from core.router import RoutingError, resolve_target

LANG = {"py": "python", "js": "javascript", "html": "html", "css": "css", "json": "json", "md": "markdown",
        "sh": "bash", "yml": "yaml", "yaml": "yaml", "sql": "sql", "ts": "typescript", "txt": None}


def render() -> None:
    ss = st.session_state
    ss.setdefault("ws_up_n", 0)
    st.markdown("## 📁 Workspace")
    st.caption(f"Sem ukladá agent súbory a odtiaľto ich môže čítať: `{WORKSPACE_DIR}`")

    with st.expander("⬆️ Nahrať súbory do workspace"):
        uploads = st.file_uploader("Súbory", accept_multiple_files=True, key=f"ws_up_{ss.ws_up_n}",
                                   label_visibility="collapsed")
        if uploads and st.button("Nahrať", key="ws_upload_go"):
            for f in uploads:
                try:
                    workspace.write_text(f.name, f.getvalue().decode("utf-8"))
                except (UnicodeDecodeError, workspace.WorkspaceError) as e:
                    st.warning(f"{f.name}: {e}")
            ss.ws_up_n += 1
            st.rerun()

    files = workspace.list_tree()
    if not files:
        st.info("Workspace je zatiaľ prázdny. Požiadaj agenta, aby niečo vytvoril, alebo súbory nahraj vyššie.")
        return

    # ---- quick access: everything at once / selection / open on this PC
    c_all, c_open, _ = st.columns([3, 3, 4])
    c_all.download_button(f"📦 Všetko ako ZIP ({len(files)})", workspace.make_zip(), use_container_width=True,
                          file_name=workspace.zip_name(files), mime="application/zip", key="ws_zip_all")
    if c_open.button("📂 Otvoriť priečinok na PC", use_container_width=True, key="ws_open_dir"):
        try:
            workspace.open_in_explorer()
            st.toast("Otvorené v správcovi súborov", icon="📂")
        except workspace.WorkspaceError as e:
            st.warning(str(e))
    with st.expander("📦 ZIP z vybraných súborov"):
        picked = st.multiselect("Vyber súbory", files, key="ws_zip_pick")
        if picked:
            st.download_button(f"⬇ Stiahnuť {len(picked)} súborov ako ZIP", workspace.make_zip(picked),
                               file_name=workspace.zip_name(picked), mime="application/zip", key="ws_zip_sel")
    sel = st.selectbox("Súbor", files, key="ws_sel")
    path = workspace.safe_path(sel)
    ext = sel.rsplit(".", 1)[-1].lower()
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        st.warning("Binárny súbor – náhľad nie je k dispozícii.")
        st.download_button("⬇ Stiahnuť", path.read_bytes(), file_name=path.name, key="ws_dl_bin")
        return

    c_dl, c_edit, c_ren, c_del, _ = st.columns([1.4, 1.2, 1.2, 1.2, 5])
    c_dl.download_button("⬇ Stiahnuť", text, file_name=path.name, key="ws_dl")
    editing = c_edit.toggle("✏️ Upraviť", key=f"ws_edit_{sel}")
    with c_ren.popover("🏷️", help="Premenovať"):
        new_name = st.text_input("Nový názov", value=sel, key=f"ws_ren_{sel}")
        if st.button("Premenovať", key="ws_ren_go"):
            try:
                workspace.rename_file(sel, new_name)
                st.rerun()
            except workspace.WorkspaceError as e:
                st.error(str(e))
    with c_del.popover("🗑️"):
        st.write(f"Zmazať `{sel}`? (záloha zostane v .history)")
        if st.button("Áno, zmazať", type="primary", key="ws_del"):
            workspace.delete_file(sel)
            st.rerun()

    if editing:
        new = st.text_area("Obsah", value=text, height=420, key=f"ws_text_{sel}", label_visibility="collapsed")
        if st.button("💾 Uložiť", type="primary", key="ws_save"):
            workspace.write_text(sel, new)
            st.toast("Uložené", icon="💾")
            st.rerun()
    else:
        st.code(text, language=LANG.get(ext), line_numbers=True)

    if ext == "py":
        st.divider()
        st.markdown("#### ▶ Spustenie a ladenie")
        stdin = st.text_area("Vstupy (stdin)", placeholder="1\n5\n10", height=80, key="ws_stdin")
        c_run, c_fix, _ = st.columns([1.3, 1.6, 6])
        if c_run.button("▶ Spustiť", key="ws_run"):
            with st.spinner(f"Spúšťam {sel}…"):
                ss.script_output = ("Výsledok", workspace.run_script(sel, stdin))
        if c_fix.button("🤖 Auto-oprava", key="ws_heal"):
            try:
                target = resolve_target(ss.get("node_choice", next(iter(NODES))))
            except RoutingError as e:
                st.error(str(e))
            else:
                with st.spinner(f"Opravujem na {target.node}…"):
                    ss.script_output = ("Priebeh ladenia", workspace.self_heal(sel, stdin, target.url, target.model))
        if ss.script_output:
            title, out = ss.script_output
            st.markdown(f"**{title}:**")
            st.code(out, language="text")
