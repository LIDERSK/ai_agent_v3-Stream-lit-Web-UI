"""Universal tool-calling layer: ONE tool definition, ANY model.

Our tools are defined once (core/skills: name, usage, Param list). This module translates them to whatever a
model speaks and translates the model's call back to our internal `ToolCall`:

    skills (Tool + Param)  ──►  Protocol  ──►  model
                           ◄──  extract() ◄──  (native tool_calls | <tool/> text | JSON | <tool_call> | harmony)

Protocols (add your own with @register_protocol - nothing else in the app has to change):
    native  Ollama `tools` field + `tool_calls` / role "tool" messages (gpt-oss, qwen, llama3.1, ...)
    text    plain-text tags  <tool name="x" arg="v">body</tool>  - works with ANY model

`extract()` is shared by all protocols and understands every format we know, so even a model that answers in
a different format than the one asked for still gets its call executed (the "universal translator").
Auto-selection: the highest-priority protocol whose `supports(model, caps)` is True; what does not work on a
given PC + model is learned (settings.json) and avoided next time.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from config import TEXT_ONLY_MODELS, TOOL_PROTOCOL
from core import settings_store
from core.skills import SKILLS, Tool, find_tool, tools_for


# ----------------------------------------------------------------- internal call
@dataclass
class ToolCall:
    name: str
    args: dict
    body: str

    def canonical(self) -> str:
        """The call in our text format (also how it is shown / stored)."""
        attrs = "".join(f' {k}="{v}"' for k, v in self.args.items())
        head = f'<tool name="{self.name}"{attrs}'
        return f"{head}>\n{self.body}\n</tool>" if self.body else f"{head}/>"

    def native_args(self) -> dict:
        """Arguments as a JSON object for native tool calling (body goes back into its named parameter)."""
        out = dict(self.args)
        if self.body:
            found = find_tool(self.name)
            out[(found[1].body_param() if found else "") or "content"] = self.body
        return out


def known_tool_names() -> set[str]:
    return {t.name for s in SKILLS.values() for t in s.tools}


# ----------------------------------------------------------------- text format <tool .../>
TOOL_RE = re.compile(r"<tool\b([^>]*?)(/?)>", re.S)
ATTR_RE = re.compile(r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')')


def _clean_body(body: str) -> str:
    body = body.strip("\n")
    lines = body.splitlines()
    if lines and lines[0].lstrip().startswith("```"):          # model wrapped content in a fence
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        body = "\n".join(lines)
    return body.rstrip() + ("\n" if body.strip() else "")


def parse_tool_call(text: str) -> tuple[str, ToolCall | None]:
    """Return (text_before_the_call, first_call_or_None). Anything after the first call is ignored."""
    m = TOOL_RE.search(text)
    if not m:
        return text.strip(), None
    attrs = {k: (a or b) for k, a, b in ATTR_RE.findall(m.group(1))}
    name = attrs.pop("name", "").strip()
    body = ""
    if not m.group(2):                                          # <tool ...> body </tool>
        close = text.find("</tool>", m.end())
        body = _clean_body(text[m.end(): close if close != -1 else len(text)])
    return text[:m.start()].strip(), ToolCall(name, attrs, body)


# ----------------------------------------------------------------- argument translation
_ALIASES = {                      # canonical param -> names other models like to use
    "path": ("file_path", "filepath", "filename", "file_name", "file"),
    "query": ("q", "search_query", "search"),
    "to": ("new_path", "new_name", "target", "dest", "destination"),
    "step": ("steps", "number"),
}
_BODY_ALIASES = ("content", "body", "text", "code", "contents", "file_text", "file_content",
                 "changes", "edits", "patch", "diff")


def _s(value) -> str:
    """Our tools take strings; models send numbers, booleans, lists..."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return "\n".join(_s(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else str(value)


def normalize_args(tool: Tool | None, raw) -> tuple[dict, str]:
    """Model arguments (any shape) -> (args, body) in the form our tools expect."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    raw = dict(raw) if isinstance(raw, dict) else {}
    body = ""
    if tool:
        specs = {p.name for p in tool.param_specs()}
        for canon, aliases in _ALIASES.items():
            if canon in specs and canon not in raw:
                for a in aliases:
                    if a in raw and a not in specs:
                        raw[canon] = raw.pop(a)
                        break
        bp = tool.body_param()
        if bp:
            if bp not in raw:
                for a in _BODY_ALIASES:
                    if a in raw and a not in specs:
                        raw[bp] = raw.pop(a)
                        break
            if bp in raw:
                body = _s(raw.pop(bp))
    return {k: _s(v) for k, v in raw.items()}, body


def call_from_native(item: dict) -> ToolCall:
    """One entry of Ollama's message.tool_calls -> ToolCall."""
    fn = item.get("function", item)
    name = str(fn.get("name", "")).strip()
    if name.startswith("functions."):
        name = name[len("functions."):]
    found = find_tool(name)
    args, body = normalize_args(found[1] if found else None, fn.get("arguments"))
    return ToolCall(name, args, body)


def tool_schemas(enabled) -> list[dict]:
    """JSON schema of every enabled tool in the shape Ollama / OpenAI expect."""
    out = []
    for _, t in tools_for(enabled):
        specs = t.param_specs()
        out.append({"type": "function", "function": {
            "name": t.name,
            "description": t.usage,
            "parameters": {
                "type": "object",
                "properties": {p.name: {"type": p.type, **({"description": p.description} if p.description else {})}
                               for p in specs},
                "required": [p.name for p in specs if p.required],
            }}})
    return out


# ----------------------------------------------------------------- foreign formats ("universal translator")
_TAIL_OK = re.compile(r"[\s`]*(?:(?:</?tool_call>|<\|[^|>]*\|>)[\s`]*)*")
_FN_NAME = re.compile(r"(?:to=functions\.|functions\.|to=)([A-Za-z_]\w*)")
_HERMES = re.compile(r"<tool_call>(.*?)(?:</tool_call>|$)", re.S)
_DEC = json.JSONDecoder()


def _call_from_obj(obj, known: set[str], hint: str = "") -> ToolCall | None:
    if isinstance(obj, list) and len(obj) == 1:
        obj = obj[0]
    if not isinstance(obj, dict):
        return None
    if isinstance(obj.get("tool_calls"), list) and obj["tool_calls"]:        # {"tool_calls":[{"function":{...}}]}
        return _call_from_obj(obj["tool_calls"][0], known)
    inner = obj["function"] if isinstance(obj.get("function"), dict) else obj
    name = next((inner[k] for k in ("name", "tool", "tool_name", "function_name") if isinstance(inner.get(k), str)), None)
    if name is None and isinstance(obj.get("function"), str):
        name = obj["function"]
    args = next((inner[k] for k in ("arguments", "parameters", "args", "input") if k in inner), None)
    if name is None and hint:                                                # harmony: name outside, args = object
        name, args = hint, (obj if args is None else args)
    if not name:
        return None
    name = name[len("functions."):] if name.startswith("functions.") else name
    if name not in known:
        return None
    return ToolCall(name, *normalize_args(find_tool(name)[1], args))


def parse_foreign(text: str, known: set[str] | None = None) -> tuple[str, ToolCall | None]:
    """A tool call in any other format a model may use:
         <tool_call>{"name": ..., "arguments": {...}}</tool_call>          (Hermes / Qwen)
         {"name": ..., "arguments": {...}}  /  {"tool": ..., "args": ...}   (plain or fenced JSON)
         <|channel|>commentary to=functions.NAME <|message|>{...}<|call|>   (gpt-oss / harmony)
       Only a known tool name counts, and plain JSON only at the END of the text (so an answer that merely
       quotes an example is not executed). Returns (text_before, call_or_None)."""
    known = known or known_tool_names()
    text = text[-30000:]
    m = _HERMES.search(text)
    if m:
        try:
            call = _call_from_obj(json.loads(m.group(1).strip()), known)
        except ValueError:
            call = None
        if call:
            return text[:m.start()].strip(), call
    pos, tries = text.find("{"), 0
    while pos != -1 and tries < 400:
        tries += 1
        try:
            obj, end = _DEC.raw_decode(text, pos)
        except ValueError:
            pos = text.find("{", pos + 1)
            continue
        if _TAIL_OK.fullmatch(text, end):
            names = _FN_NAME.findall(text[:pos])
            call = _call_from_obj(obj, known, names[-1] if names else "")
            if call:
                before = re.sub(r"(```\w*|<tool_call>|<\|[^|>]*\|>|\bto=functions\.\w+|commentary|analysis)\s*$", "",
                                text[:pos].rstrip()).rstrip()
                return before.split("<|channel|>")[0].strip(), call
        pos = text.find("{", pos + 1)
    return text.strip(), None


_LOOSE_ARG = re.compile(r"(\w+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')")


_QBODY = re.compile(r"""^\W*(\w+)((?:[ \t]+\w+\s*=\s*(?:"[^"\n]*"|'[^'\n]*'))+)\s*\+?\s*(?:\"\"\"|\'\'\')(.*?)(?:\"\"\"|\'\'\')\s*$""",
                    re.S | re.M)


def parse_quoted_body(text: str, known: set[str]) -> tuple[str, ToolCall | None]:
    """write_file path="a.py" + \"\"\"...code...\"\"\"   (content in triple quotes at the END of the text)"""
    for m in _QBODY.finditer(text):
        if m.group(1) in known and not text[m.end():].strip():
            args = {a: (b or c) for a, b, c in _LOOSE_ARG.findall(m.group(2))}
            return text[:m.start()].strip(), ToolCall(m.group(1), args, _clean_body(m.group(3)))
    return text.strip(), None


def parse_loose(text: str, known: set[str]) -> tuple[str, ToolCall | None]:
    """Last line written like a function call without tags:  run_code path="app.py"  /  list_files"""
    before, call = parse_quoted_body(text, known)
    if call:
        return before, call
    lines = text.rstrip().splitlines()
    if not lines:
        return text.strip(), None
    last = lines[-1].strip().strip("`").strip()
    loose = re.match(r"^(?:\W*\b(?:zavolaj|zavolám|spustím|použi)\b\s+)?(\w+)\b[^=\n]*?((?:\s*\w+\s*=\s*(?:\"[^\"]*\"|'[^']*'))+)\s*\.?$", last, re.I)
    if loose and loose.group(1) in known:                          # "Zavolaj run_code s argumentom path="a.py"."
        args = {a: (b or c) for a, b, c in _LOOSE_ARG.findall(loose.group(2))}
        return "\n".join(lines[:-1]).strip(), ToolCall(loose.group(1), args, "")
    m = re.match(r"^(\w+)((?:\s+\w+\s*=\s*(?:\"[^\"]*\"|'[^']*'))*)\s*/?>?$", last)
    if not m or m.group(1) not in known:
        return text.strip(), None
    args = {a: (b or c) for a, b, c in _LOOSE_ARG.findall(m.group(2))}
    return "\n".join(lines[:-1]).strip(), ToolCall(m.group(1), args, "")


# ----------------------------------------------------------------- announced intent + code block
INTENT_RE = re.compile(                                  # "Cieľ: Vytvorím súbor…" / "Teraz vytvorím…" = announced, not done
    r"^\s*(?:(?:Cieľ|Ciel|Goal)\s*:|(?:(?:Teraz|Následne|Potom)\s+)?(?:vytvorím|uložím|zapíšem|napíšem|spustím|overím|prečítam)\b)",
    re.I)
_ACTION_RE = re.compile(r"\b(?:vytvorím|uložím|zapíšem|napíšem|spustím|overím|prečítam|skontrolujem|pridám|upravím|opravím|"
                        r"zavolám|nainštalujem|vytvoriť|spustiť|overiť|prečítať|zapísať|uložiť)\b", re.I)
_DONE_RE = re.compile(r"\bhotov|dokonč|úspešn|vytvoril som|uložil som|spustil som|bez chýb|je vytvoren|sú vytvoren", re.I)


def announces_action(text: str) -> bool:
    """True only for a short "Cieľ: Vytvorím súbor…" that PROMISES an action. The prompt makes the model start every
    step with "Cieľ:", so its closing summary ("Cieľ: Kalkulačka je hotová.") must NOT count as an unfinished stub."""
    t = (text or "").strip()
    if not t or len(t) > 400 or not INTENT_RE.match(t):
        return False
    return bool(_ACTION_RE.search(t.splitlines()[0])) and not _DONE_RE.search(t)


_FENCE = re.compile(r"```[ \t]*([\w+#-]*)[ \t]*\n(.*?)\n?```", re.S)
_FNAME = re.compile(r"(?<![\w./\\-])((?:[\w-]+[/\\])*[\w-]+\.(?:bat|cmd|py|txt|html?|js|c|cpp|h|json|md|css|sh|ps1|csv|ini|ya?ml))\b", re.I)
_LANG_EXT = {"bat": ("bat", "cmd"), "batch": ("bat", "cmd"), "cmd": ("cmd", "bat"), "dos": ("bat",), "batchfile": ("bat",),
             "python": ("py",), "py": ("py",), "html": ("html", "htm"), "javascript": ("js",), "js": ("js",),
             "c": ("c",), "cpp": ("cpp",), "c++": ("cpp",), "json": ("json",), "bash": ("sh",), "sh": ("sh",),
             "powershell": ("ps1",), "ps1": ("ps1",), "css": ("css",), "markdown": ("md",), "md": ("md",), "text": ("txt",), "txt": ("txt",)}


def parse_implicit_write(text: str, known: set[str], written=()) -> tuple[str, ToolCall | None]:
    """A model that announces a file ("Cieľ: Vytvorím súbor start.bat") and puts the content into ONE code block
    instead of calling write_file. Used only for such announcing turns (see INTENT_RE), never for a normal answer."""
    if "write_file" not in known:
        return text.strip(), None
    fences = list(_FENCE.finditer(text))
    if len(fences) != 1:
        return text.strip(), None
    m = fences[0]
    head, lang = text[:m.start()], m.group(1).lower()
    names = [n.replace("\\", "/") for n in _FNAME.findall(head)]
    exts = _LANG_EXT.get(lang, ())
    path = next((n for n in names if n.rsplit(".", 1)[-1].lower() in exts), names[0] if names else "")
    if not path and lang in ("bat", "batch", "cmd", "dos", "batchfile"):          # unnamed batch file: next to the last script
        py = next((str(w) for w in reversed(list(written)) if str(w).lower().endswith(".py")), "")
        path = (py.rsplit(".", 1)[0] + ".bat") if py else "spustit.bat"
    if not path:
        return text.strip(), None
    body = _clean_body(m.group(2))
    try:                                                         # never let a snippet replace a bigger existing file
        from core import workspace
        target = workspace.safe_path(path)
        if target.is_file() and len(body) < 0.7 * target.stat().st_size:
            return text.strip(), None
    except Exception:
        pass
    return head.strip(), ToolCall("write_file", {"path": path}, body)


# ----------------------------------------------------------------- protocols
class ToolProtocol:
    """How tools are offered to a model and how calls / results travel in the message list."""
    name = ""
    label = ""
    priority = 0                       # auto-selection: highest priority among those that support the model
    stop: list | None = None           # stop sequences for the request
    empty_nudge = ""

    @classmethod
    def supports(cls, model: str, caps) -> bool:
        return True

    def request_extras(self, enabled) -> dict:
        """Extra keyword arguments for stream_chat (e.g. tools=[...])."""
        return {}

    def system_section(self, enabled) -> str:
        """Text for the system prompt: how to call tools. Must be deterministic (it is swapped on fallback)."""
        raise NotImplementedError

    def assistant_msg(self, before: str, call: ToolCall, thought: str = "") -> dict:
        raise NotImplementedError

    def result_msg(self, call: ToolCall, ok: bool, result: str, notes: str = "") -> dict:
        raise NotImplementedError

    def extract(self, content: str, thought: str, native: list, known: set[str] | None = None,
                written=()) -> tuple[str, ToolCall | None]:
        """(text_before_call, call) from one model turn - whatever format the model used."""
        known = known or known_tool_names()
        if native:                                                           # structured call from the server
            return content.strip(), call_from_native(native[0])
        before, call = parse_tool_call(content)
        if call is None and content.strip():
            before, call = parse_foreign(content, known)
        if call is None and content.strip():
            before, call = parse_loose(content, known)
        if call is None and INTENT_RE.match(content):                         # announced a file + code block
            before, call = parse_implicit_write(content, known, written)
        if call is None and not content.strip():                             # call hidden in the reasoning
            _, call = parse_tool_call(thought)
            if call is None:
                _, call = parse_foreign(thought, known)
            before = ""
        return before, call


PROTOCOLS: dict[str, type[ToolProtocol]] = {}


def register_protocol(cls: type[ToolProtocol]) -> type[ToolProtocol]:
    PROTOCOLS[cls.name] = cls
    return cls


TEXT_SECTION = (
    "Nástroj zavoláš tak, že PRIAMO napíšeš značku <tool ...> – nestačí napísať, že ho zavoláš. Zavolaj "
    "JEDEN nástroj naraz a hneď za značkou skonči odpoveď. Systém nástroj vykoná SÁM a výsledok ti pošle "
    "ako ďalšiu správu; na nič nemusíš čakať ani to oznamovať. Nikdy nevymýšľaj výsledky nástrojov.\n"
    "Príklad prvého kroku: <tool name=\"list_files\"/>\n\n"
    "FORMÁT:\n<tool name=\"názov\" argument=\"hodnota\"/>\n"
    "alebo, ak nástroj berie obsah:\n<tool name=\"názov\" argument=\"hodnota\">\nobsah\n</tool>\n\n"
    "DOSTUPNÉ NÁSTROJE:\n{tools}")

NATIVE_SECTION = (
    "Nástroje voláš cez rozhranie na volanie funkcií (tool calling), NIE textom v odpovedi – nepíš značky "
    "<tool> ani JSON. Zavolaj JEDEN nástroj naraz; systém ho vykoná SÁM a výsledok ti pošle v správe s rolou "
    "tool, na nič nemusíš čakať. Nikdy nevymýšľaj výsledky nástrojov. Prvý krok napr.: zavolaj list_files.\n\n"
    "DOSTUPNÉ NÁSTROJE:\n{tools}")


@register_protocol
class TextProtocol(ToolProtocol):
    name = "text"
    label = "textové značky"
    priority = 0
    stop = ["</tool>", "<tool_result", "[VÝSLEDOK NÁSTROJA"]
    empty_nudge = ("[UPOZORNENIE] Tvoja odpoveď neobsahovala nástroj ani výsledok. Nepopisuj, čo zavoláš – napíš "
                   "PRIAMO značku, napr. <tool name=\"list_files\"/>. Systém ju vykoná sám, nemusíš čakať. "
                   "Ak je úloha hotová, odpovedz používateľovi výsledkom.")

    def system_section(self, enabled) -> str:
        from core.skills import tool_prompt
        return TEXT_SECTION.replace("{tools}", tool_prompt(enabled))

    def assistant_msg(self, before, call, thought=""):
        return {"role": "assistant", "content": (before + "\n" if before else "") + call.canonical()}

    def result_msg(self, call, ok, result, notes=""):
        return {"role": "user", "content": (
            f"[VÝSLEDOK NÁSTROJA {call.name}] {'OK' if ok else 'CHYBA'}\n{result}\n"
            "[KONIEC VÝSLEDKU]\nPokračuj v úlohe. Ak je hotová, odpovedz používateľovi "
            "bez volania nástroja." + notes)}


@register_protocol
class NativeProtocol(ToolProtocol):
    name = "native"
    label = "natívne volanie nástrojov"
    priority = 20
    stop = None
    empty_nudge = ("[UPOZORNENIE] Tvoja odpoveď neobsahovala volanie nástroja ani výsledok. Zavolaj nástroj cez "
                   "rozhranie funkcií (nepíš ho ako text) alebo, ak je úloha hotová, odpovedz používateľovi "
                   "výsledkom.")

    @classmethod
    def supports(cls, model, caps) -> bool:
        return "tools" in caps

    def request_extras(self, enabled) -> dict:
        schemas = tool_schemas(enabled)
        return {"tools": schemas} if schemas else {}

    def system_section(self, enabled) -> str:
        lines = "\n".join(f"- {t.name}: {t.usage}" for _, t in tools_for(enabled))
        return NATIVE_SECTION.replace("{tools}", lines)

    def assistant_msg(self, before, call, thought=""):
        msg = {"role": "assistant", "content": before,
               "tool_calls": [{"function": {"name": call.name, "arguments": call.native_args()}}]}
        if thought.strip():                       # gpt-oss & co. work better when their reasoning is passed back
            msg["thinking"] = thought.strip()[-1500:]
        return msg

    def result_msg(self, call, ok, result, notes=""):
        return {"role": "tool", "tool_name": call.name, "content": (
            f"{'OK' if ok else 'CHYBA'}\n{result}\n"
            "Pokračuj v úlohe. Ak je hotová, odpovedz používateľovi bez volania nástroja." + notes)}


# ----------------------------------------------------------------- choosing / switching
def _pkey(url: str, model: str) -> str:
    return f"{url}|{model}"


def choose_protocol(url: str, model: str, caps=None) -> ToolProtocol:
    """settings.json / config.py force a protocol; otherwise the best one this model supports, minus what
    was learned NOT to work on this PC + model."""
    if caps is None:
        from core.ollama_client import get_capabilities
        caps = get_capabilities(url, model)
    forced = settings_store.get("tool_protocol", None) or TOOL_PROTOCOL
    if forced in PROTOCOLS:
        return PROTOCOLS[forced]()
    learned = (settings_store.get("protocol_limits", {}) or {}).get(_pkey(url, model))
    if learned in PROTOCOLS:
        return PROTOCOLS[learned]()
    if any(s.lower() in model.lower() for s in TEXT_ONLY_MODELS):
        return PROTOCOLS["text"]()
    best = max((c for c in PROTOCOLS.values() if c.supports(model, caps)), key=lambda c: c.priority)
    return best()


def remember_protocol(url: str, model: str, name: str) -> None:
    limits = dict(settings_store.get("protocol_limits", {}) or {})
    limits[_pkey(url, model)] = name
    settings_store.put("protocol_limits", limits)


def to_text_history(messages: list[dict]) -> list[dict]:
    """Rewrite native tool messages as text-protocol messages (used when we fall back mid-run)."""
    text, out = TextProtocol(), []
    for m in messages:
        if m["role"] == "tool":
            out.append({"role": "user", "content":
                        f"[VÝSLEDOK NÁSTROJA {m.get('tool_name', '?')}] {m['content']}\n[KONIEC VÝSLEDKU]"})
        elif m["role"] == "assistant" and m.get("tool_calls"):
            fn = m["tool_calls"][0]["function"]
            call = call_from_native(m["tool_calls"][0])
            out.append(text.assistant_msg(m.get("content", "") or "", call))
        else:
            out.append({k: v for k, v in m.items() if k != "thinking"})
    return out


def switch_protocol(messages: list[dict], old: ToolProtocol, new: ToolProtocol, enabled) -> list[dict]:
    """New message list for `new`: swapped system section, history rewritten into its format."""
    if new.name == "text":
        messages = to_text_history(messages)
    old_sec, new_sec = old.system_section(enabled), new.system_section(enabled)
    sysmsg = dict(messages[0])
    sysmsg["content"] = (sysmsg["content"].replace(old_sec, new_sec) if old_sec in sysmsg["content"]
                         else sysmsg["content"] + "\n\n" + new_sec)
    return [sysmsg, *messages[1:]]
