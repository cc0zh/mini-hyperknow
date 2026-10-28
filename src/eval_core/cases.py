"""Offline, immutable Case publication, Benchmark freezing and sample linkage."""

from copy import deepcopy
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .contracts import StrictModel, Text, validate_case
from .store import digest, exclusive, now, read_json, write_json


def _immutable(path, value):
    if path.exists():
        if read_json(path) != value:
            raise ValueError(f"immutable content mismatch: {path}")
    else:
        write_json(path, value)


def _same_version(directory, identity, version, content_hash, key):
    for path in directory.glob("*.json"):
        record = read_json(path)
        content = record[key]
        if record.get(f"{key}_hash") != digest(content) or path.stem != record[f"{key}_hash"]:
            raise ValueError(f"stored {key} does not match its content hash")
        if content["id"] == identity and content["version"] == version and record[f"{key}_hash"] != content_hash:
            raise ValueError(f"{key} id/version already published with different content")


def publish_case(case: dict, library, reviewed_by) -> Path:
    """Publish an explicit review declaration, not a claim of human calibration.

    reviewed_by is a nonempty identity supplied by the caller. Assistant identities
    are valid, but no identity string is evidence of independent human review.
    """
    case = validate_case(case)
    if type(reviewed_by) is not str or not reviewed_by.strip():
        raise ValueError("reviewed_by must identify the actual reviewer")
    identity = digest(case)
    library = Path(library)
    path = library / "cases" / f"{identity}.json"
    with exclusive(library / ".writer.lock"):
        _same_version(path.parent, case["id"], case["version"], identity, "case")
        if path.exists():
            record = read_json(path)
            if record.get("case_hash") != identity or record.get("case") != case:
                raise ValueError("stored Case does not match its content hash")
            return path
        reviewed_at = now()
        record = {"schema_version": 2, "case_hash": identity, "case": case,
                  "status": "published", "review_status": "reviewed",
                  "reviewed_by": reviewed_by.strip(), "reviewed_at": reviewed_at,
                  "published_at": reviewed_at, "independent_human_review": "not_verified",
                  "calibration_status": "uncalibrated",
                  "lifecycle": ["candidate", "reviewed", "published"]}
        write_json(path, record)
    return path


class Member(StrictModel):
    id: Text
    version: Text
    case_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class Benchmark(StrictModel):
    schema_version: Literal[2] = 2
    id: Text
    version: Text
    title: Text
    members: list[Member] = Field(min_length=1)
    usage: Literal["development", "regression", "holdout"] = "development"
    tags: list[Text] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_members(self):
        keys = [(member.id, member.version) for member in self.members]
        if len(keys) != len(set(keys)):
            raise ValueError("Benchmark members must be unique")
        return self


def freeze_benchmark(value: dict, library) -> Path:
    if type(value) is not dict or ("schema_version" in value and type(value["schema_version"]) is not int):
        raise ValueError("Benchmark schema_version must be the integer 2")
    digest(value)
    benchmark = Benchmark.model_validate(value).model_dump()
    identity = digest(benchmark)
    library = Path(library)
    path = library / "benchmarks" / f"{identity}.json"
    with exclusive(library / ".writer.lock"):
        for member in benchmark["members"]:
            record = read_json(library / "cases" / f"{member['case_hash']}.json")
            case = validate_case(record["case"])
            if (record.get("status") != "published" or record.get("case_hash") != member["case_hash"]
                    or digest(case) != member["case_hash"]
                    or (case["id"], case["version"]) != (member["id"], member["version"])):
                raise ValueError("Benchmark member is not the specified published Case")
        _same_version(path.parent, benchmark["id"], benchmark["version"], identity, "benchmark")
        _immutable(path, {"schema_version": 2, "benchmark_hash": identity, "benchmark": benchmark})
    return path


def collect_sample(result: dict, library) -> Path:
    """Append an unreviewed immutable sample; never edit or auto-publish its Case."""
    digest(result)
    case = validate_case(result["case"])
    if (type(result.get("schema_version")) is not int or result["schema_version"] != 2
            or result.get("case_hash") != digest(case)):
        raise ValueError("result Case identity/schema mismatch")
    if type(result.get("trial_id")) is not str or not result["trial_id"].strip():
        raise ValueError("sample must identify its Trial")
    identity = digest(result)
    library = Path(library)
    path = library / "samples" / result["case_hash"] / f"{identity}.json"
    with exclusive(library / ".writer.lock"):
        if path.exists():
            record = read_json(path)
            if (record.get("result") != result or record.get("sample_hash") != identity
                    or record.get("case_hash") != result["case_hash"] or record.get("trial_id") != result["trial_id"]):
                raise ValueError("immutable sample mismatch")
            return path
        write_json(path, {"schema_version": 2, "sample_hash": identity,
                          "case_hash": result["case_hash"], "trial_id": result["trial_id"],
                          "review_status": "unreviewed", "calibration_status": "uncalibrated",
                          "collected_at": now(), "result": deepcopy(result)})
    return path
