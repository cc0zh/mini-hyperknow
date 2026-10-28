"""Shared evaluation safety and trace checks; no execution or grading engine."""

from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

from dotenv import dotenv_values

from agent_core.skills import SkillRegistry


ROOT = Path(__file__).resolve().parents[2]


def private_output(path: Path) -> Path:
    path = path.resolve()
    if path.is_relative_to(ROOT) and not path.is_relative_to(ROOT / "data"):
        raise ValueError("mutable evaluation evidence must be under ignored data/ or outside the repository")
    return path


def local_origin(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
        raise ValueError("the evaluation backend must be an explicit loopback HTTP origin")
    return url.rstrip("/")


def isolated_database(data_dir: Path) -> Path:
    directory = data_dir.resolve()
    configured = dotenv_values(ROOT / ".env").get("HK_DATA_DIR")
    protected = {(ROOT / "data").resolve()}
    if configured:
        protected.add((ROOT / configured).resolve())
    if directory in protected:
        raise ValueError("refusing the author's configured/default data directory; start an isolated backend")
    path = directory / "hyperknow.sqlite3"
    if not path.is_file():
        raise ValueError("start the isolated backend first; evaluation never creates or migrates its database")
    return path


@contextmanager
def readonly(path: Path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        yield conn


def skill_trace_matches(run: dict, turn: dict, calls: list[dict]) -> bool:
    """Optional uses must match successful load steps, requests and frozen snapshots."""
    try:
        snapshots = SkillRegistry(run["input"]["skill_snapshots"]).snapshot()
        requested = [tool["arguments"]["name"] for call in calls
                     for tool in call.get("response", {}).get("tool_calls", [])
                     if tool.get("name") == "get_skills"]
        loaded = [{key: step[key] for key in ("name", "version", "sha256")}
                  for step in run["steps"] if step.get("tool") == "get_skills" and step.get("status") == "ready"]
        uses = turn["skill_uses"]
        return (uses == loaded and len({use["name"] for use in uses}) == len(uses)
                and all(use["name"] in requested and use == {
                    key: snapshots[use["name"]][key] for key in ("name", "version", "sha256")}
                        for use in uses))
    except (KeyError, TypeError, ValueError):
        return False
