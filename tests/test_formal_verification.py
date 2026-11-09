from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_state_machines.py"
SPEC = importlib.util.spec_from_file_location("verify_state_machines", SCRIPT)
assert SPEC and SPEC.loader
verification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verification)


class ModelCheckerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        (self.directory / "Model.cfg").write_text("CONSTANT Broken = FALSE\n", encoding="utf-8")
        (self.directory / "Model.tla").write_text("MODULE Model", encoding="utf-8")
        self.item = {
            "directory": self.directory, "config": "Model.cfg", "spec": "Model.tla",
            "id": "example", "invariant": "NoLateSave",
        }

    def result(self, code: int, text: str) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess([], code, stdout=text, stderr="")

    def test_baseline_requires_completed_exploration(self) -> None:
        with patch.object(verification.subprocess, "run", return_value=self.result(0, "partial output")):
            with self.assertRaisesRegex(RuntimeError, "Unexpected baseline"):
                verification.run_tlc(self.item, Path("tool.jar"), self.directory, False)

    def test_baseline_reports_distinct_states(self) -> None:
        output = "Model checking completed. No error has been found.\n1,024 distinct states found"
        with patch.object(verification.subprocess, "run", return_value=self.result(0, output)):
            result = verification.run_tlc(self.item, Path("tool.jar"), self.directory, False)
        self.assertEqual(result["states"], 1024)
        self.assertTrue((self.directory / "example-baseline.out").is_file())

    def test_mutant_requires_the_expected_invariant(self) -> None:
        for code, output in [
            (12, "Invariant DifferentRule is violated."),
            (1, "Invariant NoLateSave is violated."),
            (150, "Parse error"),
            (0, "Model checking completed. No error has been found."),
        ]:
            with self.subTest(code=code, output=output):
                with patch.object(verification.subprocess, "run", return_value=self.result(code, output)):
                    with self.assertRaisesRegex(RuntimeError, "Unexpected mutant"):
                        verification.run_tlc(self.item, Path("tool.jar"), self.directory, True)

    def test_mutant_accepts_only_a_real_invariant_violation(self) -> None:
        with patch.object(verification.subprocess, "run", return_value=self.result(
            12, "Error: Invariant NoLateSave is violated.\n5 distinct states found"
        )):
            result = verification.run_tlc(self.item, Path("tool.jar"), self.directory, True)
        self.assertEqual(result["violated"], "NoLateSave")

    def test_code_mutation_anchor_must_be_unique(self) -> None:
        config = (self.directory / "Model.cfg").read_text(encoding="utf-8")
        (self.directory / "Model.cfg").write_text(config + config, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Expected one"):
            verification.run_tlc(self.item, Path("tool.jar"), self.directory, True)


if __name__ == "__main__":
    unittest.main()
