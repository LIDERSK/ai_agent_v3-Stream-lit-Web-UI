"""The agent's task plan: a checklist that survives context shortening.

It lives in memory (ToolContext.plan) AND in workspace/.plan/<chat>.md (hidden folder, not in ZIPs), and the
agent loop shows it to the model after EVERY step, so even a long task never loses track of what is left.
"""
from __future__ import annotations

import re

from config import WORKSPACE_DIR

PLAN_DIR = WORKSPACE_DIR / ".plan"
MAX_STEPS = 12


def parse_steps(body: str) -> list[dict]:
    """One step per line; leading '-', '1.', '[ ]' are removed."""
    steps = []
    for line in body.splitlines():
        t = re.sub(r"^\s*(?:[-*•]\s+|\d+[.)]\s+)", "", line)
        t = re.sub(r"^\s*\[[ xX]?\]\s*", "", t).strip()
        if t:
            steps.append({"text": t[:200], "done": False})
    return steps[:MAX_STEPS]


def parse_numbers(spec: str, n: int) -> list[int]:
    """'2', '1,2', '2-4', '1 a 3' -> 0-based indexes inside 1..n."""
    out: list[int] = []
    for a, b in re.findall(r"(\d+)\s*(?:-|–|až)\s*(\d+)", spec or ""):
        out += range(int(a), int(b) + 1)
    out += [int(x) for x in re.findall(r"\d+", re.sub(r"\d+\s*(?:-|–|až)\s*\d+", " ", spec or ""))]
    return sorted({i - 1 for i in out if 1 <= i <= n})


def render(plan: list[dict]) -> str:
    return "\n".join(f"{'☑' if s['done'] else '☐'} {i}. {s['text']}" for i, s in enumerate(plan, 1))


def pending(plan: list[dict]) -> list[str]:
    return [f"{i}. {s['text']}" for i, s in enumerate(plan, 1) if not s["done"]]


def progress(plan: list[dict]) -> tuple[int, int]:
    return sum(1 for s in plan if s["done"]), len(plan)


def _path(chat_id: str):
    return PLAN_DIR / f"{re.sub(r'[^A-Za-z0-9_-]', '', chat_id or '')[:60] or 'default'}.md"


def save(chat_id: str, plan: list[dict]) -> None:
    PLAN_DIR.mkdir(parents=True, exist_ok=True)
    _path(chat_id).write_text("\n".join(f"- [{'x' if s['done'] else ' '}] {s['text']}" for s in plan) + "\n",
                              encoding="utf-8")


def load(chat_id: str) -> list[dict]:
    try:
        text = _path(chat_id).read_text(encoding="utf-8")
    except OSError:
        return []
    return [{"text": m.group(2).strip(), "done": m.group(1).lower() == "x"}
            for m in re.finditer(r"^- \[([ xX])\] (.+)$", text, re.M)]
