"""Real Uvicorn/HTTP and temporary disk SQLite, with search always disabled.

Explicit domain inputs only prove persistence/transport rules. They are not
evidence that a model searched, read pages, or produced a research report.
"""

import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import httpx

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from hyperknow.research_domain import ResearchReport
from hyperknow.storage import Database
from test_research import page_input, read_step, report_input, search_step


class ResearchLiveServerTests(unittest.TestCase):
    model_configuration = ""
    configuration_error = "model_not_configured"

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="hyperknow-research-http-")
        root = Path(cls.directory.name)
        cls.db = Database(root / "hyperknow.sqlite3")
        cls.initial = {}
        for status in ("ready", "failed", "generating"):
            run = cls.db.create_research(f"http-domain-input-{status}", "理解 Python 协程",
                                         "只验证保存与读取", "stored-model",
                                         configured=True, search_configured=True)
            run = cls.db.transition(run["run_id"], {"queued"}, status="generating")
            cls.db.research_step(run["run_id"], search_step())
            source = cls.db.research_step(run["run_id"], read_step(), page_input())
            if status == "ready":
                cls.db.finish_research(run["run_id"], ResearchReport.model_validate(report_input(source["source_id"])))
            elif status == "failed":
                cls.db.transition(run["run_id"], {"generating"}, status="failed",
                                  error={"code": "research_failed", "message": "Rule input", "retryable": True})
            cls.initial[status] = cls.db.get_run(run["run_id"])
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        cls.client = httpx.Client(base_url=f"http://127.0.0.1:{cls.port}", trust_env=False, timeout=5)
        cls.process = None
        cls.server_log = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
        repository = Path(__file__).resolve().parents[1]
        env = {**os.environ, "OPENAI_API_KEY": cls.model_configuration, "TAVILY_API_KEY": "",
               "HK_DATA_DIR": str(root), "PYTHON_DOTENV_DISABLED": "1",
               "PYTHONPATH": str(repository / "src")}
        try:
            cls.process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "hyperknow.main:app", "--host", "127.0.0.1",
                 "--port", str(cls.port), "--log-level", "warning"],
                # Never load the repository .env or the author's database.
                cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=cls.server_log)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if cls.process.poll() is not None:
                    cls.server_log.seek(0)
                    raise RuntimeError(f"real Uvicorn exited before startup:\n{cls.server_log.read()}")
                try:
                    if cls.client.get("/api/health").status_code == 200:
                        return
                except httpx.TransportError:
                    pass
                time.sleep(.05)
            raise RuntimeError("real Uvicorn startup timed out")
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        if cls.process is not None:
            cls.process.terminate()
            try:
                cls.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                cls.process.kill()
                cls.process.wait(timeout=5)
        cls.server_log.close()
        cls.directory.cleanup()

    def snapshot(self):
        with self.db.transaction() as conn:
            receipts = [tuple(row) for row in conn.execute("SELECT * FROM command_receipts ORDER BY id")]
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM model_calls").fetchone()[0], 0)
        return self.db.list_records("runs"), receipts

    def test_health_configuration_is_not_connectivity_evidence(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["database"], "ok")
        self.assertEqual(response.json()["model"]["configured"], bool(self.model_configuration))
        self.assertFalse(response.json()["model"]["verified"])

    def test_missing_configuration_returns_503_without_run_or_command_receipt(self):
        before = self.snapshot()
        for context in ({}, {"context": "会基础 Python"}):
            data = {"client_command_id": "missing-research-configuration", "goal": "理解 Python 协程", **context}
            for _ in range(2):
                response = self.client.post("/api/research-runs", json=data)
                self.assertEqual(response.status_code, 503, response.text)
                self.assertEqual(response.json()["error"]["code"], self.configuration_error)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.client.get("/api/courses").json(), {"courses": []})

    def test_course_requires_search_configuration_before_paid_clarification(self):
        before = self.snapshot()
        response = self.client.post("/api/course-runs", json={
            "client_command_id": "missing-course-search-config", "goal": "理解Python协程"})
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json()["error"]["code"], self.configuration_error)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_input_is_422_before_configuration_and_without_writes(self):
        before = self.snapshot()
        valid = {"client_command_id": "invalid-research-input", "goal": "理解 Python 协程"}
        cases = [{}, {"goal": valid["goal"]}, {"client_command_id": valid["client_command_id"]}]
        cases += [{**valid, **patch} for patch in (
            {"client_command_id": "short"}, {"client_command_id": " " * 8},
            {"client_command_id": "x" * 121}, {"goal": " "}, {"goal": "x"},
            {"goal": "x" * 4001}, {"goal": None}, {"goal": ["not text"]},
            {"context": None}, {"context": {}}, {"context": "x" * 6001}, {"unknown": True},
        )]
        for index, data in enumerate(cases):
            with self.subTest(case=index):
                response = self.client.post("/api/research-runs", json=data)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json()["error"]["code"], "invalid_request")
        malformed = self.client.post("/api/research-runs", content='{"goal":',
                                     headers={"Content-Type": "application/json"})
        self.assertEqual(malformed.status_code, 422)
        self.assertEqual(self.snapshot(), before)

    def test_get_preserves_report_sources_and_interrupted_steps_without_new_calls(self):
        before = self.snapshot()
        for _ in range(2):
            response = self.client.get("/api/runs")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"runs": before[0]})
            for status, original in self.initial.items():
                response = self.client.get(f"/api/runs/{original['run_id']}")
                self.assertEqual(response.status_code, 200)
                current = response.json()
                self.assertEqual(current["kind"], "research")
                self.assertEqual(current["research"], original["research"])
                self.assertEqual(current["input"], original["input"])
                if status == "generating":
                    self.assertEqual((current["status"], current["version"]),
                                     ("interrupted", original["version"] + 1))
                    self.assertEqual(current["error"]["code"], "interrupted")
                else:
                    self.assertEqual(current, original)
        self.assertEqual(self.client.get("/api/runs/missing").status_code, 404)
        self.assertEqual(self.snapshot(), before)

    def test_retry_missing_configuration_and_invalid_version_have_no_side_effects(self):
        before = self.snapshot()
        for run in before[0]:
            if run["status"] not in {"failed", "interrupted"}:
                continue
            data = {"client_command_id": f"missing-retry-{run['run_id']}", "expected_version": run["version"]}
            path = f"/api/runs/{run['run_id']}/retry"
            response = self.client.post(path, json=data)
            self.assertEqual(response.status_code, 503, response.text)
            self.assertEqual(response.json()["error"]["code"], self.configuration_error)
            invalid = self.client.post(path, json={**data, "expected_version": 0})
            self.assertEqual(invalid.status_code, 422)
            stale = self.client.post(path, json={**data, "expected_version": run["version"] - 1})
            self.assertEqual(stale.status_code, 409)
            self.assertEqual(stale.json()["error"]["code"], "version_conflict")
        self.assertEqual(self.snapshot(), before)


class ResearchMissingSearchLiveServerTests(ResearchLiveServerTests):
    # A noncredential configuration marker, never sent to any endpoint: absent
    # Tavily configuration must reject the request before a run is scheduled.
    model_configuration = "configuration-only-not-a-real-credential"
    configuration_error = "search_not_configured"
