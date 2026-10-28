"""Resolve compact Trial directories without moving or rewriting older results."""

from pathlib import Path


def result_path(output: Path) -> Path:
    """New directories use details; explicit files and old directories keep their layout."""
    output = Path(output)
    if output.suffix.lower() == ".json":
        return output
    legacy, compact = output / "result.json", output / "details/result.json"
    if legacy.exists() and compact.exists():
        raise ValueError("ambiguous Trial directory: both result.json and details/result.json exist")
    return legacy if legacy.exists() else compact


def run_directory(result: Path) -> Path | None:
    """Only an explicit compact result owns the adjacent managed report.html."""
    result = Path(result)
    if result.name == "result.json" and result.parent.name == "details":
        return result.parent.parent
    return None
