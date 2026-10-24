"""Skill registry.

A *skill* is a capability the user can switch on/off (checkbox in the ＋ menu or on the Skills page).
Skills may also provide *tools* that the agent can call.

ADD YOUR OWN SKILL: create core/skills/my_skill.py that defines  SKILL = Skill(...)
It is discovered automatically and shows up in the UI. See fs_read.py for a small example.
"""
from __future__ import annotations

import importlib
import pkgutil
import re
from dataclasses import dataclass, field
from typing import Callable

from core import settings_store


class ToolError(Exception):
    """Raise inside a tool to give the model a readable error."""


@dataclass
class ToolContext:
    node: str                      # PC chosen in the UI
    temperature: float = 0.3
    history: str = ""              # earlier conversation as plain text (for the cluster)
    on_event: Callable | None = None   # live progress callback set by the UI (cluster stages)
    written: list = field(default_factory=list)   # workspace paths created / changed during this run
    chat_id: str = ""              # for the saved task plan
    plan: list = field(default_factory=list)      # [{"text", "done"}] - the agent's checklist
    verified: bool = True          # False after a file was written until it was run / read back
    last_run: str = ""             # what the last run_code really returned ("" = the code was never run)
    enabled: frozenset = frozenset()   # skills switched on in this chat (tools may adapt their advice)
    read_hashes: dict = field(default_factory=dict)   # path -> hash of the content the agent last read
    originals: dict = field(default_factory=dict)     # path -> text BEFORE the agent first changed it in this task (None = new)
    warned_unread: set = field(default_factory=set)   # files the agent was told once to read before overwriting

    def has_read(self, rel: str) -> bool:
        return any(k.startswith(rel + "#") for k in self.read_hashes)

    def mark_written(self, rel: str) -> None:
        self.read_hashes.pop(rel, None)                # changed on disk -> reading it again is meaningful
        if rel not in self.written:
            self.written.append(rel)


@dataclass(frozen=True)
class Param:
    """One argument of a tool. Used to build the JSON schema for models with native tool calling."""
    name: str
    description: str = ""
    required: bool = True
    type: str = "string"


@dataclass(frozen=True)
class Tool:
    name: str
    usage: str                     # one line: which arguments it takes
    example: str                   # example call shown to the model (text protocol)
    run: Callable                  # run(args: dict, body: str, ctx: ToolContext) -> str
    params: tuple = ()             # (Param, ...) - optional; derived from `usage` when empty
    body: str = ""                 # name of the param that is passed as the tag BODY (e.g. file content)

    def param_specs(self) -> tuple:
        """Declared params, or - for a tool without declaration - guessed from its usage text (name="...")."""
        if self.params:
            return self.params
        optional = set(re.findall(r'\[\s*(\w+)\s*=', self.usage))
        names = list(dict.fromkeys(re.findall(r'(\w+)\s*=\s*"', self.usage)))
        out = [Param(n, required=n not in optional) for n in names]
        if self.body_param() and self.body_param() not in names:
            out.append(Param(self.body_param(), "obsah / telo volania", required=False))
        return tuple(out)

    def body_param(self) -> str:
        if self.body:
            return self.body
        if self.params:
            return ""
        return "content" if re.search(r"tel[eo]|medzi značky|obsah", self.usage, re.I) else ""


@dataclass(frozen=True)
class Skill:
    id: str
    icon: str
    name: str
    short: str                     # one-line description for the menu
    description: str               # longer text for the Skills page
    default: bool = True           # on/off the first time
    scope: str = "both"            # "both" | "agent" (agent chats only) | "chat" (normal chats only)
    mode: bool = False             # True = changes how EVERY message is processed (shown as a chip)
    warning: str = ""
    order: int = 50
    tools: tuple = ()


def _discover() -> dict[str, Skill]:
    found: dict[str, Skill] = {}
    for mod in pkgutil.iter_modules(__path__):
        module = importlib.import_module(f"{__name__}.{mod.name}")
        skill = getattr(module, "SKILL", None)
        if isinstance(skill, Skill):
            found[skill.id] = skill
    return dict(sorted(found.items(), key=lambda kv: (kv[1].order, kv[0])))


SKILLS: dict[str, Skill] = _discover()


def enabled_ids() -> set[str]:
    saved = settings_store.get("skills", {})
    return {sid for sid, s in SKILLS.items() if saved.get(sid, s.default)}


def is_enabled(skill_id: str) -> bool:
    return skill_id in enabled_ids()


def set_enabled(skill_id: str, value: bool) -> None:
    saved = dict(settings_store.get("skills", {}))
    saved[skill_id] = bool(value)
    settings_store.put("skills", saved)


def tools_for(enabled) -> list[tuple[Skill, Tool]]:
    return [(s, t) for s in SKILLS.values() if s.id in enabled for t in s.tools]


def find_tool(name: str):
    for s in SKILLS.values():
        for t in s.tools:
            if t.name == name:
                return s, t
    return None


def tool_prompt(enabled) -> str:
    return "\n".join(f"- {t.name}: {t.usage}\n  Príklad: {t.example}" for _, t in tools_for(enabled))
