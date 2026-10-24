"""Ochrany pri úprave projektu: veľké prepísanie, syntax, undo, AGENTS.md, code_map, run_tests."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import prompts, project, sandbox, skills, workspace  # noqa: E402
from core.skills import ToolContext, ToolError  # noqa: E402

BIG = "\n".join(f"def f{i}():\n    return {i}\n" for i in range(20))          # 60 lines of valid Python


class Guards(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".history").mkdir()
        self._old = (workspace.WORKSPACE_DIR, workspace.HISTORY_DIR, sandbox.WORKSPACE_DIR)
        workspace.WORKSPACE_DIR = sandbox.WORKSPACE_DIR = self.tmp
        workspace.HISTORY_DIR = self.tmp / ".history"
        (self.tmp / "app").mkdir()
        (self.tmp / "app" / "main.py").write_text(BIG, encoding="utf-8")
        self.ctx = ToolContext(node="x")

    def tearDown(self):
        workspace.WORKSPACE_DIR, workspace.HISTORY_DIR, sandbox.WORKSPACE_DIR = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_tool(self, name, args, body=""):
        return skills.find_tool(name)[1].run(args, body, self.ctx)

    # ---- write_file
    def test_unread_file_must_be_read_first_once(self):
        new = BIG.replace("return 3", "return 33")
        with self.assertRaises(ToolError) as e:
            self.run_tool("write_file", {"path": "app/main.py"}, new)
        self.assertIn("nečítal", str(e.exception))
        with self.assertRaises(ToolError) as e:                  # the second try is judged by the next rule
            self.run_tool("write_file", {"path": "app/main.py"}, new)
        self.assertIn("edit_file", str(e.exception))

    def test_small_change_by_full_rewrite_is_refused(self):
        self.run_tool("read_file", {"path": "app/main.py"})
        with self.assertRaises(ToolError) as e:
            self.run_tool("write_file", {"path": "app/main.py"}, BIG.replace("return 3", "return 33"))
        self.assertIn("edit_file", str(e.exception))
        self.assertEqual((self.tmp / "app" / "main.py").read_text(encoding="utf-8"), BIG)   # untouched

    def test_overwrite_true_allows_it(self):
        self.run_tool("read_file", {"path": "app/main.py"})
        self.run_tool("write_file", {"path": "app/main.py", "overwrite": "true"}, BIG.replace("return 3", "return 33"))
        self.assertIn("return 33", (self.tmp / "app" / "main.py").read_text(encoding="utf-8"))

    def test_broken_syntax_never_replaces_valid_code(self):
        self.run_tool("read_file", {"path": "app/main.py"})
        with self.assertRaises(ToolError) as e:
            self.run_tool("write_file", {"path": "app/main.py", "overwrite": "true"}, "def f(:\n    pass\n")
        self.assertIn("syntaktick", str(e.exception))
        self.assertEqual((self.tmp / "app" / "main.py").read_text(encoding="utf-8"), BIG)

    def test_new_file_with_syntax_error_is_saved_with_warning(self):
        out = self.run_tool("write_file", {"path": "app/novy_modul.py"}, "def f(:\n    pass\n")
        self.assertIn("[SYNTAX]", out)

    # ---- edit_file
    def test_edit_that_breaks_syntax_is_refused(self):
        self.run_tool("read_file", {"path": "app/main.py"})
        blocks = "<<<<<<< SEARCH\ndef f1():\n    return 1\n=======\ndef f1(:\n    return 1\n>>>>>>> REPLACE\n"
        with self.assertRaises(ToolError) as e:
            self.run_tool("edit_file", {"path": "app/main.py"}, blocks)
        self.assertIn("syntaktick", str(e.exception))
        self.assertEqual((self.tmp / "app" / "main.py").read_text(encoding="utf-8"), BIG)

    def test_small_edit_works_and_undo_restores(self):
        blocks = "<<<<<<< SEARCH\ndef f1():\n    return 1\n=======\ndef f1():\n    return 100\n>>>>>>> REPLACE\n"
        self.run_tool("edit_file", {"path": "app/main.py"}, blocks)
        self.assertIn("return 100", (self.tmp / "app" / "main.py").read_text(encoding="utf-8"))
        self.run_tool("undo_file", {"path": "app/main.py"})
        self.assertEqual((self.tmp / "app" / "main.py").read_text(encoding="utf-8"), BIG)

    def test_undo_of_a_file_created_in_this_task_deletes_it(self):
        self.run_tool("write_file", {"path": "app/pomocny_modul.py"}, "x = 1\n")
        self.assertTrue((self.tmp / "app" / "pomocny_modul.py").exists())
        self.run_tool("undo_file", {"path": "app/pomocny_modul.py"})
        self.assertFalse((self.tmp / "app" / "pomocny_modul.py").exists())

    def test_undo_without_anything_to_restore(self):
        with self.assertRaises(ToolError):
            self.run_tool("undo_file", {"path": "app/main.py"})

    # ---- project memory + map + tests
    def test_agents_md_is_injected_into_the_prompt(self):
        (self.tmp / "app" / "AGENTS.md").write_text("Pravidlo: nikdy nemeň názvy funkcií.", encoding="utf-8")
        self.assertIn("nikdy nemeň názvy", project.project_notes())
        msgs = prompts.build_messages([{"role": "user", "content": "pridaj funkciu"}], mode="agent",
                                      enabled=frozenset({"fs_read", "fs_write"}))
        self.assertIn("PAMÄŤ PROJEKTU", msgs[0]["content"])
        self.assertIn("PRÁCA NA PROJEKTE", msgs[0]["content"])

    def test_code_map_lists_functions_with_lines(self):
        out = self.run_tool("code_map", {"path": "app"})
        self.assertIn("app/main.py", out)
        self.assertIn("def f19()", out)

    def test_run_tests_reports_pass_and_fail(self):
        (self.tmp / "app" / "tests").mkdir()
        (self.tmp / "app" / "tests" / "test_main.py").write_text(
            "import unittest\nfrom main import f1\n\nclass T(unittest.TestCase):\n    def test_f1(self):\n"
            "        self.assertEqual(f1(), 1)\n", encoding="utf-8")
        (self.tmp / "app" / "tests" / "__init__.py").write_text("", encoding="utf-8")
        res = sandbox.run_tests("app")
        self.assertIn("OK", res.text, res.text)
        (self.tmp / "app" / "main.py").write_text(BIG.replace("return 1\n", "return 2\n", 1), encoding="utf-8")
        self.assertNotEqual(sandbox.run_tests("app").code, 0)

    def test_run_tests_without_tests_says_so(self):
        self.assertIn("nenašiel", sandbox.run_tests("app").text)


if __name__ == "__main__":
    unittest.main()
