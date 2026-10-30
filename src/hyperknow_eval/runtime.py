"""Single-send HTTP execution and read-only, content-addressed product evidence.

The caller owns the backend process.  Neither a terminal run nor a cancellation
is evidence that an already dispatched provider request has stopped costing money.
"""

from collections import defaultdict
from contextlib import closing, contextmanager
from copy import deepcopy
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import socket
import sqlite3
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

from .schema import Budget
from .storage import add_evidence, artifact_path, digest, encode, utcnow


ROOT = Path(__file__).resolve().parents[2]
TABLE_KINDS = {
    "runs": "run", "courses": "course", "lesson_scripts": "lesson_script",
    "lesson_states": "lesson_state", "lesson_interactions": "lesson_interaction",
    "activity_progress": "activity_progress", "quizzes": "quiz",
    "quiz_states": "quiz_state", "quiz_attempts": "quiz_attempt",
    "assistance_conversations": "conversation", "assistance_artifacts": "artifact",
}
TABLES = set(TABLE_KINDS) | {"command_receipts", "model_calls"}
RUN_STATES = {"queued", "clarifying", "generating", "awaiting_answers", "awaiting_blueprint",
              "ready", "failed", "cancelled", "interrupted"}
RUN_BOUNDARIES = {"awaiting_answers", "awaiting_blueprint", "ready", "failed", "cancelled", "interrupted"}


class RuntimeFailure(RuntimeError):
    """A safe error code, never an arbitrary provider/transport exception message."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # A redirect must never move a command, even to another local backend.


def local_origin(value: str) -> str:
    """Resolve localhost once, check *all* results and pin a numeric loopback."""
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
                or any(char.isspace() for char in value) or "\\" in value):
            raise ValueError
        host = parsed.hostname
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
        if not 1 <= port <= 65535 or "%" in host:
            raise ValueError
        if host == "localhost":
            addresses = {item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
            if not addresses or not all(ipaddress.ip_address(item).is_loopback for item in addresses):
                raise ValueError
            host = "127.0.0.1" if "127.0.0.1" in addresses else sorted(addresses)[0]
        elif not ipaddress.ip_address(host).is_loopback:
            raise ValueError
        host = f"[{host}]" if ":" in host else host
        return f"{parsed.scheme}://{host}:{port}"
    except (ValueError, OSError):
        raise RuntimeFailure("non_loopback_origin") from None


@contextmanager
def readonly(path: Path):
    """Do not instantiate the product Database: even its reads acquire write locks."""
    path = artifact_path(path)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        yield connection


class Runtime:
    def __init__(self, base_url: str, data_dir: Path, record: dict, checkpoint: Callable[[], None]):
        self.base_url = base_url
        self.data_dir = artifact_path(data_dir)
        self.record, self.checkpoint = record, checkpoint
        self.budget = Budget.model_validate(record.get("case", {}).get("budget", {})).model_dump()
        self.started = time.monotonic()
        self.deadline = self.started + self.budget["timeout_seconds"]
        self.database: Path | None = None
        self.storage_id: str | None = None
        self._file_identity: tuple[int, int] | None = None
        self._ready = False
        self._health: dict = {}
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())
        self._frozen: dict[str, tuple[str, str]] = {}
        self._observed_calls = 0
        self._writes_stopped = any(action.get("status") in {"in_flight", "submission_unknown"}
                                   for action in record["actions"])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if isinstance(exc, RuntimeFailure) and self.record["error"] is None:
            self.failure(exc.code, exception=exc)
        elif exc is not None and not isinstance(exc, RuntimeFailure):
            self.failure("execution_failed", exception=exc)
        try:
            if self.database is not None and self._file_identity is not None:
                self.collect(enforce_budget=False)
        except Exception as collection_error:
            self.check("final_collection", False, {"error_type": type(collection_error).__name__})
            if exc is None and not self.record.get("error"):
                self.failure("evidence_collection_failed", exception=collection_error)
        self.record["environment"]["remote_cost_status"] = "unknown"
        self.check("remote_cost_finished", None, {
            "reason": "Local state cannot prove completion or cancellation of remote charges; "
                      "no cleanup write or command replay was sent."}, category="billing_observation")
        self.checkpoint()
        return False

    def set_budget(self, budget: dict) -> None:
        fixed = Budget.model_validate(budget).model_dump()
        # A public case may tighten but cannot extend a trial's existing budget.
        self.budget = {key: min(value, self.budget[key]) for key, value in fixed.items()}
        self.deadline = self.started + self.budget["timeout_seconds"]
        self.record["environment"]["execution_budget"] = deepcopy(self.budget)
        self.record["environment"]["max_actions_scope"] = "write_commands_only"
        self.record["environment"]["observed_calls_scope"] = "persisted_product_calls_only_not_a_dispatch_cap"
        self.checkpoint()

    def check(self, name: str, passed: bool | None, details: dict | None = None,
              evidence_ids: list[str] | None = None, *, category: str = "engineering") -> None:
        self.record["checks"].append({"id": name, "passed": passed,
                                      "category": category,
                                      "status": "unknown" if passed is None else "passed" if passed else "failed",
                                      "details": deepcopy(details or {}),
                                      "evidence_ids": list(evidence_ids or []), "at": utcnow()})
        self.checkpoint()

    def failure(self, code: str, *, status: str = "failed", exception: BaseException | None = None,
                details: dict | None = None) -> RuntimeFailure:
        self.record["status"] = status
        self.record["error"] = {"code": code, "type": type(exception).__name__ if exception else "RuntimeFailure",
                                **(details or {})}
        self.record["checks"].append({"id": "execution_" + code, "passed": False, "status": "failed",
                                      "details": deepcopy(self.record["error"]), "evidence_ids": [], "at": utcnow()})
        self.checkpoint()
        return RuntimeFailure(code)

    def remaining(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            self._writes_stopped = True
            raise self.failure("trial_timeout", status="timed_out")
        return remaining

    def freeze(self, kind: str, content, source: dict) -> str:
        """Save changed observations, not an unbounded journal of identical polls."""
        key, fingerprint = encode({"kind": kind, "source": source}), digest(content)
        previous = self._frozen.get(key)
        if previous and previous[0] == fingerprint:
            return previous[1]
        identity = add_evidence(self.record, kind, content, source)
        self._frozen[key] = fingerprint, identity
        self.checkpoint()
        return identity

    def transcript(self, role: str, text: str, evidence_id: str, **identities) -> None:
        if role not in {"student", "tutor"} or not isinstance(text, str):
            raise self.failure("invalid_transcript")
        if evidence_id not in {item["id"] for item in self.record["evidence"]}:
            raise self.failure("missing_transcript_evidence")
        # Collection may observe a committed answer before the HTTP wait returns,
        # or salvage it after a budget/transport stop. Keep exactly one tutor turn.
        if role == "tutor" and identities.get("run_id"):
            previous = next((turn for turn in self.record["transcript"]
                             if turn["role"] == role and turn.get("run_id") == identities["run_id"]), None)
            if previous:
                if previous["text"] != text:
                    raise self.failure("saved_tutor_transcript_changed")
                return
        self.record["transcript"].append({"role": role, "text": text, "evidence_id": evidence_id, **identities})
        self.checkpoint()

    def _database_path(self) -> Path:
        path = (self.data_dir.resolve() / "hyperknow.sqlite3").resolve()
        protected = {(ROOT / "data" / "hyperknow.sqlite3").resolve()}
        configured = os.environ.get("HK_DATA_DIR", "").strip()
        if configured:
            protected.add((Path(configured).resolve() / "hyperknow.sqlite3").resolve())
        if any(path == item or (path.exists() and item.exists() and path.samefile(item)) for item in protected):
            raise self.failure("protected_database", status="blocked")
        if not path.is_file():
            raise self.failure("database_missing", status="blocked")
        return path

    def _assert_file(self) -> None:
        path = self._database_path()
        stat = path.stat()
        if path != self.database or (stat.st_dev, stat.st_ino) != self._file_identity:
            self._writes_stopped = True
            raise self.failure("database_identity_changed", status="blocked")

    def preflight(self) -> dict:
        if self._ready:
            return deepcopy(self._health)
        try:
            self.remaining()
            self.base_url = local_origin(self.base_url)
            path = self._database_path()
            with readonly(path) as connection:
                tables = {row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
                if not TABLES <= tables or connection.execute("PRAGMA user_version").fetchone()[0] != 3:
                    raise self.failure("unsupported_database_schema", status="blocked")
                # Include unfamiliar tables: an occupied extension table is not an empty trial.
                occupied = [table for table in sorted(tables) if connection.execute(
                    'SELECT 1 FROM "' + table.replace('"', '""') + '" LIMIT 1').fetchone() is not None]
                if occupied:
                    raise self.failure("database_not_empty", status="blocked", details={"tables": occupied})
            stat = path.stat()
            self.database, self._file_identity = path, (stat.st_dev, stat.st_ino)
            self.storage_id = hashlib.sha256(str(path).encode("utf-8")).hexdigest()
            self.record["environment"].update({
                "base_url": self.base_url, "database": str(path), "storage_id": self.storage_id,
                "database_file": {"device": stat.st_dev, "inode": stat.st_ino},
                "python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
                "remote_cost_status": "unknown",
                "isolation_limit": "Path/file identity prevents accidental misconnection, not concurrent writers or rollback.",
            })
            self.checkpoint()
            health = self.get("/api/health")
            evidence_id = self.freeze("health", health, {"transport": "http", "path": "/api/health"})
            model = health.get("model") if isinstance(health.get("model"), dict) else {}
            self.record["subject"] = {"identity": "unknown", "backend_build": "unknown",
                                      "model": model.get("name") or "unknown",
                                      "model_configured": model.get("configured") is True,
                                      "model_verified": model.get("verified") is True}
            self.checkpoint()
            if health.get("storage_id") != self.storage_id:
                self.check("storage_binding", False, evidence_ids=[evidence_id])
                raise self.failure("storage_identity_mismatch", status="blocked")
            if health.get("status") != "ok" or health.get("database") != "ok":
                raise self.failure("backend_unhealthy", status="blocked")
            self.check("storage_binding", True, evidence_ids=[evidence_id])
            self.check("initial_database_empty", True)
            if model.get("configured") is not True:
                self.check("model_configured", False, evidence_ids=[evidence_id])
                raise self.failure("model_not_configured", status="blocked")
            self._health = deepcopy(health)
            self._ready = True
            self.check("model_configured", True, evidence_ids=[evidence_id])
            return deepcopy(health)
        except RuntimeFailure as exc:
            if self.record["error"] is None:
                self.failure(exc.code, status="blocked", exception=exc)
            raise
        except Exception as exc:
            raise self.failure("preflight_failed", status="blocked", exception=exc) from None

    def require_search(self) -> None:
        if self._health.get("search", {}).get("configured") is not True:
            raise self.failure("search_not_configured", status="blocked")

    @staticmethod
    def _path(path: str) -> str:
        parsed = urlsplit(path)
        if (not path.startswith("/api/") or parsed.scheme or parsed.netloc or parsed.query or parsed.fragment
                or "\\" in path or "%" in path or "//" in path
                or any(part in {".", ".."} for part in path.split("/"))
                or any(char.isspace() for char in path)):
            raise RuntimeFailure("invalid_api_path")
        return path

    def _send(self, method: str, path: str, body: dict | None = None) -> dict:
        """Transport protocol; public writes additionally enforce preflight and budgets."""
        try:
            path = self._path(path)
            self.base_url = local_origin(self.base_url)
        except RuntimeFailure as exc:
            raise self.failure(exc.code, status="blocked", exception=exc) from None
        headers = {"Accept": "application/json"}
        action = None
        payload = None
        if method != "GET":
            self.remaining()
            if method not in {"POST", "PUT"} or not isinstance(body, dict):
                raise self.failure("invalid_write_request")
            body = deepcopy(body)
            command_id = body.setdefault("client_command_id", f"eval-{uuid4().hex}")
            if not isinstance(command_id, str) or not 8 <= len(command_id) <= 120:
                raise self.failure("invalid_command_id")
            if any(item.get("command_id") == command_id for item in self.record["actions"]):
                raise self.failure("command_replay_forbidden", status="blocked")
            if self._writes_stopped or any(item.get("status") in {"in_flight", "submission_unknown"}
                                            for item in self.record["actions"]):
                raise self.failure("writes_stopped", status="blocked")
            if len(self.record["actions"]) >= self.budget["max_actions"]:
                self._writes_stopped = True
                raise self.failure("max_actions_exceeded", status="budget_exceeded")
            headers["Content-Type"] = "application/json"
            serialized = encode(body)
            payload = serialized.encode("utf-8")
            action = {"command_id": command_id, "status": "in_flight", "started_at": utcnow(),
                      "request": {"method": method, "url": self.base_url + path, "path": path,
                                  "headers": deepcopy(headers), "body": body, "body_text": serialized},
                      "response": None, "error": None}
            self.record["actions"].append(action)
            self.checkpoint()  # May fail: in that case absolutely no HTTP command is sent.
        try:
            request = Request(self.base_url + path, data=payload, headers=headers, method=method)
            try:
                response = self._opener.open(request, timeout=min(15, self.remaining()))
            except HTTPError as exc:
                response = exc  # Do not replay, including 307/308 and a post-commit 5xx.
            with response:
                status = response.code
                reader = response.fp if isinstance(response, HTTPError) else response
                chunks, size = [], 0
                while True:
                    # read(n) can silently reset its timeout on every received byte.
                    # read1 performs at most one receive; recheck the trial deadline.
                    remaining = self.remaining()
                    stream = reader.fp
                    transport = getattr(getattr(stream, "raw", None), "_sock", None)
                    if transport is not None:
                        transport.settimeout(min(15, remaining))
                    chunk = reader.read1(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > 32 * 1024 * 1024:
                        raise RuntimeFailure("response_too_large")
                    chunks.append(chunk)
                raw = b"".join(chunks)
            result = json.loads(raw.decode("utf-8"))
            if not isinstance(result, dict):
                raise RuntimeFailure("invalid_http_response")
            if action is not None:
                action["response"] = {"http_status": status, "body": deepcopy(result)}
                action["status"] = "completed" if 200 <= status < 300 else "rejected" if 400 <= status < 500 else "submission_unknown"
                action["finished_at"] = utcnow()
                self.checkpoint()
            if not 200 <= status < 300:
                error = result.get("error", {})
                code = error.get("code", "") if isinstance(error, dict) else ""
                details = {"http_status": status}
                if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code):
                    details["api_code"] = code
                if action is not None and action["status"] == "submission_unknown":
                    self._writes_stopped = True
                raise self.failure("http_error", details=details)
            self.remaining()
            return result
        except Exception as exc:
            if action is not None:
                if action["status"] == "in_flight":
                    action["status"] = "submission_unknown"
                    self._writes_stopped = True
                action["error"] = {"type": type(exc).__name__,
                                   "code": exc.code if isinstance(exc, RuntimeFailure) else "transport_failed"}
                action["finished_at"] = utcnow()
                self.checkpoint()
            if isinstance(exc, RuntimeFailure):
                if self.record["error"] is None:
                    self.failure(exc.code, exception=exc)
                raise
            error_type = type(exc.reason).__name__ if isinstance(exc, URLError) else type(exc).__name__
            raise self.failure("transport_failed", exception=exc, details={"transport_type": error_type}) from None

    def get(self, path: str) -> dict:
        return self._send("GET", path)

    def _write(self, method: str, path: str, body: dict) -> dict:
        if not self._ready:
            raise self.failure("preflight_required", status="blocked")
        self.remaining()
        self._assert_file()
        if self.get("/api/health").get("storage_id") != self.storage_id:
            raise self.failure("storage_identity_mismatch", status="blocked")
        self.collect()
        result = self._send(method, path, body)
        self.collect()
        return result

    def post(self, path: str, body: dict) -> dict:
        return self._write("POST", path, body)

    def put(self, path: str, body: dict) -> dict:
        return self._write("PUT", path, body)

    def wait_run(self, run_id: str) -> dict:
        """Stop at user-decision boundaries as well as terminal states; never retry."""
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", run_id):
            raise self.failure("invalid_run_id")
        while True:
            run = self.get(f"/api/runs/{run_id}")
            if (run.get("run_id") != run_id or run.get("status") not in RUN_STATES
                    or type(run.get("version")) is not int or run["version"] < 1):
                raise self.failure("invalid_run_snapshot")
            self.freeze("run", run, {"transport": "http", "path": f"/api/runs/{run_id}", "run_id": run_id})
            self.collect()
            if run["status"] in RUN_BOUNDARIES:
                return run
            time.sleep(min(0.25, self.remaining()))

    def collect(self, *, enforce_budget: bool = True) -> list[str]:
        """Freeze a consistent read-only SQLite observation, including real call records."""
        if self.database is None or self._file_identity is None:
            return []
        self._assert_file()
        captured = []
        with readonly(self.database) as connection:
            contents = {table: [dict(row) for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
                        for table in sorted(TABLES)}
        for table, kind in TABLE_KINDS.items():
            for row in contents[table]:
                content = json.loads(row["data"])
                source = {"transport": "sqlite", "storage_id": self.storage_id, "table": table, "record_id": row["id"]}
                if table == "runs":
                    source["run_id"] = row["id"]
                    if row["id"] not in self.record["business_runs"]:
                        self.record["business_runs"].append(row["id"])
                        self.checkpoint()
                identity = self.freeze(kind, content, source)
                captured.append(identity)
                if table == "assistance_conversations":
                    for index, turn in enumerate(content["turns"]):
                        if turn["status"] not in {"ready", "failed", "cancelled", "interrupted"}:
                            continue
                        saved_turn = self.freeze("tutor_turn", turn, {
                            "transport": "sqlite", "storage_id": self.storage_id,
                            "conversation_id": content["conversation_id"], "turn_id": turn["turn_id"],
                            "run_id": turn["run_id"]})
                        captured.append(saved_turn)
                        self.transcript("tutor", (turn.get("response") or {}).get("text", ""), saved_turn,
                                        conversation_id=content["conversation_id"], turn_id=turn["turn_id"],
                                        run_id=turn["run_id"], turn_index=index)
                elif table == "lesson_interactions" and content["status"] in {"ready", "failed", "cancelled", "interrupted"}:
                    self.transcript("tutor", content.get("answer") or "", identity,
                                    session_id=row["session_id"], run_id=content["run_id"])
        for row in contents["command_receipts"]:
            captured.append(self.freeze("command_receipt", row, {"transport": "sqlite", "storage_id": self.storage_id,
                                                                  "command_id": row["id"]}))
        calls = defaultdict(list)
        for row in contents["runs"]:
            calls[row["id"]]  # An empty list is evidence of no *persisted* calls, not zero cost.
        for row in contents["model_calls"]:
            calls[row["run_id"]].append((row["id"], json.loads(row["data"])))
        requests = []
        for run_id, rows in calls.items():
            identity = self.freeze("model_calls", [content for _, content in rows],
                                   {"transport": "sqlite", "storage_id": self.storage_id, "run_id": run_id})
            captured.append(identity)
            for call_id, content in rows:
                requests.append({**deepcopy(content), "role": "business", "call_id": call_id,
                                 "run_id": run_id, "evidence_id": identity})
        self.record["model_requests"] = [item for item in self.record["model_requests"] if item.get("role") != "business"] + requests
        self._observed_calls = len(requests)
        self.record["environment"]["observed_product_calls"] = self._observed_calls
        self.checkpoint()
        if self._observed_calls > self.budget["max_observed_calls"]:
            self._writes_stopped = True
            if not any(check["id"] == "max_observed_calls" for check in self.record["checks"]):
                self.check("max_observed_calls", False, {
                    "observed": self._observed_calls, "limit": self.budget["max_observed_calls"],
                    "limitation": "Observation only: cannot undo or count unpersisted/dispatched provider requests."})
            if enforce_budget:
                raise self.failure("max_observed_calls_exceeded", status="budget_exceeded")
            if self.record["status"] in {"running", "completed"}:
                self.failure("max_observed_calls_exceeded", status="budget_exceeded")
        if enforce_budget:
            self.remaining()
        return captured
