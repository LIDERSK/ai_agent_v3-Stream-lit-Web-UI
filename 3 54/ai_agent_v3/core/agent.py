"""Autonomous agent loop.

Talks to the model through a ToolProtocol (core/toolcalling.py): native tool calling where the model supports
it, plain-text tags everywhere else - the loop itself does not care which one is used:

    <tool name="read_file" path="app.py"/>                  (text protocol)
    message.tool_calls = [{function: {name, arguments}}]    (native protocol)

We run ONE tool per turn, feed the result back and repeat until the model answers without a tool call.
"""
from __future__ import annotations

import hashlib
import json
import re
import time

from core import plan as planlib
from core import workspace
from config import (AGENT_MAX_SECONDS, AGENT_MAX_STEPS, AGENT_NUDGE_AT, AGENT_PROMPT_SHARE,
                    AGENT_REPEAT_LIMIT, AGENT_STALL_LIMIT, CHARS_PER_TOKEN, TOOL_RESULT_MAX)
from core.ollama_client import ToolsUnsupported, effective_ctx, stream_chat
from core.skills import ToolContext, ToolError, find_tool, tools_for
from core.sandbox import RUNNABLE
from core.skills.fs_read import NO_CHANGE
from core.toolcalling import (INTENT_RE, TextProtocol, announces_action, ToolCall, ToolProtocol, known_tool_names,   # noqa: F401 (re-exported)
                              parse_tool_call, remember_protocol, switch_protocol)

STOP = TextProtocol.stop


RUN_TOOLS = ("run_code", "run_python", "run_tests")       # run_python = old name, still accepted




DELIVERABLES = {"bat": re.compile(r"\bbat\b|\.bat\b|\bbatch\b", re.I),        # file types a task may ask for by name
                "txt": re.compile(r"\.txt\b|\btxt\b", re.I),
                "html": re.compile(r"\.html\b|\bhtml\b", re.I)}


def missing_deliverables(task: str, written) -> list[str]:
    done = [str(w).lower() for w in written]
    return [ext for ext, rx in DELIVERABLES.items()
            if rx.search(task or "") and not any(w.endswith("." + ext) for w in done)]


def auto_bat(lacking: list[str], ctx: ToolContext) -> ToolCall | None:
    """The task asked for a .bat that the model never wrote: build the (trivial) launcher for the last script."""
    if "bat" not in lacking:
        return None
    py = next((str(w) for w in reversed(list(ctx.written)) if str(w).lower().endswith(".py")), "")
    if not py:
        return None
    folder, _, name = py.replace("\\", "/").rpartition("/")
    bat = (folder + "/" if folder else "") + name.rsplit(".", 1)[0] + ".bat"
    body = f'@echo off\ncd /d "%~dp0"\npython "{name}"\nif errorlevel 1 pause\n'
    return ToolCall("write_file", {"path": bat}, body)


_NAME_PREFIX = re.compile(r"^(?:tools?|functions?|default_api|api)[.:/]", re.I)


FOREIGN_TOOLS = {"repo_browser.open_file": "read_file", "repo_browser.read_file": "read_file", "open_file": "read_file",
                 "repo_browser.print_tree": "list_files", "print_tree": "list_files",
                 "repo_browser.search": "search_files", "repo_browser.grep": "search_files"}
_FOREIGN_ARGS = {"line_start": "start", "line_end": "end", "start_line": "start", "end_line": "end",
                 "file_path": "path", "q": "query", "pattern": "query"}


REASON_RE = re.compile(r"^\s*(?:We need to|We should|We can|We have to|We must|The user|Let's|Let me|I need to|I should)\b", re.I)


def run_tool(call: ToolCall, enabled, ctx: ToolContext) -> tuple[bool, str]:
    clean = _NAME_PREFIX.sub("", call.name or "")             # models write "tool.run_code" / "functions.read_file"
    clean = FOREIGN_TOOLS.get(clean.lower(), clean)           # gpt-oss was trained on "repo_browser.open_file" & co.
    if clean and clean != call.name:
        args = call.args
        if clean in ("read_file", "search_files") and call.name.lower() in FOREIGN_TOOLS:
            args = {_FOREIGN_ARGS.get(k, k): v for k, v in call.args.items()}
        call = ToolCall(clean, args, call.body)
    if call.name == "run_python":                                # legacy name -> sandbox
        call = ToolCall("run_code", call.args, call.body)
    found = find_tool(call.name)
    if not found:
        known = ", ".join(t.name for _, t in tools_for(enabled)) or "žiadne"
        return False, f"Neznámy nástroj '{call.name}'. Dostupné nástroje: {known}."
    skill, tool = found
    if skill.id not in enabled:
        return False, f"Nástroj '{call.name}' je vypnutý (zapni skill „{skill.name}“)."
    try:
        return True, str(tool.run(call.args, call.body, ctx))[:TOOL_RESULT_MAX]
    except ToolError as e:
        return False, str(e)
    except Exception as e:                                       # never crash the loop
        return False, f"Chyba nástroja: {e}"


BODY_RE = re.compile(r"(<tool [^>]*>\n)(.*?)(\n</tool>)", re.S)
SHORTENED = "[... skrátené kvôli dĺžke kontextu – súbor je uložený vo workspace/, prečítaj ho cez read_file ...]"
OMITTED = ("\n\n[POZNÁMKA] Starší priebeh práce bol vynechaný kvôli dĺžke kontextu. "
           "Stav súborov zisti cez list_files / read_file.")


def prompt_budget(url: str, model: str) -> int:
    """How many characters the prompt may have: a share of the context window this PC REALLY uses."""
    return int(effective_ctx(url, model) * CHARS_PER_TOKEN * AGENT_PROMPT_SHARE)


def msg_size(m: dict) -> int:
    n = len(m.get("content") or "") + len(m.get("thinking") or "")
    if m.get("tool_calls"):
        n += len(json.dumps(m["tool_calls"], ensure_ascii=False))
    return n


def _size(messages: list[dict]) -> int:
    return sum(msg_size(m) for m in messages)


def _is_result(m: dict) -> bool:
    return m["role"] == "tool" or (m["role"] == "user" and m["content"].startswith("[VÝSLEDOK NÁSTROJA"))


def _shorten_body(m: re.Match) -> str:
    body = m.group(2)
    return m.group(1) + (body[:300] + "\n" + SHORTENED if len(body) > 800 else body) + m.group(3)


def _shorten_calls(m: dict, limit: int, keep: int) -> None:
    """Native protocol: long file contents inside a tool call's arguments (they are on disk anyway)."""
    for c in m.get("tool_calls") or []:
        args = (c.get("function") or {}).get("arguments")
        if isinstance(args, dict):
            for k, v in args.items():
                if isinstance(v, str) and len(v) > limit:
                    args[k] = v[:keep] + "\n" + SHORTENED


def _compact(messages: list[dict], task_idx: int, budget: int) -> int:
    """Keep a LONG task inside the context window (else Ollama silently drops the start = the instructions).
    Shortens, from the cheapest loss to the most expensive:
      1. old tool results   2. file contents the agent wrote earlier (they are on disk anyway)
      3. conversation before this task   4. the oldest agent steps.
    The system prompt (index 0) and the task message are never touched. Returns the (new) task index.
    Works for both protocols (text tags in content, or native tool_calls / role "tool" messages)."""
    if _size(messages) <= budget:
        return task_idx
    steps = lambda: messages[task_idx + 1:]                                        # noqa: E731
    for m in [m for m in steps() if _is_result(m)][:-1]:
        if len(m["content"]) > 700:
            m["content"] = m["content"][:600] + "\n" + SHORTENED
    for m in [m for m in steps() if m["role"] == "assistant"][:-1]:                # old reasoning is not needed
        m.pop("thinking", None)
    if _size(messages) <= budget:
        return task_idx
    for m in [m for m in steps() if m["role"] == "assistant"][:-2]:
        m["content"] = BODY_RE.sub(_shorten_body, m["content"])
        _shorten_calls(m, 800, 300)
    while _size(messages) > budget and task_idx > 1:                               # older conversation
        del messages[1]
        task_idx -= 1
    omitted = False
    while _size(messages) > budget and len(steps()) > 4:                           # oldest agent steps
        del messages[task_idx + 1: task_idx + 3]
        omitted = True
    while steps() and messages[task_idx + 1]["role"] == "tool":                    # never start with an orphan result
        del messages[task_idx + 1]
    if _size(messages) > budget:                                                   # tiny window: last resort
        for m in steps():
            if m["role"] == "assistant":
                m["content"] = BODY_RE.sub(lambda mm: mm.group(1) + mm.group(2)[:200] + "\n" + SHORTENED + mm.group(3),
                                           m["content"])
                _shorten_calls(m, 400, 200)
            elif len(m["content"]) > 400:
                m["content"] = m["content"][:300] + "\n" + SHORTENED
    if omitted and OMITTED not in messages[task_idx]["content"]:
        messages[task_idx]["content"] += OMITTED
    return task_idx


TASK_CUT = "\n[… zvyšok správy skrátený, aby sa zmestil do okna modelu; súbory čítaj nástrojmi …]"


def fit_task(messages: list[dict], task_idx: int, budget: int) -> bool:
    """Safety net: system prompt + the task must fit the window, otherwise Ollama cuts the START of the prompt.
    The instruction is at the beginning of the task message, so the END (attachments) is what gets cut."""
    room = int(budget * 1.15) - len(messages[0].get("content") or "")     # budget is only ~60 % of the window
    keep = max(room, 2500)
    text = messages[task_idx].get("content") or ""
    if len(text) <= keep:
        return False
    messages[task_idx]["content"] = text[:keep] + TASK_CUT
    return True


CLAIM_RE = re.compile(r"vytvoril|vytvoren|uložil|ulozil|napísal|napisal|zapísal|created|saved|wrote|súbor(?:y|ov)? .{0,40}(?:je|sú) (?:pripraven|hotov)", re.I)
FILE_RE = re.compile(r"(?<![\w/.-])([\w][\w\-]*(?:/[\w\-]+)*\.(?:py|md|txt|html|css|js|json|csv|bat|ps1|sh|yaml|yml|toml|ini|xml|sql|ts|jsx|tsx))\b", re.I)
LEAK_RE = re.compile(r"\[(?:Použité nástroje|VÝSLEDOK NÁSTROJA|KONIEC VÝSLEDKU|UPOZORNENIE|PLÁN|DIAGNÓZA)[^\]]*\]?", re.I)


def claimed_missing_files(text: str, written=()) -> list[str]:
    """Files the answer claims to have created although they do not exist in workspace/.
    A bare name ("k.bat") counts as existing when the agent wrote it in a folder ("kalk/k.bat")."""
    if not CLAIM_RE.search(text):
        return []
    have = {str(w).replace("\\", "/").rsplit("/", 1)[-1].lower() for w in written}
    missing = []
    for name in dict.fromkeys(FILE_RE.findall(text)):
        if name.rsplit("/", 1)[-1].lower() in have:
            continue
        try:
            if not workspace.safe_path(name).is_file():
                missing.append(name)
        except workspace.WorkspaceError:
            pass
    return missing


def claim_nudge(missing: list[str]) -> str:
    return ("[UPOZORNENIE] Tvrdíš, že si vytvoril súbory (" + ", ".join(missing) + "), ale vo workspace/ NEEXISTUJÚ – "
            "nezavolal si write_file. Vytvor ich teraz skutočne cez nástroj write_file (každý súbor jedným volaním) "
            "a až potom odpovedz. Nepíš hranaté technické značky.")


# ----------------------------------------------------------------- plan / verification / diagnosis
DIAG_NOTE = ("[DIAGNÓZA] Najprv napíš 1 – 2 vety: aká je PRÍČINA chyby (nielen čo hlási, ale prečo vznikla). "
             "Až potom ju oprav. Neopravuj naslepo a neopakuj ten istý krok.")


ENV_NOTE = ("[POZNÁMKA] Tá istá chyba sa opakuje už 3×. Ak pochádza z knižnice alebo prostredia (nie z tvojho kódu), "
            "NEPATCHUJ knižnice ani nepíš obchádzky (monkey patch). Prestaň a v odpovedi povedz používateľovi, čo má "
            "nainštalovať alebo aktualizovať (napr. pip install -U …).")


ENV_ERR = re.compile(r"ModuleNotFoundError: No module named '([\w.]+)'|ImportError: cannot import name|"
                     r"get_loader|module 'pkgutil'|ast\.Str|has no attribute '(?:Str|Num)'|DeprecationWarning: .*removed")


def missing_module(call: "ToolCall", result: str) -> str:
    """Name of the module a failed run could not import ('' otherwise)."""
    if call.name not in RUN_TOOLS or result.startswith("Exit code 0"):
        return ""
    m = re.search(r"No module named '([\w.]+)'", result)
    return m.group(1).split(".")[0] if m and not is_local_module(m.group(1)) else ""


def is_local_module(name: str) -> bool:
    """True when `name` exists as <name>.py or a package folder somewhere in the workspace (it is the project's own code)."""
    top = name.split(".")[0]
    try:
        root = workspace.WORKSPACE_DIR
    except AttributeError:
        return False
    for base in [root, *[d for d in root.iterdir() if d.is_dir()][:50]]:
        if (base / f"{top}.py").is_file() or (base / top).is_dir():
            return True
    return False


def env_problem(call: "ToolCall", result: str) -> str:
    """Text for the user when a failed run is caused by the installation (missing / too old library), else ''.
    The agent cannot install packages, so more attempts only burn time."""
    if call.name not in RUN_TOOLS or result.startswith("Exit code 0"):
        return ""
    m = ENV_ERR.search(result)
    if not m:
        return ""
    if m.group(1) and is_local_module(m.group(1)):       # the project's own package (import core): a layout problem, not pip
        return ""
    lines = [l.strip() for l in result.splitlines() if l.strip()]
    err = next((l for l in reversed(lines) if "Error" in l), lines[-1] if lines else "")[:200]
    if m.group(1):
        fix = f"`pip install {m.group(1).split('.')[0]}`"
    else:
        fix = "`pip install -U flask werkzeug` (alebo aktualizuj knižnicu z chyby) – inštalovaná verzia nesedí s tvojím Pythonom"
    return (f"⚠️ **Kód je napísaný, ale nedá sa spustiť kvôli prostrediu, nie kvôli chybe v kóde.**\n\n"
            f"Chyba: `{err}`\n\nRiešenie: spusti vo svojom termináli {fix} a napíš „pokračuj“. "
            f"Súbory sú uložené vo `workspace/`.")


def auto_fix(url: str, model: str, temperature: float, path: str, error: str, hint: str = "") -> str:
    """Ask the model (no tools, one narrow job) for the corrected whole file. Returns code or ''."""
    try:
        src = workspace.read_text(path, 20000)
    except workspace.WorkspaceError:
        return ""
    prompt = (f"Súbor {path} sa nepodarilo spustiť.\n\nCHYBA:\n{error[-1800:]}\n\nSÚBOR:\n```\n{src}\n```\n\n"
              "Najprv v jednej vete zisti príčinu, potom vráť OPRAVENÝ CELÝ súbor v JEDNOM bloku ```python "
              "(bez názvu súboru v bloku a bez vysvetlenia po ňom)." + (f"\n{hint}" if hint else ""))
    think = "low" if model.lower().startswith("gpt-oss") else False
    text = ""
    try:
        for ev in stream_chat(url, model, [{"role": "user", "content": prompt}], 0.2, think=think):
            if ev["type"] == "content":
                text += ev["text"]
    except Exception:
        return ""
    blocks = re.findall(r"```[^\s`]*[ \t]*\n(.*?)```", text, re.S)
    if not blocks:
        return ""
    code, _ = workspace.strip_name_line(max(blocks, key=len).strip("\n") + "\n")
    return code if len(code.strip().splitlines()) >= 3 else ""


def last_error_line(result: str) -> str:
    lines = [l.strip() for l in result.splitlines() if l.strip()]
    return next((l for l in reversed(lines) if "Error" in l or "Exception" in l), lines[-1] if lines else "")[:220]


def plan_nudge(pending: list[str]) -> str:
    return ("[UPOZORNENIE] Plán má ešte nedokončené kroky: " + "; ".join(pending) + ". Pokračuj nasledujúcim krokom. "
            "NEPOPISUJ, čo urobíš – ZAVOLAJ nástroj. Ak je niektorý už hotový, označ ho cez plan_done; ak je zbytočný, uprav plán cez plan_set. "
            "Odpovedz používateľovi až keď je všetko hotové.")


def verify_nudge(enabled, ctx: ToolContext) -> str:
    py = next((f for f in reversed(ctx.written) if f.lower().endswith(RUNNABLE)), None)
    if py and "run_code" in enabled:
        how = f'spusti ho (run_code path="{py}")'
    else:
        how = f'prečítaj ho späť (read_file path="{ctx.written[-1]}") a skontroluj, že obsahuje, čo má'
    return ("[UPOZORNENIE] Pred ukončením OVER výsledok: " + how + ". Až potom odpovedz používateľovi. "
            "Ak overenie odhalí chybu, najprv napíš jej príčinu a potom ju oprav.")


DOC_EXT = (".bat", ".cmd", ".txt", ".md", ".json", ".csv", ".ini", ".yml", ".yaml", ".toml", ".cfg", ".sh", ".ps1")


def update_state(call: "ToolCall", ok: bool, result: str, ctx: ToolContext) -> None:
    """Track whether what the agent wrote has been checked (run successfully / read back)."""
    if call.name in RUN_TOOLS:
        ctx.last_run = ("OK: " if ok and result.startswith("Exit code 0") else "ZLYHALO: ") + " ".join(result.split())[:300]
    if not ok:
        return
    if call.name in ("write_file", "edit_file", "rename_file", "cluster_solve"):
        if not (call.name in ("write_file", "edit_file") and call.args.get("path", "").lower().endswith(DOC_EXT)):
            ctx.verified = False          # a launcher / text file is not code that could be run or tested
    elif call.name in RUN_TOOLS:
        ctx.verified = result.startswith("Exit code 0")
    elif call.name == "read_file" and call.args.get("path") in ctx.written:
        ctx.verified = True


def needs_diagnosis(call: "ToolCall", ok: bool, result: str) -> bool:
    return (not ok) or (call.name in RUN_TOOLS and not result.startswith("Exit code 0"))


CODE_WORDS = re.compile(r"napíš|napis|vytvor|naprogramuj|implementuj|oprav|uprav|refaktor|skript|program|kód|kod\b|"
                        r"server|aplikáci|aplikaci|funkci|trie[dď]|modul|endpoint|api\b|write|create|implement|script|code",
                        re.I)


def wants_cluster(task: str) -> bool:
    """A real coding task (not 'pokračuj' or a short question) - then the cluster must do the writing."""
    return len(task.strip()) >= 25 and bool(CODE_WORDS.search(task))


def finish_gate(enabled, ctx: ToolContext, used: dict) -> tuple[str, str] | None:
    """Before the agent may say 'done': is the plan finished and the result verified? Each gate fires a limited
    number of times so it can never trap the agent. Returns (note_for_model, short_text_for_user) or None."""
    pend = planlib.pending(ctx.plan) if "planning" in enabled else []
    if pend and used["plan"] < 3:
        used["plan"] += 1
        return plan_nudge(pend), f"Plán nie je dokončený ({len(pend)} krokov zostáva) – agent pokračuje."
    if ctx.written and not ctx.verified and ("run_code" in enabled or "fs_read" in enabled) and used["verify"] < 2:
        used["verify"] += 1
        return verify_nudge(enabled, ctx), "Agent ešte neoveril výsledok – vyzvaný, aby ho spustil / prečítal."
    return None


class ProgressTracker:
    """Decides whether the agent is still getting somewhere.

    A step is PROGRESS when it is new (tool + arguments + content + result never seen before)
    and succeeded. It is a STALL when the tool failed or the very same call is repeated.
    The run only ends because of a stall streak (or the safety ceilings), never because of a
    small fixed number of steps.
    """

    def __init__(self) -> None:
        self.seen: dict[str, int] = {}
        self.stalled = 0                 # consecutive steps without progress
        self.steps = 0

    @staticmethod
    def signature(call: ToolCall, result: str = "") -> str:
        digest = hashlib.md5(result.encode("utf-8", "ignore")).hexdigest()[:8]
        return f"{call.name}|{sorted(call.args.items())}|{call.body.strip()[:2000]}|{digest}"

    def record(self, call: ToolCall, ok: bool, result: str = "", no_progress: bool = False) -> bool:
        """Register a finished step, return True if it counted as progress.
        The RESULT is part of the signature: running a script after a fix (different output) is progress,
        the same call with the same result again is not."""
        self.steps += 1
        sig = self.signature(call, result)
        self.seen[sig] = self.seen.get(sig, 0) + 1
        repeated = self.seen[sig] > AGENT_REPEAT_LIMIT
        progress = ok and not repeated and not no_progress
        self.stalled = 0 if progress else self.stalled + 1
        return progress

    def note_idle(self) -> None:                       # model answered without anything usable
        self.stalled += 1

    @property
    def should_nudge(self) -> bool:
        return self.stalled == AGENT_NUDGE_AT

    @property
    def is_stuck(self) -> bool:
        return self.stalled >= AGENT_STALL_LIMIT


NUDGE = ("[UPOZORNENIE] Posledné kroky nikam nepostúpili (chyby alebo opakovanie rovnakého volania). "
         "ZMEŇ PRÍSTUP: prečítaj si chybu, skontroluj stav cez list_files / read_file a skús iný spôsob. "
         "Ak sa to nedá dokončiť, odpovedz používateľovi a vysvetli, čo sa nepodarilo.")
WRAPUP = ("[UPOZORNENIE] Na ďalšie volanie nástrojov už nie je priestor. Nevolaj žiadny nástroj. Napíš používateľovi "
          "STRUČNÉ zhrnutie: čo je hotové (vymenuj vytvorené súbory), čo sa neoverilo alebo nepodarilo a čo má "
          "urobiť ďalej. Nič nevymýšľaj – opieraj sa len o to, čo naozaj urobili nástroje.")


def _facts(ctx) -> str:
    """What REALLY happened, handed to the summary so the model cannot invent test results."""
    lines = ["Vytvorené súbory: " + (", ".join(map(str, ctx.written)) if ctx.written else "žiadne") + "."]
    if "run_code" not in ctx.enabled:
        lines.append("Sandbox je VYPNUTÝ – kód sa nespustil. Nepíš, že bol otestovaný; povedz, že sa nespúšťal, a ako ho spustí používateľ.")
    if "run_code" in ctx.enabled:
        lines.append("Posledné spustenie kódu: " + ctx.last_run if ctx.last_run else
                     "Kód sa NIKDY NESPUSTIL – nepíš, že bol otestovaný, ani že test odhalil chybu.")
    return "[FAKTY – len toto sa naozaj stalo]\n" + "\n".join(lines) + "\n"


def _wrapup(url, model, messages, temperature, think_param, step, ctx):
    """The agent is stuck: instead of ending with a bare warning, ask the model for a short honest summary of
    the work done so far (no tools). Yields the same events as a normal turn, ending with `final`."""
    from core.ollama_client import OllamaError
    yield {"type": "turn_start", "step": step + 1}
    text = ""
    try:
        for ev in stream_chat(url, model, [*messages, {"role": "user", "content": _facts(ctx) + WRAPUP}], temperature,
                              think=think_param):
            if ev["type"] == "content":
                text += ev["text"]
            if ev["type"] in ("thinking", "content", "done", "wait"):
                yield ev
    except OllamaError:
        pass
    yield {"type": "turn_end", "text": text.strip(), "call": None, "stats": {}}
    if not text.strip() and ctx.written:
        text = "Vytvorené súbory: " + ", ".join(ctx.written) + "."
    if text.strip():
        yield {"type": "final", "text": LEAK_RE.sub("", text).strip()}


def run_agent(api_messages: list[dict], *, url: str, model: str, think_param, temperature: float,
              enabled, ctx: ToolContext, max_steps: int = AGENT_MAX_STEPS,
              max_seconds: float = AGENT_MAX_SECONDS, protocol: ToolProtocol | None = None):
    """Generator of events (dicts):
        protocol {name, reason}        which tool protocol is used (again when it changes mid-run)
        turn_start {step}
        thinking|content {text}        live stream of the current model turn
        done {stats}
        turn_end {text, call}          text = what the model said before its tool call (or final answer)
        tool_call {name, args, body}   about to run
        tool_result {name, ok, text, progress}
        nudge {text}                   agent was told to change approach
        final {text}
        stopped {reason, detail}       reason: "stuck" | "time" | "steps"  (work done so far is kept)

    The agent keeps going for as long as it makes progress. Slow thinking is never a problem:
    only failed / repeated steps count towards stopping it.
    """
    protocol = protocol or TextProtocol()
    ctx.enabled = frozenset(enabled)
    known = known_tool_names()
    messages = list(api_messages)
    tracker = ProgressTracker()
    claim_checked = False
    gates = {"plan": 0, "verify": 0}
    same_error, sig = 0, ""                          # defined up-front: the idle-turn branch reads them before any tool ran
    err_counts: dict[str, int] = {}                   # same run error again and again = problem is not the code
    started = time.monotonic()
    step = 0
    task_idx = len(messages) - 1                      # the user's task; never dropped by _compact
    empty_turns = 0                                   # consecutive turns with no usable answer
    intent_turns = 0                                  # consecutive turns that only announced an action
    reason_turns = 0                                  # turns whose "answer" was the model's own English reasoning
    deliver_nudges = 0                                # how often the model was reminded of the task's named file type
    if "planning" in enabled and planlib.pending(ctx.plan):     # unfinished plan from earlier work in this chat
        messages[task_idx]["content"] += ("\n\n[PLÁN] Rozpracovaný plán z predošlej práce:\n" + planlib.render(ctx.plan))
    full_task = messages[task_idx].get("content") or ""
    has_attachment = "[Priložený súbor:" in full_task
    task_text = full_task.split("\n\n[Priložený súbor:")[0].split("\n\n[PLÁN]")[0]    # the user's own words only
    auto_runs = 0                                     # tests the agent started itself because the model never did

    def _auto(call: ToolCall, shown: str, note: str):
        """The agent performs a step that the model keeps announcing but never calls (the .bat, the test run)."""
        yield {"type": "nudge", "text": shown}
        yield {"type": "tool_call", "name": call.name, "args": call.args, "body": call.body}
        ok, result = run_tool(call, enabled, ctx)
        update_state(call, ok, result, ctx)
        yield {"type": "tool_result", "name": call.name, "ok": ok, "text": result, "progress": ok}
        extra = note + ("\n\n" + DIAG_NOTE if needs_diagnosis(call, ok, result) else "")
        messages.append(protocol.assistant_msg("", call, ""))
        messages.append(protocol.result_msg(call, ok, result, extra))

    yield {"type": "protocol", "name": protocol.name, "reason": ""}
    if fit_task(messages, task_idx, prompt_budget(url, model)):
        yield {"type": "nudge", "text": "Zadanie s prílohami bolo príliš dlhé pre okno modelu – prílohy som skrátil (agent ich číta nástrojmi)."}
    if "cluster" in enabled and "fs_write" in enabled and wants_cluster(task_text) and not has_attachment and find_tool("cluster_solve"):
        # Cluster is on: do NOT rely on a small model to decide - the team writes the code as the FIRST step.
        call = ToolCall("cluster_solve", {}, task_text)
        if "planning" in enabled and not planlib.pending(ctx.plan):      # the checklist the user sees
            check = "Spustiť súbor a overiť výsledok" if "run_code" in enabled else "Prečítať a skontrolovať súbor"
            ctx.plan[:] = planlib.parse_steps(
                f"Kód napíše tím klastra (architekt → programátor → recenzent)\n{check}")
        yield {"type": "nudge", "text": "Klaster je zapnutý – kód píše tím (architekt → programátor → recenzent)."}
        if ctx.plan:
            planlib.save(ctx.chat_id, ctx.plan)
            yield {"type": "plan"}                                       # the checklist is visible BEFORE the work
        forced = [call]
        fixes = 0
        last_run = None
        for call in forced:
            yield {"type": "tool_call", "name": call.name, "args": call.args, "body": call.body}
            ok, result = run_tool(call, enabled, ctx)
            update_state(call, ok, result, ctx)
            if call.name == "cluster_solve" and not (ok and ctx.written) and ctx.plan:
                ctx.plan.clear()                                         # the automatic checklist no longer applies
            if ctx.plan:
                if call.name == "cluster_solve" and ok and ctx.written:
                    ctx.plan[0]["done"] = True
                elif call.name in RUN_TOOLS and ok and result.startswith("Exit code 0") and len(ctx.plan) > 1:
                    ctx.plan[1]["done"] = True
                planlib.save(ctx.chat_id, ctx.plan)
            yield {"type": "tool_result", "name": call.name, "ok": ok, "text": result, "progress": ok}
            if call.name in RUN_TOOLS:
                last_run = (call, ok, result)
            mod = missing_module(call, result)
            unrequested = bool(mod) and mod.lower() not in task_text.lower() and fixes < 3 and "fs_write" in enabled
            env = "" if unrequested else env_problem(call, result)      # extra package nobody asked for: drop it, don't ask the user to install it
            if env:
                yield {"type": "final", "text": env}
                return
            notes = ("\n\n[PLÁN]\n" + planlib.render(ctx.plan)) if ctx.plan else ""
            if needs_diagnosis(call, ok, result):
                notes += ("\n\n[POKYN] Súbor sa nespustil. Teraz ZAVOLAJ read_file na " +
                          (call.args.get("path") or "súbor") + ", nájdi príčinu chyby a oprav ju cez write_file. "
                          "Nepopisuj, čo urobíš.\n\n") + DIAG_NOTE
            messages.append(protocol.assistant_msg("", call, ""))
            messages.append(protocol.result_msg(call, ok, result, notes))
            if (call.name in RUN_TOOLS and needs_diagnosis(call, ok, result) and fixes < 3 and call.args.get("path")
                    and "fs_write" in enabled):                          # broken code: repair it without the model's tool juggling
                fixes += 1
                yield {"type": "nudge", "text": f"Automatická oprava {fixes}/3 – chyba: {last_error_line(result)}"}
                hint = (f"Knižnicu `{mod}` NEMÁME nainštalovanú a zadanie ju nežiada: odstráň ju a použi len štandardnú knižnicu "
                        "a knižnice výslovne spomenuté v zadaní." if unrequested else "")
                code = auto_fix(url, model, temperature, call.args["path"], result, hint)
                if code:
                    forced.append(ToolCall("write_file", {"path": call.args["path"]}, code))
                    forced.append(ToolCall("run_code", {"path": call.args["path"]}, ""))
            if call.name == "cluster_solve" and ok and "run_code" in enabled:
                main = next((f for f in ctx.written if f.lower().endswith(RUNNABLE)), None)
                if main:                                                 # verification is automatic, not left to the model
                    forced.append(ToolCall("run_code", {"path": main}, ""))
        if last_run and needs_diagnosis(*last_run):                    # repairs did not help: do not let the model flail
            path = last_run[0].args.get("path", "súbor")
            yield {"type": "final", "text": (
                f"⚠️ **`{path}` sa po {fixes} automatických opravách stále nespúšťa.**\n\n"
                f"Posledná chyba:\n```\n{last_run[2][-1500:]}\n```\n"
                "Súbor je uložený vo `workspace/`. Pošli mi túto chybu, alebo napíš „pokračuj“ a skúsim ďalší postup.")}
            return
    while True:
        if step >= max_steps:
            yield {"type": "stopped", "reason": "steps",
                   "detail": f"Dosiahnutý bezpečnostný strop {max_steps} krokov."}
            return
        if time.monotonic() - started > max_seconds:
            yield {"type": "stopped", "reason": "time",
                   "detail": f"Uplynulo {int(max_seconds // 60)} minút – úloha beží príliš dlho."}
            return
        step += 1
        task_idx = _compact(messages, task_idx, prompt_budget(url, model))
        yield {"type": "turn_start", "step": step}
        content, stats, thought, native = "", {}, "", []
        try:
            for ev in stream_chat(url, model, messages, temperature, think=think_param, stop=protocol.stop,
                                  **protocol.request_extras(enabled)):
                if ev["type"] == "tool_calls":
                    native += ev["calls"]
                    continue
                if ev["type"] == "thinking":
                    thought += ev["text"]
                elif ev["type"] == "content":
                    content += ev["text"]
                elif ev["type"] == "done":
                    stats = ev["stats"]
                yield ev
        except ToolsUnsupported:                                  # model has no native tools: learn it, use text
            if protocol.name == "text":
                raise
            remember_protocol(url, model, "text")
            yield {"type": "turn_end", "text": "", "call": None, "stats": {}}
            messages = switch_protocol(messages, protocol, TextProtocol(), enabled)
            protocol = TextProtocol()
            yield {"type": "protocol", "name": protocol.name,
                   "reason": "Model nepodporuje natívne volanie nástrojov – používam textový protokol."}
            step -= 1
            continue
        if stats.get("truncated"):
            yield {"type": "nudge", "text": f"⚠️ Prompt ({stats.get('prompt_tokens')} tokenov) zaplnil celé okno {stats.get('ctx')} – "
                                           "Ollama mohla odrezať začiatok. Zmenšujem históriu."}
            task_idx = _compact(messages, task_idx, int(prompt_budget(url, model) * 0.6))
        before, call = protocol.extract(content, thought, native, known, written=ctx.written)
        if call is not None:
            empty_turns = intent_turns = reason_turns = 0
        yield {"type": "turn_end", "text": before, "call": call, "stats": stats}
        if call is None and stats.get("stopped") == "toolparse" and protocol.name != "text":
            # the native tool call came out as broken JSON (typical for big files in write_file): use text tags
            remember_protocol(url, model, "text")
            messages = switch_protocol(messages, protocol, TextProtocol(), enabled)
            protocol = TextProtocol()
            yield {"type": "protocol", "name": protocol.name,
                   "reason": "Model poslal pokazené natívne volanie nástroja – prepínam na textový protokol."}
            continue
        if call is None:
            if not content.strip():                      # empty answer: nudge instead of giving up silently
                empty_turns += 1
                if empty_turns == 2:
                    if think_param not in (None, False):
                        # reasoning eats the whole turn (gpt-oss then tries its own tool format): think less
                        think_param = "low" if model.lower().startswith("gpt-oss") else False
                    if protocol.name != "text":              # the structured route does not work here: text tags
                        messages = switch_protocol(messages, protocol, TextProtocol(), enabled)
                        protocol = TextProtocol()
                        yield {"type": "protocol", "name": protocol.name,
                               "reason": "Model opakovane nevolá nástroje natívne – prepínam na textový protokol."}
                tracker.note_idle()
                if tracker.is_stuck or same_error >= 5:
                    yield from _wrapup(url, model, messages, temperature, think_param, step, ctx)
                    yield {"type": "stopped", "reason": "stuck",
                           "detail": "Model opakovane nevrátil žiadnu odpoveď."}
                    return
                hint = thought.strip()[-400:]
                messages.append({"role": "user", "content": protocol.empty_nudge + (
                    f"\nTvoje posledné uvažovanie skončilo takto: «{hint}». Teraz z neho urob PRIAMO volanie nástroja."
                    if hint else "")})
                yield {"type": "nudge", "text": "Agent poslal prázdnu odpoveď – vyzvaný, aby pokračoval."}
                continue
            if deliver_nudges < 2 and "fs_write" in enabled and ctx.written:        # task asked for e.g. a .bat that was never written
                lacking = missing_deliverables(task_text, ctx.written)
                if lacking and deliver_nudges == 0:
                    deliver_nudges = 1
                    tracker.note_idle()
                    messages.append({"role": "assistant", "content": LEAK_RE.sub("", content).strip()})
                    messages.append({"role": "user", "content": (
                        "Zadanie spomína súbor typu " + ", ".join("." + e for e in lacking) + ", ale taký súbor si "
                        "nevytvoril. Ak ho zadanie naozaj chce, vytvor ho TERAZ nástrojom write_file "
                        "(napr. .bat: dva riadky `@echo off` a `python nazov.py`, potom `pause`). "
                        "Ak ho nechce, stručne odpovedz, že je hotovo.\n" + protocol.empty_nudge)})
                    yield {"type": "nudge", "text": "Zadanie spomína " + ", ".join("." + e for e in lacking)
                                                    + " súbor, ktorý ešte nevznikol – agent ho má vytvoriť."}
                    continue
                if lacking and deliver_nudges == 1:                  # reminded already: for a .bat we can build it ourselves
                    deliver_nudges = 2
                    auto = auto_bat(lacking, ctx)
                    if auto:
                        yield from _auto(auto, f"Model .bat nevytvoril ani po výzve – agent ho zostavil sám ({auto.args['path']}).",
                                         "\n[POZNÁMKA] Tento súbor vytvoril agent sám, lebo ho model nevytvoril. "
                                         "Pokračuj v úlohe (napr. spusti test), alebo ak je všetko hotové, zhrň výsledok.")
                        continue
            if "run_code" in enabled and not ctx.verified and auto_runs < 2 and (intent_turns >= 1 or gates["verify"] >= 1):
                target = next((str(w) for w in reversed(list(ctx.written)) if str(w).lower().endswith(RUNNABLE)), "")
                if target:                                   # reminded already and still no test: run it ourselves
                    auto_runs += 1
                    yield from _auto(ToolCall("run_code", {"path": target}, ""),
                                     f"Model kód nespustil ani po výzve – agent ho spustil sám ({target}).",
                                     "\n[POZNÁMKA] Tento test spustil agent sám. Ak výsledok ukazuje chybu, oprav ju (write_file); "
                                     "ak je všetko v poriadku, stručne zhrň výsledok používateľovi.")
                    continue
            work_left = (not ctx.written) or (not ctx.verified) or bool(planlib.pending(ctx.plan) if "planning" in enabled else [])
            if REASON_RE.match(content) and reason_turns < 2:      # internal reasoning leaked into the answer
                reason_turns += 1
                tracker.note_idle()
                messages.append({"role": "assistant", "content": ""})
                messages.append({"role": "user", "content": (
                    "Tvoj text bol interná úvaha v angličtine, nie odpoveď. Úloha používateľa zostáva: "
                    + task_text[:300].replace("\n", " ") + "\nPokračuj: zavolaj ďalší nástroj, alebo ak máš dosť "
                    "informácií, napíš výslednú odpoveď po slovensky.\n" + protocol.empty_nudge)})
                yield {"type": "nudge", "text": "Model napísal len vnútornú úvahu – vyzvaný, aby pokračoval nástrojom alebo odpoveďou."}
                continue
            if announces_action(content) and intent_turns < 3 and work_left:   # only said what it WILL do: make it do it
                intent_turns += 1
                tracker.note_idle()
                messages.append({"role": "assistant", "content": LEAK_RE.sub("", content).strip()})
                messages.append({"role": "user", "content": (
                    "Napísal si len zámer („Cieľ: …“) a nezavolal si nástroj, takže sa nič nestalo. "
                    "Zavolaj TERAZ nástroj, ktorý ten zámer vykoná (napr. write_file s celým kódom). "
                    "Nepíš ďalší opis ani plán.\n" + protocol.empty_nudge)})
                said = " ".join(content.split())[:90]
                yield {"type": "nudge", "text": f"Agent len ohlásil, čo urobí, a nástroj nezavolal – vyzvaný, aby ho zavolal. (napísal: „{said}“)"}
                continue
            if not claim_checked and "fs_write" in enabled:        # "I created X" without write_file?
                missing = claimed_missing_files(content, ctx.written)
                if missing:
                    claim_checked = True
                    tracker.note_idle()
                    note = claim_nudge(missing)
                    messages.append({"role": "assistant", "content": LEAK_RE.sub("", content).strip()})
                    messages.append({"role": "user", "content": note})
                    yield {"type": "nudge", "text": "Agent tvrdil, že vytvoril súbory, ktoré neexistujú – vyzvaný, aby ich naozaj vytvoril."}
                    continue
            gate = finish_gate(enabled, ctx, gates)
            if gate:                                             # plan unfinished / result not verified
                note, shown = gate
                messages.append({"role": "assistant", "content": LEAK_RE.sub("", content).strip()})
                messages.append({"role": "user", "content": note})
                yield {"type": "nudge", "text": shown}
                continue
            final_text = re.sub(r"^\s*(?:Cieľ|Ciel|Goal)\s*:\s*", "", LEAK_RE.sub("", content).strip(), flags=re.I)
            if announces_action(content):                         # the last word is a stub ("Počkám na testovanie…")
                if ctx.written:                                   # work exists: let the model summarise it honestly
                    yield from _wrapup(url, model, messages, temperature, think_param, step, ctx)
                    return
                final_text = ("⚠️ **Model len ohlásil, čo urobí, a nástroj nezavolal.** Napíš „pokračuj“ alebo "
                              "skús silnejší model (gpt-oss:20b) / zapni 🤝 Klastrovú spoluprácu.")
            left = planlib.pending(ctx.plan) if "planning" in enabled else []
            if left:                                             # the model gave up: say so instead of looking done
                final_text += ("\n\n⚠️ **Úloha nie je dokončená** – model skončil, hoci v pláne zostáva: "
                               + "; ".join(left) + ". Napíš „pokračuj“ a agent naváže.")
            yield {"type": "final", "text": final_text}
            return
        yield {"type": "tool_call", "name": call.name, "args": call.args, "body": call.body}
        ok, result = run_tool(call, enabled, ctx)
        update_state(call, ok, result, ctx)
        if ok:                                                   # real work done: the finish gates may fire again
            gates["plan"] = gates["verify"] = 0
        progress = tracker.record(call, ok, result, no_progress=result.startswith(NO_CHANGE))
        yield {"type": "tool_result", "name": call.name, "ok": ok, "text": result, "progress": progress}
        env = env_problem(call, result)
        if env:
            yield {"type": "final", "text": env}
            return
        notes = ""
        if ok and not progress:
            notes += "\n[POZNÁMKA] Toto volanie si už robil – opakovanie nepomáha, skús niečo iné."
        same_error = 0
        if call.name in RUN_TOOLS and needs_diagnosis(call, ok, result):
            lines = [l.strip() for l in result.splitlines() if l.strip()]
            sig = (lines[-1] if lines else "")[:200]
            err_counts[sig] = err_counts.get(sig, 0) + 1
            same_error = err_counts[sig]
            if same_error == 3:
                notes += "\n\n" + ENV_NOTE
        if needs_diagnosis(call, ok, result):
            notes += "\n\n" + DIAG_NOTE
        if "planning" in enabled and ctx.plan:                   # the plan is shown after EVERY step
            notes += "\n\n[PLÁN]\n" + planlib.render(ctx.plan)
        if tracker.is_stuck:
            messages.append(protocol.assistant_msg(before, call, thought))
            messages.append(protocol.result_msg(call, ok, result, notes))
            yield from _wrapup(url, model, messages, temperature, think_param, step, ctx)
            yield {"type": "stopped", "reason": "stuck",
                   "detail": (f"Rovnaká chyba sa zopakovala {same_error}× („{sig}“) – pravdepodobne nejde o chybu v kóde, "
                              "ale v prostredí (verzia Pythonu / knižnice). Skús `pip install -U flask werkzeug` "
                              "alebo aktualizovať príslušnú knižnicu." if same_error >= 5 else
                              f"{AGENT_STALL_LIMIT} krokov po sebe bez pokroku (chyby alebo opakovanie).")}
            return
        if tracker.should_nudge:
            notes += "\n\n" + NUDGE
            yield {"type": "nudge", "text": "Agent sa zasekol – dostal pokyn zmeniť postup."}
        messages.append(protocol.assistant_msg(before, call, thought))
        messages.append(protocol.result_msg(call, ok, result, notes))
