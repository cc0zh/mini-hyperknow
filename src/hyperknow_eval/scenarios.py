"""Eight explicit product workflows. Only public task material enters requests."""

import re
from typing import Callable

from .runtime import Runtime
from .schema import Budget, Task, WORKFLOWS


def validate_public_case(value: dict) -> dict:
    """Do not silently drop a private rubric/reference/learner supplied by a caller."""
    if not isinstance(value, dict) or set(value) != {"id", "workflow", "task", "budget"}:
        raise ValueError("execution requires only id, workflow, task and budget")
    if not isinstance(value["id"], str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,95}", value["id"]):
        raise ValueError("invalid public case identity")
    if value["workflow"] not in WORKFLOWS:
        raise ValueError("unsupported workflow")
    task = Task.model_validate(value["task"]).model_dump(mode="json")
    budget = Budget.model_validate(value["budget"]).model_dump(mode="json")
    if value["workflow"] not in {"assistance", "artifact"} and (task["mode"] != "scripted" or task["follow_ups"]):
        raise ValueError("only conversations support follow-ups or student simulation")
    if value["workflow"] in {"lesson", "question", "practice", "exam"} and not task["course_goal"]:
        raise ValueError("downstream workflows require a public course_goal")
    if value["workflow"] == "artifact" and not task["artifact_kind"]:
        raise ValueError("artifact workflow requires an intended representation")
    goal = task["opening"] if value["workflow"] == "research" else task["course_goal"] or task["opening"]
    if value["workflow"] not in {"assistance", "artifact"} and not 2 <= len(goal) <= 4000:
        raise ValueError("course/research goals must fit the real product API")
    if value["workflow"] == "question" and not 2 <= len(task["opening"]) <= 2000:
        raise ValueError("classroom questions must fit the real product API")
    if value["workflow"] in {"assistance", "artifact"} and any(
            len(text) > 12000 for text in [task["opening"], *task["follow_ups"]]):
        raise ValueError("conversation messages must fit the real product API")
    if task["clarification_facts"] and len(task["clarification_facts"]) > 2000:
        raise ValueError("public clarification facts must fit the real product API")
    return {"id": value["id"], "workflow": value["workflow"], "task": task, "budget": budget}


def clarification_answers(task: dict, questions: list[dict]) -> dict:
    """No guessed option IDs or inferred learner facts; custom text must be allowed."""
    facts = task.get("clarification_facts")
    answers = []
    if task.get("clarification") == "facts" and isinstance(facts, str) and facts.strip():
        answers = [{"question_id": question["id"], "option_ids": [], "custom_text": facts}
                   for question in questions if question.get("allow_custom") is True]
    return {"skip": not bool(answers), "answers": answers}


def _ready(runtime: Runtime, run: dict) -> dict:
    if run.get("status") != "ready":
        runtime.check("business_run_ready", False, {"run_id": run.get("run_id"), "status": run.get("status")})
        raise runtime.failure("business_run_" + str(run.get("status", "invalid")))
    runtime.check("business_run_ready", True, {"run_id": run["run_id"]})
    return run


def _course(runtime: Runtime, task: dict) -> dict:
    runtime.require_search()
    goal = task.get("course_goal") or task["opening"]
    run = runtime.post("/api/course-runs", {"goal": goal})
    run = runtime.wait_run(run["run_id"])
    if run["status"] == "awaiting_answers":
        answer = clarification_answers(task, run["questions"])
        runtime.check("public_clarification", True, {"mode": "skip" if answer["skip"] else "public_custom_facts",
                                                    "answered_question_ids": [item["question_id"] for item in answer["answers"]]})
        run = runtime.post(f"/api/runs/{run['run_id']}/answers", {"expected_version": run["version"], **answer})
        run = runtime.wait_run(run["run_id"])
    if run["status"] == "awaiting_blueprint":
        blueprint = runtime.get(f"/api/courses/{run['course_id']}")
        runtime.freeze("course_blueprint", blueprint, {"transport": "http", "course_id": run["course_id"]})
        run = runtime.post(f"/api/runs/{run['run_id']}/blueprint", {
            "expected_version": run["version"], "approve": True, "feedback": ""})
        run = runtime.wait_run(run["run_id"])
    _ready(runtime, run)
    if not run.get("course_id"):
        raise runtime.failure("ready_course_missing")
    saved = runtime.get(f"/api/courses/{run['course_id']}")
    identity = runtime.freeze("course", saved, {"transport": "http", "course_id": run["course_id"]})
    if saved.get("structure_status") != "ready" or saved.get("creation_run_id") != run["run_id"]:
        raise runtime.failure("course_not_materialized")
    runtime.check("generated_course_saved", True, {"course_id": run["course_id"]}, [identity])
    return saved


def _first_session(runtime: Runtime, saved_course: dict) -> str:
    for unit in saved_course["units"]:
        for lecture in unit["lectures"]:
            for session in lecture["sessions"]:
                return session["session_id"]
    raise runtime.failure("generated_course_has_no_sessions")


def _lesson(runtime: Runtime, session_id: str) -> dict:
    snapshot = runtime.post(f"/api/sessions/{session_id}/prepare", {})
    run = snapshot.get("generation_run")
    if run is None:
        raise runtime.failure("lesson_generation_run_missing")
    _ready(runtime, runtime.wait_run(run["run_id"]))
    snapshot = runtime.get(f"/api/sessions/{session_id}")
    identity = runtime.freeze("lesson", snapshot, {"transport": "http", "session_id": session_id})
    if not snapshot.get("script") or not snapshot["script"].get("steps"):
        raise runtime.failure("ready_lesson_missing_script")
    runtime.check("generated_lesson_saved", True, {"session_id": session_id}, [identity])
    return snapshot


def _progress(runtime: Runtime, snapshot: dict, cursor: int) -> dict:
    # Product requires each confirmed cursor to advance by at most one step.
    return runtime.put(f"/api/sessions/{snapshot['session']['session_id']}/progress", {
        "expected_version": snapshot["progress"]["version"], "script_id": snapshot["script"]["script_id"],
        "cursor": cursor, "play_intent": "paused"})


def _conversation(runtime: Runtime, task: dict, student_callback: Callable[[], str] | None) -> None:
    if task["mode"] == "simulated" and student_callback is None:
        raise runtime.failure("student_callback_required", status="blocked")
    conversation = runtime.post("/api/assistance/conversations", {})
    conversation_id = conversation["conversation_id"]
    text = task["opening"]
    turns = task["max_turns"] if task["mode"] == "simulated" else len(task["follow_ups"]) + 1
    for index in range(turns):
        runtime.remaining()
        if index:
            if task["mode"] == "scripted":
                text = task["follow_ups"][index - 1]
            else:
                # The callback's owner supplies the isolated, budgeted student model.
                if student_callback is None:
                    raise runtime.failure("student_callback_required", status="blocked")
                text = student_callback()
                runtime.remaining()
            if not isinstance(text, str) or not text.strip():
                raise runtime.failure("empty_student_message")
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 12000:
            raise runtime.failure("invalid_student_message")
        body = {"expected_version": conversation["version"], "text": text, "action": "message"}
        evidence_id = runtime.freeze("student_message", {"text": text, "action": "message"},
                                     {"conversation_id": conversation_id, "turn_index": index})
        runtime.transcript("student", text, evidence_id, conversation_id=conversation_id, turn_index=index)
        conversation = runtime.post(f"/api/assistance/conversations/{conversation_id}/turns", body)
        active = conversation.get("active_run")
        if active is None:
            raise runtime.failure("assistance_run_missing")
        run = runtime.wait_run(active["run_id"])
        conversation = runtime.get(f"/api/assistance/conversations/{conversation_id}")
        turn = next((item for item in conversation["turns"] if item["run_id"] == run["run_id"]), None)
        if turn is None:
            raise runtime.failure("saved_tutor_turn_missing")
        identity = runtime.freeze("tutor_turn", turn, {"transport": "http", "conversation_id": conversation_id,
                                                       "turn_id": turn["turn_id"], "run_id": run["run_id"]})
        response = turn.get("response") or {}
        runtime.transcript("tutor", response.get("text", ""), identity, conversation_id=conversation_id,
                           turn_id=turn["turn_id"], run_id=run["run_id"], turn_index=index)
        for artifact in turn["artifacts"]:
            saved = runtime.get(f"/api/assistance/artifacts/{artifact['artifact_id']}")
            artifact_evidence = runtime.freeze("artifact", saved, {"transport": "http", "artifact_id": artifact["artifact_id"],
                                                                   "run_id": run["run_id"]})
            runtime.check("artifact_round_trip", saved == artifact, {"artifact_id": artifact["artifact_id"]}, [artifact_evidence])
            if saved != artifact:
                raise runtime.failure("artifact_persistence_mismatch")
        _ready(runtime, run)
        if turn["status"] != "ready" or not response:
            raise runtime.failure("ready_tutor_response_missing")
        # waiting_for=continue is not an authorization to click continue. Every
        # subsequent action remains an explicit public/student-generated message.
    runtime.collect()


def assistance(runtime: Runtime, public_case: dict, student_callback: Callable[[], str] | None = None) -> None:
    _conversation(runtime, public_case["task"], student_callback)


def artifact(runtime: Runtime, public_case: dict, student_callback: Callable[[], str] | None = None) -> None:
    _conversation(runtime, public_case["task"], student_callback)
    intended = public_case["task"]["artifact_kind"]
    identities = [item["id"] for item in runtime.record["evidence"] if item["kind"] == "artifact"
                  and item["content"].get("kind") == intended]
    runtime.check("requested_artifact_saved", bool(identities), {"kind": intended}, identities)
    if not identities:
        raise runtime.failure("requested_artifact_missing")


def course(runtime: Runtime, public_case: dict, student_callback: Callable[[], str] | None = None) -> None:
    _course(runtime, public_case["task"])


def research(runtime: Runtime, public_case: dict, student_callback: Callable[[], str] | None = None) -> None:
    runtime.require_search()
    run = runtime.post("/api/research-runs", {"goal": public_case["task"]["opening"], "context": ""})
    run = _ready(runtime, runtime.wait_run(run["run_id"]))
    report = run.get("research", {})
    identity = runtime.freeze("research", report, {"transport": "http", "run_id": run["run_id"]})
    valid = bool(report.get("report") and report.get("sources"))
    runtime.check("research_report_saved", valid, {"run_id": run["run_id"]}, [identity])
    if not valid:
        raise runtime.failure("ready_research_missing_sources_or_report")


def lesson(runtime: Runtime, public_case: dict, student_callback: Callable[[], str] | None = None) -> None:
    saved_course = _course(runtime, public_case["task"])
    snapshot = _lesson(runtime, _first_session(runtime, saved_course))
    for cursor in range(snapshot["progress"]["cursor"] + 1, len(snapshot["script"]["steps"])):
        snapshot = _progress(runtime, snapshot, cursor)
    identity = runtime.freeze("lesson_progress", snapshot, {"transport": "http", "session_id": snapshot["session"]["session_id"]})
    runtime.check("lesson_cursor_saved", snapshot["progress"]["cursor"] == len(snapshot["script"]["steps"]) - 1,
                  evidence_ids=[identity])


def question(runtime: Runtime, public_case: dict, student_callback: Callable[[], str] | None = None) -> None:
    saved_course = _course(runtime, public_case["task"])
    session_id = _first_session(runtime, saved_course)
    snapshot = _lesson(runtime, session_id)
    snapshot = _progress(runtime, snapshot, 0)
    text = public_case["task"]["opening"]
    identity = runtime.freeze("student_message", {"text": text, "cursor": snapshot["progress"]["cursor"]},
                              {"session_id": session_id})
    runtime.transcript("student", text, identity, session_id=session_id)
    snapshot = runtime.post(f"/api/sessions/{session_id}/questions", {
        "expected_version": snapshot["progress"]["version"], "script_id": snapshot["script"]["script_id"],
        "cursor": snapshot["progress"]["cursor"], "question": text, "was_playing": False})
    pending = [item for item in snapshot["interactions"] if item["status"] == "pending"]
    if len(pending) != 1:
        raise runtime.failure("question_run_missing")
    run = runtime.wait_run(pending[0]["run_id"])
    snapshot = runtime.get(f"/api/sessions/{session_id}")
    interaction = next(item for item in snapshot["interactions"] if item["run_id"] == run["run_id"])
    identity = runtime.freeze("lesson_interaction", interaction, {"transport": "http", "session_id": session_id,
                                                                  "run_id": run["run_id"]})
    runtime.transcript("tutor", interaction.get("answer") or "", identity, session_id=session_id, run_id=run["run_id"])
    _ready(runtime, run)
    if interaction["status"] != "ready" or not interaction.get("answer"):
        raise runtime.failure("saved_question_answer_missing")


def _quiz(runtime: Runtime, path: str) -> None:
    snapshot = runtime.post(path + "/prepare", {})
    if snapshot.get("generation_run") is None:
        raise runtime.failure("quiz_generation_run_missing")
    run = _ready(runtime, runtime.wait_run(snapshot["generation_run"]["run_id"]))
    snapshot = runtime.get(path)
    identity = runtime.freeze("quiz_target", snapshot, {"transport": "http", "path": path, "run_id": run["run_id"]})
    valid = bool(snapshot.get("quiz") and snapshot["quiz"].get("questions") and snapshot["quiz"].get("source_refs"))
    runtime.check("generated_quiz_saved", valid, evidence_ids=[identity])
    if not valid:
        raise runtime.failure("ready_quiz_missing_content_or_sources")
    # Do not answer from correct_option_ids or fabricate a successful learner attempt.


def practice(runtime: Runtime, public_case: dict, student_callback: Callable[[], str] | None = None) -> None:
    saved_course = _course(runtime, public_case["task"])
    session_id = _first_session(runtime, saved_course)
    _lesson(runtime, session_id)
    _quiz(runtime, f"/api/sessions/{session_id}/practice")


def exam(runtime: Runtime, public_case: dict, student_callback: Callable[[], str] | None = None) -> None:
    saved_course = _course(runtime, public_case["task"])
    for unit in saved_course["units"]:
        for activity in unit["exams"]:
            _quiz(runtime, f"/api/exams/{activity['exam_id']}")
            return
    raise runtime.failure("generated_course_has_no_exam")


def execute_scenario(runtime: Runtime, public_case: dict, student_callback: Callable[[], str] | None = None) -> None:
    fixed = validate_public_case(public_case)
    if any(fixed[key] != runtime.record["case"][key] for key in ("id", "workflow", "task", "budget")):
        raise runtime.failure("public_case_identity_mismatch", status="blocked")
    if fixed["task"]["mode"] == "simulated" and student_callback is None:
        raise runtime.failure("student_callback_required", status="blocked")
    runtime.set_budget(fixed["budget"])
    runtime.preflight()
    runtime.record["environment"]["interaction_mode"] = fixed["task"]["mode"]
    runtime.checkpoint()
    # Explicit functions, not an interpreted state-machine/adapter contract.
    workflow = fixed["workflow"]
    if workflow == "assistance":
        assistance(runtime, fixed, student_callback)
    elif workflow == "artifact":
        artifact(runtime, fixed, student_callback)
    elif workflow == "course":
        course(runtime, fixed)
    elif workflow == "research":
        research(runtime, fixed)
    elif workflow == "lesson":
        lesson(runtime, fixed)
    elif workflow == "question":
        question(runtime, fixed)
    elif workflow == "practice":
        practice(runtime, fixed)
    elif workflow == "exam":
        exam(runtime, fixed)
    runtime.collect()
    runtime.check("scenario_completed", True, {"workflow": workflow})
