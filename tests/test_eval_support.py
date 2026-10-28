"""Shared evaluation guards use real local files and SQLite; no model calls."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import sqlite3
import tempfile
import unittest

from hyperknow.eval_support import (ROOT, isolated_database, local_origin, private_output,
                                     readonly, skill_trace_matches)
from hyperknow.storage import Database


class EvaluationSupportTests(unittest.TestCase):
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

    def test_backend_origin_is_explicit_loopback_without_credentials_or_extra_paths(self):
        for url in ("https://example.com", "http://127.0.0.1/path", "http://u:p@localhost",
                    "http://localhost?q=1", "http://localhost#fragment", "ftp://localhost"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                local_origin(url)
        self.assertEqual(local_origin("http://127.0.0.1:8039/"), "http://127.0.0.1:8039")
        self.assertEqual(local_origin("http://[::1]:8039"), "http://[::1]:8039")

    def test_default_and_missing_database_are_rejected_without_creating_files(self):
        with self.assertRaises(ValueError):
            isolated_database(ROOT / "data")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(ValueError):
                isolated_database(root)
            self.assertEqual(list(root.iterdir()), [])
            Database(root / "hyperknow.sqlite3")
            self.assertEqual(isolated_database(root), root.resolve() / "hyperknow.sqlite3")

    def test_private_output_rejects_source_tree_but_allows_private_or_external_paths(self):
        with self.assertRaises(ValueError):
            private_output(ROOT / "evals" / "mutable-output")
        self.assertEqual(private_output(ROOT / "data/evals/test"), (ROOT / "data/evals/test").resolve())
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(private_output(Path(temp)), Path(temp).resolve())

    def test_sqlite_evidence_is_read_only_and_never_creates_missing_database(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "hyperknow.sqlite3"
            Database(path)
            with readonly(path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0], 0)
                with self.assertRaises(sqlite3.OperationalError):
                    conn.execute("DELETE FROM command_receipts")
            missing = Path(temp) / "missing.sqlite3"
            with self.assertRaises(sqlite3.OperationalError), readonly(missing):
                self.fail("opening missing evidence must fail")
            self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
