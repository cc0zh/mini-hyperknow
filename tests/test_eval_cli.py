"""Offline integration, real disk and actual ASGI health; no model stand-ins."""

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from fastapi.testclient import TestClient

from eval_core.contracts import validate_case
from eval_core.grading import grading_definition_hash
from eval_core.reporting import build_experiment, validate_experiment
from eval_core.store import digest, read_json, write_json
from hyperknow.config import Settings
from hyperknow.eval_migration import migrate_case
from hyperknow.main import create_app


ROOT = Path(__file__).resolve().parents[1]


class EvaluationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.review_temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.review_temp.cleanup)

    def invoke(self, arguments):
        from hyperknow.eval_cli import main
        output = io.StringIO()
        with redirect_stdout(output):
            if arguments[0] in {"execute", "resume", "regrade", "report", "compare", "review"}:
                arguments = [*arguments, "--review-dir", self.review_temp.name]
            code = main(arguments)
        return code, json.loads(output.getvalue())

    def test_legacy_migration_is_explicit_deterministic_and_preserves_source(self):
        path = ROOT / "evals/concept-explanation/case.json"
        original = path.read_bytes()
        case = read_json(path)
        backup = deepcopy(case)
        migrated = migrate_case(case)
        self.assertEqual(case, backup)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(migrated, migrate_case(case))
        self.assertEqual(migrated["prerequisites"]["legacy_source"]["case_hash"], digest(case))
        for item in case["rubric"]:
            check = next(c for c in migrated["checks"] if c["check_id"] == item["id"])
            self.assertEqual(check["criterion"], item["criterion"])
            self.assertEqual(check["pass_when"], item["pass_when"])
            self.assertEqual(check["fail_when"], item["fail_when"])
        self.assertEqual(migrated["task"]["input"]["text"], case["input"])
        self.assertEqual(migrated, validate_case(read_json(ROOT / "evals/general/concept-chain-rule/case.json")))

    def test_authored_catalog_covers_all_businesses_and_artifact_types(self):
        cases = [validate_case(read_json(path)) for path in (ROOT / "evals/general").glob("*/case.json")]
        tags = {tag for case in cases for tag in case["tags"]}
        self.assertTrue({f"B{i:02d}" for i in range(1, 9)} <= tags)
        self.assertTrue({"flashcards", "quiz", "whiteboard", "animation", "diagram"} <= tags)
        self.assertTrue(all("development" in case["tags"] for case in cases))
        self.assertTrue(all("uncalibrated" in case["tags"] for case in cases))
        benchmark = read_json(ROOT / "evals/general/benchmark.json")
        self.assertEqual({m["case_hash"] for m in benchmark["members"]}, {digest(case) for case in cases})

    def test_validate_migrate_publish_and_plan_are_offline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "migrated.json"
            code, migrated = self.invoke(["migrate", "--case", str(ROOT / "evals/concept-explanation/case.json"),
                                         "--output", str(target)])
            self.assertEqual(code, 0)
            self.assertEqual(migrated["calls"], 0)
            self.assertEqual(self.invoke(["validate", "--case", str(target)])[0], 0)
            self.assertEqual(self.invoke(["migrate", "--case", str(ROOT / "evals/concept-explanation/case.json"),
                                          "--output", str(target)])[0], 2)
            library = root / "library"
            code, published = self.invoke(["publish", "--case", str(target), "--library", str(library),
                                           "--reviewed-by", "assistant:local-structure-review"])
            self.assertEqual(code, 0)
            self.assertTrue(Path(published["path"]).is_file())
            case = validate_case(read_json(target))
            manifest = root / "benchmark.json"
            write_json(manifest, {"schema_version": 2, "id": "local-development", "version": "1",
                "title": "离线结构检查，非模型验收", "usage": "development", "tags": [],
                "members": [{"id": case["id"], "version": case["version"], "case_hash": digest(case)}]})
            code, frozen = self.invoke(["benchmark", "--manifest", str(manifest), "--library", str(library)])
            self.assertEqual(code, 0)
            subjects = root / "subjects.json"
            write_json(subjects, [{"identity": "unknown", "label": "baseline"},
                                  {"identity": "unknown", "label": "candidate"}])
            plan = root / "experiment.json"
            grading_config = root / "grading.json"
            write_json(grading_config, {"model": "offline-configuration-not-executed",
                "base_url": "https://api.openai.com/v1", "timeout": 90,
                "max_output_tokens": 2048, "context_budget": 16384})
            code, blocked = self.invoke(["experiment", "--benchmark", frozen["path"], "--subjects", str(subjects),
                                         "--library", str(library), "--output", str(plan)])
            self.assertEqual(code, 2)
            self.assertFalse(plan.exists())
            code, experiment = self.invoke(["experiment", "--benchmark", frozen["path"], "--subjects", str(subjects),
                                            "--library", str(library), "--grading-config", str(grading_config),
                                            "--repetitions", "2", "--output", str(plan)])
            self.assertEqual(code, 0)
            self.assertEqual(len(experiment["trials"]), 4)
            code, report = self.invoke(["report", "--experiment", str(plan)])
            self.assertEqual(code, 0)
            self.assertNotIn("passed", [entry.get("status") for entry in report.get("trials", [])])

    def test_script_exposes_only_the_unified_commands(self):
        process = subprocess.run([sys.executable, "scripts/run_eval.py", "--help"], cwd=ROOT,
                                 capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("{validate,publish,migrate,", process.stdout)
        self.assertNotIn("{prepare,run,grade,show}", process.stdout)
        process = subprocess.run([sys.executable, "-c",
            "import sys; import hyperknow.eval_cli; "
            "assert not {'hyperknow.evaluation', 'hyperknow.eval_grading', "
            "'hyperknow.eval_cases'} & sys.modules.keys()"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)

    def test_removed_commands_fail_without_writing_or_dispatching(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            commands = [
                ["prepare", "--library", str(root / "library")],
                ["run", "--data-dir", str(root / "backend"), "--output", str(root / "trial")],
                ["grade", "--output", str(root / "trial")],
                ["show", "--output", str(root / "trial")],
            ]
            for arguments in commands:
                with self.subTest(command=arguments[0]):
                    process = subprocess.run([sys.executable, "scripts/run_eval.py", *arguments], cwd=ROOT,
                                             capture_output=True, text=True, encoding="utf-8")
                    self.assertEqual(process.returncode, 2, process.stderr)
                    self.assertIn("removed", process.stderr)
                    self.assertEqual(list(root.iterdir()), [])

    def test_legacy_report_is_read_only_json_and_preserves_budget_facts(self):
        from tests.test_eval_legacy import historical_result
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "result.json"
            state = historical_result()
            state["grades"][0].update(config={"max_output_tokens": 2048}, usage={"completion_tokens": 6109})
            write_json(path, state)
            original = path.read_bytes()
            code, result = self.invoke(["report", "--result", str(path)])
            self.assertEqual(code, 0)
            self.assertEqual(result["calls"], 0)
            self.assertTrue(result["legacy_read_only"])
            self.assertEqual(result["trials"][0]["grades"][0]["budget_check"]["status"], "exceeded")
            self.assertEqual(result["trials"][0]["final_response"], state["final_response"])
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(self.review_temp.name).iterdir()), [])
            code, result = self.invoke(["report", "--result", str(path), "--html", str(path.with_suffix(".html"))])
            self.assertEqual(code, 2)
            self.assertIn("schema-v1", result["message"])
            self.assertFalse(path.with_suffix(".html").exists())
            self.assertEqual(path.read_bytes(), original)

    def test_legacy_result_cannot_resume_regrade_compare_or_enter_v2_review(self):
        from tests.test_eval_legacy import historical_result
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "result.json"
            write_json(path, historical_result())
            original = path.read_bytes()
            commands = [
                ["resume", "--output", str(root), "--data-dir", str(root / "missing"), "--execute"],
                ["regrade", "--output", str(root), "--execute"],
                ["review", "--result", str(root)],
                ["compare", "--baseline", str(root), "--candidate", str(root)],
            ]
            for arguments in commands:
                with self.subTest(command=arguments[0]):
                    code, result = self.invoke(arguments)
                    self.assertEqual(code, 2)
                    self.assertIn("schema-v1", result["message"])
                    self.assertEqual(path.read_bytes(), original)
                    self.assertEqual(list(root.iterdir()), [path])
                    self.assertEqual(list(Path(self.review_temp.name).iterdir()), [])

    def test_equal_timeout_representations_align_to_frozen_plan_without_rehashing_history(self):
        from dataclasses import asdict
        from secrets import token_hex
        from eval_core.grading import ModelSettings
        from hyperknow.eval_cli import _settings_for_plan
        case = migrate_case(read_json(ROOT / "evals/concept-explanation/case.json"))
        for frozen_timeout, actual_timeout in ((90, 90.0), (180.0, 180), (90.5, 90.5)):
            with self.subTest(frozen=frozen_timeout, actual=actual_timeout):
                settings = ModelSettings(model="offline-grader", api_key=token_hex(24), timeout=actual_timeout)
                public = {key: value for key, value in asdict(settings).items() if key != "api_key"}
                public["timeout"] = frozen_timeout
                plan = build_experiment({"id": "timeout-identity", "version": "1", "cases": [case],
                                         "grading_config": public}, [{"identity": "offline"}], 1)
                original = deepcopy(plan)
                aligned = _settings_for_plan(settings, plan["grading_config"])
                self.assertEqual(type(aligned.timeout), type(frozen_timeout))
                self.assertEqual(grading_definition_hash(case, aligned), plan["trials"][0]["grading_definition_hash"])
                self.assertEqual(validate_experiment(plan), original)
                self.assertEqual(plan, original)
                self.assertEqual(type(settings.timeout), type(actual_timeout))
                with self.assertRaisesRegex(ValueError, "Grader settings differ"):
                    _settings_for_plan(settings, {**public, "timeout": frozen_timeout + 1})
                with self.assertRaises(ValueError):
                    _settings_for_plan(settings, {**public, "timeout": True})
        self.assertIsNone(_settings_for_plan(None, None))

    def test_grader_context_budget_is_explicit_and_changes_only_the_public_budget(self):
        import os
        from dataclasses import asdict
        from secrets import token_hex
        from hyperknow.eval_cli import _parser, _settings
        arguments = ["regrade", "--output", "not-opened", "--grader-model", "offline-model",
                     "--grader-base-url", "https://example.org/v1"]
        args = _parser().parse_args([*arguments, "--grader-context-budget", "32768"])
        previous = os.environ.get("HK_EVAL_GRADER_API_KEY")
        os.environ["HK_EVAL_GRADER_API_KEY"] = token_hex(24)
        try:
            default = _settings(_parser().parse_args(arguments))
            explicit = _settings(args)
            self.assertEqual(default.context_budget, 16384)
            self.assertEqual(explicit.context_budget, 32768)
            before, after = asdict(default), asdict(explicit)
            self.assertEqual({key for key in before if before[key] != after[key]}, {"context_budget"})
            for value in ("0", "-1"):
                with self.assertRaises(ValueError):
                    _settings(_parser().parse_args([*arguments, "--grader-context-budget", value]))
        finally:
            if previous is None:
                os.environ.pop("HK_EVAL_GRADER_API_KEY", None)
            else:
                os.environ["HK_EVAL_GRADER_API_KEY"] = previous

    def test_health_exposes_search_readiness_but_no_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            with TestClient(create_app(Settings(data_dir=Path(temp)))) as client:
                health = client.get("/api/health").json()
                self.assertEqual(health["search"], {"configured": False, "verified": False})
                self.assertNotIn("api_key", json.dumps(health))
                self.assertFalse(health["model"]["configured"])

    def test_partial_experiment_edits_are_rejected_before_adapter_creation(self):
        case = migrate_case(read_json(ROOT / "evals/concept-explanation/case.json"))
        plan = build_experiment({"id": "integrity", "version": "1", "cases": [case]},
                                [{"identity": "unknown", "label": "not-executed"}], 1)
        self.assertEqual(validate_experiment(plan), plan)
        for field in ("case", "subject", "repetition", "trial_id"):
            broken = deepcopy(plan)
            trial = broken["trials"][0]
            if field == "case":
                trial["case"]["task"]["input"]["text"] = "tampered input, no longer the fixed Case"
            elif field == "subject":
                trial["subject"]["label"] = "changed subject"
            elif field == "repetition":
                trial["repetition"] = 2
            else:
                trial["trial_id"] = "wrong-trial"
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_experiment(broken)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            broken = deepcopy(plan)
            broken["trials"][0]["case"]["task"]["input"]["text"] = "tampered"
            path = root / "experiment.json"
            write_json(path, broken)
            output = root / "trial"
            code, result = self.invoke(["execute", "--experiment", str(path),
                "--trial-id", broken["trials"][0]["trial_id"], "--data-dir", str(root / "no-backend"),
                "--output", str(output), "--library", str(root / "library"), "--execute"])
            self.assertEqual(code, 2)
            self.assertIn("Case hash mismatch", result["message"])
            self.assertFalse(output.exists())

    def test_mixed_benchmark_does_not_apply_model_config_to_rule_only_case(self):
        model_case = migrate_case(read_json(ROOT / "evals/concept-explanation/case.json"))
        rule_case = deepcopy(model_case)
        rule_case["id"] = "rule-only-engineering"
        rule_case["checks"] = [c for c in rule_case["checks"] if c["kind"] == "rule"]
        config = {"model": "offline-configuration-not-executed", "base_url": "https://api.openai.com/v1",
                  "timeout": 90, "max_output_tokens": 2048, "context_budget": 16384}
        plan = build_experiment({"id": "mixed", "version": "1", "cases": [model_case, rule_case],
                                 "grading_config": config}, [{"identity": "unknown"}], 1)
        selected = next(t for t in plan["trials"] if t["case"]["id"] == rule_case["id"])
        self.assertEqual(selected["grading_definition_hash"], grading_definition_hash(rule_case, None))
        self.assertEqual(validate_experiment(plan), plan)


if __name__ == "__main__":
    unittest.main()
