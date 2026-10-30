"""Actual HTTP transport refusals, not fabricated successful model responses."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest

from hyperknow_eval.cases import load_suite
from hyperknow_eval.judging import ModelSettings, judge_trial, output_budget_exceeded, student_reply
from hyperknow_eval.storage import add_evidence, load_trial, new_trial, save_trial


class RefusalHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.server.requests.append(self.path)
        self.send_response(self.server.refusal_status)
        self.send_header("Location", "/must-not-follow")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_POST

    def log_message(self, *_):
        pass


class EvaluatorTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), RefusalHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def test_sdk_neither_follows_redirects_nor_retries_refusals(self):
        case = load_suite()[1][0]
        settings = ModelSettings(model="local-transport-boundary", api_key="local-transport-boundary-credential",
                                 base_url=f"http://127.0.0.1:{self.server.server_port}/v1",
                                 context_budget=96000)
        for status in (301, 302, 303, 307, 308, 429, 500, 503):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temporary:
                self.server.requests = []
                self.server.refusal_status = status
                directory = Path(temporary) / "trial"
                record = new_trial(directory, case)
                add_evidence(record, "output", "Transport-only test, not a teaching response.", {})
                attempt = judge_trial(record, settings, lambda: save_trial(directory, record), execute=True)
                self.assertEqual(self.server.requests, ["/v1/chat/completions"])
                self.assertEqual(attempt["status"], "error")
                self.assertEqual(attempt["raw_response"]["http_status"], status)
                self.assertIsNone(attempt["usage"])
                self.assertTrue(all(item["verdict"] == "insufficient" for item in attempt["results"]))
                self.assertEqual(load_trial(directory)["judgments"][-1]["raw_response"], attempt["raw_response"])

    def test_student_redirect_is_also_one_request_and_no_fallback(self):
        self.server.requests = []
        self.server.refusal_status = 307
        case = next(case for case in load_suite()[1] if case["task"]["mode"] == "simulated")
        settings = ModelSettings(model="local-transport-boundary", api_key="local-transport-boundary-credential",
                                 base_url=f"http://127.0.0.1:{self.server.server_port}/v1", context_budget=96000)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "trial"
            record = new_trial(directory, case)
            record["transcript"] = [{"role": "student", "text": case["task"]["opening"]},
                                    {"role": "tutor", "text": "Transport-only boundary text."}]
            with self.assertRaisesRegex(RuntimeError, "transport failed"):
                student_reply(record, settings, lambda: save_trial(directory, record), execute=True)
            self.assertEqual(self.server.requests, ["/v1/chat/completions"])
            self.assertEqual(record["model_requests"][-1]["status"], "error")

    def test_known_output_violation_halts_but_unknown_usage_is_not_invented(self):
        for role in ("model_requests", "judgments"):
            self.assertTrue(output_budget_exceeded({role: [{"budget_check": {"status": "exceeded"}}]}))
        for status in ("unknown", "not_requested", "within_reported_usage"):
            self.assertFalse(output_budget_exceeded({"judgments": [{"budget_check": {"status": status}}]}))
        self.assertFalse(output_budget_exceeded({}))


if __name__ == "__main__":
    unittest.main()
