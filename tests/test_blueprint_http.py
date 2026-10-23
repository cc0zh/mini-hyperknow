"""Live HTTP/WS and real SQLite over explicit domain inputs, never a model stand-in."""

import json
from uuid import uuid4
import unittest

from websockets.sync.client import connect

import test_blueprint
import test_research_http


class BlueprintLiveServerTests(unittest.TestCase):
    model_configuration = ""
    setUpClass = classmethod(test_research_http.ResearchLiveServerTests.setUpClass.__func__)
    tearDownClass = classmethod(test_research_http.ResearchLiveServerTests.tearDownClass.__func__)

    def waiting(self):
        helper = test_blueprint.BlueprintStorageTests()
        helper.db = self.db
        return helper.awaiting("live-blueprint-" + uuid4().hex)

    def test_repeated_get_preserves_waiting_blueprint_without_model_calls(self):
        run = self.waiting()
        path = f"/api/runs/{run['run_id']}"
        course = self.db.get_course(run["course_id"])
        for _ in range(3):
            self.assertEqual(self.client.get(path).json(), run)
            self.assertEqual(self.client.get(f"/api/courses/{run['course_id']}").json(), course)
        self.assertEqual(self.db.calls(run["run_id"]), [])
        self.assertIsNone(course["progress"])
        self.assertEqual(course["next_item"]["run_id"], run["run_id"])

    def test_invalid_stale_and_unconfigured_approval_never_expand_units(self):
        run = self.waiting()
        path = f"/api/runs/{run['run_id']}/blueprint"
        base = {"client_command_id": "blueprint-" + uuid4().hex, "expected_version": run["version"], "approve": True}
        for patch in ({"approve": "true"}, {"approve": 1}, {"feedback": "x" * 6001},
                      {"expected_version": 0}, {"unknown": True}):
            response = self.client.post(path, json={**base, **patch})
            self.assertEqual(response.status_code, 422, response.text)
        response = self.client.post(path, json={**base, "expected_version": run["version"] - 1})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "version_conflict")
        response = self.client.post(path, json=base)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "model_not_configured")
        self.assertEqual(self.db.get_run(run["run_id"]), run)
        self.assertEqual(self.db.calls(run["run_id"]), [])

    def test_cancel_waiting_blueprint_notifies_run_and_course_and_is_idempotent(self):
        run = self.waiting()
        topics = [f"run:{run['run_id']}", f"course:{run['course_id']}"]
        with connect(f"ws://127.0.0.1:{self.port}/api/events", proxy=None) as socket:
            self.assertEqual(json.loads(socket.recv(timeout=3))["type"], "connected")
            for topic in topics:
                socket.send(json.dumps({"type": "subscribe", "topic": topic}))
                self.assertEqual(json.loads(socket.recv(timeout=3))["type"], "subscribed")
            body = {"client_command_id": "cancel-" + uuid4().hex, "expected_version": run["version"]}
            path = f"/api/runs/{run['run_id']}/cancel"
            response = self.client.post(path, json=body)
            self.assertEqual(response.status_code, 200, response.text)
            changes = [json.loads(socket.recv(timeout=3)) for _ in range(2)]
            self.assertEqual({entry["resource_type"] for entry in changes}, {"run", "course"})
            self.assertTrue(all(entry["type"] == "resource_changed" for entry in changes))
            self.assertEqual(self.client.post(path, json=body).json(), response.json())
        self.assertEqual(self.db.get_run(run["run_id"])["status"], "cancelled")
        course = self.db.get_course(run["course_id"])
        self.assertTrue(all(unit["generation_status"] == "cancelled" for unit in course["units"]))
        self.assertEqual(self.db.calls(run["run_id"]), [])
