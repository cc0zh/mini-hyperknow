"""Direct file/SQLite/CLI checks for the opt-in classroom acceptance runner."""

import importlib.util
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verify_classroom", ROOT / "scripts/verify_classroom.py")
verification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verification)


class ClassroomVerificationTests(unittest.TestCase):
    def test_missing_execute_does_not_create_directory_or_read_source(self):
        with TemporaryDirectory() as temp:
            target = Path(temp) / "must-not-exist"
            result = subprocess.run([sys.executable, str(ROOT / "scripts/verify_classroom.py"),
                                     "--source-db", str(Path(temp) / "missing.sqlite3"),
                                     "--course-id", "missing", "--session-id", "missing",
                                     "--data-dir", str(target)], cwd=ROOT, text=True,
                                    encoding="utf-8", capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("--execute is required", result.stdout)
            self.assertFalse(target.exists())

    def test_source_is_read_only_and_unknown_sessions_are_rejected(self):
        # This is a direct SQLite selection rule, not a model-response fixture.
        with TemporaryDirectory() as temp:
            path = Path(temp) / "course.sqlite3"
            course = {"course_id": "course", "units": [{"lectures": [{"sessions": [
                {"session_id": "session", "title": "真实持久化选择规则"}]}]}]}
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.execute("CREATE TABLE courses(id TEXT PRIMARY KEY,data TEXT)")
                conn.execute("CREATE TABLE runs(id TEXT PRIMARY KEY,data TEXT)")
                conn.execute("INSERT INTO courses VALUES (?,?)", ("course", json.dumps(course)))
            original = path.read_bytes()
            selected, run, sessions = verification.read_source(path, "course", ["session"])
            self.assertEqual(selected, course)
            self.assertIsNone(run)
            self.assertEqual(set(sessions), {"session"})
            self.assertEqual(path.read_bytes(), original)
            for ids in (["unknown"], ["session", "session"], []):
                with self.assertRaises(ValueError):
                    verification.read_source(path, "course", ids)
            self.assertEqual(path.read_bytes(), original)

    def test_missing_source_is_not_silently_created(self):
        with TemporaryDirectory() as temp:
            source = Path(temp) / "missing.sqlite3"
            with self.assertRaises(ValueError):
                verification.read_source(source, "course", ["session"])
            self.assertFalse(source.exists())

    def test_evidence_replacement_and_command_versions(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "evidence.json"
            verification.write_evidence(path, {"status": "in_flight", "中文": "保留"})
            verification.write_evidence(path, {"status": "ready"})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"status": "ready"})
            self.assertFalse(path.with_suffix(".tmp").exists())
        payload = verification.command_payload({"script": {"script_id": "current"},
                                                "progress": {"version": 8}, "version": 42})
        self.assertEqual(payload["expected_version"], 8)
        self.assertEqual(payload["script_id"], "current")
        self.assertTrue(payload["client_command_id"])


if __name__ == "__main__":
    unittest.main()
