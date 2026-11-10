"""Check the bounded TLA+ models and their real-code regression witnesses."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / ".agents" / "skills"
TLC_SHA256 = "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifests() -> dict[str, dict]:
    result = {}
    for path in sorted(SKILLS.glob("verify-*/references/coverage.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        item["directory"] = path.parent.parent
        result[item["id"]] = item
    return result


def validate(item: dict) -> None:
    directory = item["directory"]
    skill = (directory / "SKILL.md").read_text(encoding="utf-8")
    header = re.match(r"\A---\n(.*?)\n---\n", skill, re.DOTALL)
    if not header:
        raise ValueError(f"Missing frontmatter: {directory.name}")
    name = re.search(r"^name: (.+)$", header[1], re.MULTILINE)
    description = re.search(r"^description: (.+)$", header[1], re.MULTILINE)
    if not name or name[1] != directory.name or not re.fullmatch(
        r"[a-z0-9]+(?:-[a-z0-9]+)*", name[1]
    ) or len(name[1]) > 64:
        raise ValueError(f"Invalid skill name: {directory.name}")
    if not description or not 1 <= len(description[1].strip('"')) <= 1024:
        raise ValueError(f"Invalid skill description: {directory.name}")
    if "/statechart" not in skill or "/maintain-formal-verification-skill" not in skill:
        raise ValueError(f"Missing maintenance guidance: {directory.name}")
    for field in ("spec", "config", "view"):
        if not (directory / item[field]).is_file():
            raise ValueError(f"Missing {field}: {directory.name}")
    for source in item["sources"]:
        path = ROOT / source["path"]
        if digest(path) != source["sha256"]:
            raise ValueError(
                f"Source drift in {source['path']}. Review the model and coverage record "
                "with /maintain-formal-verification-skill before advancing its digest."
            )
        text = path.read_text(encoding="utf-8")
        for symbol in source["symbols"]:
            if not re.search(rf"\b{re.escape(symbol)}\b", text):
                raise ValueError(f"Missing covered symbol {symbol} in {path}")
    mutation = item["code_mutation"]
    source = (ROOT / mutation["path"]).read_text(encoding="utf-8")
    if source.count(mutation["before"]) != 1:
        raise ValueError(f"Code mutation must match exactly once: {item['id']}")
    if not re.fullmatch(r"[0-9a-f]{40}", item["sync_commit"]):
        raise ValueError(f"Invalid sync commit: {item['id']}")


def run_tlc(item: dict, jar: Path, output: Path, broken: bool) -> dict:
    directory = item["directory"]
    config = (directory / item["config"]).read_text(encoding="utf-8")
    if broken:
        if config.count("Broken = FALSE") != 1:
            raise ValueError("Expected one Broken = FALSE constant assignment")
        config = config.replace("Broken = FALSE", "Broken = TRUE")
    with tempfile.TemporaryDirectory(prefix="hyperknow-tlc-") as scratch:
        work = Path(scratch)
        cfg = work / "model.cfg"
        cfg.write_text(config, encoding="utf-8")
        spec = work / Path(item["spec"]).name
        shutil.copyfile(directory / item["spec"], spec)
        command = [
            os.environ.get("JAVA", "java"), "-XX:+UseParallelGC", "-Xmx512m",
            f"-Djava.io.tmpdir={work}",
            f"-DTLA-Library={work}", "-cp", str(jar),
            "tlc2.TLC", "-workers", "1", "-seed", "1", "-metadir",
            str(work / "states"), "-config", cfg.name, spec.name,
        ]
        process = subprocess.run(
            command, cwd=work, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=90, check=False,
        )
    label = "mutant" if broken else "baseline"
    (output / f"{item['id']}-{label}.out").write_text(
        process.stdout + process.stderr, encoding="utf-8"
    )
    violation = re.search(r"Invariant (\w+) is violated", process.stdout)
    if broken:
        ok = process.returncode == 12 and violation is not None and violation[1] == item["invariant"]
    else:
        ok = process.returncode == 0 and "Model checking completed. No error has been found." in process.stdout
    if not ok:
        raise RuntimeError(
            f"Unexpected {label} result for {item['id']}, exit {process.returncode}. "
            f"Read {output / (item['id'] + '-' + label + '.out')}"
        )
    count = re.search(r"([\d,]+) distinct states found", process.stdout)
    return {"kind": label, "expected_result_observed": True,
            "states": int(count[1].replace(",", "")) if count else None,
            "violated": violation[1] if violation else None}


def run_code_witness(item: dict, output: Path) -> dict:
    mutation = item["code_mutation"]
    with tempfile.TemporaryDirectory(prefix="hyperknow-source-witness-") as scratch:
        work = Path(scratch)
        shutil.copytree(ROOT / "src", work / "src", ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
        shutil.copytree(ROOT / "tests", work / "tests", ignore=shutil.ignore_patterns("__pycache__"))
        environment = {**os.environ, "PYTHONPATH": os.pathsep.join(
            [str(work / "src"), str(work / "tests")]), "PYTHONNOUSERSITE": "1"}
        environment.pop("OPENAI_API_KEY", None)
        command = [sys.executable, "-m", "unittest", *mutation["tests"], "-v"]
        results = {}
        for label in ("baseline", "mutant", "restored"):
            path = work / mutation["path"]
            if label == "mutant":
                original = path.read_text(encoding="utf-8")
                path.write_text(original.replace(mutation["before"], mutation["after"]), encoding="utf-8")
            elif label == "restored":
                shutil.copyfile(ROOT / mutation["path"], path)
            for cache in (work / "src").rglob("__pycache__"):
                shutil.rmtree(cache)
            process = subprocess.run(
                command, cwd=work, env=environment, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=90, check=False,
            )
            log = process.stdout + process.stderr
            (output / f"{item['id']}-code-{label}.out").write_text(log, encoding="utf-8")
            ok = process.returncode == 0 if label != "mutant" else (
                process.returncode == 1 and "FAIL:" in log and "AssertionError" in log
                and "ERROR:" not in log
            )
            if not ok:
                raise RuntimeError(f"Unexpected code {label} for {item['id']}. Read its output log.")
            results[label] = process.returncode
    return {"kind": "real-code-witness", "expected_result_observed": True, "exit_codes": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system", default="all")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--mutants", action="store_true")
    parser.add_argument("--code-mutations", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    items = manifests()
    if not items or args.system != "all" and args.system not in items:
        raise ValueError(f"Unknown system {args.system}. Available: {', '.join(items)}")
    selected = items.values() if args.system == "all" else [items[args.system]]
    for item in selected:
        validate(item)
    if args.validate_only:
        print(f"Validated {len(selected)} skills, source mappings, and mutation anchors.")
        return 0
    value = os.environ.get("TLA2TOOLS")
    if not value or not Path(value).is_file():
        raise ValueError("Set TLA2TOOLS to the official tla2tools 1.7.4 JAR. See docs/formal-verification/README.md.")
    jar = Path(value).resolve()
    if digest(jar) != TLC_SHA256:
        raise ValueError("TLC 1.7.4 SHA256 mismatch")
    output = args.out.resolve() if args.out else Path(tempfile.mkdtemp(prefix="hyperknow-formal-"))
    if args.out:
        output.mkdir(parents=True, exist_ok=False)
    summary = {"tool": "TLC 1.7.4", "scope": "bounded model safety, not a proof of the whole product", "systems": []}
    print(f"Output: {output}", flush=True)
    for item in selected:
        results = [run_tlc(item, jar, output, False)]
        if args.mutants:
            results.append(run_tlc(item, jar, output, True))
        if args.code_mutations:
            results.append(run_code_witness(item, output))
        summary["systems"].append({"id": item["id"], "invariant": item["invariant"], "results": results})
        (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary["systems"][-1], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from error
