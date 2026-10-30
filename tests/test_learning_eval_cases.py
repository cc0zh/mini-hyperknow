"""Task trust boundaries and durable evidence, without model substitutes."""

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

from hyperknow_eval.calibration import load_controls
from hyperknow_eval.cases import ROOT, inventory, load_suite
from hyperknow_eval.cli import _input, main
from hyperknow_eval.runner import private_path
from hyperknow_eval.schema import WORKFLOWS, public_case, validate_case
from hyperknow_eval.storage import (add_evidence, digest, evidence_hash, exclusive, load_trial,
                                   new_trial, read_json, save_trial, write_json)


class LearningContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.cases = load_suite()

    def test_curated_suite_covers_domains_and_real_workflows_without_claiming_holdout(self):
        summary = inventory(self.cases)
        self.assertGreaterEqual(summary["cases"], 15)
        self.assertEqual(set(summary["workflows"]), WORKFLOWS)
        self.assertGreaterEqual(len(summary["domains"]), 8)
        self.assertEqual(summary["review_status"], {"author_reviewed": len(self.cases)})
        self.assertEqual(summary["calls"], 0)
        self.assertIn("not a held-out", summary["purpose"])

    def test_private_standards_and_hidden_learner_are_not_in_execution_projection(self):
        case = deepcopy(self.cases[0])
        case["reference"]["facts"].append("PRIVATE-ANSWER-CANARY")
        case["learner"]["misconceptions"].append("HIDDEN-PROFILE-CANARY")
        case["rubric"][0]["description"] = "PRIVATE-RUBRIC-CANARY"
        projected = public_case(case)
        self.assertEqual(set(projected), {"id", "workflow", "task", "budget"})
        self.assertNotIn("CANARY", json.dumps(projected))

    def test_invalid_rubrics_and_unbounded_interactions_are_rejected(self):
        changes = [
            lambda case: case["rubric"].append(case["rubric"][0]),
            lambda case: case["task"].update(max_turns=0),
            lambda case: case["task"].update(max_turns=1),
            lambda case: case["task"].update(mode="simulated"),
            lambda case: case["learner"].update(misconceptions=[" "]),
            lambda case: case["reference"].update(facts=[""]),
            lambda case: case["budget"].update(max_actions=True),
            lambda case: case["rubric"][0].update(critical="yes"),
            lambda case: case.update(unknown="field"),
        ]
        for change in changes:
            with self.subTest(change=change):
                case = deepcopy(self.cases[0])
                change(case)
                with self.assertRaises(ValueError):
                    validate_case(case)

    def test_downstream_case_cannot_turn_a_student_question_into_course_goal(self):
        case = deepcopy(next(case for case in self.cases if case["workflow"] == "question"))
        self.assertNotEqual(case["task"]["opening"], case["task"]["course_goal"])
        case["task"]["course_goal"] = None
        with self.assertRaises(ValueError):
            validate_case(case)

    def test_manifest_cannot_escape_to_an_arbitrary_file_or_duplicate_a_case(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            manifest = {"schema_version": 3, "id": "test", "revision": 1,
                        "purpose": "development", "cases": ["../secrets.json"]}
            write_json(directory / "suite.json", manifest)
            with self.assertRaisesRegex(ValueError, "within"):
                load_suite(directory / "suite.json")
            write_json(directory / "case.json", self.cases[0])
            manifest["cases"] = ["case.json", "case.json"]
            write_json(directory / "suite.json", manifest)
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_suite(directory / "suite.json")

    def test_controls_are_explicit_authored_samples_not_real_business_runs(self):
        controls = load_controls(ROOT / "evals" / "calibration.json")
        self.assertEqual(len(controls["controls"]), 6)
        expected = {verdict for control in controls["controls"] for verdict in control["expected"].values()}
        self.assertEqual(expected, {"met", "not_met", "insufficient"})
        self.assertIn("not-human", controls["purpose"])


class LearningStorageAndCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="learning-eval-contract-")
        self.root = Path(self.temporary.name)
        _, cases = load_suite()
        self.case = cases[0]

    def tearDown(self):
        self.temporary.cleanup()

    def test_trial_evidence_tampering_and_cross_trial_identity_are_rejected(self):
        output = self.root / "trial"
        record = new_trial(output, self.case)
        identity = add_evidence(record, "tutor_turn", {"text": "a real stored quotation"}, {"run_id": "run-a"})
        record["transcript"].append({"role": "tutor", "text": "a real stored quotation", "evidence_id": identity})
        save_trial(output, record)
        original = evidence_hash(record)
        self.assertEqual(evidence_hash(load_trial(output)), original)
        record["evidence"][0]["content"]["text"] = "tampered"
        save_trial(output, record)
        with self.assertRaisesRegex(ValueError, "digest"):
            load_trial(output)
        record["evidence"][0]["sha256"] = digest(record["evidence"][0]["content"])
        record["evidence"][0]["trial_id"] = "another-trial"
        save_trial(output, record)
        with self.assertRaisesRegex(ValueError, "identity"):
            load_trial(output)

    def test_original_trial_and_single_writer_lock_are_not_overwritten(self):
        directory = self.root / "trial"
        new_trial(directory, self.case)
        saved = (directory / "trial.json").read_bytes()
        with self.assertRaises(FileExistsError):
            new_trial(directory, self.case)
        self.assertEqual((directory / "trial.json").read_bytes(), saved)
        with exclusive(directory):
            with self.assertRaises(FileExistsError):
                with exclusive(directory):
                    pass
        self.assertFalse((directory / ".writer.lock").exists())
        self.assertFalse(list(directory.glob("*.tmp")))

    def test_json_duplicate_keys_and_nonfinite_constants_fail_closed(self):
        for text in ('{"a":1,"a":2}', '{"a":NaN}'):
            path = self.root / "invalid.json"
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(ValueError):
                read_json(path)

    def test_batch_report_includes_unexecuted_cells_and_does_not_write(self):
        from hyperknow_eval.reporting import aggregate
        batch = self.root / "batch"
        batch.mkdir()
        write_json(batch / "batch.json", {"schema_version": 3, "created_at": "2026-10-29",
                   "entries": [{"case": self.case, "case_hash": digest(self.case), "repetition": 1, "path": "one"}]})
        original = (batch / "batch.json").read_bytes()
        records = _input(batch)
        result = aggregate(records)
        self.assertEqual(result["trials"], 1)
        self.assertEqual(result["execution"], {"not_run": 1})
        self.assertEqual(result["teaching"]["statuses"], {"insufficient": 1})
        self.assertEqual(result["teaching"]["dimensions"]["correctness"]["total"], 1)
        self.assertEqual((batch / "batch.json").read_bytes(), original)
        self.assertEqual(list(batch.iterdir()), [batch / "batch.json"])

    def test_cli_does_not_authorize_calls_or_create_outputs_without_execute(self):
        output = self.root / "unauthorized"
        with redirect_stdout(io.StringIO()) as stream:
            status = main(["run", "--case", str(ROOT / "evals/cases/chain-rule-transfer.json"), "--output", str(output)])
        self.assertEqual(status, 2)
        self.assertIn("--execute", stream.getvalue())
        self.assertFalse(output.exists())

    def test_validate_and_report_are_explicitly_offline(self):
        with redirect_stdout(io.StringIO()) as stream:
            self.assertEqual(main(["validate"]), 0)
        self.assertEqual(json.loads(stream.getvalue())["calls"], 0)
        output = self.root / "trial"
        new_trial(output, self.case)
        saved = (output / "trial.json").read_bytes()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["report", "--input", str(output)]), 0)
        self.assertEqual((output / "trial.json").read_bytes(), saved)
        self.assertEqual(list(output.iterdir()), [output / "trial.json"])

    def test_uncertain_remote_billing_is_not_a_failed_business_engineering_check(self):
        from hyperknow_eval.reporting import summarize
        record = new_trial(self.root / "billing", self.case)
        record["checks"] = [{"id": "saved", "passed": True},
                            {"id": "remote_cost_finished", "passed": None, "category": "billing_observation"}]
        result = summarize(record)
        self.assertEqual(result["engineering"]["status"], "met")
        self.assertEqual(result["observations"][0]["id"], "remote_cost_finished")
        self.assertEqual(result["usage"]["remote_or_in_flight_cost"], "unknown")

    def test_private_outputs_cannot_be_written_into_source_or_protected_history(self):
        for path in (ROOT / "src" / "new.json", ROOT / "eval_result" / "2026-10-29" / "anything"):
            with self.assertRaises(ValueError):
                private_path(path)
        self.assertEqual(private_path(ROOT / "data" / "new-eval"), (ROOT / "data" / "new-eval").resolve())

    def test_protected_history_reads_are_rejected_lexically_without_opening_old_files(self):
        from hyperknow_eval.runtime import Runtime, readonly

        record = new_trial(self.root / "read-guard", self.case)
        for directory in (ROOT / "eval_result" / "2026-10-29",
                          ROOT / "data" / ".." / "eval_result" / "2026-10-29"):
            for reader in (read_json, load_trial, load_suite, load_controls, _input):
                with self.subTest(reader=reader.__name__, path=directory):
                    with self.assertRaisesRegex(ValueError, "protected"):
                        reader(directory / "trial.json")
            with self.assertRaisesRegex(ValueError, "protected"):
                Runtime("http://127.0.0.1:1", directory, record, lambda: None)
            with self.assertRaisesRegex(ValueError, "protected"):
                with readonly(directory / "hyperknow.sqlite3"):
                    self.fail("protected SQLite must not be opened")

    def test_protected_history_writers_reject_before_mkdir_lock_or_report_creation(self):
        from hyperknow_eval.calibration import calibrate
        from hyperknow_eval.reporting import write_report
        from hyperknow_eval.runner import ManagedBackend

        record = new_trial(self.root / "write-guard", self.case)
        directory = ROOT / "eval_result" / "2026-10-29" / "must-not-be-created"
        for writer in (lambda: write_json(directory / "trial.json", record),
                       lambda: save_trial(directory, record),
                       lambda: new_trial(directory, self.case),
                       lambda: write_report(directory / "report.html", [record]),
                       lambda: calibrate({}, directory, None, execute=True),
                       lambda: ManagedBackend(directory)):
            with self.subTest(writer=writer):
                with self.assertRaisesRegex(ValueError, "protected"):
                    writer()
        with self.assertRaisesRegex(ValueError, "protected"):
            with exclusive(directory):
                self.fail("protected history must not acquire a lock")


if __name__ == "__main__":
    unittest.main()
