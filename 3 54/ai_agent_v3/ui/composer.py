"""The composer: a bar pinned above the chat input with
   [＋ menu]  [PC dropdown]  [thinking depth]  [active chips]
and the chat input itself. Everything is reachable without scrolling and can be changed before EVERY message.
"""
import streamlit as st

from config import BINARY_TYPES, COMPOSER_MENU, IMAGE_TYPES, NODES, TEXT_TYPES, THINKING_TIERS
from core import chat_store, intake, models, settings_store, skillpacks, skills
from core.media import prepare_image
from core.ollama_client import check_node
from core.thinking import GPTOSS_TIERS, is_gptoss, tier_for_model
from ui import state
from ui.skill_widgets import force_web_checkbox, skill_checkbox

TIER_HELP = "**Hĺbka myslenia** (platí pre ďalšiu správu)\n\n" + "\n".join(
    f"- {t.icon} **{k}** – {t.help}" for k, t in THINKING_TIERS.items())


def _bottom():
    """Streamlit's bottom container (where chat_input lives); falls back to a CSS-pinned container."""
    bottom = getattr(st, "_bottom", None)
    return bottom if bottom is not None else st.container(key="composer_bar")


def _node_label(name: str) -> str:
    node = NODES[name]
    online, installed = check_node(node.url)
    dot = "🔴" if not online else ("🟢" if models.get_model(name) else "🟡")
    return f"{dot} {name}"


def _model_label(node_name: str, value: str) -> str:
    if value == models.AUTO:
        return f"🔎 Auto · {models.get_model(node_name) or 'nič'}"
    return f"{value} {models.badges(node_name, value)}".strip()


def _save_model_pick(node_name: str) -> None:
    models.set_model(node_name, "text", st.session_state.get(f"modelpick_{node_name}"))


def _model_picker(node_name: str) -> None:
    """Model of the chosen PC, detected live from Ollama. Takes effect with the next message."""
    ss = st.session_state
    key = f"modelpick_{node_name}"
    names = models.choices(node_name, "text")
    if not names:
        st.selectbox("Model", ["— žiadny model —"], key=f"{key}_none", disabled=True,
                     label_visibility="collapsed", help="Na tomto PC som nenašiel žiadny model (ollama pull …).")
        return
    options = [models.AUTO, *names]
    ss[key] = models.AUTO if models.is_auto(node_name) else (models.get_model(node_name) or models.AUTO)
    if ss[key] not in options:
        ss[key] = models.AUTO
    st.selectbox("Model", options, key=key, format_func=lambda v: _model_label(node_name, v),
                 label_visibility="collapsed", on_change=_save_model_pick, args=(node_name,),
                 help="Model na vybranom počítači (🧠 myslenie, 👁 obrázky, 🔧 nástroje). Nájdené modely sa "
                      "zisťujú automaticky; „Auto“ vyberie najlepší nainštalovaný.")


GPTOSS_HELP = ("**gpt-oss – úsilie premýšľania** (platí pre ďalšiu správu)\n\n"
               "Tento model sa nedá úplne vypnúť, dá sa len nastaviť, koľko premýšľa:\n\n"
               "- 💡 **Low** – rýchle, krátke uvažovanie\n- 🧠 **Medium** – vyvážené\n"
               "- 🔬 **High** – dôkladné, ale pomalšie\n\nHodnota ide priamo do modelu (agent, klaster aj výskum ju používajú).")


def _tier_label(key: str) -> str:
    """Selected pill shows icon + name, the others only the icon (keeps the bar compact)."""
    icon = THINKING_TIERS[key].icon
    return f"{icon} {key}" if st.session_state.get("tier_choice") == key else icon


def _gptoss_label(key: str) -> str:
    return f"{THINKING_TIERS[key].icon} {GPTOSS_TIERS[key]}"


# ----------------------------------------------------------------- ＋ menu
def _menu_body() -> list:
    ss = st.session_state
    enabled = skills.enabled_ids()
    types = TEXT_TYPES + BINARY_TYPES + (IMAGE_TYPES if "vision" in enabled else [])
    files = st.file_uploader("📎 Pridať fotky a súbory", accept_multiple_files=True, type=types,
                             key=f"uploader_{ss.uploader_n}")
    if "vision" not in enabled:
        st.caption("👁 Obrázky sú vypnuté – zapni „Rozpoznávanie obrázkov“.")
    st.divider()
    st.caption("SCHOPNOSTI")
    for s in skills.SKILLS.values():
        if not s.mode:
            skill_checkbox(s, "menu")
    st.caption("REŽIMY")
    for s in skills.SKILLS.values():
        if s.mode:
            skill_checkbox(s, "menu")
    force_web_checkbox("menu")
    if "skillpacks" in enabled:
        packs = skillpacks.list_packs()
        if packs:
            st.caption("BALÍKY SKILLOV")
            for p in packs:
                on = skillpacks.is_enabled(p.id, p.meta.get("default_enabled", True))
                new = st.checkbox(f"🧰 {p.name}", value=on, key=f"menu_pack_{p.id}_{int(on)}", help=p.description)
                if new != on:
                    skillpacks.set_enabled(p.id, new)
                    st.rerun()
    st.divider()
    st.slider("🌡️ Kreativita (teplota)", min_value=0.0, max_value=1.0, step=0.05,
              key="temperature", on_change=state.save_prefs)
    return files or []


def _plus_menu() -> list:
    if COMPOSER_MENU == "panel":
        with st.expander("＋ Nástroje"):
            return _menu_body()
    with st.popover("＋", help="Prílohy, schopnosti a režimy"):
        return _menu_body()


# ----------------------------------------------------------------- chips
def _chips(files: list) -> None:
    ss = st.session_state
    chips = []
    if skills.is_enabled("research"):
        chips.append(("research", "🔬 Research", "Vypnúť Deep Research"))
    if skills.is_enabled("cluster"):
        chips.append(("cluster", "🤝 Klaster", "Vypnúť klastrovú spoluprácu"))
    if settings_store.get("force_web", False):
        chips.append(("web", "🌐 Web", "Vypnúť „vždy hľadať na webe“"))
    if files:
        chips.append(("files", f"📎 {len(files)}", "Odstrániť prílohy"))
    if not chips:
        return
    for col, (kind, label, tip) in zip(st.columns(len(chips), gap="small"), chips):
        if col.button(f"{label} ✕", key=f"chip_{kind}", help=tip):
            if kind == "research":
                skills.set_enabled("research", False)
            elif kind == "cluster":
                skills.set_enabled("cluster", False)
            elif kind == "web":
                settings_store.put("force_web", False)
            else:
                ss.uploader_n += 1
            st.rerun()


# ----------------------------------------------------------------- bar + input
def render_bar() -> state.Settings:
    ss = st.session_state
    with _bottom():
        if skills.is_enabled("research"):
            from ui import research_options
            with st.popover(f"🔬 Deep Research: {research_options.summary()}", use_container_width=True,
                            help="Počet krokov, čítanie stránok a schvaľovanie plánu pred štartom."):
                research_options.render()
        if skills.is_enabled("cluster"):
            from ui import cluster_team
            with st.popover(f"🤝 Tím klastra: {cluster_team.summary()}", use_container_width=True,
                            help="Vyber, ktorý počítač a model robí architekta, programátora a recenzenta."):
                cluster_team.render("chat")
        with st.container(key="composer_tools"):
            c_plus, c_node, c_model, c_tier, c_chips = st.columns([0.6, 1.9, 2.5, 3.9, 1.9],
                                                                  vertical_alignment="center")
            with c_plus:
                files = _plus_menu()
            ss._staged = files
            with c_node:
                st.selectbox("Počítač", list(NODES), key="node_choice", format_func=_node_label,
                             label_visibility="collapsed", on_change=state.save_prefs,
                             help="Ktorý počítač odpovie:\n\n" + "\n".join(
                                 f"- **{n.name}**: `{models.get_model(n.name) or '—'}`" for n in NODES.values()))
            with c_model:
                _model_picker(ss.node_choice)
            with c_tier:
                gpt = is_gptoss(models.get_model(ss.node_choice))
                if ss.get("tier_choice") in THINKING_TIERS:       # gpt-oss has no "Vypnuté": it starts at Low
                    ss.tier_choice = tier_for_model(ss.tier_choice, models.get_model(ss.node_choice))
                st.segmented_control("Hĺbka myslenia", list(GPTOSS_TIERS) if gpt else list(THINKING_TIERS),
                                     key="tier_choice", format_func=_gptoss_label if gpt else _tier_label,
                                     label_visibility="collapsed", on_change=state.save_prefs,
                                     help=GPTOSS_HELP if gpt else TIER_HELP)
            with c_chips:
                _chips(files)
    return state.current_settings()


def _binary_attachment(f) -> dict | None:
    """ZIP / PDF / Office upload: stored in workspace/nahrate/ and described in the prompt (a ZIP also gets a preview)."""
    from core import documents, workspace, zipwork
    data = f.getvalue()
    try:
        rel = workspace.save_upload(f.name, data)
    except workspace.WorkspaceError as e:
        st.toast(f"{f.name}: {e}", icon="⚠️")
        return None
    ext = f.name.rsplit(".", 1)[-1].lower()
    if ext == "zip":
        body = zipwork.preview(rel, data)
        tip = f"[Uložené ako workspace/{rel}. Agent ho otvorí cez zip_list / zip_read / zip_extract.]"
    else:
        try:
            body = documents.read_document_bytes(f.name, data)[:12000]
        except zipwork.ZipProblem as e:
            body = f"(text sa nepodarilo prečítať: {e})"
        tip = f"[Uložené ako workspace/{rel}. Agent ho prečíta cez read_document.]"
    return {"name": f.name, "text": f"{tip}\n{body}", "path": rel}


def _chat_input(placeholder: str):
    """Chat input that also takes files dropped straight onto it (no ＋ needed).
    Older Streamlit without `accept_file` falls back to a text-only input (files still work via ＋)."""
    try:
        return st.chat_input(placeholder, key="chat_input", accept_file="multiple", file_type=intake.ALL_TYPES)
    except TypeError:
        return st.chat_input(placeholder, key="chat_input")


def _attachments(files: list, settings: state.Settings) -> tuple[list, list]:
    """Uploaded / dropped files -> (saved image names, text attachments)."""
    ss = st.session_state
    images, attachments = [], []
    for f in files:
        kind = intake.kind_of(f.name)
        if kind == "image":
            if "vision" not in settings.enabled:
                st.toast("Obrázok vynechaný – rozpoznávanie obrázkov je vypnuté.", icon="👁")
                continue
            images.append(chat_store.save_upload(ss.chat_id, prepare_image(f.getvalue())))
        elif kind == "binary":
            note = _binary_attachment(f)
            if note:
                attachments.append(note)
        else:
            try:
                attachments.append({"name": f.name, "text": f.getvalue().decode("utf-8")})
            except UnicodeDecodeError:
                st.toast(f"Súbor {f.name} nie je textový (UTF-8).", icon="⚠️")
    return images, attachments


def handle_input(settings: state.Settings) -> None:
    ss = st.session_state
    pending = ss.pop("pending_prompt", None)               # set by the suggestion buttons
    placeholder = ("Zadaj agentovi úlohu… (súbory môžeš pretiahnuť sem)" if ss.chat_mode == "agent"
                   else "Napíš správu… (súbory a obrázky môžeš pretiahnuť sem)")
    typed, dropped = intake.split_value(_chat_input(placeholder))
    files = intake.dedupe([*(ss.get("_staged") or []), *dropped])      # ＋ menu attachments + drag & drop
    text = (pending or typed or "").strip()
    if not text and files:
        text = intake.default_prompt(files)                  # a file dropped without any text
    if not text:
        return

    images, attachments = _attachments(files, settings)
    state.add_message("user", text, images=images, attachments=attachments)
    ss.generate = True
    ss.uploader_n += 1                                      # clears the attachment list
    ss._staged = []
