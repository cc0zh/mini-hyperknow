"""Bounded, explicitly trusted skill snapshots; never discover user files or run scripts."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import re


class SkillRegistry:
    """Load an explicit allowlist, then disclose bodies only on activation.

    Snapshots are caller-owned data, not authority to grant tools. Keeping the
    original body and digest makes retries independent of subsequent file edits.
    """

    def __init__(self, snapshots: dict[str, dict]):
        if not snapshots or len(snapshots) > 12:
            raise ValueError("expected 1-12 trusted skill snapshots")
        self._skills = deepcopy(snapshots)
        for name, skill in self._skills.items():
            if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name):
                raise ValueError("invalid skill name")
            if set(skill) != {"name", "description", "version", "body", "sha256"} or skill["name"] != name:
                raise ValueError("invalid skill snapshot")
            if not all(isinstance(value, str) and value.strip() for value in skill.values()):
                raise ValueError("skill fields must be nonempty strings")
            if len(skill["description"]) > 1024 or len(skill["version"]) > 40:
                raise ValueError("skill metadata too large")
            if len(skill["body"].encode("utf-8")) > 12000:
                raise ValueError("skill body too large")
            if sha256(skill["body"].encode("utf-8")).hexdigest() != skill["sha256"]:
                raise ValueError("skill snapshot digest mismatch")

    @classmethod
    def from_directory(cls, root: Path, names: tuple[str, ...]):
        root = root.resolve(strict=True)
        snapshots = {}
        for name in names:
            if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name):
                raise ValueError("invalid skill name")
            path = (root / name / "SKILL.md").resolve(strict=True)
            if not path.is_relative_to(root) or path.stat().st_size > 16000:
                raise ValueError("skill path or size outside trusted boundary")
            source = path.read_text(encoding="utf-8")
            parts = source.split("---", 2)
            if len(parts) != 3 or parts[0].strip():
                raise ValueError("skill requires metadata front matter")
            metadata = {}
            for line in parts[1].strip().splitlines():
                key, separator, value = line.partition(":")
                if not separator or key in metadata or key not in {"name", "description", "version"}:
                    raise ValueError("unsupported trusted skill metadata")
                metadata[key] = value.strip()
            if metadata.get("name") != name:
                raise ValueError("skill name does not match its allowlisted directory")
            body = parts[2].strip()
            snapshots[name] = {**metadata, "body": body, "sha256": sha256(body.encode("utf-8")).hexdigest()}
        return cls(snapshots)

    def snapshot(self) -> dict[str, dict]:
        return deepcopy(self._skills)

    def catalog(self) -> list[dict]:
        return [{key: skill[key] for key in ("name", "description", "version", "sha256")}
                for skill in self._skills.values()]

    def load(self, name: str) -> dict:
        if name not in self._skills:
            raise ValueError("unknown or unavailable skill")
        return deepcopy(self._skills[name])
