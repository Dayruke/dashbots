import importlib.machinery
import importlib.util
import json
import os
import subprocess
import tempfile
import time
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
        self.menu = Path(self.tmp.name) / "omarchy-menu.jsonc"
        os.environ["XDG_STATE_HOME"] = str(self.state)
        os.environ["DASHBOTS_TOGGLE_FILE"] = str(self.flag)
        os.environ["DASHBOTS_MENU_FILE"] = str(self.menu)
        os.environ["DASHBOTS_HOOK_ASSUME"] = "1"
        os.environ["DASHBOTS_HOOK_PID"] = str(os.getpid())
        os.environ.pop("GEMINI_SESSION_ID", None)
        os.environ.pop("DASHBOTS_AGY_HOOKS_FILE", None)
        os.environ.pop("DASHBOTS_CONFIG", None)
        os.environ.pop("DASHBOTS_SHELL_FILE", None)
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
        real_alive = self.mod.pid_alive
        self.mod.pid_alive = lambda pid: int(pid) in (11, 22)
        try:
            self.mod.now_stamp = lambda: "2026-01-01T00:00:01Z"
            self.mod.write_record({
                "id": "older",
                "harness": "grok",
                "pid": 11,
                "cwd": "/work/a",
                "title": "a",
                "status": "alive",
                "window": "",
                "updated_at": "",
                "activity": "",
                "source": "hook",
                "turn": "",
            })
            self.mod.now_stamp = lambda: "2026-01-01T00:00:02Z"
            self.mod.write_record({
                "id": "newer",
                "harness": "grok",
                "pid": 22,
                "cwd": "/work/b",
                "title": "b",
                "status": "alive",
                "window": "",
                "updated_at": "",
                "activity": "",
                "source": "hook",
                "turn": "",
            })
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
        finally:
            self.mod.pid_alive = real_alive

    def test_status_change_keeps_the_mark_in_place(self):
        real_alive = self.mod.pid_alive
        self.mod.pid_alive = lambda pid: int(pid) in (11, 22)
        try:
            self.mod.now_stamp = lambda: "2026-01-01T00:00:01Z"
            self.mod.write_record({
                "id": "older",
                "harness": "grok",
                "pid": 11,
                "cwd": "/work/a",
                "title": "a",
                "status": "waiting",
                "window": "",
                "updated_at": "",
                "activity": "idle",
                "source": "hook",
                "turn": "",
            })
            self.mod.now_stamp = lambda: "2026-01-01T00:00:02Z"
            self.mod.write_record({
                "id": "newer",
                "harness": "grok",
                "pid": 22,
                "cwd": "/work/b",
                "title": "b",
                "status": "waiting",
                "window": "",
                "updated_at": "",
                "activity": "idle",
                "source": "hook",
                "turn": "",
            })
            self.mod.now_stamp = lambda: "2026-01-01T00:00:03Z"
            older = self.record("older")
            older["status"] = "working"
            older["activity"] = "working"
            self.mod.write_record(older)
            listed = self.mod.live_records()
            self.assertEqual([item["id"] for item in listed], ["newer", "older"])
            stored = self.record("older")
            self.assertEqual(stored["created_at"], "2026-01-01T00:00:01Z")
            self.assertEqual(stored["updated_at"], "2026-01-01T00:00:03Z")
            self.assertEqual(stored["status"], "working")
            self.assertEqual(self.record("newer")["created_at"], "2026-01-01T00:00:02Z")
        finally:
            self.mod.pid_alive = real_alive

    def test_old_record_keeps_its_place_when_created_at_is_missing(self):
        real_alive = self.mod.pid_alive
        self.mod.pid_alive = lambda pid: True
        try:
            path = Path(self.mod.session_path("kept"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "id": "kept",
                "harness": "grok",
                "pid": 11,
                "cwd": "/work/a",
                "title": "a",
                "status": "waiting",
                "window": "",
                "updated_at": "2026-01-01T00:00:01Z",
                "activity": "idle",
                "source": "hook",
                "turn": "",
            }))
            self.mod.now_stamp = lambda: "2026-01-01T00:00:09Z"
            current = self.record("kept")
            current["status"] = "working"
            self.mod.write_record(current)
            stored = self.record("kept")
            self.assertEqual(stored["created_at"], "2026-01-01T00:00:01Z")
            self.assertEqual(stored["updated_at"], "2026-01-01T00:00:09Z")
            self.assertEqual([item["id"] for item in self.mod.live_records()], ["kept"])
        finally:
            self.mod.pid_alive = real_alive

    def test_new_session_replaces_the_previous_mark_on_that_pid(self):
        self.mod.now_stamp = lambda: "2026-01-01T00:00:01Z"
        self.hook({"hook_event_name": "SessionStart", "sessionId": "old", "cwd": "/work/demo"})
        self.hook({
            "hook_event_name": "Notification",
            "sessionId": "old",
            "notification_type": "idle_prompt",
        })
        self.hook({
            "hook_event_name": "PreToolUse",
            "sessionId": "new",
            "toolName": "grep",
        })
        self.assertIsNone(self.record("new"))
        self.assertEqual(self.record("old")["status"], "waiting")

        self.mod.now_stamp = lambda: "2026-01-01T00:00:02Z"
        self.hook({"hook_event_name": "SessionStart", "sessionId": "new", "cwd": "/work/demo"})
        self.assertIsNone(self.record("old"))
        self.assertEqual(self.record("new")["pid"], os.getpid())

        self.mod.now_stamp = lambda: "2026-01-01T00:00:03Z"
        self.hook({
            "hook_event_name": "Notification",
            "sessionId": "old",
            "notification_type": "idle_prompt",
        })
        self.assertIsNone(self.record("old"))
        self.assertIsNotNone(self.record("new"))

        self.mod.now_stamp = lambda: "2026-01-01T00:00:01Z"
        self.mod.write_record({
            "id": "old",
            "harness": "grok",
            "pid": os.getpid(),
            "cwd": "/work/demo",
            "title": "demo",
            "status": "waiting",
            "window": "",
            "updated_at": "",
            "activity": "idle",
            "source": "hook",
            "turn": "",
        })
        self.assertEqual(self.mod.cmd_gc(["gc"]), 0)
        self.assertIsNone(self.record("old"))
        self.assertIsNotNone(self.record("new"))

    def test_body_is_unique_until_the_catalog_is_full(self):
        self.mod.random.seed(0)
        real_alive = self.mod.pid_alive
        self.mod.pid_alive = lambda pid: int(pid) >= 1000
        try:
            for index in range(4):
                os.environ["DASHBOTS_HOOK_PID"] = str(1000 + index)
                self.hook({
                    "hook_event_name": "SessionStart",
                    "sessionId": f"s{index}",
                    "cwd": "/work/demo",
                })
            bodies = [self.record(f"s{index}")["body"] for index in range(4)]
            self.assertEqual(sorted(bodies), ["blob", "circle", "square", "triangle"])
            kept = self.record("s0")["body"]
            os.environ["DASHBOTS_HOOK_PID"] = "1000"
            self.hook({
                "hook_event_name": "UserPromptSubmit",
                "sessionId": "s0",
                "promptId": "p1",
                "prompt": "keep the shape",
                "cwd": "/work/demo",
            })
            self.assertEqual(self.record("s0")["body"], kept)
            os.environ["DASHBOTS_HOOK_PID"] = "1004"
            self.hook({
                "hook_event_name": "SessionStart",
                "sessionId": "s4",
                "cwd": "/work/demo",
            })
            self.assertIn(self.record("s4")["body"], bodies)
        finally:
            self.mod.pid_alive = real_alive
            os.environ["DASHBOTS_HOOK_PID"] = str(os.getpid())

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

    def test_agy_status_map(self):
        pid = os.getpid()
        session = f"agy-{pid}"
        twin = f"scan-agy-{pid}"
        self.mod.write_record({
            "id": twin,
            "harness": "agy",
            "pid": pid,
            "cwd": "/work/demo",
            "title": "demo",
            "status": "alive",
            "window": "",
            "updated_at": "2026-01-01T00:00:00Z",
            "activity": "",
            "source": "scan",
            "turn": "",
        })
        self.hook({
            "hook_event_name": "PreInvocation",
            "conversationId": "conv-a",
            "workspacePaths": ["/work/demo"],
        }, "agy")
        rec = self.record(session)
        self.assertEqual(rec["status"], "working")
        self.assertEqual(rec["activity"], "thinking")
        self.assertEqual(rec["cwd"], "/work/demo")
        self.assertEqual(rec["source"], "hook")
        self.assertIsNone(self.record(twin))
        self.assertIsNone(self.record("conv-a"))

        self.hook({
            "hook_event_name": "PreInvocation",
            "conversationId": "conv-b",
            "workspacePaths": ["/work/other"],
        }, "agy")
        self.assertEqual(self.record(session)["cwd"], "/work/other")
        self.assertIsNone(self.record("conv-b"))

        self.hook({
            "hook_event_name": "PreToolUse",
            "toolCall": {"name": "run_command", "args": {}},
        }, "agy")
        self.assertEqual(self.record(session)["status"], "working")
        self.assertEqual(self.record(session)["activity"], "run_command")

        self.hook({
            "hook_event_name": "PostToolUse",
            "toolCall": {"name": "run_command"},
            "error": "exit status 1",
        }, "agy")
        self.assertEqual(self.record(session)["status"], "working")
        self.assertEqual(self.record(session)["activity"], "run_command")

        self.hook({
            "hook_event_name": "PreToolUse",
            "toolCall": {"name": "ask_question"},
        }, "agy")
        self.assertEqual(self.record(session)["status"], "waiting")
        self.assertEqual(self.record(session)["activity"], "needs a decision")

        self.hook({
            "hook_event_name": "PostToolUse",
            "toolCall": {"name": "ask_permission"},
        }, "agy")
        self.assertEqual(self.record(session)["status"], "working")
        self.assertEqual(self.record(session)["activity"], "ask_permission")

        self.hook({"hook_event_name": "PostInvocation"}, "agy")
        self.assertEqual(self.record(session)["status"], "working")
        self.assertEqual(self.record(session)["activity"], "ask_permission")

        self.hook({
            "hook_event_name": "Stop",
            "terminationReason": "model_stop",
            "fullyIdle": False,
        }, "agy")
        self.assertEqual(self.record(session)["status"], "waiting")
        self.assertEqual(self.record(session)["activity"], "background still running")

        self.hook({
            "hook_event_name": "Stop",
            "terminationReason": "model_stop",
            "fullyIdle": True,
        }, "agy")
        self.assertEqual(self.record(session)["status"], "waiting")
        self.assertEqual(self.record(session)["activity"], "idle")

        self.hook({
            "hook_event_name": "Stop",
            "terminationReason": "error",
            "error": "boom",
            "fullyIdle": True,
        }, "agy")
        self.assertEqual(self.record(session)["status"], "error")
        self.assertEqual(self.record(session)["activity"], "error")
        self.assertIsNotNone(self.record(session))

    def test_agy_event_flag_and_adapter_stdout(self):
        script = Path(__file__).resolve().parents[1] / "bin" / "dashbots"
        adapter = Path(__file__).resolve().parents[1] / "adapters" / "agy"
        env = os.environ.copy()
        env["DASHBOTS_HOOK_ASSUME"] = "1"
        env["DASHBOTS_HOOK_PID"] = str(os.getpid())
        result = subprocess.run(
            [str(script), "hook", "--harness", "agy", "--event", "PreInvocation"],
            input=json.dumps({"conversationId": "conv-1", "workspacePaths": ["/work/demo"]}),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.record(f"agy-{os.getpid()}")["status"], "working")

        stopped = subprocess.run(
            [str(adapter), "Stop"],
            input=json.dumps({
                "conversationId": "conv-1",
                "workspacePaths": ["/work/demo"],
                "terminationReason": "model_stop",
                "fullyIdle": True,
            }),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(stopped.returncode, 0)
        self.assertEqual(stopped.stdout, '{"decision":"allow"}\n')
        self.assertEqual(self.record(f"agy-{os.getpid()}")["status"], "waiting")
        self.assertEqual(self.record(f"agy-{os.getpid()}")["activity"], "idle")

        quiet = subprocess.run(
            [str(adapter), "PreToolUse"],
            input=json.dumps({
                "toolCall": {"name": "ask_permission"},
                "workspacePaths": ["/work/demo"],
            }),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(quiet.returncode, 0)
        self.assertEqual(quiet.stdout, '{"decision":"allow"}\n')
        self.assertEqual(self.record(f"agy-{os.getpid()}")["activity"], "needs a decision")

    def test_agy_wrapper_allows_pretool(self):
        lib = Path(self.tmp.name) / "lib"
        original = self.mod.lib_dir
        self.mod.lib_dir = lambda: str(lib)
        try:
            self.mod.install_wrapper("agy", agy=True)
        finally:
            self.mod.lib_dir = original
        text = (lib / "agy").read_text(encoding="utf-8")
        self.assertIn('if [ "$event" = "PreToolUse" ]; then', text)
        self.assertIn('{"decision":"allow"}', text)
        self.assertNotIn("printf '%s\\n' '{}'\nexit 0", text)

    def test_hook_applies_while_stdin_stays_open(self):
        script = Path(__file__).resolve().parents[1] / "bin" / "dashbots"
        env = os.environ.copy()
        env["DASHBOTS_HOOK_ASSUME"] = "1"
        env["DASHBOTS_HOOK_PID"] = str(os.getpid())
        proc = subprocess.Popen(
            [str(script), "hook", "--harness", "agy", "--event", "Stop"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            env=env,
        )
        proc.stdin.write(json.dumps({
            "terminationReason": "model_stop",
            "fullyIdle": True,
            "workspacePaths": ["/work/demo"],
        }))
        proc.stdin.flush()
        status = None
        deadline = time.time() + 2
        while time.time() < deadline:
            rec = self.record(f"agy-{os.getpid()}")
            if rec and rec.get("status") == "waiting":
                status = rec["status"]
                break
            time.sleep(0.05)
        proc.stdin.close()
        proc.stdout.close()
        proc.wait(timeout=2)
        self.assertEqual(status, "waiting")
        self.assertEqual(self.record(f"agy-{os.getpid()}")["activity"], "idle")

    def test_agy_presence_does_not_clobber_status(self):
        pid = os.getpid()
        originals = (self.mod.iter_pids, self.mod.harness_of, self.mod.cwd_of)
        self.mod.iter_pids = lambda: [pid]
        self.mod.harness_of = lambda candidate: "agy" if candidate == pid else None
        self.mod.cwd_of = lambda _candidate: "/work/demo"
        try:
            self.assertEqual(self.mod.cmd_scan(["scan"]), 0)
            rec = self.record(f"scan-agy-{pid}")
            self.assertEqual(rec["status"], "alive")
            self.assertEqual(rec["source"], "scan")
            self.assertEqual(rec["title"], "demo")
            self.mod.now_stamp = lambda: "2099-01-01T00:00:00Z"
            self.assertEqual(self.mod.cmd_scan(["scan"]), 0)
            again = self.record(f"scan-agy-{pid}")
            self.assertEqual(again["status"], "alive")
            self.assertNotEqual(again["updated_at"], "2099-01-01T00:00:00Z")
        finally:
            self.mod.iter_pids, self.mod.harness_of, self.mod.cwd_of = originals

    def test_agy_gc_keeps_presence_until_a_hook_exists(self):
        pid = os.getpid()
        marker = Path(self.mod.adapters_dir())
        marker.mkdir(parents=True)
        (marker / "agy").write_text("")
        (marker / "grok").write_text("")
        self.mod.write_record({
            "id": f"scan-agy-{pid}",
            "harness": "agy",
            "pid": pid,
            "cwd": "/work/demo",
            "title": "demo",
            "status": "alive",
            "window": "",
            "updated_at": "2026-01-01T00:00:00Z",
            "activity": "",
            "source": "scan",
            "turn": "",
        })
        self.mod.write_record({
            "id": f"scan-grok-{pid}",
            "harness": "grok",
            "pid": pid,
            "cwd": "/work/demo",
            "title": "demo",
            "status": "alive",
            "window": "",
            "updated_at": "2026-01-01T00:00:00Z",
            "activity": "",
            "source": "scan",
            "turn": "",
        })
        self.assertEqual(self.mod.cmd_gc(["gc"]), 0)
        self.assertIsNotNone(self.record(f"scan-agy-{pid}"))
        self.assertIsNone(self.record(f"scan-grok-{pid}"))

        self.hook({
            "hook_event_name": "PreInvocation",
            "workspacePaths": ["/work/demo"],
        }, "agy")
        self.assertIsNone(self.record(f"scan-agy-{pid}"))
        self.mod.write_record({
            "id": f"scan-agy-{pid}",
            "harness": "agy",
            "pid": pid,
            "cwd": "/work/demo",
            "title": "demo",
            "status": "alive",
            "window": "",
            "updated_at": "2026-01-01T00:00:00Z",
            "activity": "",
            "source": "scan",
            "turn": "",
        })
        self.assertEqual(self.mod.cmd_gc(["gc"]), 0)
        self.assertIsNone(self.record(f"scan-agy-{pid}"))
        self.assertEqual(self.record(f"agy-{pid}")["status"], "working")

    def test_harness_of_skips_cmdline_for_other_comms(self):
        originals = (self.mod.comm_of, self.mod.cmdline)
        opened = []
        comms = {1: "bash", 2: "node", 3: "codex"}
        self.mod.comm_of = lambda pid: comms[pid]

        def fake_cmdline(pid):
            opened.append(pid)
            return {2: ["/usr/bin/node", "/opt/gemini.js"], 3: ["/usr/bin/codex"]}.get(pid, [])

        self.mod.cmdline = fake_cmdline
        try:
            self.assertIsNone(self.mod.harness_of(1))
            self.assertEqual(self.mod.harness_of(2), "gemini")
            self.assertEqual(self.mod.harness_of(3), "codex")
            self.assertEqual(opened, [2, 3])
        finally:
            self.mod.comm_of, self.mod.cmdline = originals

    def test_scanner_classifies_a_pid_once_until_the_recheck(self):
        names = ("iter_pids", "harness_of", "pid_alive", "cwd_of", "hypr_clients")
        originals = {name: getattr(self.mod, name) for name in names}
        pids = [101, 202]
        looked = []
        hypr = []
        clock = [1000.0]

        def harness_of(pid):
            looked.append(pid)
            return "codex" if pid == 202 else None

        def clients():
            hypr.append(1)
            return [{"pid": 202, "address": "0xabc"}]

        self.mod.iter_pids = lambda: list(pids)
        self.mod.harness_of = harness_of
        self.mod.pid_alive = lambda pid: True
        self.mod.cwd_of = lambda pid: "/work/demo"
        self.mod.hypr_clients = clients
        try:
            scanner = self.mod.Scanner(clock=lambda: clock[0])
            scanner.scan()
            self.assertEqual(sorted(looked), [101, 202])
            self.assertEqual(len(hypr), 1)
            self.assertEqual(self.record("scan-codex-202")["window"], "0xabc")

            looked.clear()
            clock[0] += 2
            pids.append(303)
            scanner.scan()
            self.assertEqual(looked, [303])
            self.assertEqual(len(hypr), 1)

            pids.remove(101)
            clock[0] += 2
            scanner.scan()
            self.assertNotIn(101, scanner.harnesses)

            looked.clear()
            clock[0] += self.mod.RECHECK_SECONDS
            scanner.scan()
            self.assertEqual(sorted(looked), [202, 303])
            self.assertEqual(len(hypr), 2)
        finally:
            for name, value in originals.items():
                setattr(self.mod, name, value)

    def test_scanner_skips_hyprctl_without_a_candidate(self):
        names = ("iter_pids", "harness_of", "hypr_clients")
        originals = {name: getattr(self.mod, name) for name in names}
        hypr = []
        self.mod.iter_pids = lambda: [101, 202]
        self.mod.harness_of = lambda pid: None
        self.mod.hypr_clients = lambda: hypr.append(1) or []
        try:
            self.assertEqual(self.mod.cmd_scan(["scan"]), 0)
            self.assertEqual(hypr, [])
        finally:
            for name, value in originals.items():
                setattr(self.mod, name, value)

    def test_scanner_retries_a_missing_window_slowly(self):
        names = ("iter_pids", "harness_of", "pid_alive", "cwd_of", "hypr_clients")
        originals = {name: getattr(self.mod, name) for name in names}
        hypr = []
        clock = [1000.0]
        self.mod.iter_pids = lambda: [202]
        self.mod.harness_of = lambda pid: "codex"
        self.mod.pid_alive = lambda pid: True
        self.mod.cwd_of = lambda pid: "/work/demo"
        self.mod.hypr_clients = lambda: hypr.append(1) or []
        try:
            scanner = self.mod.Scanner(clock=lambda: clock[0])
            scanner.scan()
            clock[0] += 2
            scanner.scan()
            self.assertEqual(len(hypr), 1)
            clock[0] += self.mod.WINDOW_RETRY_SECONDS
            scanner.scan()
            self.assertEqual(len(hypr), 2)
        finally:
            for name, value in originals.items():
                setattr(self.mod, name, value)

    def test_agy_hook_merge_keeps_other_hooks(self):
        path = Path(self.tmp.name) / "hooks.json"
        path.write_text(json.dumps({
            "lint": {
                "PostToolUse": [{
                    "matcher": "run_command",
                    "hooks": [{"command": "./lint.sh"}],
                }],
            },
        }), encoding="utf-8")
        os.environ["DASHBOTS_AGY_HOOKS_FILE"] = str(path)
        self.assertTrue(self.mod.install_agy_hooks())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["lint"]["PostToolUse"][0]["hooks"][0]["command"], "./lint.sh")
        entry = data["dashbots"]
        self.assertEqual(entry["PreToolUse"][0]["matcher"], "*")
        self.assertTrue(entry["PreToolUse"][0]["hooks"][0]["command"].endswith("agy PreToolUse"))
        self.assertTrue(entry["Stop"][0]["command"].endswith("agy Stop"))
        self.assertEqual(entry["Stop"][0]["timeout"], 5)
        self.assertTrue(self.mod.install_agy_hooks())
        again = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(again["lint"]["PostToolUse"][0]["hooks"][0]["command"], "./lint.sh")
        self.assertEqual(len(again["dashbots"]["PreInvocation"]), 1)
        self.mod.uninstall_agy_hooks()
        left = json.loads(path.read_text(encoding="utf-8"))
        self.assertNotIn("dashbots", left)
        self.assertIn("lint", left)

        bad = Path(self.tmp.name) / "bad.json"
        bad.write_text("{", encoding="utf-8")
        os.environ["DASHBOTS_AGY_HOOKS_FILE"] = str(bad)
        self.assertFalse(self.mod.install_agy_hooks())
        self.assertEqual(bad.read_text(encoding="utf-8"), "{")

    def test_focus_keeps_the_pointer_and_restores_warps(self):
        lua = self.mod.focus_lua("0xabc", (12, -4), "true", "1")
        self.assertIn("no_warps = true", lua)
        self.assertIn("warp_on_change_workspace = 0", lua)
        self.assertIn('window = "address:0xabc"', lua)
        self.assertIn("x = 12, y = -4", lua)
        self.assertIn("no_warps = true, warp_on_change_workspace = 1", lua)
        self.assertLess(lua.index("hl.dsp.focus"), lua.index("hl.dsp.cursor.move"))
        self.assertLess(lua.index("hl.dsp.cursor.move"), lua.rindex("hl.config"))

        self.assertIsNone(self.mod.parse_cursor_pos("nope"))
        self.assertEqual(self.mod.parse_cursor_pos("744, 18\n"), (744, 18))
        self.assertEqual(self.mod.parse_hypr_bool("bool: false\nset: true\n"), "false")
        self.assertEqual(self.mod.parse_hypr_choice("int: 1\nset: true\n"), "1")
        self.assertEqual(self.mod.cmd_focus(["focus", "not-an-address"]), 2)

        calls = []

        def fake_hypr(args):
            calls.append(list(args))
            if args[1:] == ["cursorpos"]:
                return "10, 20\n"
            if args[1:] == ["getoption", "cursor:no_warps"]:
                return "bool: false\nset: false\n"
            if args[1:] == ["getoption", "cursor:warp_on_change_workspace"]:
                return "int: 1\nset: true\n"
            if args[1] == "eval":
                return "ok\n"
            return ""

        original = self.mod.hypr_text
        self.mod.hypr_text = fake_hypr
        try:
            self.assertEqual(self.mod.cmd_focus(["focus", "0x55"]), 0)
        finally:
            self.mod.hypr_text = original
        self.assertEqual(calls[-1][1], "eval")
        expr = calls[-1][2]
        self.assertIn('window = "address:0x55"', expr)
        self.assertIn("x = 10, y = 20", expr)
        self.assertIn("warp_on_change_workspace = 1", expr)
        self.assertTrue(expr.endswith("warp_on_change_workspace = 1 } })"))

    def test_menu_trigger_round_trip(self):
        sample = """{
  // Extend the menu.

  "install.ai.grok-bot": { "when": "false" }
}
"""
        self.menu.write_text(sample, encoding="utf-8")
        self.assertTrue(self.mod.install_menu_trigger())
        text = self.menu.read_text(encoding="utf-8")
        self.assertIn("// Extend the menu.", text)
        parsed = self.mod.parse_menu_jsonc(text)
        self.assertEqual(parsed["trigger.toggle.dashbots"], self.mod.MENU_ENTRY)
        self.assertEqual(parsed["install.ai.grok-bot"], {"when": "false"})
        self.assertTrue(self.mod.install_menu_trigger())
        self.assertEqual(self.menu.read_text(encoding="utf-8"), text)

        stale = text.replace("omarchy-toggle dashbots", "omarchy-toggle other")
        self.menu.write_text(stale, encoding="utf-8")
        self.assertTrue(self.mod.install_menu_trigger())
        parsed = self.mod.parse_menu_jsonc(self.menu.read_text(encoding="utf-8"))
        self.assertEqual(parsed["trigger.toggle.dashbots"]["action"], "omarchy-toggle dashbots")
        self.assertEqual(parsed["install.ai.grok-bot"], {"when": "false"})

        spread = """{
  "trigger.toggle.dashbots": {
    "label": "Old"
  },
  "install.ai.grok-bot": { "when": "false" }
}
"""
        self.menu.write_text(spread, encoding="utf-8")
        self.assertTrue(self.mod.install_menu_trigger())
        parsed = self.mod.parse_menu_jsonc(self.menu.read_text(encoding="utf-8"))
        self.assertEqual(parsed["trigger.toggle.dashbots"], self.mod.MENU_ENTRY)
        self.assertEqual(list(parsed), ["install.ai.grok-bot", "trigger.toggle.dashbots"])

        self.assertTrue(self.mod.uninstall_menu_trigger())
        left = self.menu.read_text(encoding="utf-8")
        self.assertNotIn("trigger.toggle.dashbots", left)
        parsed = self.mod.parse_menu_jsonc(left)
        self.assertEqual(parsed, {"install.ai.grok-bot": {"when": "false"}})
        self.assertTrue(self.mod.uninstall_menu_trigger())

    def test_menu_trigger_creates_and_skips_invalid(self):
        self.assertFalse(self.menu.exists())
        self.assertTrue(self.mod.install_menu_trigger())
        parsed = self.mod.parse_menu_jsonc(self.menu.read_text(encoding="utf-8"))
        self.assertEqual(parsed["trigger.toggle.dashbots"]["label"], "Dashbots")
        self.assertTrue(self.mod.uninstall_menu_trigger())
        parsed = self.mod.parse_menu_jsonc(self.menu.read_text(encoding="utf-8"))
        self.assertEqual(parsed, {})

        broken = "{ not json\n"
        self.menu.write_text(broken, encoding="utf-8")
        self.assertFalse(self.mod.install_menu_trigger())
        self.assertEqual(self.menu.read_text(encoding="utf-8"), broken)

    def test_parse_config(self):
        parsed = self.mod.parse_config(
            "# note\nswingMs 800\nanimate false\nplace workspaces\nplace sideways\n"
        )
        self.assertEqual(parsed["swingMs"], 800)
        self.assertFalse(parsed["animate"])
        self.assertEqual(parsed["place"], "workspaces")
        defaults = self.mod.parse_config("swingMs 0\nanimate maybe\n")
        self.assertEqual(defaults["swingMs"], 2000)
        self.assertTrue(defaults["animate"])
        self.assertEqual(defaults["place"], "center-right")

    def test_install_config_keeps_an_existing_file(self):
        path = Path(self.tmp.name) / "config"
        os.environ["DASHBOTS_CONFIG"] = str(path)
        self.mod.install_config()
        self.assertEqual(path.read_text(encoding="utf-8"), self.mod.default_config_text())
        path.write_text("swingMs 50\n", encoding="utf-8")
        self.mod.install_config()
        self.assertEqual(path.read_text(encoding="utf-8"), "swingMs 50\n")

    def test_place_follows_config(self):
        shell = Path(self.tmp.name) / "shell.json"
        shell.write_text(json.dumps({
            "bar": {"layout": {
                "left": [{"id": "omarchy.menu"}, {"id": "omarchy.workspaces"}],
                "center": [
                    {"id": "omarchy.keyboard-layout"},
                    {"id": "omarchy.clock", "format": "HH:mm"},
                    {"id": "omarchy.weather"},
                    {"id": "dashbots"},
                ],
                "right": [{"id": "omarchy.tray"}],
            }},
        }), encoding="utf-8")
        os.environ["DASHBOTS_SHELL_FILE"] = str(shell)
        config = Path(self.tmp.name) / "config"
        os.environ["DASHBOTS_CONFIG"] = str(config)
        config.write_text("place center-left\n", encoding="utf-8")
        self.assertEqual(self.mod.cmd_place(["place"]), 0)
        data = json.loads(shell.read_text(encoding="utf-8"))
        center = data["bar"]["layout"]["center"]
        self.assertEqual(
            [entry["id"] for entry in center],
            ["omarchy.keyboard-layout", "dashbots", "omarchy.clock", "omarchy.weather"],
        )
        self.assertEqual(center[2]["format"], "HH:mm")

        config.write_text("place center-right\n", encoding="utf-8")
        self.assertEqual(self.mod.cmd_place(["place"]), 0)
        data = json.loads(shell.read_text(encoding="utf-8"))
        center = data["bar"]["layout"]["center"]
        self.assertEqual(
            [entry["id"] for entry in center],
            ["omarchy.keyboard-layout", "omarchy.clock", "omarchy.weather", "dashbots"],
        )
        parked = shell.read_text(encoding="utf-8")
        self.assertEqual(self.mod.cmd_place(["place"]), 0)
        self.assertEqual(shell.read_text(encoding="utf-8"), parked)

        config.write_text("place workspaces\n", encoding="utf-8")
        self.assertEqual(self.mod.cmd_place(["place"]), 0)
        data = json.loads(shell.read_text(encoding="utf-8"))
        self.assertEqual(
            [entry["id"] for entry in data["bar"]["layout"]["left"]],
            ["omarchy.menu", "dashbots", "omarchy.workspaces"],
        )
        self.assertNotIn("dashbots", [entry["id"] for entry in data["bar"]["layout"]["center"]])

        bare = {"bar": {"layout": {"left": [], "center": [{"id": "omarchy.indicators"}], "right": []}}}
        self.mod.move_slot(bare["bar"]["layout"], "center-left")
        self.assertEqual(
            [entry["id"] for entry in bare["bar"]["layout"]["center"]],
            ["dashbots", "omarchy.indicators"],
        )
        self.mod.move_slot(bare["bar"]["layout"], "center-right")
        self.assertEqual(
            [entry["id"] for entry in bare["bar"]["layout"]["center"]],
            ["omarchy.indicators", "dashbots"],
        )


if __name__ == "__main__":
    unittest.main()
