"""Explicit, offline migration; original Case files and experiment facts stay intact."""

from eval_core.contracts import validate_case
from eval_core.store import digest

from .eval_legacy import validate_case as validate_legacy_case


def check(identity: str, evaluator: str, *, evidence: str = "final",
          criterion: str, pass_when: str, fail_when: str, kind: str = "rule") -> dict:
    return {"check_id": identity, "version": "1", "kind": kind, "evaluator": evaluator,
            "criterion": criterion, "pass_when": pass_when, "fail_when": fail_when,
            "evidence": [evidence], "evidence_fields": ["turns", "artifacts"] if kind == "llm" else [],
            "required": True, "applicable_when": {}}


def step(identity: str, action: str, inputs: dict | None = None, *,
         checkpoint: str | None = None, optional: bool = False, initial: bool = False) -> dict:
    return {"id": identity, "action": action, "input": inputs or {},
            "when": {"state": (["preparing"] if initial else []) + ["waiting", "terminal"], "action": action},
            "optional": optional, "checkpoint": checkpoint or identity}


def migrate_case(value: dict) -> dict:
    """Convert the one-turn v1 contract without relabelling its historic executions."""
    old = validate_legacy_case(value)
    checks = [
        check("delivery", "saved_assistance", criterion="回复真实保存且属于本次原始运行",
              pass_when="本次turn与run均ready并保存非空回复", fail_when="本次运行未交付回复"),
        check("no_artifacts", "no_artifacts", criterion="遵守不创建产物的要求",
              pass_when="最终turn无产物", fail_when="最终turn包含产物"),
        check("no_questions", "no_questions", criterion="一次直接解释，不提问或展开计划",
              pass_when="无问题、无等待、无计划", fail_when="要求回答、等待或展开计划"),
        check("skill_trace", "skill_trace", criterion="可选Skill使用与快照及实际加载一致",
              pass_when="未使用或使用记录可靠", fail_when="使用记录与冻结输入或调用不一致"),
    ]
    checks.extend(check(item["id"], "rubric-v1", criterion=item["criterion"],
                        pass_when=item["pass_when"], fail_when=item["fail_when"], kind="llm")
                  for item in old["rubric"])
    return validate_case({
        "schema_version": 2, "id": old["id"], "version": f"{old['version']}.general-2",
        "title": "链式求导：一次直接解释",
        "tags": ["B07", "regression", "migrated-v1", "development", "uncalibrated"],
        "task": {"profile": "assistance", "input": {"text": old["input"]}},
        "prerequisites": {"legacy_source": {"case_hash": digest(old), "version": old["version"],
                                            "rubric_version": old["rubric_version"]}},
        "steps": [step("create", "conversation.create", initial=True),
                  step("explain", "assistance.message", {"text": old["input"]}, checkpoint="final")],
        "capture": ["final"], "checks": checks, "reference_facts": old["reference_facts"],
        "limits": {"max_actions": 2, "max_model_calls": 9, "wait_seconds": 420,
                   "poll_seconds": 0.25},
        "completion": {"states": ["waiting", "terminal"], "outcomes": ["success"]},
    })
