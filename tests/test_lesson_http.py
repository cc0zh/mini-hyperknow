"""Actual Uvicorn/HTTP/WS over domain inputs on real temporary SQLite.

No model is configured or substituted. These checks prove persistence and
transport behavior, never real generated lesson/answer quality.
"""

from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import httpx
from websockets.sync.client import connect

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from hyperknow.domain import CourseDraft
from hyperknow.lesson_domain import BoardScriptDraft
from hyperknow.storage import Database
from test_course import course_data
from test_lesson import script_input


class LessonLiveServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="hyperknow-live-lesson-")
        cls.db = Database(Path(cls.directory.name) / "hyperknow.sqlite3")
        draft = course_data()
        session = draft["units"][0]["lectures"][0]["sessions"][0]
        draft["units"][0]["lectures"][0]["sessions"] = [deepcopy(session) for _ in range(4)]
        run = cls.db.create_run("live-domain-course", "理解协程", "stored-model")
        cls.db.transition(run["run_id"], {"queued"}, status="generating")
        ready = cls.db.finish_course(run["run_id"], CourseDraft.model_validate(draft))
        cls.cid = ready["course_id"]
        course = cls.db.get_course(cls.cid)
        cls.sids = [s["session_id"] for s in course["units"][0]["lectures"][0]["sessions"]]
        for sid in cls.sids[:3]:
            run = cls.db.prepare_lesson(sid, f"live-script-{sid}", "stored-model", True)["generation_run"]
            cls.db.transition(run["run_id"], {"queued"}, status="generating")
            cls.db.finish_lesson(run["run_id"], BoardScriptDraft.model_validate(script_input()))
        sid = cls.sids[2]
        saved = cls.db.get_lesson(sid)
        cls.db.ask_question(sid, {"client_command_id": "live-interrupted-question",
            "expected_version": saved["progress"]["version"], "script_id": saved["script"]["script_id"],
            "cursor": -1, "question": "为什么会暂停？", "was_playing": False}, "stored-model", True)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        env = {**os.environ, "OPENAI_API_KEY": "", "HK_DATA_DIR": cls.directory.name}
        cls.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "hyperknow.main:app", "--host", "127.0.0.1",
             "--port", str(cls.port), "--log-level", "warning"],
            cwd=Path(__file__).resolve().parents[1], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.client = httpx.Client(base_url=f"http://127.0.0.1:{cls.port}", trust_env=False, timeout=5)
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if cls.process.poll() is not None:
                    raise RuntimeError("Uvicorn exited before startup")
                try:
                    if cls.client.get("/api/health").status_code == 200:
                        return
                except httpx.TransportError:
                    pass
                time.sleep(0.05)
            raise RuntimeError("Uvicorn startup timed out")
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        # Only terminate this test-owned process, never the user's service.
        cls.process.terminate()
        try:
            cls.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait(timeout=5)
        cls.directory.cleanup()

    def snapshot(self, sid):
        response = self.client.get(f"/api/sessions/{sid}/lesson")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def payload(self, saved, command, **patch):
        return {"client_command_id": command, "expected_version": saved["progress"]["version"],
                "script_id": saved["script"]["script_id"], **patch}

    def test_reads_and_prepare_existing_script_need_no_model_configuration(self):
        sid = self.sids[0]
        before = self.snapshot(sid)
        self.assertEqual(before, self.client.get(f"/api/sessions/{sid}").json())
        prepared = self.client.post(f"/api/sessions/{sid}/prepare",
                                    json={"client_command_id": "http-existing-script"})
        self.assertEqual(prepared.status_code, 200)
        self.assertEqual(prepared.json()["script"], before["script"])
        self.assertFalse(self.client.get("/api/health").json()["model"]["configured"])
        self.assertEqual(self.db.calls(before["generation_run"]["run_id"]), [])
        missing = self.sids[3]
        response = self.client.post(f"/api/sessions/{missing}/prepare",
                                    json={"client_command_id": "http-no-model"})
        self.assertEqual(response.status_code, 503)
        self.assertIsNone(self.snapshot(missing)["generation_run"])

    def test_progress_conflict_idempotency_and_real_session_notification(self):
        sid = self.sids[1]
        path = f"/api/sessions/{sid}/progress"
        with connect(f"ws://127.0.0.1:{self.port}/api/events", proxy=None) as ws:
            self.assertEqual(json.loads(ws.recv())["type"], "connected")
            ws.send(json.dumps({"type": "subscribe", "topic": f"session:{sid}"}))
            self.assertEqual(json.loads(ws.recv()), {"type": "subscribed", "topic": f"session:{sid}"})
            saved = self.snapshot(sid)  # Read after subscription acknowledgment.
            payload = self.payload(saved, "http-progress-first", cursor=0, play_intent="playing")
            response = self.client.put(path, json=payload)
            self.assertEqual(response.status_code, 200)
            first = response.json()
            event = json.loads(ws.recv(timeout=3))
            self.assertEqual((event["resource_type"], event["resource_id"], event["version"]),
                             ("session", sid, first["version"]))
            self.assertNotIn("script", event)
            self.assertEqual(self.snapshot(sid)["progress"]["play_intent"], "playing")
            self.assertEqual(self.snapshot(sid), first)
            self.assertEqual(self.client.put(path, json=payload).json(), first)
            second = self.client.put(path, json=self.payload(first, "http-progress-second",
                                                             cursor=1, play_intent="paused")).json()
            self.assertEqual(self.client.put(path, json=payload).json(), second)
            stale = self.client.put(path, json=self.payload(saved, "http-stale",
                                                            cursor=0, play_intent="paused"))
            self.assertEqual(stale.status_code, 409)
            self.assertEqual(stale.json()["error"]["latest_version"], second["progress"]["version"])
            backward = self.client.put(path, json=self.payload(second, "http-backward",
                                                               cursor=0, play_intent="paused"))
            self.assertEqual(backward.status_code, 409)

    def test_restart_preserves_question_and_never_automatically_retries(self):
        saved = self.snapshot(self.sids[2])
        interaction = saved["interactions"][0]
        self.assertEqual(interaction["status"], "interrupted")
        self.assertEqual(interaction["question"], "为什么会暂停？")
        run = self.client.get(f"/api/runs/{interaction['run_id']}").json()
        self.assertEqual(run["kind"], "question")
        self.assertEqual(run["status"], "interrupted")
        self.assertEqual(self.db.calls(run["run_id"]), [])
        retry = self.client.post(f"/api/runs/{run['run_id']}/retry", json={
            "client_command_id": "http-retry-without-model", "expected_version": run["version"]})
        self.assertEqual(retry.status_code, 503)
        self.assertEqual(self.snapshot(self.sids[2])["interactions"][0]["run_id"], run["run_id"])

    def test_question_input_bounds_ownership_and_missing_configuration(self):
        sid = self.sids[0]
        saved = self.snapshot(sid)
        for question in ("a", "字" * 2001, "  "):
            response = self.client.post(f"/api/sessions/{sid}/questions", json=self.payload(
                saved, "http-invalid-question", cursor=-1, question=question, was_playing=False))
            self.assertEqual(response.status_code, 422)
        data = self.payload(saved, "http-question-no-config", cursor=-1, question="为什么？", was_playing=False)
        response = self.client.post(f"/api/sessions/{sid}/questions", json=data)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.snapshot(sid)["interactions"], [])
        data["script_id"] = self.snapshot(self.sids[2])["script"]["script_id"]
        self.assertEqual(self.client.post(f"/api/sessions/{sid}/questions", json=data).status_code, 409)

    def test_complete_updates_parent_course_and_emits_real_course_notification(self):
        sid = self.sids[2]
        with connect(f"ws://127.0.0.1:{self.port}/api/events", proxy=None) as ws:
            self.assertEqual(json.loads(ws.recv())["type"], "connected")
            ws.send(json.dumps({"type": "subscribe", "topic": f"course:{self.cid}"}))
            self.assertEqual(json.loads(ws.recv())["type"], "subscribed")
            before = self.client.get(f"/api/courses/{self.cid}").json()
            saved = self.snapshot(sid)
            payload = self.payload(saved, "http-complete")
            response = self.client.post(f"/api/sessions/{sid}/complete", json=payload)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["completed"])
            event = json.loads(ws.recv(timeout=3))
            self.assertEqual(event["resource_type"], "course")
            after = self.client.get(f"/api/courses/{self.cid}").json()
            self.assertEqual(after["version"], before["version"] + 1)
            self.assertEqual(after["progress"], 25)
            self.assertEqual(after["version"], event["version"])
            self.assertEqual(self.client.post(f"/api/sessions/{sid}/complete", json=payload).json(), response.json())
            self.assertEqual(self.client.get(f"/api/courses/{self.cid}").json(), after)
            self.assertEqual(self.client.get("/api/courses").json()["courses"], [after])
