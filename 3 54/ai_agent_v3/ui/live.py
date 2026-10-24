"""LiveTurn: live display of ONE model turn (collapsible thinking box + streaming answer)."""
from __future__ import annotations

import time

import streamlit as st

from core.loopguard import trim_repetition

REDRAW_EVERY = 0.15       # seconds between UI refreshes while streaming
FULL_RENDER_LIMIT = 2500  # longer live text is shown as a fixed-size "tail" window (see render_stream)
TAIL_LINES = 16
_FENCE_SAFE = "'" * 3

STOP_NOTES = {
    "loop": "⚠️ Model sa začal opakovať, tak som výstup ukončil a opakovanie odstránil.",
    "think_runaway": "⚠️ Premýšľanie trvalo neprimerane dlho, preto som odpoveď vyžiadal bez neho.",
    "length": "⚠️ Dosiahol sa limit dĺžky odpovede – môže byť neúplná. Napíš „pokračuj“.",
}


def render_stream(slot, text: str, cursor: bool = True, tail_lines: int = TAIL_LINES) -> None:
    """Live view that never grows the page: short text is shown whole, long text (e.g. big code) only as a
    small fixed-height window with its last lines. The full text appears once the model is done.
    A page that keeps growing under your hands is what made scrolling jump and the bottom bar glitch."""
    if len(text) <= FULL_RENDER_LIMIT:
        slot.markdown(text + (" ▌" if cursor else ""))
        return
    lines = text.splitlines()
    tail = "\n".join(lines[-tail_lines:])[-1600:].replace("```", _FENCE_SAFE)
    slot.markdown(f"✍️ _Píšem… {len(lines)} riadkov · {len(text):,} znakov – celé sa zobrazí po dokončení_\n\n"
                  f"```text\n{tail}\n```")


def wait_text(ev: dict) -> str:
    """Status line while Ollama has not produced anything yet (model loading / prompt processing)."""
    sec = int(ev.get("seconds") or 0)
    loaded = ev.get("loaded")
    if loaded is False:
        what = "model sa načítava do pamäte (veľký model môže trvať minúty)"
    elif loaded:
        what = "model je načítaný, spracúva sa zadanie"
    else:
        what = "čakám na Ollamu"
    return f"⏳ {sec} s – {what}. Tlačidlom ⏹ Zastaviť to môžeš kedykoľvek prerušiť."


class Flat:
    """Stand-in for st.status inside ANOTHER expander (Streamlit forbids nested expanders): a plain container."""

    def __init__(self):
        self.box = st.container()

    def empty(self):
        with self.box:
            return st.empty()

    def update(self, **kw) -> None:
        pass


class Step:
    """One tool call shown as a plain bordered block inside the agent's single "Postup" expander."""

    def __init__(self, parent, label: str):
        self.label = label
        with parent:
            self.box = st.container(border=True)
        self.head = self.box.empty()
        self.head.markdown(f"⏳ 🔧 {label}")

    def update(self, state: str | None = None, **kw) -> None:
        if state in ("complete", "error"):
            self.head.markdown(f"{'⚠️' if state == 'error' else '✅'} 🔧 {self.label}")

    def __enter__(self):
        return self.box.__enter__()

    def __exit__(self, *a):
        return self.box.__exit__(*a)


THINK_LABEL = "🧠 Myšlienkový proces"     # NEVER changes while streaming (see LiveTurn)


class LiveTurn:
    """Live view of one model turn.

    IMPORTANT: Streamlit resets the open/closed state of an expander/status whenever its LABEL changes.
    So the label of the thinking box is constant for the whole run; the elapsed time is shown INSIDE the box
    and the box is not force-collapsed, therefore whatever you opened/closed yourself stays that way.
    `collapse_when_done` is only for agent runs (many turns), to keep the page short."""

    def __init__(self, want_think: bool, hide_tools: bool = False, collapse_when_done: bool = False, flat: bool = False):
        self.want_think, self.hide_tools = want_think, hide_tools
        self.collapse_when_done = collapse_when_done
        self.thinking = self.answer = ""
        self.stopped = None
        self.think_t0 = self.think_t1 = None
        self._last = 0.0
        self.outer, self.status, self.think_slot, self.timer_slot = st.empty(), None, None, None
        if want_think:
            with self.outer.container():
                self.status = Flat() if flat else st.status(THINK_LABEL, expanded=True)
                self.timer_slot = self.status.empty()
                self.timer_slot.caption("⏱ 0 s")
                self.think_slot = self.status.empty()
                self.think_slot.caption("⏳ Čakám na model – načítava sa kontext a model sa spúšťa…")
        self.answer_slot = st.empty()
        if not want_think:
            self.answer_slot.caption("⏳ Čakám na model…")

    # ---- text helpers
    def shown(self) -> str:
        text = self.answer
        if self.hide_tools:                           # never show raw <tool ...> markup
            i = text.find("<tool")
            if i != -1:
                text = text[:i]
        return text.lstrip()

    def _close_thinking(self, seconds: float) -> None:
        self.think_slot.markdown(self.thinking)
        self.timer_slot.caption(f"⏱ Premýšľal som {seconds:.1f} s")
        # no label change, and no forced collapse unless asked: that would override what the user did
        self.status.update(state="complete", expanded=False if self.collapse_when_done else None)

    def _draw(self) -> None:
        if self.think_slot is not None and self.thinking.strip() and self.think_t1 is None:
            render_stream(self.think_slot, self.thinking)
            self.timer_slot.caption(f"⏱ Premýšľam… {time.perf_counter() - self.think_t0:.0f} s")
        if self.shown().strip():
            render_stream(self.answer_slot, self.shown())

    # ---- events
    def feed(self, ev: dict) -> None:
        now, kind = time.perf_counter(), ev["type"]
        if kind == "thinking":
            if self.think_t0 is None:
                self.think_t0 = now
            self.thinking += ev["text"]
        elif kind == "content":
            if self.think_t0 is not None and self.think_t1 is None and self.status is not None:
                self.think_t1 = now
                self._close_thinking(now - self.think_t0)
            self.answer += ev["text"]
        elif kind == "wait":                          # nothing from the model yet: keep the UI alive (and stoppable)
            text = wait_text(ev)
            if self.think_slot is not None and self.think_t0 is None:
                self.timer_slot.caption(f"⏱ {int(ev.get('seconds') or 0)} s")
                self.think_slot.caption(text)
            elif not self.answer and not self.thinking:
                self.answer_slot.caption(text)
            return
        elif kind == "done":
            self.stopped = (ev.get("stats") or {}).get("stopped")
            return
        else:
            return
        if now - self._last > REDRAW_EVERY:
            self._last = now
            self._draw()

    def finish(self) -> tuple[str, str, float | None]:
        """Close the boxes. Returns (thinking, answer_without_tool_markup, thinking_seconds)."""
        end = time.perf_counter()
        if self.think_t0 is not None and self.think_t1 is None:
            self.think_t1 = end
        think_s = (self.think_t1 - self.think_t0) if self.think_t0 is not None else None
        if len(self.thinking.strip()) < 12:           # nothing worth showing (empty / just a word)
            self.thinking = ""
        if self.status is not None:
            if self.thinking:
                self._close_thinking(think_s)
            else:
                self.outer.empty()                    # model didn't think -> remove empty box
        text = self.shown().rstrip()
        if self.stopped == "loop":
            text = trim_repetition(text)
        if text:
            self.answer_slot.markdown(text)
        else:
            self.answer_slot.empty()
        if self.stopped in STOP_NOTES:
            st.caption(STOP_NOTES[self.stopped])
        return self.thinking, text, think_s
