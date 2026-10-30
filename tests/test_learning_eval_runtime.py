"""Real product HTTP, disk SQLite and pure boundary checks, without provider fees.

The low-level send tests exercise the write-ahead transport independently of the
execution gate, only creating empty conversations (a non-model product command).
Successful model generation is deliberately not represented by seeded content.
"""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest

import httpx
import uvicorn

from hyperknow.config import Settings
from hyperknow.domain import Clarification, resolve_answers
from hyperknow.main import create_app
from hyperknow.storage import Database, storage_identity
from hyperknow_eval.runtime import Runtime, RuntimeFailure, local_origin, readonly
from hyperknow_eval.scenarios import clarification_answers, execute_scenario, validate_public_case
from hyperknow_eval.schema import public_case
from hyperknow_eval.storage import (digest, evidence_hash, load_trial, new_trial, save_trial,
                                    validate_record)


def case_value():
    return {
        "schema_version": 3, "id": "runtime-local", "revision": 1, "title": "真实执行边界",
        "domain": "programming", "workflow": "assistance",
        "learner": {"background": "PRIVATE_BACKGROUND", "goal": "PRIVATE_GOAL", "misconceptions": ["PRIVATE_GAP"]},
        "task": {"opening": "请解释生成器与迭代器", "follow_ups": ["为什么第一次访问才计算？"], "max_turns": 2},
        "budget": {"timeout_seconds": 10, "max_actions": 4, "max_observed_calls": 2},
        "rubric": [{"id": "knowledge", "dimension": "correctness", "description": "PRIVATE_RUBRIC"},
                   {"id": "teaching", "dimension": "pedagogy", "description": "PRIVATE_TEACHING"},
                   {"id": "followup", "dimension": "adaptation", "description": "PRIVATE_ADAPTATION"}],
        "reference": {"facts": ["PRIVATE_REFERENCE"], "sources": [{"title": "Python docs",
                      "url": "https://docs.python.org/3/glossary.html", "locator": "generator"}],
                      "review_status": "author_reviewed", "reviewer": "test author"},
        "provenance": "Local execution-boundary test, not a teaching-quality benchmark",
    }


@contextmanager
def backend(directory: Path):
    """An actual TCP listener serving the unmodified product with explicit empty keys."""
    settings = Settings(data_dir=directory, api_key="", tavily_api_key="")
    application = create_app(settings)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(32)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(application, log_level="critical", access_log=False, lifespan="on"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(base_url=url, timeout=2, trust_env=False) as client:
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError("actual product HTTP service did not start")
                time.sleep(0.01)
            health = client.get("/api/health")
            health.raise_for_status()
            yield url, client
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        if thread.is_alive():
            raise RuntimeError("actual product HTTP service did not stop")


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="learning-eval-runtime-")
        self.root = Path(self.temporary.name)
        self.output = self.root / "trial"
        self.record = new_trial(self.output, case_value())

    def tearDown(self):
        self.temporary.cleanup()

    def runtime(self, url="http://127.0.0.1:1", directory=None, checkpoint=None):
        return Runtime(url, directory or self.root / "backend", self.record,
                       checkpoint or (lambda: save_trial(self.output, self.record)))

    def assert_failure(self, expected, callback):
        with self.assertRaises(RuntimeFailure) as caught:
            callback()
        self.assertEqual(caught.exception.code, expected)

    def test_loopback_origin_is_strict_and_localhost_is_pinned(self):
        for url in ["https://example.com", "http://127.0.0.1.example.com", "http://0.0.0.0:9000",
                    "http://127.0.0.1:9000/api", "http://u:p@127.0.0.1:9000",
                    "http://127.0.0.1:9000?token=hidden", "http://127.0.0.1:9000/#hidden",
                    "file:///data", "http://127.0.0.1:99999", "http://127.0.0.1:0",
                    "http://127.0.0.1:9000\\@example.com", "http://[::1%lo]:9000"]:
            with self.subTest(url=url):
                self.assert_failure("non_loopback_origin", lambda: local_origin(url))
        self.assertEqual(local_origin("http://127.0.0.1:9000/"), "http://127.0.0.1:9000")
        self.assertEqual(local_origin("http://[::1]:9000"), "http://[::1]:9000")
        self.assertIn(local_origin("http://localhost:9000"), {"http://127.0.0.1:9000", "http://[::1]:9000"})

    def test_default_author_database_and_missing_database_are_rejected_without_creation(self):
        repository = Path(__file__).resolve().parents[1]
        with self.runtime(directory=repository / "data") as runtime:
            self.assert_failure("protected_database", runtime.preflight)
        absent = self.root / "absent"
        with self.runtime(directory=absent) as runtime:
            self.assert_failure("database_missing", runtime.preflight)
        self.assertFalse(absent.exists())
        self.assertEqual(self.record["actions"], [])

    def test_current_parent_data_directory_is_protected_without_reading_dotenv(self):
        directory = self.root / "parent-data"
        Database(directory / "hyperknow.sqlite3")
        source = """
import sys
from pathlib import Path
from hyperknow_eval.runtime import Runtime, RuntimeFailure
from hyperknow_eval.storage import load_trial, save_trial
out, directory = map(Path, sys.argv[1:])
record = load_trial(out)
try:
    Runtime('http://127.0.0.1:1', directory, record, lambda: save_trial(out, record)).preflight()
except RuntimeFailure as exc:
    print(exc.code)
"""
        completed = subprocess.run([sys.executable, "-c", source, str(self.output), str(directory)],
                                   env={**os.environ, "HK_DATA_DIR": str(directory)}, capture_output=True,
                                   text=True, check=True, timeout=10)
        self.assertEqual(completed.stdout.strip(), "protected_database")
        self.assertEqual(load_trial(self.output)["actions"], [])

    def test_occupied_empty_conversation_is_not_an_empty_trial_database(self):
        directory = self.root / "occupied"
        database = Database(directory / "hyperknow.sqlite3")
        database.create_assistance_conversation("real-empty-conversation")
        with self.runtime(directory=directory) as runtime:
            self.assert_failure("database_not_empty", runtime.preflight)
        self.assertIn("assistance_conversations", self.record["error"]["tables"])

    def test_real_http_health_binding_mismatch_blocks_before_any_write(self):
        directory = self.root / "backend"
        other = self.root / "other-backend"
        Database(other / "hyperknow.sqlite3")
        with backend(directory) as (url, client), self.runtime(url, other) as runtime:
            self.assert_failure("storage_identity_mismatch", runtime.preflight)
            self.assertEqual(client.get("/api/assistance/conversations").json(), {"conversations": []})
        self.assertEqual(self.record["status"], "blocked")
        self.assertEqual(self.record["actions"], [])

    def test_actual_unconfigured_product_preflight_blocks_execution_and_preserves_real_identity(self):
        directory = self.root / "backend"
        with backend(directory) as (url, client), self.runtime(url, directory) as runtime:
            self.assert_failure("model_not_configured", lambda: execute_scenario(runtime, public_case(case_value())))
            self.assertEqual(self.record["environment"]["storage_id"], storage_identity(directory / "hyperknow.sqlite3"))
            self.assertEqual(self.record["subject"]["model"], client.get("/api/health").json()["model"]["name"])
            self.assertEqual(self.record["subject"]["identity"], "unknown")
            self.assertEqual(self.record["subject"]["backend_build"], "unknown")
            self.assertFalse(self.record["subject"]["model_verified"])
            self.assert_failure("preflight_required", lambda: runtime.post("/api/assistance/conversations", {}))
            self.assertEqual(client.get("/api/runs").json(), {"runs": []})
            self.assertEqual(client.get("/api/assistance/conversations").json(), {"conversations": []})
        saved = load_trial(self.output)
        self.assertEqual(saved["actions"], [])
        self.assertEqual(saved["environment"]["remote_cost_status"], "unknown")
        self.assertIsNone(next(check for check in saved["checks"] if check["id"] == "remote_cost_finished")["passed"])

    def test_single_send_transport_checkpoints_exact_identity_before_the_real_product_write(self):
        directory = self.root / "backend"
        observations = []
        with backend(directory) as (url, client):
            def checkpoint():
                save_trial(self.output, self.record)
                saved = load_trial(self.output)
                if saved["actions"] and saved["actions"][-1]["status"] == "in_flight":
                    observations.append((saved["actions"][-1], client.get("/api/assistance/conversations").json()))

            body = {"client_command_id": "write-ahead-real-conversation"}
            with self.runtime(url, directory, checkpoint) as runtime:
                result = runtime._send("POST", "/api/assistance/conversations", body)
                self.assertEqual(len(observations), 1)
                action, before = observations[0]
                self.assertEqual(before, {"conversations": []})
                self.assertEqual(action["command_id"], body["client_command_id"])
                self.assertEqual(action["request"]["body"], body)
                self.assertEqual(json.loads(action["request"]["body_text"]), body)
                self.assertEqual(action["request"]["method"], "POST")
                self.assertEqual(action["request"]["url"], url + "/api/assistance/conversations")
                self.assertEqual(self.record["actions"][-1]["status"], "completed")
                self.assertEqual(client.get(f"/api/assistance/conversations/{result['conversation_id']}").json(), result)
                self.assert_failure("command_replay_forbidden", lambda: runtime._send("POST", "/api/assistance/conversations", body))
                self.assertEqual(len(client.get("/api/assistance/conversations").json()["conversations"]), 1)
            with readonly((directory / "hyperknow.sqlite3").resolve()) as connection:
                receipts = connection.execute("SELECT id FROM command_receipts").fetchall()
            self.assertEqual([row["id"] for row in receipts], [body["client_command_id"]])

    def test_checkpoint_disk_failure_sends_nothing_and_blocks_later_unknown_submission(self):
        directory = self.root / "backend"
        with backend(directory) as (url, client):
            def unwritable_checkpoint():
                # Real filesystem failure: an existing directory cannot become a trial file.
                with self.output.open("w", encoding="utf-8"):
                    pass

            runtime = self.runtime(url, directory, unwritable_checkpoint)
            with self.assertRaises(OSError):
                runtime._send("POST", "/api/assistance/conversations", {})
            self.assertEqual(client.get("/api/assistance/conversations").json(), {"conversations": []})
            self.assertEqual(self.record["actions"][0]["status"], "in_flight")
            # A new runtime reconstructs the conservative no-new-writes decision.
            with self.runtime(url, directory) as resumed:
                self.assert_failure("writes_stopped", lambda: resumed._send("POST", "/api/assistance/conversations", {}))
            self.assertEqual(self.record["actions"][0]["status"], "in_flight")

    def test_real_http_redirect_is_not_followed_and_no_new_identity_replays_unknown_command(self):
        directory = self.root / "backend"
        with backend(directory) as (url, client), self.runtime(url, directory) as runtime:
            self.assert_failure("transport_failed", lambda: runtime._send("POST", "/api/assistance/conversations/", {}))
            self.assertEqual(self.record["actions"][0]["status"], "submission_unknown")
            self.assert_failure("writes_stopped", lambda: runtime._send("POST", "/api/assistance/conversations", {}))
            self.assertEqual(client.get("/api/assistance/conversations").json(), {"conversations": []})
            self.assertEqual(len(self.record["actions"]), 1)

    def test_write_budget_stops_subsequent_non_model_commands_but_reads_do_not_accumulate_actions(self):
        directory = self.root / "backend"
        with backend(directory) as (url, client), self.runtime(url, directory) as runtime:
            runtime.set_budget({"timeout_seconds": 10, "max_actions": 1, "max_observed_calls": 2})
            runtime._send("POST", "/api/assistance/conversations", {})
            for _ in range(10):
                runtime.get("/api/health")
            self.assertEqual(len(self.record["actions"]), 1)
            self.assert_failure("max_actions_exceeded", lambda: runtime._send("POST", "/api/assistance/conversations", {}))
            self.assertEqual(len(client.get("/api/assistance/conversations").json()["conversations"]), 1)

    def test_readonly_collection_saves_hashed_immutable_content_and_deduplicates_polls(self):
        directory = self.root / "backend"
        with backend(directory) as (url, client), self.runtime(url, directory) as runtime:
            self.assert_failure("model_not_configured", runtime.preflight)
            conversation = client.post("/api/assistance/conversations", json={"client_command_id": "collect-real-conversation"}).json()
            pending = {"role": "student", "status": "not_requested"}
            self.record["model_requests"].append(pending)
            runtime.collect()
            evidence = next(item for item in self.record["evidence"] if item["kind"] == "conversation")
            self.assertEqual(evidence["content"]["conversation_id"], conversation["conversation_id"])
            self.assertEqual(evidence["source"]["transport"], "sqlite")
            self.assertEqual(evidence["sha256"], digest(evidence["content"]))
            self.assertEqual(len(evidence["sha256"]), hashlib.sha256().digest_size * 2)
            count = len(self.record["evidence"])
            fingerprint = evidence_hash(load_trial(self.output))
            runtime.collect()
            self.assertEqual(len(self.record["evidence"]), count)
            self.assertEqual(evidence_hash(load_trial(self.output)), fingerprint)
            with readonly((directory / "hyperknow.sqlite3").resolve()) as connection:
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute("DELETE FROM assistance_conversations")
            changed = deepcopy(self.record)
            changed["evidence"][0]["content"]["status"] = "tampered"
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                validate_record(changed)
            self.assertEqual(self.record["model_requests"], [pending])
            self.assertEqual(client.get("/api/runs").json(), {"runs": []})

    def test_private_case_is_rejected_before_transport_and_public_material_is_small(self):
        fixed = public_case(case_value())
        self.assertEqual(set(fixed), {"id", "workflow", "task", "budget"})
        self.assertNotIn("PRIVATE_", json.dumps(fixed))
        runtime = self.runtime()
        for key in ("rubric", "reference", "learner"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                execute_scenario(runtime, {**fixed, key: case_value()[key]})
        with self.assertRaises(ValueError):
            execute_scenario(runtime, case_value())
        with self.assertRaises(ValueError):
            validate_public_case({**fixed, "task": {**fixed["task"], "reference": "hidden"}})
        self.assertEqual(self.record["actions"], [])
        self.assertEqual(self.record["evidence"], [])

    def test_downstream_goal_followup_and_simulator_boundaries_fail_before_preflight(self):
        fixed = public_case(case_value())
        for workflow in ("course", "research", "lesson", "question", "practice", "exam"):
            with self.subTest(workflow=workflow), self.assertRaises(ValueError):
                validate_public_case({**fixed, "workflow": workflow})
        task = {**fixed["task"], "follow_ups": [], "course_goal": "学习 Python 迭代协议"}
        valid = validate_public_case({**fixed, "workflow": "question", "task": task})
        self.assertNotEqual(valid["task"]["opening"], valid["task"]["course_goal"])
        with self.assertRaises(ValueError):
            validate_public_case({**fixed, "workflow": "question", "task": {**task, "course_goal": None}})
        # No callback invocation or provider request is possible without a callback.
        value = case_value()
        value["task"].update(mode="simulated", follow_ups=[])
        self.output = self.root / "simulated-trial"
        self.record = new_trial(self.output, value)
        fixed = public_case(value)
        self.assert_failure("student_callback_required", lambda: execute_scenario(self.runtime(), fixed))
        self.assertEqual(self.record["actions"], [])

    def test_public_case_identity_cannot_be_swapped_into_another_trial(self):
        fixed = public_case(case_value())
        fixed["task"]["opening"] = "另一份任务"
        self.assert_failure("public_case_identity_mismatch", lambda: execute_scenario(self.runtime(), fixed))
        self.assertEqual(self.record["actions"], [])

    def test_invalid_paths_and_actual_connection_failure_save_types_not_arbitrary_error_text(self):
        with self.runtime() as runtime:
            self.assert_failure("invalid_api_path", lambda: runtime.get("/api/health?key=PRIVATE_NETWORK_DETAIL"))
        self.assertNotIn("PRIVATE_NETWORK_DETAIL", json.dumps(load_trial(self.output)))
        with socket.socket() as unserved:
            unserved.bind(("127.0.0.1", 0))  # Real reserved TCP port with no HTTP listener.
            port = unserved.getsockname()[1]
            with self.runtime(f"http://127.0.0.1:{port}") as runtime:
                self.assert_failure("transport_failed", lambda: runtime.get("/api/health"))
        error = load_trial(self.output)["error"]
        self.assertEqual(error["type"], "URLError")
        self.assertIn(error["transport_type"], {"ConnectionRefusedError", "TimeoutError"})
        self.assertNotIn("message", error)
        self.assertEqual(self.record["actions"], [])

    def test_public_facts_map_only_to_allowed_custom_answers_and_otherwise_explicitly_skip(self):
        questions = Clarification.model_validate({"questions": [
            {"id": "prior", "question": "当前基础？", "type": "single", "allow_custom": True,
             "options": [{"id": "new", "label": "初学"}, {"id": "used", "label": "用过"}]},
            {"id": "style", "question": "偏好？", "type": "single", "allow_custom": False,
             "options": [{"id": "theory", "label": "理论"}, {"id": "practice", "label": "实践"}]}]})
        questions = questions.model_dump()["questions"]
        task = {"clarification": "facts", "clarification_facts": "我用过for循环，未理解惰性求值。"}
        submission = clarification_answers(task, questions)
        self.assertFalse(submission["skip"])
        self.assertEqual(submission["answers"], [{"question_id": "prior", "option_ids": [], "custom_text": task["clarification_facts"]}])
        resolved = resolve_answers(questions, submission["answers"], submission["skip"])
        self.assertEqual(resolved[0]["custom_text"], task["clarification_facts"])
        for task_value, offered in [({"clarification": "skip"}, questions), (task, questions[1:])]:
            skipped = clarification_answers(task_value, offered)
            self.assertEqual(skipped, {"skip": True, "answers": []})
            self.assertEqual(resolve_answers(offered, skipped["answers"], skipped["skip"]), [])


if __name__ == "__main__":
    unittest.main()
