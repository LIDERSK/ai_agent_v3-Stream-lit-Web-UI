"""Which model runs on which PC.

Models are DETECTED on every PC (Ollama /api/tags + /api/show), so whatever you `ollama pull` shows up by
itself. Your choice per PC is stored in settings.json; config.py only provides the defaults.

Resolution for a PC and a kind ("text" | "vision"):
  1. the model you picked (if it is still installed)
  2. the default from config.py (if installed)
  3. the best installed model by config.MODEL_PREFERENCE (automatic detection)
No Streamlit imports here.
"""
from __future__ import annotations

from config import CLUSTER_PLANNER, CLUSTER_WORKER, MODEL_PREFERENCE, NODES
from core import settings_store
from core.ollama_client import get_capabilities, list_models, model_installed

AUTO = "Automaticky"


def _caps(url: str, model: str) -> frozenset:
    return get_capabilities(url, model)


def installed(node_name: str) -> tuple[str, ...]:
    return tuple(m["name"] for m in list_models(NODES[node_name].url))


def size_gb(node_name: str, model: str) -> float | None:
    for m in list_models(NODES[node_name].url):
        if m["name"] == model:
            return round(m["size"] / 1e9, 1) if m["size"] else None
    return None


def info(node_name: str, model: str) -> dict:
    """Capabilities of one model: thinking / vision / tools / embedding."""
    caps = _caps(NODES[node_name].url, model)
    return {"thinking": "thinking" in caps, "vision": "vision" in caps, "tools": "tools" in caps,
            "embedding": "embedding" in caps and "completion" not in caps}


def badges(node_name: str, model: str) -> str:
    i = info(node_name, model)
    return " ".join(b for b, on in (("🧠", i["thinking"]), ("👁", i["vision"]), ("🔧", i["tools"])) if on)


def choices(node_name: str, kind: str = "text") -> list[str]:
    """Installed models usable for this kind. Text: everything that can chat (not embedding-only)."""
    out = []
    for name in installed(node_name):
        i = info(node_name, name)
        if i["embedding"]:
            continue
        if kind == "vision" and not i["vision"]:
            continue
        out.append(name)
    return out


def _chosen(node_name: str, kind: str) -> str | None:
    return (settings_store.get("models", {}) or {}).get(node_name, {}).get(kind)


def _auto(node_name: str, kind: str) -> str | None:
    names = choices(node_name, kind)
    if not names:
        return None
    if kind == "vision":
        return names[0]
    plain = [n for n in names if not info(node_name, n)["vision"]] or names      # prefer non-vision chat models
    for pattern in MODEL_PREFERENCE:
        for n in plain:
            if pattern in n.lower():
                return n
    return plain[0]


def get_model(node_name: str, kind: str = "text") -> str | None:
    """The model that will really be used on this PC (None if nothing suitable is installed / PC offline)."""
    have = installed(node_name)
    pick = _chosen(node_name, kind)
    if pick and model_installed(have, pick):
        return pick
    default = NODES[node_name].model if kind == "text" else NODES[node_name].vision_model
    if default and model_installed(have, default):
        return default
    return _auto(node_name, kind)


def is_auto(node_name: str, kind: str = "text") -> bool:
    return not _chosen(node_name, kind)


def set_model(node_name: str, kind: str, model: str | None) -> None:
    """model=None or AUTO -> go back to automatic detection."""
    all_ = dict(settings_store.get("models", {}) or {})
    mine = dict(all_.get(node_name, {}))
    if not model or model == AUTO:
        mine.pop(kind, None)
    else:
        mine[kind] = model
    all_[node_name] = mine
    settings_store.put("models", all_)


# ----------------------------------------------------------------- cluster team
ROLES = ("architect", "programmer", "reviewer")
ROLE_LABEL = {"architect": "🧠 Architekt – plánuje", "programmer": "💻 Programátor – píše kód",
              "reviewer": "🔍 Recenzent – kontroluje a dokončí"}


def _default_pc(role: str) -> str:
    return CLUSTER_WORKER if role == "programmer" else CLUSTER_PLANNER


def cluster_team() -> dict[str, tuple[str, str | None]]:
    """role -> (PC, model or None = automatic). Chosen in the UI, config.py gives the PC defaults."""
    saved = settings_store.get("cluster_team", {}) or {}
    old = settings_store.get("cluster_roles", {}) or {}               # older versions: planner / worker only
    out = {}
    for role in ROLES:
        mine = saved.get(role) or {}
        legacy = old.get("worker" if role == "programmer" else "planner")
        pc = mine.get("pc") if mine.get("pc") in NODES else (legacy if legacy in NODES else _default_pc(role))
        out[role] = (pc, mine.get("model") or None)
    return out


def set_cluster_role(role: str, pc: str, model: str | None) -> None:
    team = dict(settings_store.get("cluster_team", {}) or {})
    team[role] = {"pc": pc, "model": None if (not model or model == AUTO) else model}
    settings_store.put("cluster_team", team)


def resolve_role_model(pc: str, chosen: str | None) -> str | None:
    """The chosen model if it is still installed on that PC, otherwise that PC's usual model."""
    if chosen and model_installed(installed(pc), chosen):
        return chosen
    return get_model(pc)


def recommended(role: str, node_name: str, model: str) -> bool:
    """Rough hint for the picker: coder models for the programmer, reasoning models for architect/reviewer."""
    if role == "programmer":
        return "coder" in model.lower() or "devstral" in model.lower()
    return info(node_name, model)["thinking"] or "coder" in model.lower()
