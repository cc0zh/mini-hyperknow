"""Offline catalog and real-file CLI regression checks; no model calls."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from eval_core.html_report import report_bundle
from eval_core.review import publish_review, publish_workspace_home, refresh_review
from eval_core.store import read_json, write_json
from hyperknow.eval_cli import main
from test_eval_html_report import embedded_bundle
from test_eval_reporting import trial_record


class ReviewTests(unittest.TestCase):
    def test_home_is_a_managed_link_and_only_one_report_is_expanded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            publish_review(root / "review", report_bundle([trial_record()]), {"source": "one"})
            publish_review(root / "review", report_bundle([trial_record(verdict="fail")]), {"source": "two"})
            home = publish_workspace_home(root)
            self.assertIn('href="review/index.html"', home.read_text(encoding="utf-8"))
            self.assertEqual(publish_workspace_home(root), home)
            content = (root / "review/index.html").read_text(encoding="utf-8")
            self.assertEqual(content.split("</section>", 1)[0].count('<a href="snapshots/'), 1)
            self.assertIn("其他已收录报告（1）", content)
            home.write_text("user document", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unmanaged"):
                publish_workspace_home(root)
            self.assertEqual(home.read_text(encoding="utf-8"), "user document")

    def invoke(self, arguments):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(arguments)
        return code, json.loads(out.getvalue()), err.getvalue()

    def test_fixed_entry_updates_latest_and_preserves_snapshots(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trial = trial_record(verdict="fail")
            bundle = report_bundle([trial])
            first = publish_review(root, bundle, {"results": ["source-a"]})
            original = first.read_bytes()
            second = publish_review(root, report_bundle([trial_record()]), {"results": ["source-a"]})
            self.assertNotEqual(first, second)
            self.assertEqual(first.read_bytes(), original)
            catalog = read_json(root / "catalog.json")
            self.assertEqual(len(catalog["reports"]), 2)
            self.assertEqual([r["latest"] for r in catalog["reports"]], [False, True])
            content = (root / "index.html").read_text(encoding="utf-8")
            self.assertIn(second.name, content)
            self.assertIn(first.name, content)
            self.assertIn("历史快照", content)
            self.assertEqual(embedded_bundle(second.read_text(encoding="utf-8"))["entries"][0]["status"], "passed")
            self.assertEqual(bundle["entries"][0]["status"], "failed")

    def test_catalog_is_rebuildable_without_reading_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = refresh_review(root)
            self.assertIn("还没有报告", path.read_text(encoding="utf-8"))
            publish_review(root, report_bundle([trial_record()]), {"results": ["not-an-existing-file"]})
            original = read_json(root / "catalog.json")
            path.unlink()
            refresh_review(root)
            self.assertEqual(read_json(root / "catalog.json"), original)
            self.assertIn(original["reports"][0]["filename"], path.read_text(encoding="utf-8"))

    def test_catalog_escapes_titles_and_refuses_unmanaged_index_or_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trial = trial_record()
            trial["case"]["title"] = '<script>alert(1)</script><img src="https://invalid.test">'
            publish_review(root, report_bundle([trial]), {"results": ["one"]})
            content = (root / "index.html").read_text(encoding="utf-8")
            self.assertNotIn("<script>", content)
            self.assertNotIn("<img", content)
            self.assertIn("&lt;script&gt;", content)
            self.assertIn("default-src 'none'", content)
            catalog = read_json(root / "catalog.json")
            catalog["reports"][0]["filename"] = "../../outside.html"
            write_json(root / "catalog.json", catalog)
            with self.assertRaises(ValueError):
                refresh_review(root)
            other = root / "other"
            other.mkdir()
            (other / "index.html").write_text("user document", encoding="utf-8")
            with self.assertRaises(ValueError):
                publish_review(other, report_bundle([trial_record()]), {})
            self.assertEqual((other / "index.html").read_text(), "user document")

    def test_cli_review_imports_saved_result_without_modifying_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "trial" / "result.json"
            write_json(source, trial_record(verdict="fail"))
            original = source.read_bytes()
            code, report, err = self.invoke(["review", "--result", str(source.parent),
                                             "--review-dir", str(root / "review")])
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(report["calls"], 0)
            self.assertTrue(Path(report["index"]).is_file())
            self.assertEqual(source.read_bytes(), original)
            code, rebuilt, _ = self.invoke(["review", "--review-dir", str(root / "review")])
            self.assertEqual(code, 0)
            self.assertEqual(rebuilt["index"], report["index"])
            self.assertEqual(len(read_json(root / "review/catalog.json")["reports"]), 1)

    def test_missing_snapshot_refuses_rebuild_without_discarding_catalog(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot = publish_review(root, report_bundle([trial_record()]), {})
            original = (root / "catalog.json").read_bytes()
            snapshot.unlink()
            with self.assertRaises(ValueError):
                refresh_review(root)
            self.assertEqual((root / "catalog.json").read_bytes(), original)

    def test_snapshot_symlink_cannot_link_to_unmanaged_html(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot = publish_review(root, report_bundle([trial_record()]), {})
            target = root / "unmanaged.html"
            target.write_text("<script>alert(1)</script>", encoding="utf-8")
            snapshot.unlink()
            try:
                snapshot.symlink_to(target)
            except OSError:
                self.skipTest("Windows symlink privilege unavailable; missing-file boundary tested separately")
            with self.assertRaises(ValueError):
                refresh_review(root)

    def test_invalid_case_titles_still_export_visible_invalid_material(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index, title in enumerate((["invalid"], {"invalid": True}, 123, None, "")):
                with self.subTest(title=title):
                    trial = trial_record(trial_id=f"invalid-title-{index}")
                    trial["case"]["title"] = title
                    bundle = report_bundle([trial])
                    snapshot = publish_review(root, bundle, {"source": index})
                    saved = embedded_bundle(snapshot.read_text(encoding="utf-8"))
                    self.assertFalse(saved["entries"][0]["summary"]["passed"])
                    self.assertEqual(saved["entries"][0]["case"]["title"], title)
                    self.assertIn(trial["trial_id"], (root / "index.html").read_text(encoding="utf-8"))

    def test_report_automatically_publishes_but_keeps_json_and_exit_code(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "result.json"
            write_json(source, trial_record(verdict="fail"))
            arguments = ["report", "--result", str(source), "--review-dir", str(root / "review")]
            code, report, err = self.invoke(arguments)
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(report["trials"][0]["status"], "failed")
            self.assertTrue((root / "review/index.html").exists())
            with patch("eval_core.review.publish_review", side_effect=OSError("private details")):
                code, unchanged, err = self.invoke(arguments)
            self.assertEqual(code, 0)
            self.assertEqual(unchanged, report)
            self.assertIn("OSError", err)
            self.assertNotIn("private details", err)

    def test_execute_completion_publishes_actual_saved_result_with_no_extra_actions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "trial/result.json"
            trial = trial_record(verdict="fail")
            write_json(source, trial)
            from eval_core.reporting import summarize_trial
            with patch("hyperknow.eval_cli._run", return_value=summarize_trial(trial)) as run:
                code, report, err = self.invoke(["execute", "--output", str(source.parent),
                    "--data-dir", str(root / "no-business-db"), "--execute", "--review-dir", str(root / "review")])
            self.assertEqual((code, err), (1, ""))
            self.assertEqual(run.call_count, 1)
            self.assertEqual(report["status"], "failed")
            self.assertTrue((root / "review/index.html").is_file())
            self.assertEqual(read_json(source), trial)

    def test_compare_is_indexed_separately_from_single_trial_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            before, after = root / "before.json", root / "after.json"
            write_json(before, trial_record(verdict="fail"))
            write_json(after, trial_record(subject={"assembly": "candidate"}, trial_id="candidate"))
            options = ["--review-dir", str(root / "review")]
            self.assertEqual(self.invoke(["report", "--result", str(before), *options])[0], 0)
            code, report, err = self.invoke(["compare", "--baseline", str(before),
                                            "--candidate", str(after), *options])
            self.assertEqual((code, err), (0, ""))
            records = read_json(root / "review/catalog.json")["reports"]
            self.assertEqual([r["kind"] for r in records], ["report", "comparison"])
            self.assertTrue(all(r["latest"] for r in records))
            self.assertEqual(report["counts"]["changes"], {"improved": 1})


if __name__ == "__main__":
    unittest.main()
