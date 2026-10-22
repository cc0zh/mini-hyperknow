"""Real Uvicorn HTTP/WS and disk SQLite, with no configured model.

Deterministic domain inputs are passed to real storage transactions. This is
transport/persistence evidence only, not evidence of real model generation.
"""

from concurrent.futures import ThreadPoolExecutor
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

from hyperknow.domain import CourseDraft, uid
from hyperknow.lesson_domain import BoardScriptDraft
from hyperknow.quiz_domain import MAX_ELAPSED_MS, QuizDraft
from hyperknow.storage import Database
from test_course import course_data
from test_lesson import script_input
from test_quiz import quiz_input


class QuizLiveServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="hyperknow-live-quiz-")
        cls.db = Database(Path(cls.directory.name) / "hyperknow.sqlite3")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        cls.client = httpx.Client(base_url=f"http://127.0.0.1:{cls.port}", trust_env=False, timeout=5)
        try:
            cls.start_server()
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def start_server(cls):
        env = {**os.environ, "OPENAI_API_KEY": "", "HK_DATA_DIR": cls.directory.name}
        cls.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "hyperknow.main:app", "--host", "127.0.0.1",
             "--port", str(cls.port), "--log-level", "warning"],
            cwd=Path(__file__).resolve().parents[1], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if cls.process.poll() is not None:
                raise RuntimeError("Uvicorn exited before startup")
            try:
                if cls.client.get("/api/health").status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(.05)
        raise RuntimeError("Uvicorn startup timed out")

    @classmethod
    def stop_server(cls):
        # Only the process owned by this suite, never a user service.
        cls.process.terminate()
        try:
            cls.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait(timeout=5)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.stop_server()
        cls.directory.cleanup()

    def setUp(self):
        self.prefix = uid("http")
        run = self.db.create_run(self.prefix, "理解协程", "stored-model")
        self.db.transition(run["run_id"], {"queued"}, status="generating")
        ready = self.db.finish_course(run["run_id"], CourseDraft.model_validate(course_data()))
        self.cid = ready["course_id"]
        self.course = self.db.get_course(self.cid)
        unit = self.course["units"][0]
        self.sid = unit["lectures"][0]["sessions"][0]["session_id"]
        self.eid = unit["exams"][0]["exam_id"]

    def command(self, name, snapshot=None, **patch):
        data = {"client_command_id": f"{self.prefix}-{name}", **patch}
        if snapshot:
            data["expected_version"] = snapshot["attempt"]["version"]
        return data

    def get(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def post(self, path, data):
        response = self.client.post(path, json=data)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def lesson(self):
        run = self.db.prepare_lesson(self.sid, f"{self.prefix}-lesson", "stored-model", True)["generation_run"]
        self.db.transition(run["run_id"], {"queued"}, status="generating")
        self.db.finish_lesson(run["run_id"], BoardScriptDraft.model_validate(script_input()))

    def ready(self, kind="practice"):
        target_id = self.sid if kind == "practice" else self.eid
        if kind == "practice":
            self.lesson()
        saved = self.db.prepare_quiz(kind, target_id, f"{self.prefix}-quiz-{kind}", "stored-model", True)
        run = saved["generation_run"]
        self.db.transition(run["run_id"], {"queued"}, status="generating")
        draft = QuizDraft.model_validate(quiz_input(run["input"]["allowed_source_refs"][0]))
        self.db.finish_quiz(run["run_id"], draft)
        return self.db.get_quiz_target(kind, target_id)

    def create_attempt(self, target, name="attempt"):
        return self.post(f"/api/quizzes/{target['quiz']['quiz_id']}/attempts", self.command(name))

    def answer_data(self, saved, name, *, ids=None, skipped=False, elapsed=10000):
        question = saved["quiz"]["questions"][saved["attempt"]["cursor"]]
        return self.command(name, saved, question_id=question["question_id"],
                            option_ids=[] if skipped else ids if ids is not None else question["correct_option_ids"],
                            skipped=skipped, elapsed_ms=elapsed)

    def all_answered(self, saved):
        path = f"/api/attempts/{saved['attempt']['attempt_id']}"
        for index in range(3):
            saved = self.post(f"{path}/answers", self.answer_data(saved, f"answer-{index}"))
            if index < 2:
                saved = self.post(f"{path}/next", self.command(f"next-{index}", saved))
        return saved

    def subscribe(self, ws, *topics):
        self.assertEqual(json.loads(ws.recv(timeout=3)), {"type": "connected"})
        for topic in topics:
            ws.send(json.dumps({"type": "subscribe", "topic": topic}))
            self.assertEqual(json.loads(ws.recv(timeout=3)), {"type": "subscribed", "topic": topic})

    def events(self, ws, expected):
        received = [json.loads(ws.recv(timeout=3)) for _ in expected]
        self.assertEqual({(e["resource_type"], e["resource_id"]): e["version"] for e in received}, expected)
        self.assertTrue(all(e["type"] == "resource_changed" and "quiz" not in e for e in received))

    def test_reads_missing_configuration_and_cached_prepare_do_not_generate(self):
        practice_path = f"/api/sessions/{self.sid}/practice"
        exam_path = f"/api/exams/{self.eid}"
        before = self.get(practice_path)
        self.assertIsNone(before["quiz"])
        self.assertIsNone(before["latest_attempt"])
        self.assertFalse(self.get("/api/health")["model"]["configured"])
        missing_lesson = self.client.post(f"{practice_path}/prepare", json=self.command("missing-lesson"))
        self.assertEqual(missing_lesson.status_code, 409)
        self.assertEqual(missing_lesson.json()["error"]["code"], "lesson_required")
        missing_model = self.client.post(f"{exam_path}/prepare", json=self.command("missing-model"))
        self.assertEqual(missing_model.status_code, 503)
        self.assertIsNone(self.get(exam_path)["generation_run"])
        self.assertEqual(self.get(practice_path), before)
        target = self.ready()
        cached = self.post(f"{practice_path}/prepare", self.command("cached-prepare"))
        self.assertEqual(cached, target)
        self.assertEqual(self.get(f"/api/quizzes/{target['quiz']['quiz_id']}/attempts"), {"attempts": []})
        self.assertEqual(self.db.calls(target["generation_run"]["run_id"]), [])
        self.assertEqual(self.client.get("/api/exams/missing").status_code, 404)

    def test_feedback_next_explicit_submit_and_real_attempt_target_course_notifications(self):
        target = self.ready()
        saved = self.create_attempt(target)
        aid = saved["attempt"]["attempt_id"]
        path = f"/api/attempts/{aid}"
        key = f"practice:{self.sid}"
        with connect(f"ws://127.0.0.1:{self.port}/api/events", proxy=None) as ws:
            self.subscribe(ws, f"attempt:{aid}", f"quiz_target:{key}", f"course:{self.cid}", f"session:{self.sid}")
            saved = self.get(path)  # Read only after all subscription acknowledgements.
            initial = saved
            target_version = self.get(f"/api/sessions/{self.sid}/practice")["version"]
            payload = self.answer_data(saved, "first-answer")
            saved = self.post(f"{path}/answers", payload)
            answer = saved["attempt"]["answers"][0]
            self.assertEqual((answer["correct"], answer["fast"], answer["points"]), (True, True, 800))
            self.assertEqual(saved["attempt"]["cursor"], 0)
            self.assertEqual(saved["attempt"]["question_started_at"], initial["attempt"]["question_started_at"])
            self.assertEqual(self.get(path), saved)
            self.events(ws, {("attempt", aid): saved["attempt"]["version"],
                             ("quiz_target", key): target_version + 1})
            self.assertEqual(self.post(f"{path}/answers", payload), saved)
            self.events(ws, {("attempt", aid): saved["attempt"]["version"],
                             ("quiz_target", key): target_version + 1})
            conflict = self.client.post(f"{path}/answers", json=self.answer_data(initial, "stale-answer"))
            self.assertEqual(conflict.status_code, 409)
            self.assertEqual(conflict.json()["error"]["latest_version"], saved["attempt"]["version"])
            for index in (1, 2):
                previous_start = saved["attempt"]["question_started_at"]
                saved = self.post(f"{path}/next", self.command(f"next-{index}", saved))
                self.assertEqual(saved["attempt"]["cursor"], index)
                self.assertNotEqual(saved["attempt"]["question_started_at"], previous_start)
                target_version += 1
                self.events(ws, {("attempt", aid): saved["attempt"]["version"],
                                 ("quiz_target", key): target_version + 1})
                saved = self.post(f"{path}/answers", self.answer_data(
                    saved, f"answer-{index}", ids=["a"], skipped=index == 2, elapsed=10001))
                self.assertFalse(saved["attempt"]["answers"][-1]["correct"])
                target_version += 1
                self.events(ws, {("attempt", aid): saved["attempt"]["version"],
                                 ("quiz_target", key): target_version + 1})
            self.assertEqual(saved["attempt"]["status"], "in_progress")
            self.assertIsNone(saved["attempt"]["result"])
            self.assertFalse(self.get(f"/api/sessions/{self.sid}/practice")["completed"])
            submit = self.command("explicit-result", saved)
            result = self.post(f"{path}/submit", submit)
            self.assertEqual(result["attempt"]["result"], {
                "total_score": 800, "max_score": 2700, "correct_count": 1, "question_count": 3,
                "skipped_count": 1, "fast_count": 1, "best_streak": 1, "stars": 1,
                "total_elapsed_ms": 30002, "scoring_version": 1})
            lesson = self.get(f"/api/sessions/{self.sid}")
            self.events(ws, {("attempt", aid): result["attempt"]["version"],
                             ("quiz_target", key): target_version + 2,
                             ("session", self.sid): lesson["version"], ("course", self.cid): 2})
            self.assertTrue(lesson["completed"])
            self.assertEqual(result["course"]["progress"], 100)
            self.assertEqual(result["course"]["next_item"]["type"], "project")
            self.assertEqual(self.get(path), result)
            self.assertEqual(self.post(f"{path}/submit", submit), result)
        retry = self.create_attempt(target, "explicit-repractice")
        self.assertNotEqual(retry["attempt"]["attempt_id"], aid)
        self.assertEqual(retry["quiz"], result["quiz"])
        self.assertEqual(self.get(path), result)
        self.assertEqual(self.db.calls(target["generation_run"]["run_id"]), [])

    def test_actual_http_concurrent_attempt_answer_submit_and_exam_completion(self):
        target = self.ready("exam")
        quiz_id = target["quiz"]["quiz_id"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = list(pool.map(lambda i: self.create_attempt(target, f"attempt-tab-{i}"), range(2)))
        self.assertEqual(attempts[0], attempts[1])
        saved = attempts[0]
        path = f"/api/attempts/{saved['attempt']['attempt_id']}"
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda i: self.client.post(f"{path}/answers", json=self.answer_data(
                saved, f"answer-tab-{i}")), range(2)))
        self.assertEqual(sorted(r.status_code for r in responses), [200, 409])
        saved = self.get(path)
        for index in (1, 2):
            saved = self.post(f"{path}/next", self.command(f"next-{index}", saved))
            saved = self.post(f"{path}/answers", self.answer_data(saved, f"answer-{index}"))
        payload = self.command("concurrent-submit", saved)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.post(f"{path}/submit", payload), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0]["attempt"]["result"]["total_score"], 2700)
        self.assertTrue(self.get(f"/api/exams/{self.eid}")["completed"])
        self.assertEqual(results[0]["course"]["progress"], 0)
        self.assertEqual(results[0]["course"]["version"], 2)
        self.assertNotIn("passed", results[0]["course"]["units"][0]["exams"][0])
        self.assertEqual(len(self.get(f"/api/quizzes/{quiz_id}/attempts")["attempts"]), 1)

    def test_http_rejects_elapsed_types_bounds_and_selection_without_writes(self):
        saved = self.create_attempt(self.ready())
        path = f"/api/attempts/{saved['attempt']['attempt_id']}"
        valid = self.answer_data(saved, "correctable")
        for elapsed in (-1, MAX_ELAPSED_MS + 1, .5, 10000.0, True, "1000"):
            with self.subTest(elapsed=elapsed):
                response = self.client.post(f"{path}/answers", json={**valid, "elapsed_ms": elapsed})
                self.assertEqual(response.status_code, 422)
        for patch in ({"option_ids": []}, {"option_ids": ["a", "a"]}, {"option_ids": ["unknown"]},
                      {"option_ids": ["a", "b"]}, {"skipped": True}, {"question_id": "q2"}):
            with self.subTest(patch=patch):
                self.assertIn(self.client.post(f"{path}/answers", json={**valid, **patch}).status_code, (409, 422))
        self.assertEqual(self.get(path), saved)
        self.assertEqual(self.client.post(f"{path}/submit", json=self.command("too-early", saved)).status_code, 409)
        self.assertEqual(self.post(f"{path}/answers", valid)["attempt"]["answers"][0]["points"], 800)

    def test_manual_complete_emits_practice_version_even_without_a_quiz(self):
        self.lesson()
        target = self.get(f"/api/sessions/{self.sid}/practice")
        lesson = self.get(f"/api/sessions/{self.sid}")
        key = f"practice:{self.sid}"
        with connect(f"ws://127.0.0.1:{self.port}/api/events", proxy=None) as ws:
            self.subscribe(ws, f"quiz_target:{key}")
            self.post(f"/api/sessions/{self.sid}/complete", self.command("manual-complete",
                expected_version=lesson["progress"]["version"], script_id=lesson["script"]["script_id"]))
            after = self.get(f"/api/sessions/{self.sid}/practice")
            self.assertTrue(after["completed"])
            self.assertIsNone(after["quiz"])
            self.assertEqual(after["version"], target["version"] + 1)
            self.events(ws, {("quiz_target", key): after["version"]})

    def test_restart_preserves_feedback_results_and_interrupts_pending_without_model_calls(self):
        practice = self.ready()
        saved = self.create_attempt(practice)
        path = f"/api/attempts/{saved['attempt']['attempt_id']}"
        saved = self.post(f"{path}/answers", self.answer_data(saved, "restart-answer"))
        exam = self.ready("exam")
        answered = self.all_answered(self.create_attempt(exam, "exam-attempt"))
        exam_path = f"/api/attempts/{answered['attempt']['attempt_id']}"
        result = self.post(f"{exam_path}/submit", self.command("exam-result", answered))
        # Course derivation is current, even for the older in-progress attempt.
        saved = self.get(path)
        type(self).stop_server()
        # A queued direct storage input is found on startup, not sent to a provider.
        run = self.db.create_run(f"{self.prefix}-pending-course", "理解暂停", "stored-model")
        self.db.transition(run["run_id"], {"queued"}, status="generating")
        ready = self.db.finish_course(run["run_id"], CourseDraft.model_validate(course_data()))
        pending_eid = self.db.get_course(ready["course_id"])["units"][0]["exams"][0]["exam_id"]
        pending = self.db.prepare_quiz("exam", pending_eid, f"{self.prefix}-pending-quiz", "stored-model", True)
        pending_run = pending["generation_run"]
        try:
            type(self).start_server()
            self.assertEqual(self.get(path), saved)
            self.assertEqual(self.get(exam_path), result)
            self.assertEqual(self.get(f"/api/sessions/{self.sid}/practice")["latest_attempt"], saved["attempt"])
            self.assertEqual(self.db.calls(practice["generation_run"]["run_id"]), [])
            self.assertEqual(self.db.calls(exam["generation_run"]["run_id"]), [])
            interrupted = self.get(f"/api/exams/{pending_eid}")
            self.assertEqual(interrupted["generation_run"]["status"], "interrupted")
            self.assertGreater(interrupted["version"], pending["version"])
            self.assertEqual(self.db.calls(pending_run["run_id"]), [])
            response = self.client.post(f"/api/runs/{pending_run['run_id']}/retry", json=self.command(
                "no-config-retry", expected_version=interrupted["generation_run"]["version"]))
            self.assertEqual(response.status_code, 503)
            self.assertEqual(self.get(f"/api/exams/{pending_eid}"), interrupted)
        finally:
            # Class teardown remains responsible for the restarted test-owned process.
            self.assertIsNone(type(self).process.poll())
