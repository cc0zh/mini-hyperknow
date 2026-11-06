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
        draft["units"][0]["lectures"][0]["sessions"] = [deepcopy(session) for _ in range(5)]
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
        cls.legacy_source = '{ "schema_version": 1, "script_id": "old-http-script", "steps": [] }'
        with cls.db.transaction() as conn:
            conn.execute("INSERT INTO lesson_scripts VALUES (?,?,?)", ("old-http-script", cls.sids[4], cls.legacy_source))
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
            early = self.client.post(f"/api/sessions/{sid}/complete", json=self.payload(saved, "http-early-complete"))
            self.assertEqual((early.status_code, early.json()["error"]["code"]), (409, "lesson_incomplete"))
            self.assertFalse(self.snapshot(sid)["completed"])
            for cursor in range(len(saved["script"]["steps"])):
                response = self.client.put(f"/api/sessions/{sid}/progress", json=self.payload(
                    saved, f"http-complete-progress-{cursor}", cursor=cursor, play_intent="paused"))
                self.assertEqual(response.status_code, 200)
                saved = response.json()
            payload = self.payload(saved, "http-complete")
            response = self.client.post(f"/api/sessions/{sid}/complete", json=payload)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["completed"])
            event = json.loads(ws.recv(timeout=3))
            self.assertEqual(event["resource_type"], "course")
            after = self.client.get(f"/api/courses/{self.cid}").json()
            self.assertEqual(after["version"], before["version"] + 1)
            self.assertEqual(after["progress"], 20)
            self.assertEqual(after["version"], event["version"])
            self.assertEqual(self.client.post(f"/api/sessions/{sid}/complete", json=payload).json(), response.json())
            self.assertEqual(self.client.get(f"/api/courses/{self.cid}").json(), after)
            self.assertEqual(self.client.get("/api/courses").json()["courses"], [after])

    def test_unsupported_lesson_is_readable_and_only_explicit_regeneration_creates_a_run(self):
        sid = self.sids[4]
        saved = self.snapshot(sid)
        self.assertIsNone(saved["script"])
        self.assertEqual(saved["format_error"]["code"], "lesson_format_unsupported")
        self.assertIsNone(saved["generation_run"])
        self.assertEqual(saved["progress"]["version"], 1)
        self.assertEqual(self.client.get(f"/api/sessions/{sid}").json(), saved)
        prepare = self.client.post(f"/api/sessions/{sid}/prepare", json={"client_command_id": "old-http-prepare"})
        self.assertEqual((prepare.status_code, prepare.json()["error"]["code"]), (409, "lesson_format_unsupported"))
        path = f"/api/sessions/{sid}/regenerate"
        body = {"client_command_id": "old-http-regenerate", "expected_version": saved["progress"]["version"]}
        response = self.client.post(path, json=body)
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (503, "model_not_configured"))
        self.assertEqual(self.snapshot(sid), saved)
        for patch in ({"expected_version": 0}, {"unknown": True}):
            self.assertEqual(self.client.post(path, json={**body, **patch}).status_code, 422)
        # Direct command input queues real storage work but does not enqueue a model worker.
        queued = self.db.regenerate_lesson(sid, body, "stored-model", True)
        run = queued["generation_run"]
        self.assertEqual(self.snapshot(sid), queued)
        self.assertEqual(run["status"], "queued")
        self.assertEqual(run["previous_script_data"], self.legacy_source)
        self.db.transition(run["run_id"], {"queued"}, status="failed", error={"code": "direct-input-failure"})
        failed = self.snapshot(sid)
        self.assertEqual(failed["generation_run"]["status"], "failed")
        self.assertEqual(failed["format_error"], saved["format_error"])
        self.assertEqual(self.db.calls(run["run_id"]), [])
        with self.db.transaction() as conn:
            self.assertEqual(conn.execute("SELECT data FROM lesson_scripts WHERE session_id=?", (sid,)).fetchone()["data"], self.legacy_source)

    def test_z_question_anchor_fields_are_validated_before_model_configuration(self):
        sid = self.sids[1]
        saved = self.snapshot(sid)
        steps = saved["script"]["steps"]
        path = f"/api/sessions/{sid}/questions"
        base = self.payload(saved, "http-anchor-question", cursor=saved["progress"]["cursor"],
                            question="这个对象为什么？", was_playing=False)
        for patch in ({"anchor_step_id": steps[-1]["step_id"]}, {"anchor_object_id": "summary"},
                      {"anchor_object_id": "foreign-object"}, {"anchor_step_id": ""}):
            response = self.client.post(path, json={**base, **patch})
            self.assertEqual(response.status_code, 422)
        accepted = self.client.post(path, json={**base, "anchor_step_id": steps[0]["step_id"], "anchor_object_id": "call"})
        self.assertEqual(accepted.status_code, 503)
        self.assertEqual(accepted.json()["error"]["code"], "model_not_configured")
        self.assertEqual(self.snapshot(sid), saved)
