"""Real HTTP and WS server with missing credentials; no model substitution.

This intentionally tests the unconfigured path, NOT successful model generation.
"""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import httpx
from websockets.sync.client import connect


class LiveLocalServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="hyperknow-http-")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        cls.url = f"http://127.0.0.1:{cls.port}"
        env = {**os.environ, "OPENAI_API_KEY": "", "HK_DATA_DIR": cls.directory.name}
        cls.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "hyperknow.main:app", "--host", "127.0.0.1",
             "--port", str(cls.port), "--log-level", "warning"],
            cwd=Path(__file__).resolve().parents[1], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        cls.client = httpx.Client(base_url=cls.url, trust_env=False, timeout=5)
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if cls.process.poll() is not None:
                    raise RuntimeError("real local server exited before startup")
                try:
                    if cls.client.get("/api/health").status_code == 200:
                        return
                except httpx.TransportError:
                    pass
                time.sleep(0.05)
            raise RuntimeError("real local server did not start")
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.process.terminate()
        try:
            cls.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait(timeout=5)
        cls.directory.cleanup()

    def test_health_distinguishes_configuration_from_connectivity(self):
        data = self.client.get("/api/health").json()
        self.assertEqual(data["database"], "ok")
        self.assertFalse(data["model"]["configured"])
        self.assertFalse(data["model"]["verified"])

    def test_missing_key_is_real_error_not_fake_course(self):
        response = self.client.post("/api/course-runs", json={
            "goal": "学习 Python asyncio", "client_command_id": "missing-model-command"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "model_not_configured")
        self.assertEqual(self.client.get("/api/courses").json(), {"courses": []})
        self.assertEqual(self.client.get("/api/runs").json(), {"runs": []})

    def test_invalid_input_and_unknown_routes_are_not_success(self):
        response = self.client.post("/api/course-runs", json={"goal": " ", "client_command_id": "invalid-input-command"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get("/api/runs/missing").status_code, 404)
        self.assertEqual(self.client.get("/api/not-implemented").status_code, 404)

    def test_actual_websocket_connection_and_unknown_subscription(self):
        with connect(f"ws://127.0.0.1:{self.port}/api/events", proxy=None) as ws:
            self.assertEqual(json.loads(ws.recv())["type"], "connected")
            ws.send(json.dumps({"type": "subscribe", "topic": "run:missing"}))
            self.assertEqual(json.loads(ws.recv())["type"], "error")
            ws.send(json.dumps({"type": "ping"}))
            self.assertEqual(json.loads(ws.recv())["type"], "pong")
