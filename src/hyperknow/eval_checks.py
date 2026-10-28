"""Explicit product checks over frozen evidence; no business calls or model access."""

from .eval_support import skill_trace_matches


def _snapshots(view: dict):
    for identity, item in view.items():
        # Grading supplies raw data or the immutable evidence envelope.
        data = item.get("data", item) if isinstance(item, dict) else {}
        yield identity, data


def _answer(verdict: str, reason: str, refs: list[str]) -> dict:
    return {"verdict": verdict, "reason": reason, "evidence_refs": refs}


def _turns(data: dict) -> list[dict]:
    turns = data.get("turns", [])
    return list(turns.values()) if isinstance(turns, dict) else turns


def saved_assistance(_check: dict, view: dict) -> dict:
    refs, seen = [], []
    for ref, data in _snapshots(view):
        runs = data.get("runs", {})
        runs = {r["run_id"]: r for r in runs} if isinstance(runs, list) else runs
        for turn in _turns(data):
            run = runs.get(turn.get("run_id"))
            if not run:
                continue
            refs.append(ref)
            response = turn.get("response") or {}
            seen.append(run.get("status") == turn.get("status") == "ready"
                        and not run.get("parent_run_id")
                        and run.get("turn_id") == turn.get("turn_id")
                        and bool(response.get("text")))
    if not seen:
        return _answer("undetermined", "missing_output: 缺少关联的原始run与turn", list(view))
    return _answer("pass" if all(seen) else "fail", "核对本次原始运行与已保存回复", list(dict.fromkeys(refs)))


def no_artifacts(_check: dict, view: dict) -> dict:
    turns = [(ref, turn) for ref, data in _snapshots(view) for turn in _turns(data)]
    if not turns:
        return _answer("undetermined", "missing_output: 缺少已保存轮次", list(view))
    return _answer("pass" if all(t.get("artifacts") == [] for _, t in turns) else "fail",
                   "Case要求不创建产物", list(dict.fromkeys(ref for ref, _ in turns)))


def no_questions(_check: dict, view: dict) -> dict:
    responses = [(ref, t.get("response")) for ref, data in _snapshots(view) for t in _turns(data)]
    if not responses or any(not response for _, response in responses):
        return _answer("undetermined", "missing_output: 缺少已保存回复", list(view))
    passed = all(response.get("questions") == [] and response.get("waiting_for") == "none"
                 and response.get("plan") == [] for _, response in responses)
    return _answer("pass" if passed else "fail", "Case要求不提问、不等待、不展开计划",
                   list(dict.fromkeys(ref for ref, _ in responses)))


def skill_trace(_check: dict, view: dict) -> dict:
    results, refs = [], []
    for ref, data in _snapshots(view):
        runs = data.get("runs", {})
        runs = {r["run_id"]: r for r in runs} if isinstance(runs, list) else runs
        for turn in _turns(data):
            run = runs.get(turn.get("run_id"))
            if run:
                calls = [c for c in data.get("calls", []) if c.get("run_id") == run["run_id"]]
                results.append(skill_trace_matches(run, turn, calls))
                refs.append(ref)
    return _answer("pass" if results and all(results) else "fail" if results else "undetermined",
                   "可选Skill的使用记录、实际加载和冻结快照须一致", list(dict.fromkeys(refs)) or list(view))


def saved_business_output(_check: dict, view: dict) -> dict:
    """Only checks commit/ownership. Content correctness remains a separate check."""
    runs, refs = {}, []
    for ref, data in _snapshots(view):
        values = data.get("runs", {})
        values = values.values() if isinstance(values, dict) else values
        for run in values:
            if isinstance(run, dict):
                runs[run.get("run_id")] = run
                refs.append(ref)
    if not runs:
        return _answer("undetermined", "missing_output: 没有本次业务运行证据", list(view))
    statuses = [run.get("status") for run in runs.values()]
    if any(status in {"failed", "cancelled", "interrupted"} for status in statuses):
        return _answer("fail", "本次业务运行未成功提交", list(dict.fromkeys(refs)))
    if not all(status == "ready" for status in statuses):
        return _answer("undetermined", "业务仍在运行或等待，不能认定最终交付", list(dict.fromkeys(refs)))
    return _answer("pass", "本次业务运行已提交；内容正确性须另行判断", list(dict.fromkeys(refs)))


RULES = {"saved_assistance": saved_assistance, "no_artifacts": no_artifacts,
         "no_questions": no_questions, "skill_trace": skill_trace,
         "saved_business_output": saved_business_output}
