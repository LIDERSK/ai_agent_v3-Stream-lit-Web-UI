"""Customize page (like Claude's): skills & permissions, custom instructions, connections."""
import streamlit as st

from config import NODES, WORKSPACE_DIR
from core import models, settings_store, skills
from core.ollama_client import check_node, clear_caches
from ui.skill_widgets import force_web_checkbox, skill_checkbox


def render() -> None:
    st.markdown("## 🧩 Prispôsobiť")
    tab_skills, tab_packs, tab_instr, tab_conn = st.tabs(
        ["Schopnosti (Skills)", "🧰 Balíky skillov", "Vlastné inštrukcie", "Zariadenia a modely"])

    with tab_skills:
        st.caption(f"Súborové povolenia platia len pre priečinok `{WORKSPACE_DIR.name}/` – agent nevidí zvyšok disku. "
                   "Zapnuté skills sa dajú rýchlo prepínať aj cez ＋ v chate.")
        for s in skills.SKILLS.values():
            with st.container(key=f"skillcard_{s.id}"):
                skill_checkbox(s, "page")
                st.caption(s.description)
                if s.warning:
                    st.warning(s.warning)
                if s.tools:
                    st.caption("Nástroje agenta: " + ", ".join(f"`{t.name}`" for t in s.tools))
        force_web_checkbox("page")
        with st.expander("🧪 Sandbox – čo je na tomto PC dostupné"):
            from core import sandbox
            for lang, i in sandbox.toolchains().items():
                st.markdown(f"{'✅' if i['ok'] else '❌'} **{lang}**" + (f" – `{i['path']}`" if i["ok"] else f" – {i['hint']}"))
        with st.expander("➕ Ako pridať vlastný skill"):
            st.markdown(
                "Vytvor súbor `core/skills/moj_skill.py`:\n```python\n"
                "from core.skills import Skill, Tool\n\n"
                "def _hello(args, body, ctx):\n    return f\"Ahoj {args.get('meno', 'svet')}!\"\n\n"
                "SKILL = Skill(id='hello', icon='👋', name='Pozdrav', short='Ukážkový skill',\n"
                "              description='Vráti pozdrav.',\n"
                "              tools=(Tool('hello', 'meno=\"Jano\"', '<tool name=\"hello\" meno=\"Jano\"/>', _hello),))\n"
                "```\nPo reštarte sa objaví tu aj v ＋ menu a agent ho vie používať. Nástroj sa automaticky preloží do \n"
                "natívneho volania modelu (parametre sa odvodia z popisu; presnejšie: `params=(Param('meno', 'popis'),)`).")

    with tab_packs:
        from ui.views import skillpacks as packs_view
        packs_view.render()

    with tab_instr:
        st.caption("Platí pre všetky chaty (normálne aj agent). Napr. „Odpovedaj stručne“ alebo „Kód píš s komentármi“.")
        text = st.text_area("Inštrukcie", value=settings_store.get("custom_instructions", ""), height=200,
                            key="custom_ta", label_visibility="collapsed")
        if st.button("💾 Uložiť inštrukcie", type="primary", key="custom_save"):
            settings_store.put("custom_instructions", text.strip())
            st.toast("Uložené", icon="💾")

    with tab_conn:
        _devices_tab()


def _pick(node: str, kind: str, label: str) -> None:
    ss = st.session_state
    options = [models.AUTO, *models.choices(node, kind)]
    key = f"cfg_{kind}_{node}"
    cur = models.AUTO if models.is_auto(node, kind) else models.get_model(node, kind)
    ss[key] = cur if cur in options else models.AUTO
    st.selectbox(label, options, key=key,
                 format_func=lambda v: (f"🔎 Automaticky · {models.get_model(node, kind) or 'nič'}"
                                        if v == models.AUTO else f"{v} {models.badges(node, v)}".strip()),
                 on_change=lambda n=node, k=kind, kk=key: models.set_model(n, k, st.session_state.get(kk)))


def _devices_tab() -> None:
    st.caption("Modely sa na každom PC **zisťujú automaticky** z Ollamy – stiahni nový (`ollama pull …`), "
               "stlač „Znova vyhľadať“ a objaví sa v zozname. „Automaticky“ vyberie najlepší nainštalovaný model.")
    if st.button("🔄 Znova vyhľadať modely", key="conn_recheck"):
        clear_caches()
        st.rerun()
    for n in NODES.values():
        online, _ = check_node(n.url)
        with st.container(border=True, key=f"dev_{n.name}"):
            st.markdown(f"**{'🟢' if online else '🔴'} {n.name}** · `{n.url}`")
            if not online:
                st.caption("Nedostupný – beží tam Ollama s OLLAMA_HOST=0.0.0.0 a povoleným portom 11434?")
                continue
            names = models.installed(n.name)
            if not names:
                st.caption("Nie je nainštalovaný žiadny model. Skús `ollama pull qwen2.5-coder:7b`.")
                continue
            c1, c2 = st.columns(2)
            with c1:
                _pick(n.name, "text", "Textový / kódovací model")
            with c2:
                _pick(n.name, "vision", "Model pre obrázky (👁)")
            active = models.get_model(n.name)
            if active and (models.size_gb(n.name, active) or 0) >= 12:
                st.caption("ℹ️ Veľký model – na 16 GB VRAM sa okno kontextu môže samo zmenšiť.")
            with st.expander(f"Nájdené modely ({len(names)})"):
                for name in names:
                    gb = models.size_gb(n.name, name)
                    st.caption(f"• `{name}` {models.badges(n.name, name)} · {gb} GB" if gb else f"• `{name}`")
    if len(NODES) > 1:
        st.markdown("**🤝 Klaster – kto čo robí**")
        from ui import cluster_team
        cluster_team.render("page")
