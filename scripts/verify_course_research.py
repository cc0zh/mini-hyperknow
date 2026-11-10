"""Check bounded course recovery and exhaustive finite research inputs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from verify_state_machines import TLC_SHA256, digest, manifests, run_code_witness, run_tlc, validate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    item = manifests()["course-research"]
    research = json.loads((item["directory"] / "references/research-coverage.json").read_text(encoding="utf-8"))
    validate(item)
    probes = [{**item, "id": check["id"], "code_mutation": check["code_mutation"]}
              for check in research["checks"]]
    for probe in probes:
        validate(probe)
    if args.validate_only:
        print("Validated course model, research bounds, covered sources, and four mutation anchors.")
        return 0
    value = os.environ.get("TLA2TOOLS")
    if not value or not Path(value).is_file():
        raise ValueError("Set TLA2TOOLS using docs/formal-verification/README.md.")
    jar = Path(value).resolve()
    if digest(jar) != TLC_SHA256:
        raise ValueError("TLC 1.7.4 SHA256 mismatch")
    output = args.out.resolve() if args.out else Path(tempfile.mkdtemp(prefix="hyperknow-course-research-"))
    if args.out:
        output.mkdir(parents=True, exist_ok=False)
    print("Output: " + str(output), flush=True)
    summary = {
        "scope": "Bounded TLC model plus exhaustive finite production-code inputs, not a whole-system proof.",
        "sync_commit": item["sync_commit"],
        "research_bounds": research["bounds"],
        "course_model": [run_tlc(item, jar, output, False), run_tlc(item, jar, output, True)],
        "code_witnesses": [],
    }
    for probe in [item, *probes]:
        result = run_code_witness(probe, output)
        summary["code_witnesses"].append({"id": probe["id"], **result})
        (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary["code_witnesses"][-1], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from error
