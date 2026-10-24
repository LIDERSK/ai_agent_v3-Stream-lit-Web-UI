"""Thinking support.

Two ways a model can "think":
  * native  – Ollama returns a separate `thinking` field (qwen3, deepseek-r1, gpt-oss, ...)
  * prompted – the model has no native support (e.g. qwen2.5-coder), so we ask it to write
               its reasoning between <think>...</think> and split the stream ourselves.
"""
from config import DEFAULT_TIER, OFF_TIER, THINKING_TIERS

PROMPTED_COT = (
    "Najprv si premysli úlohu: svoje uvažovanie napíš VÝHRADNE medzi značky <think> a </think>. "
    "Až potom, mimo týchto značiek, napíš finálnu odpoveď pre používateľa. {hint}"
)


class ThinkSplitter:
    """Splits a text stream into ('thinking' | 'content', text) parts at <think> tags.
    Handles tags that arrive split across chunks."""
    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self):
        self.in_think = False
        self.buf = ""

    @property
    def _kind(self) -> str:
        return "thinking" if self.in_think else "content"

    def feed(self, text: str):
        self.buf += text
        out = []
        while True:
            tag = self.CLOSE if self.in_think else self.OPEN
            idx = self.buf.find(tag)
            if idx != -1:
                if idx:
                    out.append((self._kind, self.buf[:idx]))
                self.buf = self.buf[idx + len(tag):]
                self.in_think = not self.in_think
                continue
            keep = 0                       # hold back a possible partial tag at the end
            for k in range(min(len(tag) - 1, len(self.buf)), 0, -1):
                if tag.startswith(self.buf[-k:]):
                    keep = k
                    break
            cut = len(self.buf) - keep
            if cut:
                out.append((self._kind, self.buf[:cut]))
            self.buf = self.buf[cut:]
            return out

    def flush(self):
        out = [(self._kind, self.buf)] if self.buf else []
        self.buf = ""
        return out


def plan_thinking(tier_key: str, model: str, capabilities) -> tuple:
    """Return (think_param_for_ollama, system_hint)."""
    tier = THINKING_TIERS[tier_key]
    if "thinking" in capabilities:                       # native thinking model
        gpt_oss = model.lower().startswith("gpt-oss")    # takes "low" / "medium" / "high"; cannot be turned off
        if tier.level is None:
            return ("low" if gpt_oss else False), ""
        return (tier.level if gpt_oss else True), tier.hint
    if tier.level is None:                               # no thinking requested
        return None, ""
    return None, PROMPTED_COT.format(hint=tier.hint)     # prompted reasoning


# ----------------------------------------------------------------- gpt-oss: Low / Medium / High buttons
# gpt-oss cannot think "off"; its reasoning EFFORT is low / medium / high. The composer shows exactly these three
# buttons for it (they are the tiers Ľahké / Štandardné / Hlboké under the hood), so the choice reaches Ollama as is.
GPTOSS_TIERS = {"Ľahké": "Low", "Štandardné": "Medium", "Hlboké": "High"}


def is_gptoss(model: str | None) -> bool:
    return (model or "").lower().startswith("gpt-oss")


def tier_for_model(tier_key: str, model: str | None) -> str:
    """The tier that is valid for this model: for gpt-oss "Vypnuté" does not exist, it becomes "Ľahké"."""
    if is_gptoss(model) and tier_key not in GPTOSS_TIERS:
        return "Ľahké"
    return tier_key if tier_key in THINKING_TIERS else DEFAULT_TIER


def selected_effort(model: str | None = None) -> str:
    """The level of the saved thinking button as gpt-oss effort ("low" | "medium" | "high")."""
    from core import settings_store
    tier = tier_for_model(settings_store.get("tier", DEFAULT_TIER), "gpt-oss")
    return THINKING_TIERS[tier].level or "low"
