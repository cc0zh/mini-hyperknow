"""Actual local HTTP/WebSocket transport and SQLite, without model substitution.

Completed content is written through real storage transactions to exercise reads
and commands. These tests do not claim successful provider generation.
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
from uuid import uuid4

import httpx
from websockets.sync.client import connect

from hyperknow.storage import Database
from tests.test_assistance_storage import board_draft, response_result


class AssistanceHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="hyperknow-assistance-http-")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        env = {**os.environ, "HK_DATA_DIR": cls.directory.name,
               "OPENAI_API_KEY": "", "TAVILY_API_KEY": ""}
        cls.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "hyperknow.main:app", "--host", "127.0.0.1",
             "--port", str(cls.port), "--log-level", "warning"],
            cwd=Path(__file__).resolve().parents[1], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.client = httpx.Client(base_url=f"http://127.0.0.1:{cls.port}", trust_env=False, timeout=5)
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if cls.process.poll() is not None:
                    raise RuntimeError("real assistance HTTP server exited before startup")
                try:
                    if cls.client.get("/api/health").status_code == 200:
                        cls.db = Database(Path(cls.directory.name) / "hyperknow.sqlite3")
                        return
                except httpx.TransportError:
                    pass
                time.sleep(0.05)
            raise RuntimeError("real assistance HTTP server did not start")
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

    def command(self):
        return f"assistance-http-{uuid4().hex}"

    def create(self):
        command_id = self.command()
        response = self.client.post("/api/assistance/conversations", json={"client_command_id": command_id})
        self.assertEqual(response.status_code, 200)
        return response.json(), command_id

    def queued(self, conversation, **changes):
        body = {"client_command_id": self.command(), "expected_version": conversation["version"],
                "text": "用白板分步讲清二分", "action": "message", "skill_hint": "auto", "artifact_id": None,
                **changes}
        snapshot = self.db.assistance_turn(conversation["conversation_id"], body, "saved-model", True, {})
        return snapshot, body

    def board(self):
        conversation, _ = self.create()
        queued, body = self.queued(conversation)
        run_id = queued["active_run"]["run_id"]
        self.db.transition(run_id, {"queued"}, status="generating")
        self.db.finish_assistance(run_id, response_result(board_draft()))
        snapshot = self.db.get_assistance_conversation(conversation["conversation_id"])
        return snapshot, snapshot["turns"][-1]["artifacts"][0], body

    def subscribe(self, ws, topic):
        ws.send(json.dumps({"type": "subscribe", "topic": topic}))
        self.assertEqual(json.loads(ws.recv(timeout=3)), {"type": "subscribed", "topic": topic})

    def test_creation_listing_and_idempotent_replay_need_no_credentials(self):
        conversation, command_id = self.create()
        self.assertIsNone(conversation["active_run"])
        self.assertEqual(conversation["turns"], [])
        replay = self.client.post("/api/assistance/conversations", json={"client_command_id": command_id})
        self.assertEqual(replay.json(), conversation)
        self.assertEqual(self.client.get(f"/api/assistance/conversations/{conversation['conversation_id']}").json(),
                         conversation)
        listing = self.client.get("/api/assistance/conversations").json()["conversations"]
        summary = next(c for c in listing if c["conversation_id"] == conversation["conversation_id"])
        self.assertNotIn("turns", summary)
        self.assertEqual(summary["title"], conversation["title"])
        self.assertEqual(self.client.get("/api/assistance/conversations/missing").status_code, 404)

    def test_missing_model_does_not_create_a_run_or_turn_and_validation_is_explicit(self):
        conversation, _ = self.create()
        path = f"/api/assistance/conversations/{conversation['conversation_id']}/turns"
        body = {"client_command_id": self.command(), "expected_version": 1, "text": "解释极限",
                "action": "message", "skill_hint": "auto"}
        response = self.client.post(path, json=body)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "model_not_configured")
        self.assertEqual(self.client.get(f"/api/assistance/conversations/{conversation['conversation_id']}").json(),
                         conversation)
        for patch in ({"action": "execute"}, {"action": "flashcards"}, {"action": "whiteboard"},
                      {"skill_hint": "arbitrary-file"}, {"expected_version": True},
                      {"text": "x" * 12001}, {"text": "  "}, {"unknown": "reject"},
                      {"action": "continue", "artifact_id": "board"}):
            self.assertEqual(self.client.post(path, json={**body, **patch}).status_code, 422)

    def test_shared_worker_dispatches_assistance_and_records_real_unconfigured_failure(self):
        from hyperknow.assistance_generation import build_skill_snapshots
        conversation, _ = self.create()
        body = {"client_command_id": self.command(), "expected_version": conversation["version"],
                "text": "解释迭代器", "action": "message", "skill_hint": "auto", "artifact_id": None}
        # Seed an actual queued run, then replay its command through the real
        # service. The child process has an explicitly empty API key: provider
        # initialization fails locally and cannot make a paid model request.
        queued = self.db.assistance_turn(conversation["conversation_id"], body, "saved-model", True,
                                         build_skill_snapshots)
        path = f"/api/assistance/conversations/{conversation['conversation_id']}"
        accepted = self.client.post(f"{path}/turns", json=body)
        self.assertEqual(accepted.status_code, 202)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            saved = self.client.get(path).json()
            if saved["turns"][0]["status"] == "failed":
                break
            time.sleep(0.02)
        self.assertEqual(saved["turns"][0]["status"], "failed")
        self.assertIsNone(saved["active_run"])
        self.assertIsNone(saved["turns"][0]["response"])
        self.assertEqual(saved["turns"][0]["artifacts"], [])
        self.assertEqual(self.db.calls(queued["active_run"]["run_id"]), [])

    def test_persisted_turn_receipt_replays_202_without_another_provider_call(self):
        conversation, artifact, body = self.board()
        path = f"/api/assistance/conversations/{conversation['conversation_id']}/turns"
        for _ in range(2):
            response = self.client.post(path, json=body)
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json(), conversation)
        run_id = conversation["turns"][0]["run_id"]
        self.assertEqual(self.db.calls(run_id), [])
        self.assertEqual(self.client.get(f"/api/assistance/artifacts/{artifact['artifact_id']}").json(), artifact)
        self.assertEqual(self.client.post(path, json={**body, "text": "changed"}).status_code, 409)
        self.assertEqual(self.client.get("/api/assistance/artifacts/missing").status_code, 404)

    def test_actual_websocket_cancel_updates_conversation_and_missing_key_retry_is_atomic(self):
        conversation, _ = self.create()
        queued, _ = self.queued(conversation, action="message")
        run = queued["active_run"]
        with connect(f"ws://127.0.0.1:{self.port}/api/events", proxy=None) as ws:
            self.assertEqual(json.loads(ws.recv(timeout=3))["type"], "connected")
            self.subscribe(ws, f"conversation:{conversation['conversation_id']}")
            response = self.client.post(f"/api/runs/{run['run_id']}/cancel", json={
                "client_command_id": self.command(), "expected_version": run["version"]})
            self.assertEqual(response.status_code, 200)
            cancelled = response.json()
            event = json.loads(ws.recv(timeout=3))
            saved = self.client.get(f"/api/assistance/conversations/{conversation['conversation_id']}").json()
            self.assertEqual(event["type"], "resource_changed")
            self.assertEqual(event["resource_type"], "conversation")
            self.assertEqual(event["version"], saved["version"])
            self.assertEqual(saved["turns"][0]["status"], "cancelled")
            self.assertIsNone(saved["active_run"])
            retry = self.client.post(f"/api/runs/{run['run_id']}/retry", json={
                "client_command_id": self.command(), "expected_version": cancelled["version"]})
            self.assertEqual(retry.status_code, 503)
            self.assertEqual(retry.json()["error"]["code"], "model_not_configured")
            self.assertEqual(self.db.get_assistance_conversation(conversation["conversation_id"]), saved)

    def test_actual_websocket_artifact_progress_version_and_pending_question(self):
        conversation, artifact, _ = self.board()
        aid = artifact["artifact_id"]
        path = f"/api/assistance/artifacts/{aid}/progress"
        with connect(f"ws://127.0.0.1:{self.port}/api/events", proxy=None) as ws:
            self.assertEqual(json.loads(ws.recv(timeout=3))["type"], "connected")
            self.subscribe(ws, f"artifact:{aid}")
            body = {"client_command_id": self.command(), "expected_version": 1, "cursor": 0}
            response = self.client.put(path, json=body)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["version"], 2)
            event = json.loads(ws.recv(timeout=3))
            self.assertEqual(event, {"type": "resource_changed", "resource_type": "artifact",
                                     "resource_id": aid, "version": 2})
            self.assertEqual(self.client.put(path, json=body).json(), response.json())
            ws.recv(timeout=3)  # A command replay may publish the current snapshot again.
            stale = self.client.put(path, json={**body, "client_command_id": self.command(), "cursor": 1})
            self.assertEqual(stale.status_code, 409)
            self.assertEqual(stale.json()["error"]["latest_version"], 2)
            saved = self.db.get_assistance_conversation(conversation["conversation_id"])
            self.queued(saved, text="为什么成立？", action="message", artifact_id=aid)
            pending = self.client.put(path, json={"client_command_id": self.command(),
                                                   "expected_version": 2, "cursor": 1})
            self.assertEqual(pending.status_code, 409)
            self.assertEqual(pending.json()["error"]["code"], "question_active")
            self.assertEqual(self.db.get_assistance_artifact(aid)["data"]["cursor"], 0)
        for patch in ({"cursor": -2}, {"cursor": True}, {"expected_version": 0}, {"extra": "reject"}):
            self.assertEqual(self.client.put(path, json={"client_command_id": self.command(),
                "expected_version": 2, "cursor": 0, **patch}).status_code, 422)

    def test_websocket_rejects_missing_assistance_resources_and_still_pings(self):
        with connect(f"ws://127.0.0.1:{self.port}/api/events", proxy=None) as ws:
            self.assertEqual(json.loads(ws.recv(timeout=3))["type"], "connected")
            for topic in ("conversation:missing", "artifact:missing"):
                ws.send(json.dumps({"type": "subscribe", "topic": topic}))
                self.assertEqual(json.loads(ws.recv(timeout=3))["type"], "error")
            ws.send(json.dumps({"type": "ping"}))
            self.assertEqual(json.loads(ws.recv(timeout=3))["type"], "pong")
