"""Rýchle testy jadra (bez Streamlitu a bez Ollamy): python -m unittest discover -s tests"""
import io
import os
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import loopguard, toolcalling, workspace, zipwork  # noqa: E402
from core.thinking import ThinkSplitter  # noqa: E402


class LoopGuard(unittest.TestCase):
    def test_detects_repeated_thinking_line(self):
        line = "We can read the zip file's content by reading the zip file as a text? Not possible.\n"
        self.assertTrue(loopguard.find_loop("intro\n" + line * 8))

    def test_trim_keeps_one_copy(self):
        line = "Toto je dlhší riadok, ktorý sa stále opakuje dokola a dokola.\n"
        out = loopguard.trim_repetition("Úvod\n" + line * 10)
        self.assertEqual(out.count("stále opakuje"), 1)

    def test_normal_text_is_not_a_loop(self):
        self.assertFalse(loopguard.find_loop("Normálny text bez opakovania. " * 1 + "a potom niečo iné " * 2))


class ToolParsing(unittest.TestCase):
    known = {"read_file", "run_code", "write_file", "list_files"}

    def test_tag(self):
        before, call = toolcalling.parse_tool_call('Idem na to <tool name="read_file" path="a.py"/>')
        self.assertEqual((call.name, call.args["path"]), ("read_file", "a.py"))

    def test_json_in_fence(self):
        _, call = toolcalling.parse_foreign('```\n{"name": "run_code", "arguments": {"path": "x.py"}}\n```', self.known)
        self.assertEqual(call.name, "run_code")

    def test_loose_sentence(self):
        _, call = toolcalling.parse_loose('Cieľ: x\nZavolaj run_code s argumentom path="server.py".', self.known)
        self.assertEqual(call.args["path"], "server.py")

    def test_plain_answer_is_not_a_call(self):
        self.assertIsNone(toolcalling.parse_loose("Hotovo. Server beží.", self.known)[1])


class Thinking(unittest.TestCase):
    def test_think_tags_split_even_across_chunks(self):
        sp, out = ThinkSplitter(), []
        for chunk in ("<thi", "nk>premýšľam</th", "ink>odpoveď"):
            out += sp.feed(chunk)
        out += sp.flush()
        kinds = {k: "".join(t for kk, t in out if kk == k) for k in ("thinking", "content")}
        self.assertEqual(kinds["thinking"], "premýšľam")
        self.assertEqual(kinds["content"], "odpoveď")


class WorkspaceSafety(unittest.TestCase):
    def test_path_traversal_blocked(self):
        for bad in ("../x.py", "/etc/passwd", "a/../../x", "C:\\Windows\\x"):
            with self.assertRaises(workspace.WorkspaceError, msg=bad):
                workspace.safe_path(bad)

    def test_generated_code_named_by_fence_and_dedup(self):
        txt = "```server.py\nprint(1)\nprint(2)\nprint(3)\nprint(4)\n```"
        saved = workspace.save_generated_code(txt, "t", ["server.py"])
        try:
            self.assertEqual(saved, ["server.py"])
        finally:
            workspace.safe_path("server.py").unlink(missing_ok=True)

    def test_bare_name_first_line_is_stripped(self):
        code, name = workspace.strip_name_line("`server.py`\nprint(1)\nprint(2)\n")
        self.assertEqual((code, name), ("print(1)\nprint(2)\n", "server.py"))


class ZipSafety(unittest.TestCase):
    def _zip(self, members: dict) -> str:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for n, d in members.items():
                z.writestr(n, d)
        rel = workspace.save_upload("test_bezpecnost.zip", buf.getvalue())
        self.addCleanup(lambda: workspace.safe_path(rel).unlink(missing_ok=True))
        return rel

    def test_list_and_read(self):
        rel = self._zip({"p/a.py": "print('ahoj')\n", "p/b.txt": "x"})
        self.assertIn("p/a.py", zipwork.list_zip(rel))
        self.assertIn("ahoj", zipwork.read_member(rel, "p/a.py"))

    def test_extract_blocks_traversal(self):
        rel = self._zip({"../../evil.py": "boom", "ok/fine.py": "1"})
        written, notes = zipwork.extract(rel, "rozbalene_test")
        self.addCleanup(lambda: [workspace.safe_path(w).unlink(missing_ok=True) for w in written])
        self.assertTrue(all(w.startswith("rozbalene_test/") for w in written))
        self.assertFalse(any("evil" in w for w in written))


class PromptFitsWindow(unittest.TestCase):
    """Regresia: ZIP s veľkým náhľadom zaplnil okno, Ollama odrezala začiatok a model 'nevidel' úlohu."""

    def _msgs(self):
        from core import prompts, skills
        from core.toolcalling import TextProtocol
        big = "[Uložené]\n" + "\n".join(f"--- file{i}.py ---\n" + "x = 1\n" * 400 for i in range(12))   # ~30 kB náhľad
        hist = [{"role": "user", "content": "over funkcnost kodu v zip file a vylepsi to",
                 "attachments": [{"name": "a.zip", "text": big, "path": "nahrate/a.zip"}]}]
        return prompts.build_messages(hist, mode="agent", enabled=frozenset(skills.SKILLS), protocol=TextProtocol())

    def test_agent_prompt_fits_8192_window(self):
        msgs = self._msgs()
        tokens = sum(len(m["content"]) for m in msgs) / 3
        self.assertLess(tokens, 8192 * 0.6)

    def test_instruction_stays_at_start_of_task(self):
        self.assertTrue(self._msgs()[-1]["content"].startswith("over funkcnost kodu"))

    def test_fit_task_cuts_the_end_not_the_instruction(self):
        from core import agent
        msgs = [{"role": "system", "content": "s" * 9000},
                {"role": "user", "content": "INSTRUKCIA " + "p" * 40000}]
        self.assertTrue(agent.fit_task(msgs, 1, 4000))
        self.assertTrue(msgs[1]["content"].startswith("INSTRUKCIA"))
        self.assertLess(len(msgs[1]["content"]), 5000)


class ZipListing(unittest.TestCase):
    def test_backups_and_caches_are_collapsed(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("p/main.py", "1")
            z.writestr("p/workspace/.history/a.py.bak", "x")
            z.writestr("p/__pycache__/m.cpython-313.pyc", "x")
        rel = workspace.save_upload("test_noise.zip", buf.getvalue())
        self.addCleanup(lambda: workspace.safe_path(rel).unlink(missing_ok=True))
        out = zipwork.list_zip(rel)
        self.assertIn("p/main.py", out)
        self.assertIn("skrytých 2", out)
        self.assertNotIn(".history/a.py.bak  (", out)

class SandboxProjectTests(unittest.TestCase):
    def test_project_import_and_local_module(self):
        import tempfile, shutil
        from pathlib import Path
        import config
        from core import sandbox, agent, workspace
        d = Path(tempfile.mkdtemp())
        old = config.WORKSPACE_DIR
        try:
            for m in (config, sandbox, workspace):
                m.WORKSPACE_DIR = d
            (d / "proj" / "core").mkdir(parents=True)
            (d / "proj" / "tests").mkdir()
            (d / "proj" / "core" / "__init__.py").write_text("X = 7\n")
            (d / "proj" / "tests" / "t.py").write_text("import core\nprint(core.X)\n")
            r = sandbox.run("proj/tests/t.py")
            self.assertIn("7", r.output if hasattr(r, "output") else str(r))
            self.assertTrue(agent.is_local_module("core"))
            self.assertFalse(agent.is_local_module("flask_cors_nonexistent"))
        finally:
            for m in (config, sandbox, workspace):
                m.WORKSPACE_DIR = old
            shutil.rmtree(d, ignore_errors=True)

class StreamAbortTests(unittest.TestCase):
    """stream_chat must keep the UI alive while Ollama loads the model, and a closed generator must drop the socket."""

    def _server(self, delay, lines, closed):
        import json, threading, time
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *a): pass
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                end = time.time() + delay
                while time.time() < end:
                    time.sleep(0.05)
                    self.connection.setblocking(False)
                    try:
                        if self.connection.recv(1, __import__("socket").MSG_PEEK) == b"":
                            closed.set(); return
                    except BlockingIOError:
                        pass
                    except OSError:
                        closed.set(); return
                    finally:
                        self.connection.setblocking(True)
                self.send_response(200); self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Transfer-Encoding", "chunked"); self.end_headers()
                for ln in lines:
                    b = (json.dumps(ln) + "\n").encode()
                    self.wfile.write(b"%x\r\n" % len(b) + b + b"\r\n"); self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv

    def test_heartbeat_then_stream(self):
        import threading
        from core import ollama_client as oc
        lines = [{"message": {"content": "Ahoj"}}, {"message": {"content": " svet"}, "done": True, "eval_count": 2, "eval_duration": 10**9}]
        srv = self._server(1.2, lines, threading.Event())
        try:
            evs = list(oc.stream_chat(f"http://127.0.0.1:{srv.server_port}", "m", [{"role": "user", "content": "x"}]))
        finally:
            srv.shutdown()
        self.assertGreaterEqual(sum(e["type"] == "wait" for e in evs), 2)
        self.assertEqual("".join(e["text"] for e in evs if e["type"] == "content"), "Ahoj svet")
        self.assertEqual(evs[-1]["type"], "done")

    def test_close_during_wait_aborts_connection(self):
        import threading, time
        from core import ollama_client as oc
        closed = threading.Event()
        srv = self._server(10, [], closed)
        try:
            g = oc.stream_chat(f"http://127.0.0.1:{srv.server_port}", "m", [{"role": "user", "content": "x"}])
            self.assertEqual(next(g)["type"], "wait")
            g.close()
            self.assertTrue(closed.wait(3), "server did not notice the dropped connection")
        finally:
            srv.shutdown()

class ForceGpuTests(unittest.TestCase):
    def test_small_spill_forces_all_layers_then_fits(self):
        from unittest import mock
        from core import ollama_client as oc
        store, unloaded = {}, []
        spilled = ({"name": "big:27b", "size": 15, "gpu_pct": 91, "ctx": 8192},)
        with mock.patch.object(oc.settings_store, "get", lambda k, d=None: store.get(k, d)), \
             mock.patch.object(oc.settings_store, "put", lambda k, v: store.__setitem__(k, v)), \
             mock.patch.object(oc, "loaded_models", mock.Mock(return_value=spilled, cache_clear=lambda: None)), \
             mock.patch.object(oc, "_unload", lambda url, name: unloaded.append(name)):
            oc._fit_checked.clear()
            oc.fit_check("http://x", "big:27b", 8192)
            self.assertEqual(oc._forced("http://x", "big:27b"), 999)
            self.assertEqual(unloaded, ["big:27b"])
            oc.fit_check("http://x", "big:27b", 8192)          # still spilled with the override -> now the window shrinks
            self.assertEqual(oc.effective_ctx("http://x", "big:27b", 8192), 4096)

class BrokenNativeToolCallTests(unittest.TestCase):
    def test_error_detected(self):
        from core.ollama_client import _is_toolparse_error
        self.assertTrue(_is_toolparse_error('llama-server returned invalid tool call arguments for "write_file": unexpected end of JSON input'))
        self.assertFalse(_is_toolparse_error("model requires more system memory"))

    def test_agent_switches_to_text_protocol(self):
        from unittest import mock
        from core import agent, skills
        from core.skills import ToolContext
        from core.toolcalling import NativeProtocol
        calls = []

        def fake(url, model, m, temp, **kw):
            calls.append(kw.get("tools") is not None)
            if len(calls) == 1:
                yield {"type": "done", "stats": {"stopped": "toolparse"}}
            else:
                yield {"type": "content", "text": "Hotovo."}
                yield {"type": "done", "stats": {}}

        ctx = ToolContext(node="PC1", temperature=.4, history="", chat_id="t", plan=[])
        msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "ahoj"}]
        with mock.patch.object(agent, "stream_chat", fake), mock.patch.object(agent, "remember_protocol", lambda *a: None), \
             mock.patch.object(agent, "effective_ctx", lambda *a, **k: 8192):
            evs = list(agent.run_agent(msgs, url="http://x", model="m", think_param=None, temperature=.4,
                                       enabled=frozenset(skills.SKILLS), ctx=ctx, protocol=NativeProtocol()))
        self.assertTrue(any(e["type"] == "protocol" and e["name"] == "text" for e in evs))
        self.assertEqual(calls, [True, False])                 # second request no longer sends native tools
        self.assertEqual(evs[-1]["type"], "final")


if __name__ == "__main__":
    unittest.main()
