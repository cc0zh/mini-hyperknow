"""Compact run layouts and real-file offline exports; no model requests."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from eval_core.artifacts import result_path, run_directory
from eval_core.review import RUN_MARKER
from eval_core.store import read_json, write_json
from hyperknow.eval_cli import main
from test_eval_html_report import embedded_bundle
from test_eval_reporting import trial_record


class ArtifactLayoutTests(unittest.TestCase):
    def invoke(self, arguments):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(arguments)
        return code, json.loads(out.getvalue()), err.getvalue()

    def test_new_directory_uses_details_and_explicit_json_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "run"
            self.assertEqual(result_path(root), root / "details/result.json")
            self.assertEqual(run_directory(result_path(root)), root)
            explicit = root / "custom.json"
            self.assertEqual(result_path(explicit), explicit)
            self.assertIsNone(run_directory(explicit))
            self.assertFalse(root.exists())

    def test_legacy_directory_is_kept_and_two_results_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_json(root / "result.json", trial_record())
            self.assertEqual(result_path(root), root / "result.json")
            self.assertIsNone(run_directory(result_path(root)))
            write_json(root / "details/result.json", trial_record())
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                result_path(root)

    def test_offline_report_creates_one_front_page_and_deduplicates_snapshots(self):
        with tempfile.TemporaryDirectory() as temp:
            root, review = Path(temp) / "run", Path(temp) / "review"
            source = root / "details/result.json"
            write_json(source, trial_record(verdict="fail"))
            original = source.read_bytes()
            arguments = ["report", "--result", str(root), "--review-dir", str(review)]
            code, report, err = self.invoke(arguments)
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(report["trials"][0]["status"], "failed")
            page = (root / "report.html").read_text(encoding="utf-8")
            self.assertTrue(page.startswith(RUN_MARKER))
            self.assertEqual(embedded_bundle(page)["entries"][0]["status"], "failed")
            self.assertEqual({p.name for p in root.iterdir()}, {"report.html", "details"})
            snapshot = next((review / "snapshots").iterdir())
            snapshot_bytes = snapshot.read_bytes()
            self.assertEqual(self.invoke(arguments), (code, report, err))
            self.assertEqual(len(read_json(review / "catalog.json")["reports"]), 1)
            self.assertEqual(snapshot.read_bytes(), snapshot_bytes)
            self.assertEqual(source.read_bytes(), original)

    def test_updated_result_updates_managed_page_and_keeps_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root, review = Path(temp) / "run", Path(temp) / "review"
            source = root / "details/result.json"
            write_json(source, trial_record())
            arguments = ["review", "--result", str(root), "--review-dir", str(review)]
            self.assertEqual(self.invoke(arguments)[0], 0)
            old = next((review / "snapshots").iterdir())
            original = old.read_bytes()
            write_json(source, trial_record(verdict="fail"))
            self.assertEqual(self.invoke(arguments)[0], 0)
            self.assertEqual(old.read_bytes(), original)
            records = read_json(review / "catalog.json")["reports"]
            self.assertEqual([r["latest"] for r in records], [False, True])
            page = (root / "report.html").read_text(encoding="utf-8")
            self.assertEqual(embedded_bundle(page)["entries"][0]["status"], "failed")

    def test_unmanaged_front_page_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "run"
            write_json(root / "details/result.json", trial_record())
            front = root / "report.html"
            front.write_text("user document", encoding="utf-8")
            code, _, err = self.invoke(["report", "--result", str(root),
                                        "--review-dir", str(Path(temp) / "review")])
            self.assertEqual(code, 0)
            self.assertIn("Review export deferred", err)
            self.assertEqual(front.read_text(encoding="utf-8"), "user document")

    def test_legacy_report_and_unauthorized_resume_do_not_relocate_results(self):
        with tempfile.TemporaryDirectory() as temp:
            root, review = Path(temp) / "run", Path(temp) / "review"
            source = root / "result.json"
            write_json(source, trial_record())
            original = source.read_bytes()
            self.assertEqual(self.invoke(["report", "--result", str(root),
                                          "--review-dir", str(review)])[0], 0)
            self.assertFalse((root / "details").exists())
            code, report, _ = self.invoke(["resume", "--output", str(root),
                "--data-dir", str(Path(temp) / "no-backend"), "--review-dir", str(review)])
            self.assertEqual(code, 2)
            self.assertIn("--execute is required", report["message"])
            self.assertEqual(source.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
