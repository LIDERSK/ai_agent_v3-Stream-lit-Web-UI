"""Left sidebar (like Claude's): new chat (normal / agent), navigation, chat list, PC status."""
import gc
import time

import streamlit as st
import streamlit.components.v1 as components

from config import VERSION, MODES, NODES
from core import chat_store
from config import GPU_WARN_BELOW
from core import models
from core.ollama_client import benchmark, check_node, clear_caches, loaded_models, model_installed, unload_all
from core.power import exit_app_soon, is_local, start_ollama_local, stop_ollama_local
from ui import state


def render_sidebar() -> None:
    ss = st.session_state
    with st.sidebar:
        st.markdown("### 🤖 Lokálny AI Agent")
        st.caption(f"verzia **{VERSION}**")

        with st.popover("➕ Nový chat"):
            for mode, (icon, name, desc) in MODES.items():
                if st.button(f"{icon} {name}", key=f"new_{mode}"):
                    state.new_chat(mode)
                    st.rerun()
                st.caption(desc)

        for page, label in (("chat", "💬 Chat"), ("workspace", "📁 Workspace"), ("skills", "🧩 Prispôsobiť")):
            if st.button(label, key=f"nav_{page}", type="primary" if ss.page == page else "secondary"):
                ss.page = page
                st.rerun()

        st.divider()
        st.caption("CHATY A ÚLOHY")
        query = st.text_input("Hľadať", placeholder="🔎 Hľadať v chatoch", key="chat_search",
                              label_visibility="collapsed")
        _chat_list(query)

        st.divider()
        _status_footer()


def _chat_list(query: str) -> None:
    chats = chat_store.list_chats()
    if query.strip():
        chats = [c for c in chats if query.strip().lower() in c["title"].lower()]
    if not chats:
        st.caption("Zatiaľ žiadne uložené chaty.")
        return
    for c in chats[:60]:
        current = c["id"] == st.session_state.chat_id and st.session_state.page == "chat"
        col_a, col_b = st.columns([5, 1], vertical_alignment="center")
        icon = MODES.get(c["mode"], MODES["chat"])[0]
        label = f"{'● ' if current else ''}{icon} {c['title'][:24]}"
        if col_a.button(label, key=f"sel_{c['id']}", type="primary" if current else "secondary"):
            state.open_chat(c["id"])
            st.rerun()
        if col_b.button("🗑️", key=f"del_{c['id']}", help="Zmazať chat"):
            state.delete_chat(c["id"])
            st.rerun()


def _stop_models() -> list[str]:
    """Unload every model; stop Ollama on this PC. Returns short notes for a toast."""
    notes = []
    for n in NODES.values():
        if not check_node(n.url)[0]:
            continue
        freed = unload_all(n.url)
        if is_local(n.url):
            notes.append(f"{n.name}: {stop_ollama_local()}")
        else:
            notes.append(f"{n.name}: vyložených modelov {freed} (cudzí PC sa vypnúť nedá)")
    clear_caches()
    return notes


def _start_ollama(nodes) -> None:
    """Start once, then wait (without redrawing) until it answers."""
    if not start_ollama_local():
        st.toast("Príkaz `ollama` som nenašiel (je v PATH?).", icon="⚠️")
        return
    with st.spinner("Spúšťam Ollamu…"):
        for _ in range(30):
            clear_caches()
            if any(check_node(n.url)[0] for n in nodes):
                break
            time.sleep(0.5)
    st.rerun()


CLOSE_TAB_JS = """<script>
var p = window.parent;
try {
  p.document.title = "AI Agent – vypnuté";
  p.document.body.innerHTML = '<div style="font-family:sans-serif;text-align:center;margin-top:20vh;color:#ddd">' +
    '<h2>⏻ Vypnuté</h2><p>Modely sú vyložené, Ollama aj agent sú zastavené a pamäť je uvoľnená.<br>' +
    'Túto kartu môžeš zavrieť.</p></div>';
  p.document.body.style.background = "#0e1117";
} catch (e) {}
try { p.open('', '_self'); p.close(); } catch (e) {}
</script>"""


def shutdown_everything() -> None:
    """Models out of memory -> Ollama stopped -> caches cleared -> tab closed -> this program ends."""
    notes = _stop_models()
    try:
        st.cache_data.clear()
        st.cache_resource.clear()
    except Exception:
        pass
    gc.collect()
    st.success("⏻ Vypínam… " + " · ".join(notes))
    components.html(CLOSE_TAB_JS, height=0)
    exit_app_soon(3.0)                                        # after the page had time to draw / close itself
    st.stop()


def _status_footer() -> None:
    slow = False
    for n in NODES.values():
        online, installed = check_node(n.url)
        active = models.get_model(n.name) if online else None
        dot = "🔴" if not online else ("🟢" if active else "🟡")
        st.caption(f"{dot} {n.name} · {(active or 'žiadny model') if online else 'nedostupný'}")
        for m in loaded_models(n.url) if online else ():          # what is really in memory, and where
            pct = m["gpu_pct"]
            bad = pct is not None and pct < GPU_WARN_BELOW
            slow = slow or bad
            where = f"{pct} % na GPU" if pct is not None else "?"
            st.caption(f"　↳ {'⚠️ ' if bad else ''}{m['name']} · {m['size'] / 1e9:.1f} GB · {where}")
    offline = [n for n in NODES.values() if is_local(n.url) and not check_node(n.url)[0]]
    if offline:                                              # ONE button, however many local nodes there are
        if st.button("▶ Spustiť Ollamu", key="start_ollama", use_container_width=True,
                     help="Spustí `ollama serve` na tomto PC, skryte (modely sa načítajú pri prvej správe)."):
            _start_ollama(offline)
    if slow:
        st.warning("Časť modelu beží na CPU/RAM, preto je odpoveď pomalá a berie veľa RAM. Skús „Uvoľniť pamäť“ "
                   "(iný model alebo väčšie okno mohli zabrať VRAM).", icon="🐢")
    c1, c2 = st.columns(2)
    if c1.button("🔄 Skontrolovať", key="recheck", use_container_width=True):
        clear_caches()
        st.rerun()
    if c2.button("🧹 Uvoľniť pamäť", key="unload_all", use_container_width=True,
                 help="Vyloží všetky modely z pamäte na oboch PC; pri ďalšej správe sa načítajú znova a čisto."):
        total = sum(unload_all(n.url) for n in NODES.values())
        clear_caches()
        st.toast(f"Uvoľnených modelov: {total}", icon="🧹")
        st.rerun()
    with st.popover("🔌 Vypnúť", use_container_width=True,
                    help="Vypnúť model / Ollamu, alebo všetko naraz (webové rozhranie, agent aj Ollama)."):
        st.markdown("**🔌 Len model a Ollama**")
        st.caption("Vyloží modely a na **tomto PC** ukončí Ollamu a jej procesy (`ollama`, `llama-server`) – uvoľní "
                   "VRAM aj RAM. Webové rozhranie ostane otvorené; Ollamu zapneš tlačidlom „▶ Spustiť Ollamu“. "
                   "Na druhom PC sa dajú len vyložiť modely.")
        if st.button("Vypnúť model a Ollamu", key="power_off", use_container_width=True):
            st.toast(" · ".join(_stop_models()) or "Nič nebežalo.", icon="🔌")
            time.sleep(1.5)
            st.rerun()
        st.divider()
        st.markdown("**⏻ Vypnúť úplne všetko**")
        st.caption("Vyloží modely, zastaví Ollamu, vyčistí pamäť, **zavrie toto webové rozhranie a zastaví aj agenta** "
                   "(celý program). Znova ho zapneš ikonou / `start_agent_hidden.vbs`. Prehliadač nemusí dovoliť zavrieť "
                   "kartu sám – vtedy ju zavri ručne.")
        if st.button("Áno, vypnúť všetko", type="primary", key="power_all", use_container_width=True):
            st.session_state.shutting_down = True                 # done in the MAIN area (app.py), not inside a popover
            st.rerun()
    with st.expander("🧪 Test rýchlosti"):
        st.caption("Pošle krátky prompt s rôznymi nastaveniami a ukáže, čo spomaľuje model. Trvá 1 – 2 minúty.")
        pick = st.selectbox("PC", list(NODES), key="bench_node", label_visibility="collapsed")
        if st.button("▶ Spustiť test", key="bench_go", use_container_width=True):
            node = NODES[pick]
            model = models.get_model(pick)
            if not model:
                st.warning("Na tomto PC nie je dostupný žiadny model.")
            else:
                with st.spinner(f"Testujem {node.name} ({model})…"):
                    st.session_state.bench = (pick, benchmark(node.url, model))
        if st.session_state.get("bench"):
            who, rows = st.session_state.bench
            st.markdown(f"**{who}**")
            for r in rows:
                if r.get("error"):
                    st.caption(f"❌ {r['label']}: {r['error']}")
                else:
                    gpu = f"{r['gpu_pct']} % GPU" if r.get("gpu_pct") is not None else "GPU ?"
                    st.caption(f"{r['label']}  →  **{r['tok_s'] or '?'} tok/s** · {gpu}")
