"""Central configuration.

Edit THIS file to add a PC, change a model, add a thinking tier or tweak behaviour.
Nothing else in the project hard-codes IP addresses, model names or paths.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

VERSION = "3.54"      # shown in the sidebar - bump it with every new zip

# ----------------------------------------------------------------- paths
BASE_DIR = Path(__file__).resolve().parent
CHAT_DIR = BASE_DIR / "saved_chats"
UPLOAD_DIR = BASE_DIR / "uploads"
WORKSPACE_DIR = BASE_DIR / "workspace"
HISTORY_DIR = WORKSPACE_DIR / ".history"      # backups of overwritten files
SETTINGS_PATH = BASE_DIR / "settings.json"    # remembered choices (skills, PC, thinking, ...)
SKILLPACKS_DIR = BASE_DIR / "skill_packs"     # instruction skills (SKILL.md folders): built-in + imported
APP_DOCS_PATH = BASE_DIR / "PATCH_NOTES_A_MAPA.md"   # patch notes + map of the app, read by the agent (tool app_info)

for _d in (CHAT_DIR, UPLOAD_DIR, WORKSPACE_DIR, HISTORY_DIR, SKILLPACKS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ----------------------------------------------------------------- compute nodes
@dataclass(frozen=True)
class Node:
    name: str
    url: str
    model: str                       # text / coding model
    vision_model: str | None = None  # model used when an image is attached (None = unsupported)


NODES: dict[str, Node] = {n.name: n for n in (
    Node("PC1 RX6800XT", "http://192.168.1.10:11434", "qwen2.5-coder:14b",
         vision_model="qwen2.5vl:7b"),            # ollama pull qwen2.5vl:7b
    Node("PC2 RX590", "http://192.168.1.11:11434", "qwen2.5-coder:7b",
         vision_model=None),                       # 8 GB card: add a small vision model if you like
)}
# When the configured model is not installed (or you pick "Automaticky"), the best installed one is chosen:
# the first name pattern below that matches wins.
MODEL_PREFERENCE = ("gpt-oss", "qwen3-coder", "devstral", "qwen2.5-coder", "qwen3", "gemma", "llama", "mistral")
DEFAULT_NODE = "PC1 RX6800XT"
CLUSTER_PLANNER = "PC1 RX6800XT"    # plans + reviews
CLUSTER_WORKER = "PC2 RX590"        # writes the first draft


# ----------------------------------------------------------------- thinking tiers
@dataclass(frozen=True)
class ThinkingTier:
    key: str
    icon: str
    level: str | None     # None = thinking off, otherwise "low" / "medium" / "high"
    hint: str             # extra instruction describing how deeply to think
    help: str


THINKING_TIERS: dict[str, ThinkingTier] = {t.key: t for t in (
    ThinkingTier("Vypnuté", "⚡", None, "",
                 "Okamžitá odpoveď bez uvažovania."),
    ThinkingTier("Ľahké", "💡", "low",
                 "Premýšľaj stručne: najviac 3 – 4 vety, potom odpovedz.",
                 "Krátke uvažovanie, rýchla odpoveď."),
    ThinkingTier("Štandardné", "🧠", "medium",
                 "Premýšľaj postupne krok za krokom, zváž okrajové prípady a až potom odpovedz.",
                 "Vyvážené uvažovanie."),
    ThinkingTier("Hlboké", "🔬", "high",
                 "Premýšľaj dôkladne: rozdeľ problém na časti, zváž viac riešení, over ich "
                 "a hľadaj možné chyby. Až potom napíš finálnu odpoveď.",
                 "Dôkladná analýza – pomalšie, ale presnejšie."),
)}
OFF_TIER = "Vypnuté"
DEFAULT_TIER = "Štandardné"
# gpt-oss cannot switch thinking off - its buttons are Low / Medium / High (= reasoning effort), see core/thinking.py
AGENT_GPTOSS_THINK = "low"  # gpt-oss in the agent: reasoning effort "low" even if Medium is selected ("High" is respected); None = follow the button
AGENT_TIER_CAP = "Štandardné"   # the agent never thinks deeper than this (many small tool steps); None = no cap


# ----------------------------------------------------------------- behaviour
DEFAULT_TEMPERATURE = 0.5
NUM_CTX = 8192              # context window sent to Ollama
CLUSTER_NUM_CTX = NUM_CTX   # SAME window as normal chat: a different value makes Ollama reload the model each time
CARRY_REF_CTX = 12288       # text carried between cluster stages is sized for this window and scaled down to the real one
MAX_NEW_TOKENS = 8192       # hard cap on ONE reply, so a looping model always ends
REPEAT_PENALTY = None       # e.g. 1.05; off by default - the loop guard already stops repeating models
LOOP_GUARD = True           # cut the stream when the model repeats the same block over and over
MAX_THINK_CHARS = 14000     # thinking longer than this is cut and the answer is requested without thinking
STAGE_MAX_TOKENS = {"plan": 800, "draft": 6000, "review": 1500, "final": 6000}   # cluster stages
CARRY_CHARS = {"plan": 3000, "draft": 14000, "review": 4000}   # how much of a stage is passed to the next one
GPU_WARN_BELOW = 90         # warn in the sidebar when less than this % of a model runs on the GPU
KEEP_ALIVE = "30m"          # keep the model loaded in VRAM between messages
AUTO_FIT = True            # after a reply: if the model spilled into RAM, unload the others / shrink the window so it fits in VRAM
FIT_MIN_GPU = 97           # % of the model that must sit on the GPU, otherwise AUTO_FIT acts
FORCE_GPU = True           # model spills a little into RAM although VRAM is free? Ollama's estimate is too cautious:
FORCE_GPU_MAX_SPILL = 30   # then try num_gpu=999 (all layers on GPU) when at most this % sits on the CPU; falls back on error
FIT_MIN_CTX = 4096         # AUTO_FIT never shrinks the window below this
HISTORY_MESSAGES = 12       # how many previous messages are sent to the model
# Agent runs until the task is done. It is only stopped when it gets STUCK (or hits a safety ceiling).
AGENT_MAX_STEPS = 150       # safety ceiling for tool calls in one task (not the normal limit)
AGENT_MAX_SECONDS = 45 * 60 # safety ceiling for total run time
AGENT_STALL_LIMIT = 5       # stop after this many steps in a row WITHOUT progress (errors / repeated calls)
AGENT_NUDGE_AT = 3          # after this many stalled steps the agent is told to change its approach
AGENT_REPEAT_LIMIT = 2      # the same call (same tool + arguments) more than this often counts as "no progress"
AGENT_PROMPT_SHARE = 0.6    # share of the REAL context window the agent prompt may fill (rest = room for the answer)
CHARS_PER_TOKEN = 3.0       # rough conversion used to size prompts
TOOL_PROTOCOL = "auto"      # how the agent calls tools: "auto" (native when the model supports it, else text) | "native" | "text"
TEXT_ONLY_MODELS = ()       # parts of model names that must always use the text protocol, e.g. ("qwen2.5-coder:7b",)
TOOL_RESULT_MAX = 6000      # max characters of a tool result given to the model
MAX_WRITE_CHARS = 200_000   # max size of a file the agent may write
RUN_TIMEOUT = 30            # seconds a script may run
SANDBOX_MODE = "local"      # "local" = clean temp copy + limits | "docker" = container (no network, 512 MB, 1 CPU)
SANDBOX_COMPILE_TIMEOUT = 60                 # seconds for compiling C / C++
SANDBOX_OUTPUT_MAX_BYTES = 2_000_000         # a program printing more than this is stopped
SANDBOX_DOCKER_IMAGES = {"python": "python:3.12-slim", "c": "gcc:13", "cpp": "gcc:13", "javascript": "node:20-slim"}
NOTIFY_DONE = True          # play a sound when a task finishes
NOTIFY_MIN_SECONDS = 20     # ... but only if it took at least this long
ZIP_NAME_MAX = 40           # max length of a ZIP / file name stem built from the topic
COMPOSER_MENU = "popover"   # "popover" (like ChatGPT) or "panel" (inline; use it if the + menu is cut off)
MAX_IMAGES = 4              # max images sent per request
MAX_IMAGE_SIDE = 1568       # images are downscaled to this (px)

# ----------------------------------------------------------------- skill packs (core/skillpacks.py)
SKILLPACK_MAX_BYTES = 5_000_000      # max size of one imported pack (all its files together)
SKILLPACK_MAX_FILES = 200            # max files in one pack
SKILLPACK_FILE_MAX = 1_000_000      # max size of ONE bundled file
SKILLPACK_PROMPT_CHARS = 700        # how much of the agent prompt the list of enabled packs may use (small context windows!)
SKILLPACK_DOWNLOAD_MAX = 20_000_000  # max download when importing from a URL

IMAGE_TYPES = ["png", "jpg", "jpeg", "webp", "gif"]
TEXT_TYPES = ["txt", "py", "md", "json", "csv", "js", "html", "css", "yml", "yaml", "log"]
BINARY_TYPES = ["zip", "pdf", "docx", "xlsx", "pptx"]   # saved to workspace/nahrate/, read via zip_* / read_document

WEB_TRIGGERS = ["novinky", "kto je", "čo je", "najnovšie", "vyhľadaj", "hľadaj", "aktuáln",
                "dnes", "ceny", "správy", "informácie", "news", "latest"]

# ----------------------------------------------------------------- chat modes
MODES = {
    "chat": ("💬", "Normálny chat", "Bežný rozhovor s modelom."),
    "agent": ("🤖", "Agent chat", "Pracuje samostatne: číta a píše súbory, hľadá na webe, spúšťa kód."),
}

SUGGESTIONS_CHAT = [
    "Napíš Python skript, ktorý zálohuje priečinok do ZIP archívu",
    "Vysvetli rozdiel medzi list a tuple v Pythone",
    "Navrhni štruktúru Flask aplikácie pre NAS rozhranie",
    "Aké sú najnovšie novinky v Pythone?",
]
SUGGESTIONS_AGENT = [
    "Vytvor v workspace jednoduchú todo aplikáciu v Pythone a otestuj ju",
    "Pozri sa, aké súbory sú vo workspace, a zhrň, čo robia",
    "Napíš skript na premenovanie súborov podľa dátumu a spusti ho na ukážku",
    "Nájdi na webe najnovšiu verziu Pythonu a ulož poznámku do poznamky.md",
]


# ----------------------------------------------------------------- Deep Research (core/research.py)
RESEARCH_DEFAULT_STEPS = 5        # research steps (the final report is one more)
RESEARCH_MAX_STEPS = 8
RESEARCH_RESULTS = 6              # search results per step
RESEARCH_PAGES = 2                # pages opened and read per step (best results first)
RESEARCH_PAGE_CHARS = 3000        # text taken from one page
RESEARCH_FETCH_TIMEOUT = 8        # seconds for one page
RESEARCH_PROMPT_CHARS = 9000      # sources handed to the model in one notes call (keeps it inside the context window)
