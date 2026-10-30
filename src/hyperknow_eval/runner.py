"""One isolated backend per trial. No implicit replay, retry or model fallback."""

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx

from .cases import ROOT
from .schema import public_case
from .storage import artifact_path, exclusive, new_trial, save_trial, utcnow


def private_path(path: Path) -> Path:
    resolved = artifact_path(path)
    if resolved.is_relative_to(ROOT) and not any(
            resolved.is_relative_to(ROOT / folder) for folder in ("data", "eval_result")):
        raise ValueError("private evaluation output inside the repository must be under data/ or eval_result/")
    return resolved


def source_snapshot() -> str:
    """Identity of sources actually launched by this managed process, not Git HEAD."""
    hasher = hashlib.sha256()
    paths = [ROOT / "uv.lock"]
    for folder in ("agent_core", "hyperknow"):
        paths.extend(path for path in (ROOT / "src" / folder).rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts and path.suffix in {".py", ".md", ".txt"})
    for path in sorted(paths):
        hasher.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


class ManagedBackend:
    """Starts real Uvicorn; logs and SQLite live only in the new trial directory."""

    def __init__(self, output: Path):
        self.output = artifact_path(output)
        self.data_dir = self.output / "backend"
        self.base_url = None
        self.process = None
        self.log = None
        self.source_hash = None

    def __enter__(self):
        if self.data_dir.exists():
            raise ValueError("managed backend requires a fresh data directory")
        self.data_dir.mkdir()
        self.source_hash = source_snapshot()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        self.base_url = f"http://127.0.0.1:{port}"
        environment = os.environ.copy()
        environment["HK_DATA_DIR"] = str(self.data_dir)
        self.log = (self.output / "backend.log").open("x", encoding="utf-8")
        try:
            self.process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "hyperknow.main:app", "--host", "127.0.0.1",
                 "--port", str(port), "--no-access-log"], cwd=ROOT, env=environment,
                stdout=self.log, stderr=subprocess.STDOUT,
            )
            deadline = time.monotonic() + 30
            with httpx.Client(trust_env=False, timeout=1, follow_redirects=False) as client:
                while time.monotonic() < deadline:
                    if self.process.poll() is not None:
                        raise ValueError("managed backend exited before health; inspect the private backend.log")
                    try:
                        response = client.get(self.base_url + "/api/health")
                        if response.status_code == 200:
                            return self
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
            raise ValueError("managed backend health timed out")
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        if self.process is not None and self.process.poll() is None:
            if os.name == "nt":
                # A Windows venv redirector can own a child interpreter. Stop
                # only this owned process tree, never a process guessed by port.
                subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               check=False, timeout=10)
            else:
                self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log is not None:
            self.log.close()


@contextmanager
def backend(output: Path, base_url: str | None, data_dir: Path | None):
    if base_url is not None:
        if data_dir is None:
            raise ValueError("external backend requires its explicit --data-dir")
        yield base_url, Path(data_dir), None
    else:
        if data_dir is not None:
            raise ValueError("--data-dir is only used together with --base-url")
        with ManagedBackend(output) as managed:
            yield managed.base_url, managed.data_dir, managed.source_hash


def run_trial(case: dict, output: Path, *, execute=False, judge_settings=None, student_settings=None,
              base_url: str | None = None, data_dir: Path | None = None, repetition: int = 1) -> dict:
    from .judging import (judge_trial, output_budget_exceeded, public_settings, student_definition_hash, student_reply)
    from .runtime import Runtime
    from .scenarios import execute_scenario

    if not execute:
        raise ValueError("--execute is required for potentially billable execution")
    public = public_case(case)
    if public["task"]["mode"] == "simulated" and student_settings is None:
        raise ValueError("simulated interaction requires an explicit student model before business execution")
    if (base_url is None) != (data_dir is None):
        raise ValueError("--base-url and --data-dir must be supplied together")
    output = private_path(output)
    record = new_trial(output, case, config={
        "repetition": repetition, "interaction_mode": public["task"]["mode"],
        "judge": public_settings(judge_settings) if judge_settings else None,
        "student": public_settings(student_settings) if student_settings else None,
    })
    if student_settings:
        record["config"]["student_definition_hash"] = student_definition_hash(record, student_settings)

    def checkpoint():
        save_trial(output, record)

    with exclusive(output):
        checkpoint()
        try:
            with backend(output, base_url, data_dir) as (url, directory, source_hash):
                try:
                    with Runtime(url, directory, record, checkpoint) as runtime:
                        runtime.preflight()
                        callback = (lambda: student_reply(record, student_settings, checkpoint, execute=True)) \
                            if student_settings else None
                        execute_scenario(runtime, public, callback)
                        if record["status"] == "running":
                            record["status"] = "completed"
                finally:
                    # Even a configuration-blocked owned process has known source.
                    # Runtime.__exit__ performs its final read-only collection.
                    if source_hash:
                        changed = source_snapshot() != source_hash
                        record["subject"].update(identity="unknown" if changed else source_hash,
                                                 source_hash=source_hash,
                                                 identity_source="managed-process-source-snapshot")
                        if changed:
                            record["subject"]["source_changed_during_trial"] = True
        except KeyboardInterrupt:
            record.update(status="interrupted", error={"type": "KeyboardInterrupt", "message": "execution interrupted; no commands will be replayed"})
        except Exception as exc:
            if record["status"] == "running":
                record["status"] = "failed"
            if not record.get("error"):
                record["error"] = {"type": type(exc).__name__, "message": "execution stopped; inspect saved actions and checks"}
        finally:
            record["finished_at"] = utcnow()
            record["environment"]["remote_request_cancellation"] = "unknown"
            checkpoint()
        if judge_settings and not output_budget_exceeded(record):
            judge_trial(record, judge_settings, checkpoint, execute=True)
    return record
