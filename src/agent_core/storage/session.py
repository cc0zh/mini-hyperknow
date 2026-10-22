"""Single-writer JSONL audit log; checkpoints never overwrite original events."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any, Iterable
import weakref

from ..types import Message, UserMessage
from .messages import decode_message, encode_message, validate_history


class SessionCorruptionError(ValueError):
    """A committed JSONL record is invalid; no history was silently discarded."""


class SessionBusyError(RuntimeError):
    """A session already has a writer or an attached context manager."""


class SessionConflictError(RuntimeError):
    """A context tried to commit against a stale session revision."""


@dataclass(frozen=True)
class SessionSnapshot:
    messages: list[Message]
    audit_messages: list[Message]
    turn: int
    revision: int
    awaiting_user: bool


class SessionStore:
    """Own one local session file exclusively until ``close``.

    Use a context manager. The persistent sidecar lock is OS-owned, so process
    death releases it without deleting or stealing a possibly live writer's lock.
    A newline is the commit boundary: only a non-newline-terminated final record
    is recoverable. Invalid committed records, including the last one, are errors.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._mutex = RLock()
        self._closed = False
        self._owner: weakref.ReferenceType | None = None
        self._messages: list[Message] = []
        self._audit: list[Message] = []
        self._turn = 0
        self._revision = 0
        self._awaiting_user = False
        self.recovered_tail_bytes = 0
        self._lock = self.path.with_name(self.path.name + ".lock").open("a+b")
        try:
            self._acquire_lock()
        except BaseException:
            self._lock.close()
            raise
        try:
            self._stream = self.path.open("r+b") if self.path.exists() else self.path.open("w+b")
            self._replay()
        except BaseException:
            if hasattr(self, "_stream"):
                self._stream.close()
            self._release_lock()
            self._lock.close()
            raise

    def _acquire_lock(self) -> None:
        self._lock.seek(0, os.SEEK_END)
        if self._lock.tell() == 0:
            self._lock.write(b"\0")
            self._lock.flush()
        self._lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise SessionBusyError(f"Session already has a writer: {self.path}") from exc

    def _release_lock(self) -> None:
        if os.name == "nt":
            import msvcrt
            self._lock.seek(0)
            msvcrt.locking(self._lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self._lock.fileno(), fcntl.LOCK_UN)

    def attach(self, owner: object) -> None:
        """Prevent two in-memory histories from sharing this writer object."""
        with self._mutex:
            self._ensure_open()
            if self._owner is not None and self._owner() is not None and self._owner() is not owner:
                raise SessionBusyError("SessionStore already has a ContextManager")
            self._owner = weakref.ref(owner)

    def load(self) -> SessionSnapshot:
        with self._mutex:
            self._ensure_open()
            return SessionSnapshot(deepcopy(self._messages), deepcopy(self._audit),
                                   self._turn, self._revision, self._awaiting_user)

    def begin_turn(self, *, expected_revision: int | None = None) -> int:
        with self._mutex:
            return self._append({"type": "turn", "turn": self._turn + 1}, expected_revision)

    def append_message(self, message: Message, *, expected_revision: int | None = None) -> int:
        with self._mutex:
            return self._append({"type": "message", "message": encode_message(message)}, expected_revision)

    def checkpoint(self, messages: Iterable[Message], *, expected_revision: int | None = None) -> int:
        """Commit a complete active-history replacement as one durable record."""
        with self._mutex:
            encoded = [encode_message(message) for message in messages]
            return self._append({"type": "checkpoint", "messages": encoded}, expected_revision)

    def _append(self, event: dict[str, Any], expected_revision: int | None) -> int:
        self._ensure_open()
        if expected_revision is not None and expected_revision != self._revision:
            raise SessionConflictError("Session revision changed")
        event = {"version": 1, "seq": self._revision + 1, **event}
        # Validation and allocation happen before touching the disk or live state.
        next_state = self._apply(event)
        record = (json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        self._stream.seek(0, os.SEEK_END)
        offset = self._stream.tell()
        try:
            self._stream.write(record)
            self._stream.flush()
            os.fsync(self._stream.fileno())
        except BaseException:
            try:
                self._stream.seek(offset)
                self._stream.truncate()
                self._stream.flush()
                os.fsync(self._stream.fileno())
            except BaseException:
                self.close()
            raise
        self._messages, self._audit, self._turn, self._awaiting_user = next_state
        self._revision += 1
        return self._revision

    def _apply(self, event: Any) -> tuple[list[Message], list[Message], int, bool]:
        if not isinstance(event, dict) or type(event.get("version")) is not int or event["version"] != 1:
            raise ValueError("Unsupported session record version")
        if type(event.get("seq")) is not int or event["seq"] != self._revision + 1:
            raise ValueError("Nonsequential session record")
        kind = event.get("type")
        base = {"version", "seq", "type"}
        messages, audit, turn, awaiting = self._messages, self._audit, self._turn, self._awaiting_user
        if kind == "message" and set(event) == base | {"message"}:
            message = decode_message(event["message"])
            messages = [*messages, message]
            validate_history(messages, allow_pending=True)
            audit = [*audit, deepcopy(message)]
            if isinstance(message, UserMessage):
                awaiting = False
        elif kind == "turn" and set(event) == base | {"turn"}:
            if type(event["turn"]) is not int or event["turn"] != turn + 1:
                raise ValueError("Nonsequential turn marker")
            validate_history(messages)
            turn, awaiting = event["turn"], True
        elif kind == "checkpoint" and set(event) == base | {"messages"}:
            if not isinstance(event["messages"], list):
                raise ValueError("Checkpoint messages must be a list")
            messages = [decode_message(item) for item in event["messages"]]
            validate_history(messages)
        else:
            raise ValueError("Unknown session event or fields")
        return messages, audit, turn, awaiting

    def _replay(self) -> None:
        self._stream.seek(0)
        line_number = 0
        while True:
            offset = self._stream.tell()
            line = self._stream.readline()
            if not line:
                break
            line_number += 1
            if not line.endswith(b"\n"):
                self.recovered_tail_bytes = len(line)
                break
            try:
                event = json.loads(line.decode("utf-8"))
                state = self._apply(event)
                self._messages, self._audit, self._turn, self._awaiting_user = state
                self._revision += 1
            except (ValueError, TypeError, KeyError) as exc:
                raise SessionCorruptionError(f"Invalid committed session record at line {line_number}") from exc
        if self.recovered_tail_bytes:
            self._stream.seek(offset)
            self._stream.truncate()
            self._stream.flush()
            os.fsync(self._stream.fileno())

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("SessionStore is closed")

    def close(self) -> None:
        with self._mutex:
            if not self._closed:
                self._closed = True
                try:
                    self._stream.close()
                finally:
                    try:
                        self._release_lock()
                    finally:
                        self._lock.close()

    def __enter__(self) -> SessionStore:
        self._ensure_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
