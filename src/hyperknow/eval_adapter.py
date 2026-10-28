"""Explicit real-HTTP B01--B08 adapter, without a provider or retry mechanism.

Only ``act`` sends a write. A serialized action contains its exact request,
product receipt payload, previous identities and adapter bindings. Callers must
persist it before act; ``recover(None)`` is never permission to resend.

Profiles: assistance, course, research, lesson, question, quiz, artifact.
``prerequisites.resources`` maps aliases to {kind}. Actual IDs live only in
fixture manifest bindings, with kinds course/session/exam/conversation/artifact/
run/quiz_target. A practice target is derived from its bound session, never from
an invented ID or another course's material.
Action inputs select aliases (not URLs). A missing selector uses the sole bound
resource of that kind. See ACTIONS and build_action for the small public inputs.

Fixture manifest v1: {schema_version:1, snapshot:{method:'sqlite-logical-v1',
sha256, source:{kind:'sqlite-backup'|'sqlite-consistent-read',origin}}, resources:[{table,id,sha256,
source:{kind:'business-generated',run_id,origin}}], bindings:{alias:{kind,id}}}.
Every existing data row must be listed, and its producer run must exist. The
snapshot digest includes receipts and is verified only at initial preflight.
Resume uses original bindings/actions, not a new prepare against the changed DB.
"""

from copy import deepcopy
import json
import os
from pathlib import Path

import httpx

from .domain import resolve_answers
from .eval_evidence import (checked_id, crosscheck, database_instance,
                            isolated_database, product_snapshot,
                            readonly, records, resource_path, row_data, sha256,
                            snapshot_digest, verified_receipt, verify_fixture_source)
from .eval_support import local_origin
from .storage import now, storage_identity


ACTIONS = (
    "conversation.create", "assistance.message", "assistance.continue", "course.create",
    "course.answers", "course.blueprint", "research.create", "lesson.prepare",
    "lesson.progress", "lesson.question", "quiz.prepare", "artifact.progress", "run.cancel",
)
PROFILES = {"assistance", "course", "research", "lesson", "question", "quiz", "artifact"}
CHECKPOINTS = (
    "conversation.created", "clarification.ready", "research.saved", "blueprint.awaiting",
    "course.ready", "lesson.saved", "question.saved", "quiz.saved", "turn.saved",
    "artifact.saved", "run.terminal",
)
ACTIVE = {"queued", "clarifying", "generating"}
TERMINAL = {"ready", "failed", "cancelled", "interrupted"}


def run_identity(run: dict) -> str:
    fields = ("run_id", "kind", "goal", "parent_run_id", "model", "created_at", "conversation_id",
              "turn_id", "session_id", "interaction_id", "target_type", "target_id")
    identity = {key: run.get(key) for key in fields}
    if run.get("kind", "course") != "course":
        identity["input"] = run["input"]
    return sha256(identity)


class AdapterBlocked(ValueError):
    """A required real prerequisite or evidence capability is unavailable."""


class ProtocolError(ValueError):
    """The fixed public protocol cannot legally map onto the observed product."""


def public_case(case: dict) -> dict:
    if "checks" in case or "reference_facts" in case:
        raise ProtocolError("adapter accepts only public_case without private checks/reference_facts")
    if case.get("schema_version") != 2 or case.get("task", {}).get("profile") not in PROFILES:
        raise ProtocolError("unsupported Case schema/profile")
    if set(case["task"]) - {"profile", "input", "answer_policy"}:
        raise ProtocolError("task accepts only profile, input and public answer_policy")
    capture = case.get("capture", [])
    if not isinstance(capture, list) or any(not isinstance(item, str) for item in capture):
        raise ProtocolError("capture must be list[str]")
    for step in case.get("steps", []):
        if step.get("action") not in ACTIONS:
            raise ProtocolError(f"unsupported action: {step.get('action')}")
    policy = case["task"].get("answer_policy", {})
    if policy.get("mode", "fixed") not in {"fixed", "skip"}:
        raise AdapterBlocked("bounded model answerer/other answer strategy is not implemented or authorized")
    return deepcopy(case)


def fixed_answers(questions: list[dict], policy: dict) -> list[dict]:
    """Exact question text/ID and option label/ID rules; never position guesses.

    policy={mode:'fixed',facts:{name:public text},rules:[{question:exact text OR
    question_id:actual ID, fact:name OR custom_text:public text OR
    option_labels:[exact labels] OR option_ids:[actual IDs]}],allow_skip:bool}.
    Every actual question must have exactly one rule. A fact/custom answer needs
    allow_custom; option rules must match current IDs/labels unambiguously.
    """
    if policy.get("mode", "fixed") != "fixed":
        raise AdapterBlocked("only fixed public clarification rules are implemented")
    answers = []
    for question in questions:
        rules = [rule for rule in policy.get("rules", [])
                 if (rule.get("question_id") == question["id"] if "question_id" in rule
                     else rule.get("question") == question["question"])]
        facts = policy.get("facts")
        if not rules and isinstance(facts, str) and facts.strip() and question.get("allow_custom"):
            rules = [{"custom_text": facts}]
        if len(rules) != 1:
            raise ProtocolError(f"no unique public answer rule for actual question {question['id']}")
        rule = rules[0]
        modes = [key for key in ("fact", "custom_text", "option_ids", "option_labels") if key in rule]
        if len(modes) != 1:
            raise ProtocolError("answer rule needs exactly one explicit mapping")
        answer = {"question_id": question["id"], "option_ids": [], "custom_text": ""}
        mode = modes[0]
        if mode in {"fact", "custom_text"}:
            facts = policy.get("facts", {})
            text = facts.get(rule["fact"]) if mode == "fact" and isinstance(facts, dict) else rule.get("custom_text")
            if not question.get("allow_custom") or not isinstance(text, str) or not text.strip():
                raise ProtocolError("public fact unavailable or actual question disallows custom answers")
            answer["custom_text"] = text.strip()
        elif mode == "option_ids":
            answer["option_ids"] = list(rule[mode])
        else:
            for label in rule[mode]:
                matching = [option["id"] for option in question["options"] if option["label"] == label]
                if len(matching) != 1:
                    raise ProtocolError("public option rule does not uniquely match an actual option")
                answer["option_ids"].append(matching[0])
        answers.append(answer)
    try:
        resolve_answers(questions, answers, False)
    except Exception as exc:
        raise ProtocolError(f"invalid fixed clarification answers: {exc}") from exc
    return answers


class HyperknowAdapter:
    def __init__(self, base_url: str, data_dir: Path, *, fixture_manifest: Path | None = None,
                 client: httpx.Client | None = None):
        self.base_url = local_origin(base_url)
        self.database = isolated_database(Path(data_dir))
        author_directory = os.getenv("HK_DATA_DIR")
        if author_directory and Path(author_directory).resolve() == self.database.parent:
            raise AdapterBlocked("refusing the currently configured author data directory; use a separate explicit instance")
        if client is not None and not isinstance(client, httpx.Client):
            raise TypeError("client must be an actual httpx.Client")
        self.client = client or httpx.Client(base_url=self.base_url, trust_env=False,
                                            follow_redirects=False, timeout=15)
        self._own_client = client is None
        self.manifest = (json.loads(Path(fixture_manifest).read_text(encoding="utf-8"))
                         if fixture_manifest is not None else None)
        self._environment = None
        self._baseline = None
        self._attempted = set()

    def close(self):
        if self._own_client:
            self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def _get(self, path: str) -> dict:
        response = self.client.get(self.base_url + path, follow_redirects=False)
        response.raise_for_status()
        return response.json()

    def _health(self) -> dict:
        health = self._get("/api/health")
        if (health.get("status") != "ok" or health.get("database") != "ok"
                or health.get("storage_id") != storage_identity(self.database)):
            raise AdapterBlocked("HTTP health/storage_id does not match the isolated SQLite instance")
        return health

    def preflight(self, case: dict, bindings: dict | None = None) -> dict:
        case = public_case(case)
        if bindings is not None:
            if bindings["case"] != case:
                raise ProtocolError("resume public Case differs from the original bindings")
            self._guard(bindings)
            # A persisted in-flight action may already have committed resources
            # not yet bound here. recover verifies that one exact receipt first;
            # observe/act then perform the complete ownership inventory check.
            return deepcopy(bindings["environment"])
        health = self._health()
        model = health.get("model", {})
        if not model.get("configured") or not model.get("name"):
            raise AdapterBlocked("backend has no configured real model; connectivity remains unverified")
        names = {step["action"] for step in case.get("steps", [])}
        if names & {"course.create", "research.create", "course.answers"}:
            if not health.get("search", {}).get("configured"):
                raise AdapterBlocked("actual backend search configuration is not exposed/confirmed; no research may start")
            if case.get("completion", {}).get("strict_stage_only"):
                raise AdapterBlocked("course clarification/research automatically continues; no strict stage-only boundary")
        if self._environment is not None:
            if self._environment["model"] != model["name"]:
                raise AdapterBlocked("backend model changed")
            return deepcopy(self._environment)
        with readonly(self.database) as conn:
            rows = records(conn)
            baseline_digest = snapshot_digest(conn)
            if self.manifest is None:
                if any(rows.values()):
                    raise AdapterBlocked("pre-existing data requires an explicit real fixture manifest")
            else:
                manifest = self.manifest
                snapshot = manifest.get("snapshot", {})
                source = snapshot.get("source", {})
                if (manifest.get("schema_version") != 1 or snapshot.get("method") != "sqlite-logical-v1"
                        or source.get("kind") not in {"sqlite-backup", "sqlite-consistent-read"} or not source.get("origin")
                        or snapshot.get("sha256") != baseline_digest):
                    raise AdapterBlocked("fixture consistent snapshot identity/digest mismatch")
                declarations = {(r["table"], r["id"]): r for r in manifest.get("resources", [])}
                if len(declarations) != len(manifest.get("resources", [])):
                    raise AdapterBlocked("duplicate fixture resource")
                actual = {(table, row["id"]) for table, data in rows.items()
                          if table != "command_receipts" for row in data}
                if actual != set(declarations):
                    raise AdapterBlocked("fixture manifest must inventory every existing data resource")
                for (table, identity), declaration in declarations.items():
                    data = row_data(conn, table, identity)
                    provenance = declaration.get("source", {})
                    if (sha256(data) != declaration.get("sha256")
                            or provenance.get("kind") != "business-generated" or not provenance.get("origin")):
                        raise AdapterBlocked("fixture resource hash/provenance mismatch")
                    try:
                        verify_fixture_source(conn, table, identity, provenance.get("run_id", ""))
                    except ValueError as exc:
                        raise AdapterBlocked(str(exc)) from exc
                if any(json.loads(row["data"])["status"] not in TERMINAL for row in rows["runs"]):
                    raise AdapterBlocked("fixture contains active or waiting runs; isolation is not safe")
            self._baseline = {table: {row["id"]: sha256(row) for row in data} for table, data in rows.items()}
        self._environment = {"adapter_version": 1, "base_url": self.base_url,
                             "database": str(self.database), "storage_id": storage_identity(self.database),
                             "instance": database_instance(self.database), "model": model["name"],
                             "fixture_manifest_sha256": sha256(self.manifest),
                             "fixture_snapshot_sha256": baseline_digest,
                             "backend_code_version": None,
                             "capability_gaps": ["health does not advertise backend code or provider connectivity",
                                                 "source has no durable historical checkpoint log"]}
        return deepcopy(self._environment)

    def prepare(self, case: dict) -> dict:
        case = public_case(case)
        environment = self.preflight(case)
        refs = {}
        declared = (self.manifest or {}).get("bindings", {})
        required = case.get("prerequisites", {}).get("resources", {})
        if not isinstance(required, dict):
            raise ProtocolError("prerequisites.resources must map aliases to {kind}")
        for alias, resource in required.items():
            checked_id(alias)
            ref = declared.get(alias)
            if not isinstance(ref, dict) or ref.get("kind") != resource.get("kind"):
                raise AdapterBlocked("required alias/kind has no explicit real fixture binding")
            ref = {key: ref[key] for key in ("kind", "id")}
            resource_path(ref["kind"], ref["id"])
            if ref["kind"] == "exam":
                ref = {"kind": "quiz_target", "id": "exam:" + ref["id"]}
            refs[alias] = ref
        bindings = {"schema_version": 1, "case": case, "environment": environment,
                    "baseline": deepcopy(self._baseline), "refs": refs,
                    "run_ids": [], "executions": []}
        snapshots = crosscheck(self.client, self.database, refs, base_url=self.base_url)
        for step in case.get("steps", []):
            if step["action"] == "quiz.prepare" and step.get("input", {}).get("target_type") == "practice":
                selector = step.get("input", {}).get("target")
                candidates = [(alias, ref) for alias, ref in refs.items()
                              if ref["kind"] == "session" and (selector is None or alias == selector)]
                if len(candidates) == 1:
                    alias, ref = candidates[0]
                    refs["practice_" + alias] = {"kind": "quiz_target", "id": "practice:" + ref["id"]}
        if refs != bindings["refs"]:
            bindings["refs"] = refs
        snapshots = crosscheck(self.client, self.database, refs, base_url=self.base_url)
        self._validate_fixture_refs(refs, snapshots)
        self._fresh_targets(case, refs, snapshots)
        return bindings

    def _validate_fixture_refs(self, refs: dict, snapshots: dict):
        inventory = {(r["table"], r["id"]) for r in (self.manifest or {}).get("resources", [])}
        tables = {"course": "courses", "run": "runs", "conversation": "assistance_conversations",
                  "artifact": "assistance_artifacts"}
        for alias, ref in refs.items():
            snapshot = snapshots[alias]
            if ref["kind"] in tables and (tables[ref["kind"]], ref["id"]) not in inventory:
                raise AdapterBlocked("fixture binding points outside declared resource inventory")
            if ref["kind"] in {"session", "quiz_target"}:
                if ("courses", snapshot["course_id"]) not in inventory:
                    raise AdapterBlocked("activity is not owned by a declared fixture course")

    def _fresh_targets(self, case: dict, refs: dict, snapshots: dict):
        for step in case.get("steps", []):
            name, data = step["action"], step.get("input", {})
            if not isinstance(data, dict):
                raise ProtocolError("action input must be an object")
            if name in {"lesson.prepare", "quiz.prepare"}:
                kind = "session" if name == "lesson.prepare" else "quiz_target"
                selector = data.get("session" if kind == "session" else "target")
                if kind == "quiz_target" and selector in refs and refs[selector]["kind"] == "session":
                    selector = "practice_" + selector
                candidates = [(alias, snapshots[alias]) for alias, ref in refs.items()
                              if ref["kind"] == kind and (selector is None or selector == alias)]
                for _, snapshot in candidates:
                    if snapshot.get("script" if kind == "session" else "quiz") or snapshot.get("generation_run"):
                        raise AdapterBlocked("target already has an output/generation history; prepare would reuse it")
                    if kind == "quiz_target" and snapshot["target_type"] == "practice":
                        with readonly(self.database) as conn:
                            lesson = product_snapshot(conn, "session", snapshot["target_id"])
                        if not lesson.get("script"):
                            raise AdapterBlocked("practice requires a real prerequisite lesson; no implicit generation")

    def _inventory_guard(self, bindings: dict):
        """A fixture is an allowlist, not permission to share an active library."""
        with readonly(self.database) as conn:
            current = records(conn)
            baseline = bindings["baseline"]
            for table, rows in baseline.items():
                if not set(rows).issubset({row["id"] for row in current[table]}):
                    raise ProtocolError("baseline resource/receipt disappeared; possible rollback or external deletion")
            runs = {r["id"]: json.loads(r["data"]) for r in current["runs"]}
            known_runs = set(bindings["run_ids"])
            refs = bindings["refs"].values()
            sessions = {r["id"] for r in refs if r["kind"] == "session"}
            conversations = {r["id"] for r in refs if r["kind"] == "conversation"}
            targets = {r["id"] for r in refs if r["kind"] == "quiz_target"}
            receipts = {e["command_id"] for e in bindings["executions"]}
            courses = {run.get("course_id") for rid, run in runs.items() if rid in known_runs}
            for table, rows in current.items():
                for row in rows:
                    if row["id"] in baseline[table]:
                        if sha256(row) != baseline[table][row["id"]]:
                            mutable = (table == "runs" and row["id"] in known_runs
                                       or table == "courses" and row["id"] in courses
                                       or table == "assistance_conversations" and row["id"] in conversations
                                       or table == "lesson_states" and row["id"] in sessions
                                       or table == "quiz_states" and row["id"] in targets
                                       or table == "assistance_artifacts" and any(
                                           e["resource"] == {"kind": "artifact", "id": row["id"]}
                                           for e in bindings["executions"]))
                            if not mutable:
                                raise ProtocolError("immutable fixture resource was modified externally")
                        continue
                    data = json.loads(row["data"]) if "data" in row else {}
                    allowed = False
                    if table == "runs":
                        allowed = row["id"] in known_runs
                    elif table == "command_receipts":
                        allowed = row["id"] in receipts
                    elif table == "model_calls":
                        allowed = row["run_id"] in known_runs
                    elif table == "courses":
                        allowed = row["id"] in courses and data.get("creation_run_id") in known_runs
                    elif table == "assistance_conversations":
                        allowed = row["id"] in conversations
                    elif table == "assistance_artifacts":
                        allowed = data.get("conversation_id") in conversations and any(
                            run.get("turn_id") == data.get("turn_id") for rid, run in runs.items() if rid in known_runs)
                    elif table == "lesson_states":
                        allowed = row["id"] in sessions
                    elif table == "lesson_scripts":
                        allowed = row["session_id"] in sessions and any(
                            run.get("script_id") == row["id"] for rid, run in runs.items() if rid in known_runs)
                    elif table == "lesson_interactions":
                        allowed = data.get("run_id") in known_runs
                    elif table == "quiz_states":
                        allowed = row["id"] in targets
                    elif table == "quizzes":
                        allowed = any(run.get("quiz_id") == row["id"] for rid, run in runs.items() if rid in known_runs)
                    if not allowed:
                        raise ProtocolError(f"unowned new resource in isolated trial: {table}/{row['id']}")

    def _guard(self, bindings: dict):
        environment = bindings["environment"]
        if (environment["base_url"] != self.base_url or environment["database"] != str(self.database)
                or environment["instance"] != database_instance(self.database)
                or environment["fixture_manifest_sha256"] != sha256(self.manifest)):
            raise AdapterBlocked("resume environment/instance/fixture identity changed")
        health = self._health()
        if health.get("model", {}).get("name") != environment["model"]:
            raise AdapterBlocked("backend model changed since preflight")
        with readonly(self.database) as conn:
            for execution in bindings["executions"]:
                saved = verified_receipt(conn, execution["command_id"], execution["payload"], execution["receipt_type"])
                if saved != execution["receipt"]:
                    raise ProtocolError("known command receipt disappeared/changed; possible rollback")
                for identity, version in execution.get("run_versions", {}).items():
                    run = row_data(conn, "runs", identity)
                    if run["version"] < version:
                        raise ProtocolError("run version rolled back")
                    expected_identity = execution.get("run_identity_sha256", {}).get(identity)
                    if expected_identity is not None and run_identity(run) != expected_identity:
                        raise ProtocolError("original immutable run identity/input changed")
                for resource in execution.get("resource_versions", []):
                    snapshot = product_snapshot(conn, resource["kind"], resource["id"])
                    if snapshot.get("version", 0) < resource["version"]:
                        raise ProtocolError("observed resource version rolled back")
            for identity in bindings["run_ids"]:
                run = row_data(conn, "runs", identity)
                if run.get("kind") == "assistance":
                    conversation = product_snapshot(conn, "conversation", run["conversation_id"])
                    turn = next((t for t in conversation["turns"] if t["turn_id"] == run["turn_id"]), None)
                    if turn is None or turn["run_id"] != identity:
                        raise ProtocolError("original turn now points to a retry/replacement run")
                if run.get("kind") == "question":
                    interaction = row_data(conn, "lesson_interactions", run["interaction_id"])
                    if interaction["run_id"] != identity:
                        raise ProtocolError("original interaction now points to a retry/replacement run")
                descendants = [json.loads(r[0]) for r in conn.execute("SELECT data FROM runs")]
                if any(r.get("parent_run_id") == identity for r in descendants):
                    raise ProtocolError("original business run was retried; no replacement execution is accepted")

    def _snapshots(self, bindings: dict) -> tuple[dict, dict]:
        refs = deepcopy(bindings["refs"])
        for identity in bindings["run_ids"]:
            refs.setdefault("run_" + identity, {"kind": "run", "id": identity})
        snapshots = crosscheck(self.client, self.database, refs, base_url=self.base_url)
        additions = {}
        for snapshot in snapshots.values():
            if "run_id" in snapshot and snapshot.get("course_id"):
                additions.setdefault("course_" + snapshot["course_id"], {"kind": "course", "id": snapshot["course_id"]})
            if "conversation_id" in snapshot and "turns" in snapshot:
                for turn in snapshot["turns"]:
                    for artifact in turn.get("artifacts", []):
                        additions["artifact_" + artifact["artifact_id"]] = {"kind": "artifact", "id": artifact["artifact_id"]}
        additions = {key: value for key, value in additions.items() if key not in refs}
        if additions:
            refs.update(additions)
            # Freeze all resources at the same observed version, not mixed reads.
            snapshots = crosscheck(self.client, self.database, refs, base_url=self.base_url)
        return refs, snapshots

    def observe(self, bindings: dict) -> dict:
        self._guard(bindings)
        self._inventory_guard(bindings)
        with readonly(self.database) as conn:
            model_calls = sum(row["run_id"] in bindings["run_ids"]
                              and row["id"] not in bindings["baseline"]["model_calls"]
                              for row in conn.execute("SELECT id,run_id FROM model_calls"))
        try:
            refs, snapshots = self._snapshots(bindings)
        except ValueError as exc:
            if "evidence gap:" not in str(exc):
                raise
            return {"state": "running", "outcome": None, "actions": [], "resources": {},
                    "checkpoints": [], "gaps": [str(exc)], "model_calls": model_calls,
                    "model_calls_coverage": "saved_calls_only"}
        actions, checkpoints = set(), set()
        runs = [snapshot for alias, snapshot in snapshots.items() if refs[alias]["kind"] == "run"]
        active = [run for run in runs if run["status"] in ACTIVE]
        waiting = [run for run in runs if run["status"] in {"awaiting_answers", "awaiting_blueprint"}]
        if any(run["status"] in ACTIVE | {"awaiting_answers", "awaiting_blueprint"} for run in runs):
            actions.add("run.cancel")
        for alias, snapshot in snapshots.items():
            kind = refs[alias]["kind"]
            if kind == "conversation" and not snapshot.get("active_run"):
                actions.add("assistance.message")
                if not snapshot["turns"]:
                    checkpoints.add("conversation.created")
                if snapshot["turns"]:
                    turn = snapshot["turns"][-1]
                    if turn["run_id"] in bindings["run_ids"] and turn["status"] == "ready":
                        checkpoints.add("turn.saved")
                        if turn.get("response", {}).get("waiting_for") == "continue":
                            actions.add("assistance.continue")
                        if turn.get("response", {}).get("waiting_for") in {"answer", "continue"}:
                            waiting.append({"kind": "assistance"})
            elif kind == "run":
                if snapshot["status"] == "awaiting_answers":
                    actions.add("course.answers")
                    checkpoints.add("clarification.ready")
                if snapshot["status"] == "awaiting_blueprint":
                    actions.add("course.blueprint")
                    checkpoints.add("blueprint.awaiting")
                if snapshot.get("research", {}).get("report"):
                    checkpoints.add("research.saved")
                if snapshot["status"] in TERMINAL:
                    checkpoints.add("run.terminal")
            elif kind == "course" and snapshot.get("creation_run_id") in bindings["run_ids"]:
                if snapshot.get("structure_status") == "ready":
                    checkpoints.add("course.ready")
                for unit in snapshot["units"]:
                    if unit.get("generation_status") == "ready":
                        checkpoints.add("unit.saved:" + unit["unit_id"])
            elif kind == "session":
                if not snapshot.get("script") and not snapshot.get("generation_run"):
                    actions.add("lesson.prepare")
                if snapshot.get("script") and not any(i["status"] == "pending" for i in snapshot["interactions"]):
                    actions.update({"lesson.progress", "lesson.question"})
                generation = snapshot.get("generation_run")
                if generation and generation["run_id"] in bindings["run_ids"] and generation["status"] == "ready":
                    checkpoints.add("lesson.saved")
                if any(i["run_id"] in bindings["run_ids"] and i["status"] == "ready" for i in snapshot["interactions"]):
                    checkpoints.add("question.saved")
            elif kind == "quiz_target":
                if not snapshot.get("quiz") and not snapshot.get("generation_run"):
                    actions.add("quiz.prepare")
                generation = snapshot.get("generation_run")
                if generation and generation["run_id"] in bindings["run_ids"] and generation["status"] == "ready" and snapshot.get("quiz"):
                    checkpoints.add("quiz.saved")
            elif kind == "artifact" and snapshot["kind"] == "whiteboard":
                if not active:
                    actions.add("artifact.progress")
        # Artifact creation is committed only with its original successful turn.
        for alias, artifact in snapshots.items():
            if refs[alias]["kind"] != "artifact":
                continue
            for run in runs:
                if (run.get("turn_id") == artifact["turn_id"] and run["status"] == "ready"
                        and run.get("conversation_id") == artifact["conversation_id"]):
                    conversation = next((s for a, s in snapshots.items() if refs[a]["kind"] == "conversation"
                                         and s["conversation_id"] == artifact["conversation_id"]), None)
                    turn = next((t for t in (conversation or {}).get("turns", []) if t["turn_id"] == artifact["turn_id"]), None)
                    if turn and turn["run_id"] == run["run_id"] and turn["status"] == "ready" and artifact in turn["artifacts"]:
                        checkpoints.add("artifact.saved")
        if not bindings["executions"] and not active:
            actions.update({"conversation.create", "course.create", "research.create"})
        state = ("running" if active else "waiting" if waiting else "terminal" if runs
                 else "waiting" if bindings["executions"] else "preparing")
        outcome = None
        if state == "terminal":
            statuses = {run["status"] for run in runs}
            outcome = next((s for s in ("failed", "interrupted", "cancelled") if s in statuses), "success")
        gaps = []
        unsafe_cancel = any(execution["name"] == "run.cancel"
                            and execution.get("cancelled_from") in {"generating", "clarifying"}
                            for execution in bindings["executions"])
        if unsafe_cancel:
            state = "blocked"
            gaps.append("execution_settlement_unverified: cancellation committed, but source does not expose worker/provider completion")
        return {"state": state, "outcome": outcome, "actions": sorted(actions),
                "resources": {alias: {**ref, "version": snapshots[alias].get("version"),
                                       "snapshot": snapshots[alias]} for alias, ref in refs.items()},
                "checkpoints": sorted(checkpoints), "observed_at": now(),
                "gaps": gaps, "model_calls": model_calls, "model_calls_coverage": "saved_calls_only",
                **({"error": gaps[0]} if unsafe_cancel else {})}

    @staticmethod
    def _select(resources: dict, kind: str, alias: str | None = None) -> tuple[str, dict]:
        candidates = [(key, value) for key, value in resources.items()
                      if value["kind"] == kind and (alias is None or alias == key)]
        # Multiple aliases for the same resource are not ambiguous.
        unique = {value["id"]: (key, value) for key, value in candidates}
        if len(unique) != 1:
            raise ProtocolError(f"select one bound {kind} alias explicitly")
        return next(iter(unique.values()))

    def build_action(self, step: dict, observation: dict, bindings: dict, command_id: str) -> dict:
        self._guard(bindings)
        if not isinstance(command_id, str) or not 8 <= len(command_id) <= 120:
            raise ProtocolError("client command ID must be 8--120 characters")
        name = step["action"]
        if name not in ACTIONS or name not in observation["actions"]:
            raise ProtocolError("action is not legal in this observation")
        data = deepcopy(step.get("input", {}))
        if not isinstance(data, dict):
            raise ProtocolError("action input must be an object")
        resources = observation["resources"]
        body, payload, receipt_type, method = {"client_command_id": command_id}, {}, "run", "POST"
        target = None
        if name == "conversation.create":
            if data:
                raise ProtocolError("conversation.create takes empty input")
            path, payload, receipt_type = "/api/assistance/conversations", {"action": "create_assistance_conversation"}, "conversation"
        elif name in {"course.create", "research.create"}:
            task_input = bindings["case"]["task"]["input"]
            goal = data.get("goal", task_input)
            if isinstance(goal, dict):
                goal = goal.get("goal")
            body["goal"] = goal
            path = "/api/course-runs" if name == "course.create" else "/api/research-runs"
            payload = {"action": "create" if name == "course.create" else "research", "goal": goal}
            if name == "research.create":
                body["context"] = data.get("context", task_input.get("context", "") if isinstance(task_input, dict) else "")
                payload["context"] = body["context"]
        elif name.startswith("assistance."):
            _, target = self._select(resources, "conversation", data.get("conversation"))
            snapshot = target["snapshot"]
            if snapshot.get("active_run"):
                raise ProtocolError("selected conversation still has an active run")
            text = data.get("text", "" if name.endswith("continue") else bindings["case"]["task"]["input"])
            previous = snapshot["turns"][-1] if snapshot["turns"] else None
            if name == "assistance.continue" and (previous is None or previous["status"] != "ready"
                    or previous.get("response", {}).get("waiting_for") != "continue"):
                raise ProtocolError("selected conversation has no authoritative pending continuation")
            if name == "assistance.message" and "text" not in data and previous and previous.get("response", {}).get("waiting_for") == "answer":
                policy = bindings["case"]["task"].get("answer_policy", {})
                if policy.get("mode") != "fixed" or not isinstance(policy.get("facts"), str) or not policy["facts"].strip():
                    raise ProtocolError("assistance clarification needs explicit text or fixed public facts")
                text = policy["facts"].strip()
            if isinstance(text, dict):
                text = text.get("text")
            artifact_id = None
            if data.get("artifact"):
                _, artifact = self._select(resources, "artifact", data["artifact"])
                if artifact["snapshot"]["conversation_id"] != target["id"] or artifact["snapshot"]["kind"] != "whiteboard":
                    raise ProtocolError("artifact is not a whiteboard owned by the selected conversation")
                artifact_id = artifact["id"]
            body.update(expected_version=snapshot["version"], text=text,
                        action="continue" if name.endswith("continue") else "message", artifact_id=artifact_id)
            path, receipt_type = resource_path("conversation", target["id"]) + "/turns", "conversation"
            payload = {"command": "assistance_turn", "conversation_id": target["id"], **body}
        elif name.startswith("course.") or name == "run.cancel":
            allowed_status = ({"awaiting_answers"} if name == "course.answers" else {"awaiting_blueprint"}
                              if name == "course.blueprint" else ACTIVE | {"awaiting_answers", "awaiting_blueprint"})
            legal = {alias: ref for alias, ref in resources.items()
                     if ref["kind"] != "run" or ref["snapshot"]["status"] in allowed_status}
            _, target = self._select(legal, "run", data.get("run"))
            run = target["snapshot"]
            body["expected_version"] = run["version"]
            action = name.split(".")[1]
            payload = {"run_id": target["id"], "version": run["version"], "action": action}
            path = resource_path("run", target["id"]) + "/" + action
            if name == "course.answers":
                policy = bindings["case"]["task"].get("answer_policy", {})
                skip = data.get("skip", policy.get("mode") == "skip")
                if skip and not (policy.get("allow_skip", False) or policy.get("mode") == "skip"):
                    raise ProtocolError("clarification skip was not explicitly allowed by the Case")
                answers = [] if skip else fixed_answers(run["questions"], policy)
                body.update(skip=skip, answers=answers)
                payload.update(skip=skip, answers=answers)
            elif name == "course.blueprint":
                _, course = self._select(resources, "course", data.get("course"))
                saved = course["snapshot"]
                if (saved.get("creation_run_id") != run["run_id"]
                        or saved.get("blueprint_version") != run.get("blueprint_version")
                        or saved.get("structure_status") != "blueprint" or run.get("approved_blueprint_version")):
                    raise ProtocolError("approval does not refer to the current unapproved blueprint version")
                body.update(approve=data["approve"], feedback=data.get("feedback", "").strip())
                payload.update(approve=body["approve"], feedback=body["feedback"])
        elif name.startswith("lesson."):
            _, target = self._select(resources, "session", data.get("session"))
            snapshot = target["snapshot"]
            suffix = {"lesson.prepare": "prepare", "lesson.progress": "progress", "lesson.question": "questions"}[name]
            path, receipt_type = resource_path("session", target["id"]) + "/" + suffix, "session"
            if name == "lesson.prepare":
                if snapshot.get("script") or snapshot.get("generation_run"):
                    raise ProtocolError("lesson prepare target is not fresh")
                payload = {"action": "prepare", "session_id": target["id"]}
            else:
                progress = snapshot["progress"]
                body.update(expected_version=progress["version"], script_id=snapshot["script"]["script_id"])
                if name == "lesson.progress":
                    cursor = data.get("cursor", "next")
                    cursor = progress["cursor"] + 1 if cursor == "next" else cursor
                    if type(cursor) is not int or cursor not in {progress["cursor"], progress["cursor"] + 1} or cursor >= len(snapshot["script"]["steps"]):
                        raise ProtocolError("lesson cursor can only hold or advance one saved step")
                    body.update(cursor=cursor, play_intent=data.get("play_intent", "paused"))
                    method, action = "PUT", "progress"
                else:
                    if progress["play_intent"] != "paused":
                        raise ProtocolError("save an explicit paused lesson.progress before asking a question")
                    body.update(cursor=progress["cursor"], question=data["question"], was_playing=data.get("was_playing", False))
                    action = "question"
                payload = {"action": action, "session_id": target["id"], **body}
        elif name == "quiz.prepare":
            selector = data.get("target")
            if selector in resources and resources[selector]["kind"] == "session":
                selector = "practice_" + selector
            _, target = self._select(resources, "quiz_target", selector)
            target_type, target_id = target["id"].split(":", 1)
            if data.get("target_type", target_type) != target_type:
                raise ProtocolError("quiz target_type differs from bound target")
            snapshot = target["snapshot"]
            if snapshot.get("quiz") or snapshot.get("generation_run"):
                raise ProtocolError("quiz prepare target is not fresh")
            path, receipt_type = resource_path("quiz_target", target["id"]) + "/prepare", "quiz_target"
            payload = {"action": "quiz_prepare", "target_type": target_type, "target_id": target_id}
        else:  # artifact.progress
            _, target = self._select(resources, "artifact", data.get("artifact"))
            artifact = target["snapshot"]
            if artifact["kind"] != "whiteboard":
                raise ProtocolError("only a committed whiteboard supports progress")
            previous = artifact["data"]["cursor"]
            cursor = data.get("cursor", "next")
            cursor = previous + 1 if cursor == "next" else cursor
            if type(cursor) is not int or cursor not in {previous, previous + 1} or cursor >= len(artifact["data"]["steps"]):
                raise ProtocolError("artifact cursor can only hold or advance one step")
            body.update(expected_version=artifact["version"], cursor=cursor)
            path, receipt_type, method = resource_path("artifact", target["id"]) + "/progress", "artifact", "PUT"
            payload = {"command": "assistance_progress", "artifact_id": target["id"], **body}
        # Use actual API models to freeze normalized defaults/whitespace, exactly
        # as model_dump passed to product storage (not a guessed fingerprint).
        from .assistance_api import ArtifactProgress, AssistanceCommand, SubmitTurn
        from .main import (AskQuestion, ChangeRun, Command, CreateResearch, CreateRun,
                           SaveProgress, SubmitAnswers, SubmitBlueprint)
        schemas = {"conversation.create": AssistanceCommand, "assistance.message": SubmitTurn,
                   "assistance.continue": SubmitTurn, "course.create": CreateRun, "research.create": CreateResearch,
                   "course.answers": SubmitAnswers, "course.blueprint": SubmitBlueprint,
                   "run.cancel": ChangeRun, "lesson.prepare": Command, "lesson.progress": SaveProgress,
                   "lesson.question": AskQuestion, "quiz.prepare": Command, "artifact.progress": ArtifactProgress}
        normalized = schemas[name].model_validate(body).model_dump()
        if sha256(normalized) != sha256(body):
            raise ProtocolError("action input needs normalization; provide already stripped legal product values")
        replacement = deepcopy(bindings)
        replacement["refs"].update({alias: {key: ref[key] for key in ("kind", "id")}
                                    for alias, ref in resources.items()})
        return {"schema_version": 1, "name": name, "step_id": step["id"], "input": data,
                "command_id": command_id, "method": method, "path": path,
                "url": self.base_url + path, "body": body, "receipt_payload": payload,
                "receipt_type": receipt_type, "bindings": replacement,
                "before": deepcopy(resources), "target": deepcopy(target),
                "checkpoint": step.get("checkpoint")}

    def _validate_action(self, action: dict):
        """No arbitrary request dispatch, including edited persisted actions."""
        step = {"id": action["step_id"], "action": action["name"], "input": action["input"],
                "checkpoint": action.get("checkpoint")}
        expected = self.build_action(step, {"actions": [action["name"]], "resources": action["before"]},
                                     action["bindings"], action["command_id"])
        for key in ("schema_version", "name", "step_id", "method", "path", "url", "body",
                    "receipt_payload", "receipt_type", "target"):
            if sha256(action.get(key)) != sha256(expected.get(key)):
                raise ProtocolError(f"persisted action {key} does not match the finite product request")

    def act(self, action: dict) -> dict:
        self._validate_action(action)
        command_id = action["command_id"]
        with readonly(self.database) as conn:
            saved = verified_receipt(conn, command_id, action["receipt_payload"], action["receipt_type"])
        if saved is not None:
            result = self.recover(action)
            if result is None:
                raise ProtocolError("confirmed receipt cannot be associated with its original execution")
            return result
        if command_id in self._attempted or action.get("status") in {"in_flight", "unknown", "sent"}:
            raise AdapterBlocked("in-flight command has no verified receipt; never resend unknown submission")
        self._inventory_guard(action["bindings"])
        self._attempted.add(command_id)
        # Exactly one write, no retry, no compensating command, no model driver.
        response = self.client.request(action["method"], action["url"], json=action["body"],
                                       follow_redirects=False)
        response.raise_for_status()
        result = self.recover(action)
        if result is None:
            raise AdapterBlocked("write response lacks its original durable receipt; submission is unknown")
        return result

    def recover(self, action: dict) -> dict | None:
        self._validate_action(action)
        bindings = deepcopy(action["bindings"])
        self._guard(bindings)
        name, body = action["name"], action["body"]
        with readonly(self.database) as conn:
            receipt = verified_receipt(conn, action["command_id"], action["receipt_payload"], action["receipt_type"])
            if receipt is None:
                return None  # Caller must block, not use this as permission to POST.
            identity = receipt["run_id"]
            kind = action["receipt_type"]
            if kind not in {"conversation", "session", "artifact", "run", "quiz_target"}:
                raise ProtocolError("unsupported original receipt resource")
            if action["target"] is not None and identity != action["target"]["id"]:
                raise ProtocolError("receipt points to a different resource")
            snapshot = product_snapshot(conn, kind, identity)
            run = None
            if name in {"course.create", "research.create"}:
                run = snapshot
                if (run.get("parent_run_id") is not None or run["goal"] != body["goal"]
                        or run.get("kind", "course") != ("course" if name == "course.create" else "research")):
                    raise ProtocolError("create receipt no longer identifies the original business run")
                if name == "research.create" and run["input"] != {"goal": body["goal"], "context": body["context"]}:
                    raise ProtocolError("research input differs from original action")
            elif name in {"assistance.message", "assistance.continue"}:
                before = action["target"]["snapshot"]["turns"]
                current = snapshot["turns"]
                if ([t["turn_id"] for t in current[:len(before)]] != [t["turn_id"] for t in before]
                        or len(current) <= len(before)):
                    raise ProtocolError("original turn prefix disappeared or original action has no saved turn")
                turn = current[len(before)]
                run = row_data(conn, "runs", turn["run_id"])
                if (run.get("parent_run_id") is not None or run.get("conversation_id") != identity
                        or run.get("turn_id") != turn["turn_id"] or run["kind"] != "assistance"
                        or turn["user_text"] != body["text"] or turn["action"] != body["action"]
                        or run["input"]["text"] != body["text"] or run["input"]["action"] != body["action"]
                        or run["input"].get("artifact_id") != body["artifact_id"]):
                    raise ProtocolError("original turn was retried/replaced or its frozen input changed")
                if body["action"] == "continue":
                    previous = next((t for t in reversed(before) if t["status"] == "ready"), None)
                    continuation = run["input"].get("continuation_state", {})
                    if (previous is None or continuation.get("plan") != previous["response"]["plan"]
                            or continuation.get("current_step") != previous["response"]["current_step"] + 1):
                        raise ProtocolError("continuation was not bound to the original saved plan")
            elif name in {"lesson.prepare", "quiz.prepare"}:
                run = snapshot.get("generation_run")
                if run is None or run.get("parent_run_id") is not None:
                    raise ProtocolError("prepare reused a missing/pre-existing/replacement run")
                existing_ids = {ref["snapshot"]["run_id"] for ref in action["before"].values() if ref["kind"] == "run"}
                if run["run_id"] in existing_ids or run["run_id"] in bindings["baseline"]["runs"]:
                    raise ProtocolError("prepare returned an inherited run, not this execution")
                if name == "lesson.prepare" and (run["kind"] != "lesson" or run["session_id"] != identity):
                    raise ProtocolError("lesson generation ownership mismatch")
                if name == "quiz.prepare" and (run["kind"] != "quiz"
                        or f"{run['target_type']}:{run['target_id']}" != identity):
                    raise ProtocolError("quiz generation ownership mismatch")
            elif name == "lesson.question":
                before = action["target"]["snapshot"]["interactions"]
                old_ids = {i["interaction_id"] for i in before}
                matching = [i for i in snapshot["interactions"] if i["interaction_id"] not in old_ids
                            and i["question"] == body["question"] and i["script_id"] == body["script_id"]
                            and i["cursor"] == body["cursor"]]
                if len(matching) != 1:
                    raise ProtocolError("cannot uniquely identify original question interaction")
                interaction = matching[0]
                run = row_data(conn, "runs", interaction["run_id"])
                if run.get("parent_run_id") is not None or run.get("interaction_id") != interaction["interaction_id"]:
                    raise ProtocolError("original question points to a replacement run")
            elif name in {"course.answers", "course.blueprint", "run.cancel"}:
                run = snapshot
                if run["version"] <= body["expected_version"]:
                    raise ProtocolError("receipt exists but original run mutation was rolled back")
                if name == "course.answers" and (not run["answers_submitted"] or run["skipped"] != body["skip"]):
                    raise ProtocolError("original clarification submission not present")
                if name == "course.answers":
                    expected_answers = resolve_answers(action["target"]["snapshot"]["questions"], body["answers"], body["skip"])
                    if run["answers"] != expected_answers:
                        raise ProtocolError("saved clarification answers differ from the original command")
                if name == "course.blueprint" and body["approve"]:
                    original = action["target"]["snapshot"]["blueprint_version"]
                    if run.get("approved_blueprint_version") != original:
                        raise ProtocolError("approved blueprint is not the original observed version")
                if name == "run.cancel" and run["status"] != "cancelled":
                    raise ProtocolError("original cancellation is absent")
            elif name == "lesson.progress":
                progress = snapshot["progress"]
                if (progress["version"] < body["expected_version"] or progress["script_id"] != body["script_id"]
                        or progress["cursor"] < body["cursor"]):
                    raise ProtocolError("saved lesson progress was rolled back or points to another script")
            elif name == "artifact.progress":
                if snapshot["version"] < body["expected_version"] or snapshot["data"]["cursor"] < body["cursor"]:
                    raise ProtocolError("saved artifact progress was rolled back")
            if run is not None:
                if run.get("parent_run_id") is not None and run["run_id"] not in bindings["run_ids"]:
                    raise ProtocolError("retry is a new execution, not recovery")
                if run["run_id"] not in bindings["run_ids"]:
                    bindings["run_ids"].append(run["run_id"])
                bindings["refs"].setdefault("run_" + run["run_id"], {"kind": "run", "id": run["run_id"]})
            alias = ("conversation" if name == "conversation.create" else "result_" + action["step_id"])
            bindings["refs"].setdefault(alias, {"kind": kind, "id": identity})
            execution = {"command_id": action["command_id"], "name": name,
                         "payload": deepcopy(action["receipt_payload"]), "receipt_type": kind,
                         "receipt": receipt, "run_ids": [run["run_id"]] if run else [],
                         "run_versions": {run["run_id"]: run["version"]} if run else {},
                         "run_identity_sha256": {run["run_id"]: run_identity(run)} if run else {},
                         "resource_versions": [{"kind": ref["kind"], "id": ref["id"], "version": ref["version"]}
                                               for ref in action["before"].values() if ref.get("version") is not None]
                                              + ([{"kind": kind, "id": identity, "version": snapshot["version"]}]
                                                 if snapshot.get("version") is not None else []),
                         "resource": {"kind": kind, "id": identity},
                         "version": snapshot.get("version"), "snapshot_sha256": sha256(snapshot)}
            if name == "run.cancel":
                execution["cancelled_from"] = action["target"]["snapshot"]["status"]
            bindings["executions"].append(execution)
        self._guard(bindings)
        self._inventory_guard(bindings)
        # A successful HTTP response may be newer than the command's commit.
        # Facts freeze this observed version, not a fabricated original response.
        return bindings

    def collect(self, observation: dict, bindings: dict) -> dict:
        self._guard(bindings)
        self._inventory_guard(bindings)
        refs = {alias: {key: ref[key] for key in ("kind", "id")}
                for alias, ref in observation["resources"].items()}
        current = crosscheck(self.client, self.database, refs, base_url=self.base_url)
        observed = {alias: ref["snapshot"] for alias, ref in observation["resources"].items()}
        if current != observed:
            raise AdapterBlocked("checkpoint changed since observe; do not substitute its newer resource version")
        with readonly(self.database) as conn:
            runs = {identity: row_data(conn, "runs", identity) for identity in bindings["run_ids"]}
            calls = [{**json.loads(row["data"]), "id": row["id"], "run_id": row["run_id"]}
                     for row in conn.execute("SELECT id,run_id,data FROM model_calls ORDER BY rowid")
                     if row["run_id"] in runs]
            for identity, run in runs.items():
                http = next((value for alias, value in observed.items()
                             if refs[alias] == {"kind": "run", "id": identity}), None)
                if http != run:
                    raise AdapterBlocked("run changed while freezing checkpoint evidence")
            artifacts = [json.loads(row["data"]) for row in conn.execute("SELECT data FROM assistance_artifacts")]
        turns = []
        for alias, snapshot in observed.items():
            if refs[alias]["kind"] == "conversation":
                turns.extend({"conversation_id": snapshot["conversation_id"], **turn} for turn in snapshot["turns"]
                             if turn["run_id"] in runs)
        turns = list({turn["turn_id"]: turn for turn in turns}.values())
        committed = [artifact for artifact in artifacts
                     if any(turn["turn_id"] == artifact["turn_id"] and turn["conversation_id"] == artifact["conversation_id"]
                            and turn["status"] == "ready" and runs[turn["run_id"]]["status"] == "ready"
                            and artifact in turn["artifacts"] for turn in turns)]
        declared = bindings["case"].get("capture", [])
        gaps = list(observation.get("gaps", []))
        gaps.extend("checkpoint unavailable in this frozen observation: " + checkpoint
                    for checkpoint in declared if checkpoint not in observation["checkpoints"])
        gaps.append("source has no durable historical checkpoint log; missed blueprint/unit versions cannot be reconstructed")
        gaps.append("persisted model_calls do not prove unrecorded/failed provider calls absent; usage is not filled with zero")
        return deepcopy({"schema_version": 1,
                         "source": {**bindings["environment"], "collected_at": now(),
                                    "fixture_resources": {table: sorted(rows) for table, rows in bindings["baseline"].items()},
                                    "inherited_call_ids": sorted(bindings["baseline"]["model_calls"])},
                         "runs": runs, "calls": calls, "resources": observed,
                         "artifacts": committed, "turns": turns,
                         "checkpoints": observation["checkpoints"], "gaps": gaps,
                         "observation": observation, "actions": bindings["executions"]})
