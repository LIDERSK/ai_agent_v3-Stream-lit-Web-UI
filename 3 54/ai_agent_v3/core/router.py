"""Decides WHICH computer + model handles a request (with automatic fallback)."""
from __future__ import annotations

from dataclasses import dataclass

from config import NODES
from core import models
from core.ollama_client import check_node, get_capabilities


class RoutingError(Exception):
    pass


@dataclass
class Target:
    node: str
    url: str
    model: str
    vision: bool                 # may images be sent to this model?
    warning: str | None = None


def resolve_target(node_name: str, needs_vision: bool = False) -> Target:
    order = [node_name] + [n for n in NODES if n != node_name]
    problems: list[str] = []
    for name in order:
        node = NODES[name]
        online, installed = check_node(node.url)
        if not online:
            problems.append(f"🔴 {name} ({node.url}) je nedostupný")
            continue
        kind = "vision" if needs_vision else "text"
        model = models.get_model(name, kind)
        if not model:
            what = "vision model (👁)" if needs_vision else "textový model"
            problems.append(f"🟡 {name}: nie je nainštalovaný žiadny {what} → `ollama pull <model>`")
            continue
        warn = None
        if name != node_name and problems:
            warn = f"⚠️ {problems[0]} – používam {name}."
        return Target(name, node.url, model, "vision" in get_capabilities(node.url, model), warn)
    kind = "vision model" if needs_vision else "model"
    raise RoutingError(f"Nenašiel som žiadny dostupný {kind}:\n\n" + "\n".join(f"- {p}" for p in problems))
