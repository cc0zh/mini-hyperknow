"""Exercise the actual owned backend lifecycle with model configuration disabled."""

import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urlsplit

from hyperknow_eval.cases import ROOT, load_suite
from hyperknow_eval.runner import run_trial
from hyperknow_eval.storage import load_trial, write_json


class ManagedRunnerTests(unittest.TestCase):
    def test_execute_authorization_and_simulator_configuration_precede_output_creation(self):
        _, cases = load_suite()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "trial"
            with self.assertRaisesRegex(ValueError, "--execute"):
                run_trial(cases[0], output)
            self.assertFalse(output.exists())
            case = next(case for case in cases if case["task"]["mode"] == "simulated")
            with self.assertRaisesRegex(ValueError, "student model"):
                run_trial(case, output, execute=True)
            self.assertFalse(output.exists())

    def test_actual_managed_backend_is_isolated_blocked_without_credentials_and_stopped(self):
        with tempfile.TemporaryDirectory(prefix="learning-runner-") as temporary:
            output = Path(temporary) / "trial"
            environment = {**os.environ, "OPENAI_API_KEY": "", "TAVILY_API_KEY": "", "EXA_API_KEY": "",
                           "PYTHON_DOTENV_DISABLED": "1", "PYTHONPATH": str(ROOT / "src")}
            script = ("from pathlib import Path; import sys; "
                      "from hyperknow_eval.cases import load_suite; "
                      "from hyperknow_eval.runner import run_trial; "
                      "run_trial(load_suite()[1][0], Path(sys.argv[1]), execute=True)")
            process = subprocess.run([sys.executable, "-c", script, str(output)], cwd=ROOT,
                                     env=environment, capture_output=True, timeout=45)
            self.assertEqual(process.returncode, 0, process.stderr.decode(errors="replace"))
            record = load_trial(output)
            self.assertEqual(record["status"], "blocked")
            self.assertEqual(record["actions"], [])
            self.assertEqual(record["model_requests"], [])
            self.assertEqual(record["subject"]["identity_source"], "managed-process-source-snapshot")
            self.assertNotEqual(record["subject"]["identity"], "unknown")
            self.assertTrue((output / "backend" / "hyperknow.sqlite3").is_file())
            self.assertTrue((output / "backend.log").is_file())
            endpoint = urlsplit(record["environment"]["base_url"])
            with socket.socket() as connection:
                connection.settimeout(1)
                self.assertNotEqual(connection.connect_ex((endpoint.hostname, endpoint.port)), 0)
            self.assertFalse((output / ".writer.lock").exists())

    def test_single_case_suite_keeps_the_explicit_external_backend(self):
        with tempfile.TemporaryDirectory(prefix="learning-external-suite-") as temporary:
            root = Path(temporary)
            write_json(root / "case.json", load_suite()[1][0])
            write_json(root / "suite.json", {"schema_version": 3, "id": "external-single", "revision": 1,
                       "purpose": "development", "cases": ["case.json"]})
            (root / "owned-server").mkdir()
            script = """from pathlib import Path
import sys
from hyperknow_eval.cli import main
from hyperknow_eval.runner import ManagedBackend
from hyperknow_eval.storage import load_trial
root = Path(sys.argv[1])
with ManagedBackend(root / 'owned-server') as backend:
    status = main(['run', '--suite', str(root / 'suite.json'), '--output', str(root / 'batch'),
                   '--base-url', backend.base_url, '--data-dir', str(backend.data_dir), '--execute'])
    record = load_trial(root / 'batch' / 'chain-rule-transfer' / 'r01')
    assert status == 2
    assert record['status'] == 'blocked'
    assert record['environment']['base_url'] == backend.base_url
    assert record['environment']['database'] == str((backend.data_dir / 'hyperknow.sqlite3').resolve())
    assert record['actions'] == []
"""
            environment = {**os.environ, "OPENAI_API_KEY": "", "TAVILY_API_KEY": "", "EXA_API_KEY": "",
                           "PYTHON_DOTENV_DISABLED": "1", "PYTHONPATH": str(ROOT / "src")}
            process = subprocess.run([sys.executable, "-c", script, str(root)], cwd=ROOT,
                                     env=environment, capture_output=True, timeout=45)
            self.assertEqual(process.returncode, 0, (process.stdout + process.stderr).decode(errors="replace"))
            self.assertFalse((root / "batch" / "chain-rule-transfer" / "r01" / "backend").exists())


if __name__ == "__main__":
    unittest.main()
