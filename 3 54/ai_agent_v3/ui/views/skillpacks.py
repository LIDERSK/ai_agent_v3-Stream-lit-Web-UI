"""Customize -> "Balíky skillov": drag & drop import (ZIP, SKILL.md, .mdc, link, pasted text) + list of installed packs."""
import streamlit as st

from core import skillpacks

IMPORT_TYPES = ["zip", "skill", "md", "mdc", "txt", "markdown"]


def _show_results(results: list) -> None:
    for r in results:
        st.success(f"✅ {'Aktualizovaný' if r.replaced else 'Nainštalovaný'} balík **{r.name}** (`{r.pack_id}`)")
        for n in r.notes:
            st.caption(f"↪ {n}")
        for w in r.warnings:
            st.warning(w)
        if r.warnings:
            st.caption("Balík je kvôli upozorneniam VYPNUTÝ – skontroluj ho nižšie a zapni ho, ak mu dôveruješ.")


def _import_files(files) -> None:
    results, errors = [], []
    for f in files:
        try:
            results += skillpacks.import_file(f.name, f.getvalue())
        except skillpacks.PackError as e:
            errors.append(f"{f.name}: {e}")
    st.session_state.pack_report = {"ok": results, "err": errors}


def _import_url(url: str) -> None:
    try:
        results, errors = skillpacks.import_url(url), []
    except skillpacks.PackError as e:
        results, errors = [], [f"{url}: {e}"]
    st.session_state.pack_report = {"ok": results, "err": errors}


def _import_text(text: str) -> None:
    try:
        results, errors = [skillpacks.import_text(text)], []
    except skillpacks.PackError as e:
        results, errors = [], [str(e)]
    st.session_state.pack_report = {"ok": results, "err": errors}


def _pack_card(p: skillpacks.Pack) -> None:
    enabled = skillpacks.is_enabled(p.id, p.meta.get("default_enabled", True))
    with st.container(border=True, key=f"pack_{p.id}"):
        top, act = st.columns([6, 1.4], vertical_alignment="center")
        with top:
            new = st.checkbox(f"🧰 **{p.name}**  :gray[`{p.id}` · {'vstavaný' if p.source == 'builtin' else 'importovaný'}]",
                              value=enabled, key=f"packcb_{p.id}_{int(enabled)}")
            if new != enabled:
                skillpacks.set_enabled(p.id, new)
                st.rerun()
        with act:
            st.download_button("⬇ ZIP", skillpacks.export_zip(p.id), file_name=f"{p.id}.zip", mime="application/zip",
                               key=f"packdl_{p.id}", help="Balík v štandardnom formáte (SKILL.md) – použiteľný aj v iných nástrojoch.")
        st.caption(p.description)
        meta_bits = []
        if p.meta.get("format") and p.source != "builtin":
            meta_bits.append(f"formát: {p.meta['format']}")
        if p.meta.get("origin") and p.source != "builtin":
            meta_bits.append(f"zdroj: {p.meta['origin']}")
        if p.files:
            meta_bits.append(f"súbory: {len(p.files)}")
        if meta_bits:
            st.caption(" · ".join(meta_bits))
        for n in p.meta.get("notes", []):
            st.caption(f"↪ {n}")
        for w in p.warnings:
            st.warning(w)
        with st.expander("Zobraziť postup (SKILL.md)"):
            st.markdown(skillpacks.render_for_agent(p)[:6000])
            if p.files:
                st.caption("Priložené súbory: " + ", ".join(f"`{f}`" for f in p.files[:30]))
        if p.source != "builtin" and st.button("🗑 Odstrániť", key=f"packdel_{p.id}"):
            skillpacks.remove_pack(p.id)
            st.rerun()


def render() -> None:
    st.caption("Balík skillov = priečinok so súborom `SKILL.md` (názov, popis, postup) a voliteľnými skriptmi či podkladmi. "
               "Je to bežný formát, ktorý používajú aj komerční AI asistenti – balíky z internetu sa preložia na tento formát. "
               "Agent vidí len názvy a popisy a celý postup si načíta, keď ho úloha potrebuje.")
    files = st.file_uploader("📥 Pretiahni sem ZIP, SKILL.md, .skill alebo .mdc (aj viac naraz)", type=IMPORT_TYPES,
                             accept_multiple_files=True, key=f"pack_upl_{st.session_state.get('pack_upl_n', 0)}")
    if files:
        _import_files(files)
        st.session_state.pack_upl_n = st.session_state.get("pack_upl_n", 0) + 1     # clears the drop zone
        st.rerun()
    with st.expander("🔗 Importovať z odkazu alebo vloženého textu"):
        c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
        url = c1.text_input("Odkaz (GitHub repozitár / súbor SKILL.md / ZIP)", key="pack_url",
                            placeholder="https://github.com/…/skills  alebo  …/SKILL.md")
        if c2.button("Stiahnuť", key="pack_url_go", disabled=not url.strip()):
            with st.spinner("Sťahujem…"):
                _import_url(url)
            st.rerun()
        text = st.text_area("…alebo vlož celý text skillu (aj s hlavičkou ---)", key="pack_text", height=140)
        if st.button("Pridať z textu", key="pack_text_go", disabled=not text.strip()):
            _import_text(text)
            st.rerun()
    report = st.session_state.pop("pack_report", None)
    if report:
        _show_results(report["ok"])
        for e in report["err"]:
            st.error(e)
    st.divider()
    packs = skillpacks.list_packs()
    if not packs:
        st.info("Zatiaľ žiadne balíky. Pretiahni sem prvý.")
    for p in packs:
        _pack_card(p)
    st.caption("⚠️ Balík z internetu je cudzí text, ktorým sa agent riadi. Importuj len zdroje, ktorým dôveruješ. "
               "Python súbory (`.py`) sa neinštalujú automaticky.")
