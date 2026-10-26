"""Real isolated HTTP/SQLite and deterministic recovery, never a successful fake provider."""

import json
from copy import deepcopy
from hashlib import sha256
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from uuid import uuid4

import httpx

from hyperknow.assistance_generation import build_skill_snapshots
from hyperknow.eval_cases import case_hash, load_case, read_json, write_json
from hyperknow.evaluation import (check_backend, grade_result, isolated_database, local_origin,
                                 evaluate_rules, readonly, recover_conversation, recover_turn,
                                 run_business, skill_trace_matches)
from hyperknow.storage import Database, storage_identity


ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "evals/concept-explanation/case.json"


class EvalOfflineTests(unittest.TestCase):
    def trace_data(self):
        # Handwritten rule inputs; these do not claim a model or tool was executed.
        body = "An optional trusted example for trace validation."
        skill = {"name": "optional-example", "version": "1", "description": "Trace test input",
                 "body": body, "sha256": sha256(body.encode()).hexdigest()}
        return ({"input": {"skill_snapshots": {skill["name"]: skill}}, "steps": []},
                {"skill_uses": []}, skill)

    def test_optional_skill_trace_accepts_empty_or_unused_catalog(self):
        run, turn, _ = self.trace_data()
        self.assertTrue(skill_trace_matches(run, turn, []))
        run["input"]["skill_snapshots"] = {}
        self.assertTrue(skill_trace_matches(run, turn, []))
        response = {"text": "纯规则校验输入", "questions": [], "plan": [], "current_step": 0,
                    "waiting_for": "none", "suggestions": []}
        run["status"] = "ready"
        turn.update(status="ready", response=response, artifacts=[])
        state = {"evidence": {"run": run, "turn": turn, "calls": []},
                 "trajectory_validation": {"valid": True, "complete": True}}
        rules = evaluate_rules(state)
        self.assertEqual({rule["id"] for rule in rules},
                         {"delivery", "skill_trace", "no_artifacts", "no_questions", "trajectory"})
        self.assertTrue(all(rule["verdict"] == "pass" for rule in rules))

    def test_optional_skill_trace_requires_matching_load_request_step_and_snapshot(self):
        run, turn, skill = self.trace_data()
        metadata = {key: skill[key] for key in ("name", "version", "sha256")}
        turn["skill_uses"] = [metadata]
        run["steps"] = [{"tool": "get_skills", "status": "ready", **metadata}]
        calls = [{"response": {"tool_calls": [{"name": "get_skills", "arguments": {"name": skill["name"]}}]}}]
        self.assertTrue(skill_trace_matches(run, turn, calls))
        self.assertFalse(skill_trace_matches(run, turn, []))
        for change in (
                lambda r, t, c: t.update(skill_uses=[]),
                lambda r, t, c: t["skill_uses"].append(deepcopy(metadata)),
                lambda r, t, c: r.update(steps=[]),
                lambda r, t, c: r["steps"][0].update(status="failed"),
                lambda r, t, c: r["input"]["skill_snapshots"].clear(),
                lambda r, t, c: r["input"]["skill_snapshots"][skill["name"]].update(body="tampered"),
                lambda r, t, c: t["skill_uses"][0].update(version="another-version"),
                lambda r, t, c: c[0]["response"]["tool_calls"][0]["arguments"].update(name="unavailable")):
            with self.subTest(change=change):
                changed_run, changed_turn, changed_calls = deepcopy((run, turn, calls))
                change(changed_run, changed_turn, changed_calls)
                self.assertFalse(skill_trace_matches(changed_run, changed_turn, changed_calls))

    def test_rejects_nonlocal_origin_and_author_default_database(self):
        for url in ("https://example.com", "http://127.0.0.1/path", "http://u:p@localhost", "http://localhost?q=1"):
            with self.assertRaises(ValueError):
                local_origin(url)
        self.assertEqual(local_origin("http://127.0.0.1:8039/"), "http://127.0.0.1:8039")
        with self.assertRaises(ValueError):
            isolated_database(ROOT / "data")
        with self.assertRaises(ValueError):
            run_business(load_case(CASE), base_url="http://127.0.0.1:1", data_dir=ROOT / "data",
                         output=ROOT / "data/evals/not-created", execute=False)

    def test_grading_resume_validates_saved_response_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            case = load_case(CASE)
            response = {"text": "纯解析测试材料，不声称真实生成", "questions": [], "plan": [], "current_step": 0,
                        "waiting_for": "none", "suggestions": []}
            results = [{"rubric_id": r["id"], "verdict": "pass", "reason": "纯数据校验", "evidence_refs": ["final_response"]}
                       for r in case["rubric"]]
            state = {"schema_version": 1, "case": case, "case_hash": case_hash(case), "final_response": response,
                     "evidence": {"turn": {"response": response}},
                     "grades": [{"attempt_id": "grade-known", "status": "in_flight", "raw_response": {
                         "content": json.dumps({"results": results}), "stop_reason": "stop", "tool_calls": [], "error_message": None}}]}
            write_json(output / "result.json", state)
            recovered = grade_result(output, settings=None, execute=True)
            self.assertEqual(recovered["grades"][0]["status"], "completed")
            self.assertEqual(len(recovered["grades"]), 1)
            self.assertEqual(grade_result(output, settings=None, execute=True), recovered)

    def test_unknown_grading_response_is_not_automatically_reissued(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            case = load_case(CASE)
            state = {"case": case, "case_hash": case_hash(case), "final_response": None,
                     "grades": [{"attempt_id": "grade-unknown", "status": "in_flight", "raw_response": None}]}
            write_json(output / "result.json", state)
            recovered = grade_result(output, settings=None, execute=True)
            self.assertEqual(recovered["grades"][0]["status"], "unknown")
            self.assertTrue(all(r["verdict"] == "undetermined" for r in recovered["grades"][0]["results"]))
            self.assertEqual(len(recovered["grades"]), 1)

    def test_cli_prepare_and_paid_gate_use_no_model(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory) / "cases"
            prepared = subprocess.run([sys.executable, "scripts/run_eval.py", "prepare", "--library", str(library)],
                                      cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(prepared.returncode, 0, prepared.stderr)
            self.assertEqual(len(list(library.glob("*.json"))), 1)
            blocked = subprocess.run([sys.executable, "scripts/run_eval.py", "grade", "--output", directory],
                                     cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("--execute", blocked.stderr)
            self.assertFalse((Path(directory) / "result.json").exists())

    def test_cli_show_reads_utf8_without_backend_or_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            write_json(Path(directory) / "result.json", {"execution_id": "只读报告", "stage": "prepared",
                       "rules": [], "grades": [], "error": {"message": "证据不足"}})
            shown = subprocess.run([sys.executable, "scripts/run_eval.py", "show", "--output", directory],
                                   cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(shown.returncode, 0, shown.stderr)
            self.assertEqual(json.loads(shown.stdout)["error"]["message"], "证据不足")


class EvalLiveHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="hyperknow-evaluation-http-")
        cls.data = Path(cls.directory.name) / "backend"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cls.url = f"http://127.0.0.1:{port}"
        env = {**os.environ, "HK_DATA_DIR": str(cls.data), "OPENAI_API_KEY": "", "TAVILY_API_KEY": ""}
        cls.process = subprocess.Popen([sys.executable, "-m", "uvicorn", "hyperknow.main:app", "--host", "127.0.0.1",
                                       "--port", str(port), "--log-level", "warning"], cwd=ROOT, env=env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.client = httpx.Client(base_url=cls.url, trust_env=False, timeout=5)
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if cls.process.poll() is not None:
                    raise RuntimeError("local evaluation backend exited")
                try:
                    if cls.client.get("/api/health").status_code == 200:
                        cls.database = cls.data / "hyperknow.sqlite3"
                        cls.db = Database(cls.database)
                        return
                except httpx.TransportError:
                    pass
                time.sleep(0.05)
            raise RuntimeError("local evaluation backend did not start")
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.process.terminate()
        try:
            cls.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait(timeout=5)
        cls.directory.cleanup()

    def state(self):
        case = load_case(CASE)
        return {"schema_version": 1, "execution_id": f"eval-test-{uuid4().hex}", "case": case, "case_hash": case_hash(case),
                "target": {"base_url": self.url, "database": str(self.database), "storage_id": storage_identity(self.database)},
                "commands": {"create": {"client_command_id": f"eval-create-{uuid4().hex}"}, "turn": None},
                "conversation_id": None, "run_id": None, "evidence": {}, "grades": [], "rules": [], "stage": "prepared"}

    def test_backend_identity_checked_before_any_write(self):
        health = check_backend(self.client, self.database, require_model=False)
        self.assertEqual(health["storage_id"], storage_identity(self.database))
        with tempfile.TemporaryDirectory() as directory:
            other = Path(directory) / "hyperknow.sqlite3"
            Database(other)
            with self.assertRaisesRegex(ValueError, "storage identity"):
                check_backend(self.client, other, require_model=False)
            with readonly(other) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM assistance_conversations").fetchone()[0], 0)
        with readonly(self.database) as conn:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM command_receipts")

    def test_missing_model_blocks_without_creating_billable_run(self):
        with tempfile.TemporaryDirectory() as directory:
            with readonly(self.database) as conn:
                before = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            with self.assertRaisesRegex(ValueError, "no configured"):
                run_business(load_case(CASE), base_url=self.url, data_dir=self.data, output=Path(directory), execute=True)
            with readonly(self.database) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0], before)
            state = read_json(Path(directory) / "result.json")
            self.assertEqual(state["stage"], "blocked_or_unknown")
            self.assertIsNone(state["run_id"])

    def test_create_receipt_recovers_a_lost_response_without_new_conversation(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            save = lambda: write_json(path, state)
            save()
            identity = recover_conversation(self.client, self.database, state, save)
            with readonly(self.database) as conn:
                before = conn.execute("SELECT COUNT(*) FROM assistance_conversations").fetchone()[0]
            state["conversation_id"] = None  # Only the receipt survived an interrupted client.
            self.assertEqual(recover_conversation(self.client, self.database, state, save), identity)
            with readonly(self.database) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM assistance_conversations").fetchone()[0], before)

    def test_missing_receipt_after_uncertain_submission_never_posts_again(self):
        state = self.state()
        identity = recover_conversation(self.client, self.database, state, lambda: None)
        state["commands"]["turn"] = {"client_command_id": f"eval-turn-{uuid4().hex}", "expected_version": 1,
            "text": state["case"]["input"], "action": "message", "artifact_id": None}
        state["before_turn_ids"] = []
        state["turn_request_started"] = True
        with self.assertRaisesRegex(ValueError, "refusing to POST again"):
            recover_turn(self.client, self.database, state, lambda: None)
        self.assertEqual(self.db.get_assistance_conversation(identity)["turns"], [])
        state["run_id"] = "known-run-missing-after-rollback"
        state["turn_request_started"] = False
        with self.assertRaisesRegex(ValueError, "refusing to POST again"):
            recover_turn(self.client, self.database, state, lambda: None)

    def test_lost_run_response_does_not_adopt_retried_turn(self):
        state = self.state()
        identity = recover_conversation(self.client, self.database, state, lambda: None)
        command = {"client_command_id": f"eval-turn-{uuid4().hex}", "expected_version": 1,
            "text": state["case"]["input"], "action": "message", "artifact_id": None}
        state["commands"]["turn"], state["before_turn_ids"] = command, []
        queued = self.db.assistance_turn(identity, command, "unconfigured-test", True, build_skill_snapshots())
        original = queued["turns"][-1]["run_id"]
        failed = self.db.transition(original, {"queued"}, status="failed")
        retry = self.db.retry_run(f"eval-retry-{uuid4().hex}", original, failed["version"], configured=True)
        self.assertEqual(retry["parent_run_id"], original)
        with self.assertRaisesRegex(ValueError, "retry or different execution"):
            recover_turn(self.client, self.database, state, lambda: None)
        self.assertIsNone(state["run_id"])

    def test_resume_real_worker_failure_retains_original_run_and_evidence(self):
        state = self.state()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            path = output / "result.json"
            save = lambda: write_json(path, state)
            save()
            identity = recover_conversation(self.client, self.database, state, save)
            command = {"client_command_id": f"eval-turn-{uuid4().hex}", "expected_version": 1,
                       "text": state["case"]["input"], "action": "message", "artifact_id": None}
            state["commands"]["turn"] = command
            state["before_turn_ids"] = []
            save()
            # This creates a real queued record. HTTP replays its receipt, then the actual
            # worker fails with its explicitly empty credential. No successful content is injected.
            queued = self.db.assistance_turn(identity, command, "unconfigured-evaluation-test", True, build_skill_snapshots())
            original = queued["turns"][-1]["run_id"]
            replay = self.client.post(f"/api/assistance/conversations/{identity}/turns", json=command)
            self.assertEqual(replay.status_code, 202)
            recovered = run_business(state["case"], base_url=self.url, data_dir=self.data,
                                     output=output, execute=True, resume=True, wait_seconds=15)
            self.assertEqual(recovered["run_id"], original)
            self.assertEqual(recovered["evidence"]["run"]["status"], "failed")
            self.assertIsNone(recovered["final_response"])
            self.assertFalse(recovered["trajectory_validation"]["valid"])
            self.assertEqual(len(self.db.get_assistance_conversation(identity)["turns"]), 1)
            again = run_business(state["case"], base_url=self.url, data_dir=self.data, output=output, execute=True, resume=True)
            self.assertEqual(again["run_id"], original)
            self.assertEqual(again["evidence"], recovered["evidence"])


if __name__ == "__main__":
    unittest.main()
