"""All CSS lives here. Change the look of the whole app by editing this file."""
import streamlit as st

CSS = """
<style>
:root { --accent:#7c9cff; --border:rgba(255,255,255,.09); --muted:rgba(230,232,238,.55); --radius:14px; }

/* hide Streamlit chrome */
#MainMenu, footer, .stDeployButton, [data-testid="stDecoration"] { display:none !important; }
header[data-testid="stHeader"] { background:transparent; }

/* layout */
.block-container { max-width:960px; padding-top:3rem; padding-bottom:2rem; }
[data-testid="stSidebar"] { border-right:1px solid var(--border); }
[data-testid="stSidebar"] .stButton > button,
[data-testid="stSidebar"] .stDownloadButton > button { width:100%; justify-content:flex-start; text-align:left; }
[data-testid="stSidebar"] [data-testid="stPopover"], [data-testid="stSidebar"] [data-testid="stPopover"] > div { width:100%; }
[data-testid="stSidebar"] [data-testid="stPopover"] button { width:100%; justify-content:flex-start; }
.stButton > button, .stDownloadButton > button { border-radius:10px; }
.muted { color:var(--muted); font-weight:400; }

/* composer bar pinned above the chat input (＋ menu, PC, thinking depth, chips) */
.st-key-composer_tools { padding:.15rem 0 .1rem; }
.st-key-composer_tools [data-testid="stSelectbox"] > div { min-height:2.2rem; }
.st-key-composer_tools [data-testid="stPopover"] button { border-radius:999px; font-size:1.15rem; }
.st-key-composer_tools .stButton > button { border-radius:999px; padding:.15rem .7rem; font-size:.82rem;
  min-height:2rem; background:rgba(124,156,255,.14); border:1px solid rgba(124,156,255,.4); }
[data-testid="stPopoverBody"] { min-width:min(380px, 92vw); max-height:70vh; overflow-y:auto; }
/* fallback if Streamlit has no bottom container: pin our own bar */
.st-key-composer_bar { position:fixed; left:50%; transform:translateX(-50%); bottom:4.6rem;
  width:min(920px, 94vw); z-index:90; background:var(--background-color, #0f1117); }

/* chat bubbles */
[data-testid="stChatMessage"] { background:transparent; border-radius:var(--radius); padding:.55rem .8rem; }
[data-testid="stChatMessage"]:has([data-testid*="AvatarUser"], [data-testid*="chatAvatarIcon-user"]) {
  background:rgba(124,156,255,.08); border:1px solid var(--border); }

/* small, quiet action buttons under messages */
[class*="st-key-actions_"] button { background:transparent; border:none; opacity:.55;
  padding:.1rem .45rem; min-height:1.8rem; font-size:.9rem; }
[class*="st-key-actions_"] button:hover { opacity:1; background:rgba(255,255,255,.07); }

[data-testid="stExpander"], [data-testid="stStatus"] { border-radius:12px; border-color:var(--border); }

/* welcome screen */
.hero { text-align:center; padding:2rem 0 1rem; }
.hero h1 { font-size:2rem; font-weight:650; margin-bottom:.4rem; }
.hero p { color:var(--muted); }
.st-key-welcome button { width:100%; text-align:left; justify-content:flex-start; padding:.8rem 1rem;
  border-radius:var(--radius); border:1px solid var(--border); }

/* skill cards */
[class*="st-key-skillcard_"] { border:1px solid var(--border); border-radius:var(--radius); padding:.7rem 1rem; margin-bottom:.6rem; }

/* scroll-to-bottom button */
a.scroll-bottom { position:fixed; right:1.6rem; bottom:9.5rem; width:2.4rem; height:2.4rem; border-radius:50%;
  display:flex; align-items:center; justify-content:center; text-decoration:none; color:inherit;
  background:rgba(124,156,255,.18); border:1px solid var(--border); backdrop-filter:blur(6px); z-index:100; }
a.scroll-bottom:hover { background:rgba(124,156,255,.38); }
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
