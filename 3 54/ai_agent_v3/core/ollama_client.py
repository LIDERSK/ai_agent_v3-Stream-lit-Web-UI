"""Everything that talks to an Ollama server. No Streamlit imports here."""
from __future__ import annotations

import http.client
import json
import re
import socket
import threading
import time
from urllib.parse import urlsplit

import requests

from config import AUTO_FIT, FIT_MIN_CTX, FORCE_GPU, FORCE_GPU_MAX_SPILL, FIT_MIN_GPU, KEEP_ALIVE, LOOP_GUARD, MAX_NEW_TOKENS, MAX_THINK_CHARS, NUM_CTX, REPEAT_PENALTY
from core import loopguard, settings_store
from core.thinking import ThinkSplitter
from core.utils import ttl_cache


class OllamaError(Exception):
    """Human-readable error for anything that goes wrong talking to a node."""


class ToolsUnsupported(OllamaError):
    """The model does not accept the `tools` field (no native tool calling)."""


# ----------------------------------------------------------------- discovery
@ttl_cache(10)
def check_node(url: str) -> tuple[bool, tuple[str, ...]]:
    """(is_online, installed_model_names)"""
    try:
        r = requests.get(f"{url}/api/tags", timeout=1.5)
        r.raise_for_status()
        return True, tuple(m["name"] for m in r.json().get("models", []))
    except Exception:
        return False, ()


@ttl_cache(10)
def list_models(url: str) -> tuple[dict, ...]:
    """Installed models on a PC with sizes: ({'name', 'size'}, ...) - detected live from Ollama (/api/tags)."""
    try:
        r = requests.get(f"{url}/api/tags", timeout=1.5)
        r.raise_for_status()
        return tuple({"name": m["name"], "size": m.get("size") or 0} for m in r.json().get("models", []))
    except Exception:
        return ()


def model_installed(installed, name: str) -> bool:
    return name in installed or f"{name}:latest" in installed


_THINK_NAMES = ("qwen3", "deepseek-r1", "gpt-oss", "qwq", "magistral", "phi4-reasoning")
_TOOL_NAMES = ("gpt-oss", "qwen3", "qwen2.5", "llama3.1", "llama3.2", "llama3.3", "mistral", "command-r", "granite")
_VISION_NAMES = ("vl", "llava", "vision", "minicpm-v", "gemma3", "moondream", "bakllava", "llama4")


@ttl_cache(300)
def get_capabilities(url: str, model: str) -> frozenset:
    """e.g. {'completion', 'vision', 'thinking'}. Uses /api/show, falls back to name heuristics."""
    try:
        r = requests.post(f"{url}/api/show", json={"model": model}, timeout=4)
        r.raise_for_status()
        caps = r.json().get("capabilities")
        if caps:
            return frozenset(caps)
    except Exception:
        pass
    name, caps = model.lower(), {"completion"}
    if any(k in name for k in _THINK_NAMES):
        caps.add("thinking")
    if any(k in name for k in _VISION_NAMES):
        caps.add("vision")
    if any(k in name for k in _TOOL_NAMES):
        caps.add("tools")
    return frozenset(caps)


@ttl_cache(4)
def loaded_models(url: str) -> tuple:
    """Models currently in memory on that PC: name, size, how much of it is on the GPU (gpu_pct)."""
    try:
        r = requests.get(f"{url}/api/ps", timeout=1.5)
        r.raise_for_status()
        out = []
        for m in r.json().get("models", []):
            size, vram = m.get("size") or 0, m.get("size_vram") or 0
            out.append({"name": m.get("name") or m.get("model") or "?", "size": size,
                        "gpu_pct": round(100 * vram / size) if size else None, "ctx": m.get("context_length")})
        return tuple(out)
    except Exception:
        return ()


def unload_all(url: str) -> int:
    """Free the memory: unload every model on that PC (they load again on the next message). Returns count."""
    n = 0
    for m in loaded_models(url):
        try:
            requests.post(f"{url}/api/generate", json={"model": m["name"], "keep_alive": 0}, timeout=10)
            n += 1
        except Exception:
            pass
    loaded_models.cache_clear()
    return n


def clear_caches() -> None:
    check_node.cache_clear()
    list_models.cache_clear()
    get_capabilities.cache_clear()
    loaded_models.cache_clear()


# ----------------------------------------------------------------- chat
def _error_text(resp: requests.Response) -> str:
    try:
        return resp.json().get("error") or resp.text
    except Exception:
        return resp.text or f"HTTP {resp.status_code}"


def _stats(data: dict) -> dict:
    ptok, ctok = data.get("prompt_eval_count"), data.get("eval_count")
    dur = (data.get("eval_duration") or 0) / 1e9
    return {"prompt_tokens": ptok, "completion_tokens": ctok,
            "tok_per_s": round(ctok / dur, 1) if ctok and dur else None,
            "stopped": "length" if data.get("done_reason") == "length" else None}


def _is_toolparse_error(text: str) -> bool:
    """Ollama could not parse a tool call the model wrote in its own (harmony) format - e.g. gpt-oss.
    We use our own text protocol, so this is only noise at the end of / inside a turn."""
    t = text.lower()
    return ("error parsing tool call" in t or "invalid tool call arguments" in t
            or ("tool call" in t and "unexpected end of json" in t))


_RAW_RE = re.compile(r"raw='(.*)',\s*err=", re.S)


def toolparse_raw(text: str) -> str:
    """The text the model put into its (unparsable) native tool call, so we can still use it."""
    m = _RAW_RE.search(text)
    return m.group(1).strip() if m else ""


def _salvage(err_text: str, got_content: bool):
    """Events for the text hidden in an 'error parsing tool call' message: a text-protocol <tool .../> is
    returned as content (the agent runs it); anything else is only reasoning and is shown as thinking."""
    raw = toolparse_raw(err_text)
    if not raw:
        return
    if "<tool" in raw and not got_content:
        yield {"type": "content", "text": raw}
    else:
        yield {"type": "thinking", "text": raw}


def _parse_stream(resp, guard: bool = LOOP_GUARD):
    """Yields thinking / content events. Ends early (done with stats['stopped']) when the model loops:
       'loop' = same block repeated, 'think_runaway' = thinking far too long, 'length' = token cap reached."""
    splitter = ThinkSplitter()
    content = thinking = ""
    checked_c = checked_t = 0

    def feed(kind: str, text: str):
        nonlocal content, thinking
        if kind == "thinking":
            thinking += text
        else:
            content += text
        return {"type": kind, "text": text}

    for line in resp.iter_lines():
        if not line:
            continue
        data = json.loads(line)
        if data.get("error"):
            if _is_toolparse_error(str(data["error"])):          # gpt-oss tried its own tool format: not fatal
                for kind, text in splitter.flush():
                    yield feed(kind, text)
                for ev in _salvage(str(data["error"]), bool(content.strip())):
                    yield feed(ev["type"], ev["text"])
                yield {"type": "done", "stats": {"stopped": "toolparse"}}
                return
            raise OllamaError(data["error"])
        msg = data.get("message") or {}
        if msg.get("thinking"):                                  # native thinking field
            yield feed("thinking", msg["thinking"])
        if msg.get("tool_calls"):                                # native tool call(s) parsed by Ollama
            yield {"type": "tool_calls", "calls": [
                {"function": {"name": (c.get("function") or {}).get("name", ""),
                              "arguments": (c.get("function") or {}).get("arguments") or {}}}
                for c in msg["tool_calls"]]}
        if msg.get("content"):                                   # may contain <think> tags
            for kind, text in splitter.feed(msg["content"]):
                yield feed(kind, text)
        if data.get("done"):
            for kind, text in splitter.flush():
                yield feed(kind, text)
            yield {"type": "done", "stats": _stats(data)}
            return
        if not guard:
            continue
        if len(content) - checked_c >= loopguard.CHECK_EVERY:
            checked_c = len(content)
            if loopguard.find_loop(content):
                yield {"type": "done", "stats": {"stopped": "loop"}}
                return
        if len(thinking) - checked_t >= loopguard.CHECK_EVERY and not content:
            checked_t = len(thinking)
            if len(thinking) > MAX_THINK_CHARS or loopguard.find_loop(thinking):
                yield {"type": "done", "stats": {"stopped": "think_runaway"}}
                return


# ----------------------------------------------------------------- abortable streaming request
class _Resp:
    """Minimal response object (status_code / text / json / iter_lines / close) over http.client, so the
    connection can be torn down from another thread while Ollama is still loading the model."""

    def __init__(self, conn: http.client.HTTPConnection, resp: http.client.HTTPResponse):
        self._conn, self._r, self.status_code, self._body = conn, resp, resp.status, None

    @property
    def text(self) -> str:
        if self._body is None:
            try:
                self._body = self._r.read().decode("utf-8", "replace")
            except Exception:
                self._body = ""
        return self._body

    def json(self):
        return json.loads(self.text)

    def iter_lines(self):
        while True:
            line = self._r.readline()
            if not line:
                return
            line = line.rstrip(b"\r\n")
            if line:
                yield line

    def close(self) -> None:
        _abort(self._conn)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _abort(conn: http.client.HTTPConnection) -> None:
    """Hard-close the socket (works while another thread is blocked reading): Ollama then cancels the request."""
    try:
        if conn.sock is not None:
            conn.sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        conn.close()
    except Exception:
        pass


HEARTBEAT = 0.5          # seconds between {"type": "wait"} events while Ollama has not answered yet
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 600


def _post_waiting(url: str, path: str, payload: dict, model: str = ""):
    """Generator: POSTs JSON and yields {"type": "wait", "seconds", "loaded"} heartbeats until the response headers
    arrive (model loading + prompt processing happen before that). Returns the _Resp.
    Closing the generator (Stop button, rerun) aborts the connection, so the GPU stops working."""
    parts = urlsplit(url)
    cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    conn = cls(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80), timeout=CONNECT_TIMEOUT)
    box: dict = {}
    done = threading.Event()
    body = json.dumps(payload).encode("utf-8")

    def work():
        try:
            conn.connect()
            conn.sock.settimeout(READ_TIMEOUT)
            conn.request("POST", (parts.path.rstrip("/") + path), body=body,
                         headers={"Content-Type": "application/json", "Accept": "application/x-ndjson"})
            box["resp"] = conn.getresponse()
        except BaseException as e:            # noqa: BLE001 - handed over to the caller
            box["err"] = e
        finally:
            done.set()

    threading.Thread(target=work, daemon=True).start()
    t0, last_ps, loaded = time.monotonic(), 0.0, None
    ok = False
    try:
        while not done.wait(HEARTBEAT):
            now = time.monotonic()
            if now - last_ps >= 5 and model:
                last_ps = now
                try:
                    loaded_models.cache_clear()
                    base = model.split(":")[0]
                    loaded = any(m["name"] == model or m["name"].startswith(base) for m in loaded_models(url))
                except Exception:
                    loaded = None
            yield {"type": "wait", "seconds": now - t0, "loaded": loaded}
        err = box.get("err")
        if err is not None:
            if isinstance(err, socket.timeout) or isinstance(err, TimeoutError):
                raise requests.exceptions.Timeout(str(err))
            if isinstance(err, (OSError, http.client.HTTPException)):
                raise requests.exceptions.ConnectionError(str(err))
            raise err
        ok = True
        return _Resp(conn, box["resp"])
    finally:
        if not ok:
            _abort(conn)


# ----------------------------------------------------------------- context size vs. VRAM
_OOM_MARKERS = ("out of memory", "out-of-memory", "failed to allocate", "kv cache", "unable to allocate",
                "insufficient memory", "cudamalloc", "model requires more system memory")
MIN_CTX = 2048


def _key(url: str, model: str) -> str:
    return f"{url}|{model}"


def effective_ctx(url: str, model: str, wanted: int | None = None) -> int:
    """The context size that really works on this PC: what we want, capped by what we learned from OOM errors."""
    wanted = wanted or NUM_CTX
    learned = (settings_store.get("ctx_limits", {}) or {}).get(_key(url, model))
    return min(wanted, learned) if learned else wanted


def _remember_ctx(url: str, model: str, ctx: int) -> None:
    limits = dict(settings_store.get("ctx_limits", {}) or {})
    limits[_key(url, model)] = ctx
    settings_store.put("ctx_limits", limits)


def _forced(url: str, model: str):
    """999 = all layers forced onto the GPU (num_gpu), -1 = tried and it failed, None = not tried."""
    return (settings_store.get("gpu_force", {}) or {}).get(_key(url, model))


def _set_force(url: str, model: str, value: int) -> None:
    d = dict(settings_store.get("gpu_force", {}) or {})
    d[_key(url, model)] = value
    settings_store.put("gpu_force", d)


_CRASH_MARKERS = ("terminated", "exit status", "unable to load", "failed to load", "cuda error", "hip error")


def is_oom(text: str) -> bool:
    return any(m in text.lower() for m in _OOM_MARKERS)


_fit_checked: set = set()


def _unload(url: str, name: str) -> None:
    try:
        requests.post(f"{url}/api/generate", json={"model": name, "keep_alive": 0}, timeout=10)
    except Exception:
        pass


def fit_check(url: str, model: str, ctx: int) -> None:
    """Runs once per (PC, model, window) after a reply. If the model sits partly in RAM although the GPU could hold it:
    1) other models still in memory -> unload everything (the next message loads this one cleanly into free VRAM);
    2) nothing else is loaded -> the window itself is too big: halve it (not below FIT_MIN_CTX), remember it, reload."""
    if not AUTO_FIT:
        return
    key = (url, model, ctx)
    if key in _fit_checked:
        return
    _fit_checked.add(key)
    try:
        loaded_models.cache_clear()
        ms = loaded_models(url)
        base = model.split(":")[0]
        mine = next((m for m in ms if m["name"] == model or m["name"].startswith(base)), None)
        if not mine or mine["gpu_pct"] is None or mine["gpu_pct"] >= FIT_MIN_GPU:
            return
        if len(ms) > 1:                                  # another model is hogging VRAM
            for m in ms:
                _unload(url, m["name"])
            _fit_checked.discard(key)                    # look again after the clean reload
        elif FORCE_GPU and _forced(url, model) is None and mine["gpu_pct"] >= 100 - FORCE_GPU_MAX_SPILL:
            # Ollama's estimate is cautious: part of the model sits in RAM although VRAM is free -> force all layers
            _set_force(url, model, 999)
            _unload(url, mine["name"])
            _fit_checked.discard(key)                    # check again after the reload
        else:                                            # the window (KV cache) does not fit next to the weights
            new = (ctx // 2) // 1024 * 1024
            if new < FIT_MIN_CTX:
                return
            _remember_ctx(url, model, new)
            _unload(url, mine["name"])
        loaded_models.cache_clear()
    except Exception:
        pass


def stream_chat(url: str, model: str, messages: list[dict], temperature: float = 0.5, think=None,
                stop: list[str] | None = None, num_ctx: int | None = None, num_predict: int | None = None,
                tools: list[dict] | None = None):
    """Generator of events:
        {"type": "thinking"|"content", "text": str}
        {"type": "tool_calls", "calls": [{"function": {"name", "arguments"}}]}   (only when `tools` was given)
        {"type": "done", "stats": {prompt_tokens, completion_tokens, tok_per_s, stopped}}
    stats['stopped'] is None for a normal end, or 'loop' / 'think_runaway' / 'length'.
    Out of VRAM? The context window is halved (down to 2048) and the request is repeated; the size that
    worked is remembered for this PC + model (settings.json), so the error does not come back.
    """
    ctx = effective_ctx(url, model, num_ctx)
    payload = {"model": model, "messages": messages, "stream": True, "keep_alive": KEEP_ALIVE,
               "options": {"temperature": temperature, "num_ctx": ctx,
                           "num_predict": min(num_predict or MAX_NEW_TOKENS, max(512, int(ctx * 0.6)))}}
    if REPEAT_PENALTY:
        payload["options"]["repeat_penalty"] = REPEAT_PENALTY
    if (_forced(url, model) or 0) > 0:
        payload["options"]["num_gpu"] = _forced(url, model)
    if think is not None:
        payload["think"] = think
    if stop:
        payload["options"]["stop"] = stop
    if tools:
        payload["tools"] = tools

    def shrink(err: str) -> bool:
        """True if the context was reduced and the request should be repeated."""
        if "num_gpu" in payload["options"] and (is_oom(err) or any(k in err.lower() for k in _CRASH_MARKERS)):
            payload["options"].pop("num_gpu")            # forcing all layers onto the GPU did not work: undo, same window
            _set_force(url, model, -1)
            return True
        cur = payload["options"]["num_ctx"]
        new = (cur // 2) // 1024 * 1024
        if not is_oom(err) or new < MIN_CTX:
            return False
        payload["options"]["num_ctx"] = new
        payload["options"]["num_predict"] = min(payload["options"]["num_predict"], max(512, int(new * 0.6)))
        _remember_ctx(url, model, new)
        return True

    def oom_hint(err: str) -> str:
        return (f"Ollama ({url}): {err}\n\nNa tomto PC nie je dosť VRAM ani pre najmenšie okno. Skontroluj `ollama ps` "
                f"(iný model môže držať pamäť), zavri hry/GPU programy alebo použi menší model.")

    try:
        for attempt in range(8):
            retry = False
            yielded = False
            r = yield from _post_waiting(url, "/api/chat", payload, model)
            with r:
                if r.status_code >= 400:
                    err = _error_text(r)
                    if "tools" in payload and "tool" in err.lower() and "support" in err.lower():
                        raise ToolsUnsupported(f"Model '{model}' nepodporuje natívne volanie nástrojov.")
                    if attempt == 0 and "think" in payload and "think" in err.lower():
                        payload.pop("think")          # model can't think natively -> retry plain
                        continue
                    if shrink(err):
                        continue
                    if _is_toolparse_error(err):
                        yield from _salvage(err, False)
                        yield {"type": "done", "stats": {"stopped": "toolparse"}}
                        return
                    if r.status_code == 404:
                        raise OllamaError(f"Model '{model}' nie je nainštalovaný na {url}. "
                                          f"Spusti tam: ollama pull {model}")
                    raise OllamaError(oom_hint(err) if is_oom(err) else f"Ollama ({url}): {err}")
                got_content = False
                try:
                    for ev in _parse_stream(r):
                        if ev["type"] == "content":
                            got_content = True
                        gpt_oss = model.lower().startswith("gpt-oss")       # cannot switch thinking off, only to "low"
                        if (ev["type"] == "done" and ev["stats"].get("stopped") == "think_runaway"
                                and not got_content and payload.get("think") not in (None, False)
                                and not (gpt_oss and payload.get("think") == "low")):
                            payload["think"] = "low" if gpt_oss else False   # thinking never ended -> ask again with less
                            retry = True
                            break
                        yielded = True
                        if ev["type"] == "done":
                            cur = payload["options"]["num_ctx"]
                            ev["stats"]["ctx"] = cur
                            pt = ev["stats"].get("prompt_tokens") or 0
                            ev["stats"]["truncated"] = bool(pt and pt >= int(cur * 0.97))   # prompt filled the whole window
                        yield ev
                except OllamaError as e:
                    if not yielded and shrink(str(e)):
                        retry = True
                    else:
                        raise OllamaError(oom_hint(str(e)) if is_oom(str(e)) else str(e))
            if not retry:
                fit_check(url, model, payload["options"]["num_ctx"])
                return
        raise OllamaError(f"Ollama ({url}): nepodarilo sa spustiť model ani po viacerých pokusoch.")
    except requests.exceptions.ConnectionError:
        raise OllamaError(f"Nedá sa pripojiť na {url}. Beží tam Ollama? Na tom PC nastav "
                          f"OLLAMA_HOST=0.0.0.0 a povoľ port 11434 vo firewalle.")
    except requests.exceptions.Timeout:
        raise OllamaError(f"Počítač {url} neodpovedá (timeout).")
    except requests.exceptions.RequestException as e:
        raise OllamaError(f"Chyba siete: {e}")


def chat_once(url: str, model: str, messages: list[dict], temperature: float = 0.4, think=None) -> str:
    """Blocking helper: returns only the final answer text."""
    return "".join(ev["text"] for ev in stream_chat(url, model, messages, temperature, think)
                   if ev["type"] == "content").strip()


# ----------------------------------------------------------------- speed test
BENCH_PROMPT = "Spočítaj nahlas od 1 do 40, každé číslo napíš slovom a oddeľ čiarkou."


def benchmark(url: str, model: str) -> list[dict]:
    """Same short prompt with different settings: shows what slows the model down.
    Each row: label, tok/s, % of the model on GPU, context in use (or error)."""
    variants = [
        ("A  Ollama predvolené (žiadne nastavenia)", {}),
        (f"B  okno {NUM_CTX} (ako aplikácia)", {"num_ctx": NUM_CTX}),
        (f"C  okno {NUM_CTX} + repeat_penalty 1.05 (aplikácia v3.3 – v3.5)", {"num_ctx": NUM_CTX, "repeat_penalty": 1.05}),
        ("D  okno 4096", {"num_ctx": 4096}),
    ]
    rows = []
    for label, opts in variants:
        payload = {"model": model, "stream": False, "keep_alive": KEEP_ALIVE,
                   "messages": [{"role": "user", "content": BENCH_PROMPT}],
                   "options": {"temperature": 0.2, "num_predict": 120, **opts}}
        try:
            r = requests.post(f"{url}/api/chat", json=payload, timeout=300)
            if r.status_code >= 400:
                rows.append({"label": label, "error": _error_text(r)[:120]})
                continue
            stats = _stats(r.json())
            loaded_models.cache_clear()
            mine = next((m for m in loaded_models(url) if m["name"].startswith(model.split(":")[0])), {})
            rows.append({"label": label, "tok_s": stats.get("tok_per_s"), "gpu_pct": mine.get("gpu_pct"),
                         "ctx": mine.get("ctx")})
        except Exception as e:
            rows.append({"label": label, "error": str(e)[:120]})
    return rows
