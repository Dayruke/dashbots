import importlib.machinery
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


def load_mod():
    path = Path(__file__).resolve().parents[1] / "bin" / "dashbots"
    loader = importlib.machinery.SourceFileLoader("dashbots_cli", str(path))
    spec = importlib.util.spec_from_loader("dashbots_cli", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class DashbotsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_mod()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state"
        self.state.mkdir()
        self.flag = Path(self.tmp.name) / "toggle"
        self.flag.write_text("")
        os.environ["XDG_STATE_HOME"] = str(self.state)
        os.environ["DASHBOTS_TOGGLE_FILE"] = str(self.flag)
        os.environ["DASHBOTS_HOOK_ASSUME"] = "1"
        os.environ["DASHBOTS_HOOK_PID"] = str(os.getpid())
        os.environ.pop("GEMINI_SESSION_ID", None)
        self._now_stamp = self.mod.now_stamp
        self._hypr_clients = self.mod.hypr_clients
        self.mod.hypr_clients = lambda: []

    def tearDown(self):
        self.mod.now_stamp = self._now_stamp
        self.mod.hypr_clients = self._hypr_clients
        self.tmp.cleanup()

    def record(self, session_id):
        path = Path(self.mod.session_path(session_id))
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def hook(self, payload, harness="grok"):
        self.mod.apply_hook(payload, harness)

    def test_status_map_and_file_mode(self):
        self.hook({"hook_event_name": "SessionStart", "sessionId": "s1", "cwd": "/work/demo"})
        rec = self.record("s1")
        self.assertEqual(rec["status"], "alive")
        self.assertEqual(rec["activity"], "started")
        self.assertEqual(rec["title"], "demo")
        self.assertEqual(rec["harness"], "grok")
        self.assertEqual(rec["pid"], os.getpid())
        self.assertEqual(rec["source"], "hook")
        mode = os.stat(self.mod.session_path("s1")).st_mode & 0o777
        self.assertEqual(mode, 0o600)

        self.hook({
            "hookEventName": "user_prompt_submit",
            "hook_event_name": "UserPromptSubmit",
            "sessionId": "s1",
            "promptId": "p1",
            "prompt": "first line\nsecond line",
            "cwd": "/work/demo",
        })
        rec = self.record("s1")
        self.assertEqual(rec["status"], "working")
        self.assertEqual(rec["turn"], "p1")
        self.assertEqual(rec["activity"], "first line")

        self.hook({
            "hook_event_name": "PreToolUse",
            "sessionId": "s1",
            "promptId": "p1",
            "toolName": "read_file",
        })
        self.assertEqual(self.record("s1")["status"], "working")
        self.assertEqual(self.record("s1")["activity"], "read_file")

        self.hook({
            "hook_event_name": "PostToolUse",
            "sessionId": "s1",
            "promptId": "p1",
            "toolName": "read_file",
        })
        self.assertEqual(self.record("s1")["status"], "working")

        self.hook({
            "hook_event_name": "PostToolUse",
            "sessionId": "s1",
            "promptId": "p1",
            "tool_name": "run_shell_command",
            "tool_response": {"error": "nope"},
        })
        self.assertEqual(self.record("s1")["status"], "error")

        self.hook({
            "hook_event_name": "PostToolUseFailure",
            "sessionId": "s1",
            "promptId": "p1",
            "toolName": "grep",
        })
        self.assertEqual(self.record("s1")["status"], "error")
        self.assertEqual(self.record("s1")["activity"], "grep")

        self.hook({
            "hook_event_name": "Notification",
            "sessionId": "s1",
            "notificationType": "permission_prompt",
        })
        self.assertEqual(self.record("s1")["status"], "waiting")
        self.assertEqual(self.record("s1")["activity"], "needs a decision")

        self.hook({
            "hook_event_name": "Notification",
            "sessionId": "s1",
            "notification_type": "idle_prompt",
        })
        self.assertEqual(self.record("s1")["status"], "waiting")
        self.assertEqual(self.record("s1")["activity"], "idle")

        self.hook({"hook_event_name": "StopFailure", "sessionId": "s1", "promptId": "p1"})
        self.assertEqual(self.record("s1")["status"], "error")

        self.hook({"hook_event_name": "SessionEnd", "sessionId": "s1"})
        self.assertIsNone(self.record("s1"))

    def test_turn_guard(self):
        self.hook({
            "hook_event_name": "UserPromptSubmit",
            "sessionId": "s1",
            "session_id": "ignored",
            "promptId": "new",
            "prompt": "new turn",
            "cwd": "/work/demo",
        })
        self.hook({
            "hook_event_name": "Stop",
            "sessionId": "s1",
            "promptId": "old",
        })
        rec = self.record("s1")
        self.assertEqual(rec["status"], "working")
        self.assertEqual(rec["turn"], "new")
        self.assertEqual(rec["activity"], "new turn")

        self.hook({
            "hook_event_name": "StopFailure",
            "sessionId": "s1",
            "promptId": "old",
        })
        self.assertEqual(self.record("s1")["status"], "working")

        self.hook({"hook_event_name": "Stop", "sessionId": "s1", "promptId": "new"})
        self.assertEqual(self.record("s1")["status"], "waiting")
        self.assertEqual(self.record("s1")["turn"], "new")

        self.hook({
            "hook_event_name": "UserPromptSubmit",
            "sessionId": "s1",
            "promptId": "newer",
            "prompt": "again",
        })
        self.hook({"hook_event_name": "StopCancelled", "sessionId": "s1"})
        self.assertEqual(self.record("s1")["status"], "waiting")

    def test_gemini_events_and_session_env(self):
        os.environ["GEMINI_SESSION_ID"] = "gem1"
        self.hook({"hook_event_name": "BeforeAgent", "prompt": "plan this"}, "gemini")
        rec = self.record("gem1")
        self.assertEqual(rec["harness"], "gemini")
        self.assertEqual(rec["status"], "working")
        self.assertEqual(rec["activity"], "plan this")

        self.hook({"hook_event_name": "BeforeModel"}, "gemini")
        self.assertEqual(self.record("gem1")["status"], "working")
        self.assertEqual(self.record("gem1")["activity"], "thinking")

        self.hook({"hook_event_name": "AfterModel"}, "gemini")
        self.assertEqual(self.record("gem1")["status"], "working")

        self.hook({"hook_event_name": "AfterTool", "tool_name": "read_file"}, "gemini")
        self.assertEqual(self.record("gem1")["status"], "working")

        self.hook({
            "hook_event_name": "Notification",
            "notification_type": "ToolPermission",
        }, "gemini")
        self.assertEqual(self.record("gem1")["activity"], "needs a decision")

        self.hook({"hook_event_name": "AfterAgent"}, "gemini")
        self.assertEqual(self.record("gem1")["status"], "waiting")

        self.hook({"hook_event_name": "Notification", "notification_type": "SomethingElse"}, "gemini")
        self.assertEqual(self.record("gem1")["status"], "waiting")

    def test_subagent_is_ignored(self):
        self.hook({
            "hook_event_name": "SessionStart",
            "sessionId": "child",
            "subagentType": "explore",
            "cwd": "/work/demo",
        })
        self.assertIsNone(self.record("child"))
        self.hook({
            "hook_event_name": "SessionEnd",
            "sessionId": "child",
            "subagent_type": "explore",
        })
        self.assertIsNone(self.record("child"))

    def test_wrong_harness_noop(self):
        os.environ.pop("DASHBOTS_HOOK_ASSUME", None)
        self.hook({"hook_event_name": "SessionStart", "sessionId": "nope", "cwd": "/tmp"}, "claude")
        self.assertIsNone(self.record("nope"))
        self.assertEqual(list(self.mod.iter_records()), [])

    def test_clear_and_gc(self):
        self.hook({"hook_event_name": "SessionStart", "sessionId": "keep", "cwd": "/work/demo"})
        self.mod.write_record({
            "id": "dead",
            "harness": "grok",
            "pid": 2 ** 30,
            "cwd": "/work/demo",
            "title": "demo",
            "status": "alive",
            "window": "",
            "updated_at": "2026-01-01T00:00:00Z",
            "activity": "",
            "source": "hook",
            "turn": "",
        })
        self.mod.write_record({
            "id": f"scan-grok-{os.getpid()}",
            "harness": "grok",
            "pid": os.getpid(),
            "cwd": "/work/demo",
            "title": "demo",
            "status": "alive",
            "window": "",
            "updated_at": "2026-01-01T00:00:00Z",
            "activity": "",
            "source": "scan",
            "turn": "",
        })
        marker = Path(self.mod.adapters_dir())
        marker.mkdir(parents=True)
        (marker / "grok").write_text("")

        self.assertEqual(self.mod.cmd_gc(["gc"]), 0)
        self.assertIsNotNone(self.record("keep"))
        self.assertIsNone(self.record("dead"))
        self.assertIsNone(self.record(f"scan-grok-{os.getpid()}"))

        self.assertEqual(self.mod.cmd_clear(["clear", "keep"]), 0)
        self.assertIsNone(self.record("keep"))

    def test_hook_deletes_scan_twin(self):
        twin = f"scan-grok-{os.getpid()}"
        self.mod.write_record({
            "id": twin,
            "harness": "grok",
            "pid": os.getpid(),
            "cwd": "/work/demo",
            "title": "demo",
            "status": "alive",
            "window": "",
            "updated_at": "2026-01-01T00:00:00Z",
            "activity": "",
            "source": "scan",
            "turn": "",
        })
        self.hook({"hook_event_name": "SessionStart", "sessionId": "s1", "cwd": "/work/demo"})
        self.assertIsNone(self.record(twin))
        self.assertIsNotNone(self.record("s1"))

    def test_list_filters_dead_and_sorts(self):
        self.mod.now_stamp = lambda: "2026-01-01T00:00:01Z"
        self.hook({"hook_event_name": "SessionStart", "sessionId": "older", "cwd": "/work/a"})
        self.mod.now_stamp = lambda: "2026-01-01T00:00:02Z"
        self.hook({"hook_event_name": "SessionStart", "sessionId": "newer", "cwd": "/work/b"})
        self.mod.write_record({
            "id": "dead",
            "harness": "codex",
            "pid": 2 ** 30,
            "cwd": "/work/c",
            "title": "c",
            "status": "alive",
            "window": "",
            "updated_at": "2026-01-02T00:00:00Z",
            "activity": "",
            "source": "scan",
            "turn": "",
        })
        listed = self.mod.live_records()
        self.assertEqual([item["id"] for item in listed], ["newer", "older"])

    def test_unsafe_id_is_dropped(self):
        self.hook({"hook_event_name": "SessionStart", "sessionId": "../etc/passwd", "cwd": "/work/demo"})
        self.assertEqual(list(Path(self.mod.sessions_dir()).glob("*.json")) if Path(self.mod.sessions_dir()).exists() else [], [])

    def test_off_skips_hook(self):
        self.flag.unlink()
        self.hook({"hook_event_name": "SessionStart", "sessionId": "s1", "cwd": "/work/demo"})
        self.assertFalse(Path(self.mod.sessions_dir()).exists() and any(Path(self.mod.sessions_dir()).glob("*.json")))

    def test_classify(self):
        self.assertEqual(self.mod.classify_args(["/usr/bin/grok"], "grok"), "grok")
        self.assertEqual(self.mod.classify_args(["/usr/bin/node", "/opt/gemini.js"], "node"), "gemini")
        self.assertIsNone(self.mod.classify_args(["/var/lib/dashbots/gemini"], "gemini"))
        self.assertIsNone(self.mod.classify_args(["/usr/bin/python", "/repo/bin/dashbots", "hook"], "python"))
        self.assertEqual(self.mod.classify_args(["/usr/bin/agy"], "agy"), "agy")

    def test_gemini_adapter_prints_empty_object(self):
        adapter = Path(__file__).resolve().parents[1] / "adapters" / "gemini"
        env = os.environ.copy()
        env["DASHBOTS_HOOK_ASSUME"] = "1"
        env["DASHBOTS_HOOK_PID"] = str(os.getpid())
        result = subprocess.run(
            [str(adapter)],
            input=json.dumps({
                "hook_event_name": "SessionStart",
                "session_id": "from-adapter",
                "cwd": "/work/demo",
            }),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "{}\n")
        self.assertEqual(self.record("from-adapter")["harness"], "gemini")

    def test_hook_cli_is_silent(self):
        script = Path(__file__).resolve().parents[1] / "bin" / "dashbots"
        env = os.environ.copy()
        result = subprocess.run(
            [str(script), "hook", "--harness", "grok"],
            input=json.dumps({
                "hook_event_name": "SessionStart",
                "sessionId": "quiet",
                "cwd": "/work/demo",
            }),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.record("quiet")["status"], "alive")


if __name__ == "__main__":
    unittest.main()
