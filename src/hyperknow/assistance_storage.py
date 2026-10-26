"""Atomic independent teaching conversations on the shared run ledger."""

import json
from typing import Callable

from .domain import AppError, uid


ACTIVE = {"queued", "generating"}


class AssistanceStorage:
    def _conversation(self, conn, conversation_id: str) -> dict:
        conversation = self._get(conn, "assistance_conversations", conversation_id)
        active_id = conversation.get("active_run_id")
        conversation["active_run"] = self._get(conn, "runs", active_id) if active_id else None
        conversation.pop("active_run_id", None)
        return conversation

    def _save_conversation(self, conn, conversation: dict):
        from .storage import encode
        data = {key: value for key, value in conversation.items() if key != "active_run"}
        if "active_run" in conversation:
            active = conversation["active_run"]
            data["active_run_id"] = active["run_id"] if active else None
        conn.execute("INSERT INTO assistance_conversations VALUES (?,?) ON CONFLICT(id) "
                     "DO UPDATE SET data=excluded.data", (data["conversation_id"], encode(data)))

    def get_assistance_conversation(self, conversation_id: str) -> dict:
        with self.transaction() as conn:
            return self._conversation(conn, conversation_id)

    def list_assistance_conversations(self) -> list[dict]:
        with self.transaction() as conn:
            conversations = [self._conversation(conn, row["id"]) for row in
                             conn.execute("SELECT id FROM assistance_conversations")]
        return [{key: value for key, value in conversation.items() if key != "turns"}
                for conversation in sorted(conversations, key=lambda c: c["updated_at"], reverse=True)]

    def create_assistance_conversation(self, command_id: str) -> dict:
        from .storage import now
        def create(conn):
            timestamp = now()
            conversation = {"conversation_id": uid("conversation"), "title": "新对话", "version": 1,
                            "created_at": timestamp, "updated_at": timestamp,
                            "turns": [], "active_run": None}
            self._save_conversation(conn, conversation)
            return conversation
        return self.command(command_id, {"action": "create_assistance_conversation"}, create,
                            resource_type="conversation")

    def assistance_turn(self, conversation_id: str, data: dict, model: str, configured: bool,
                        skill_snapshots: dict | Callable[[], dict]) -> dict:
        def create(conn):
            conversation = self._conversation(conn, conversation_id)
            self._version(conversation, data["expected_version"])
            if conversation["active_run"]:
                raise AppError("conversation_active", "本会话已有任务进行中", 409)
            self._model_configured(configured)
            text = data.get("text", "").strip()
            action = data.get("action", "message")
            if action == "message" and not text:
                raise AppError("invalid_message", "请输入问题", 422)
            from .assistance_domain import forbidden_artifacts, requested_artifacts
            context = {"text": text, "action": action,
                       "requested_artifacts": requested_artifacts(text),
                       "forbidden_artifacts": forbidden_artifacts(text),
                       "history": [], "skill_snapshots": (
                           skill_snapshots() if callable(skill_snapshots) else skill_snapshots)}
            artifact_id = data.get("artifact_id")
            if artifact_id:
                artifact = self._get(conn, "assistance_artifacts", artifact_id)
                if artifact["conversation_id"] != conversation_id or artifact["kind"] != "whiteboard":
                    raise AppError("artifact_conflict", "白板不属于当前会话", 409)
                if action != "message" or not text:
                    raise AppError("invalid_message", "白板提问需要问题文本", 422)
                context.update(artifact_id=artifact_id, whiteboard={
                    "artifact_id": artifact_id, "title": artifact["title"],
                    "cursor": artifact["data"]["cursor"],
                    "steps": artifact["data"]["steps"][:artifact["data"]["cursor"] + 1]})
            # Persist the precise selected history and its budget for retries/audit.
            history_size = 0
            for turn in reversed(conversation["turns"]):
                if turn["status"] != "ready":
                    continue
                entry = {key: turn[key] for key in ("turn_id", "user_text", "action", "response")}
                entry["artifacts"] = [{key: artifact[key] for key in ("artifact_id", "kind", "title")}
                                      for artifact in turn["artifacts"]]
                size = len(json.dumps(entry, ensure_ascii=False))
                if len(context["history"]) >= 12 or history_size + size > 24000:
                    break
                context["history"].insert(0, entry)
                history_size += size
            context["history_truncated"] = len(context["history"]) < sum(
                turn["status"] == "ready" for turn in conversation["turns"])
            context["history_selection"] = {"max_turns": 12, "budget_characters": 24000,
                                            "selected_turn_ids": [t["turn_id"] for t in context["history"]]}
            if action == "continue":
                previous = next((turn for turn in reversed(conversation["turns"]) if turn["status"] == "ready"), None)
                if previous is None or previous["response"]["waiting_for"] != "continue":
                    raise AppError("invalid_continuation", "当前没有等待继续的教学步骤", 409)
                from .assistance_domain import ContinuationState
                response = previous["response"]
                context["continuation_state"] = ContinuationState(
                    plan=response["plan"], current_step=response["current_step"] + 1,
                    is_last_step=response["current_step"] + 2 == len(response["plan"])).model_dump()
            turn_id = uid("turn")
            run = self._new_run(text or action, model)
            run.update(kind="assistance", conversation_id=conversation_id, turn_id=turn_id,
                       input=context, steps=[])
            turn = {"turn_id": turn_id, "run_id": run["run_id"], "user_text": text, "action": action,
                    "status": "queued", "response": None,
                    "artifacts": [], "skill_uses": [], "steps": [], "error": None}
            if not conversation["turns"] and text:
                conversation["title"] = text[:80]
            conversation["turns"].append(turn)
            self._save_conversation(conn, conversation)
            self._save_run(conn, run)
            return self._conversation(conn, conversation_id)
        return self.command(data["client_command_id"], {"command": "assistance_turn",
                            "conversation_id": conversation_id, **data}, create,
                            resource_type="conversation")

    def _assistance_run_changed(self, conn, run: dict):
        from .storage import now
        conversation = self._conversation(conn, run["conversation_id"])
        turn = next((t for t in conversation["turns"] if t["turn_id"] == run["turn_id"]), None)
        if (turn is None or turn["run_id"] != run["run_id"]
                or conversation["turns"][-1]["turn_id"] != run["turn_id"]):
            return
        # The recorded trace is authoritative for the turn, so a failed or
        # cancelled turn still shows which steps actually ran.
        turn.update(status=run["status"], error=run["error"], steps=run["steps"])
        conversation.update(active_run=run if run["status"] in ACTIVE else None,
                            version=conversation["version"] + 1, updated_at=now())
        self._save_conversation(conn, conversation)

    def _retry_assistance(self, conn, parent: dict, run: dict):
        conversation = self._conversation(conn, parent["conversation_id"])
        if (not conversation["turns"] or conversation["turns"][-1]["run_id"] != parent["run_id"]
                or conversation["active_run"]):
            raise AppError("state_conflict", "只能重试会话最后轮次的当前任务", 409)
        for key in ("kind", "conversation_id", "turn_id", "input"):
            run[key] = parent[key]
        run["steps"] = []
        conversation["turns"][-1].update(run_id=run["run_id"], response=None,
                                         artifacts=[], skill_uses=[], error=None)
        self._save_conversation(conn, conversation)

    def assistance_step(self, run_id: str, step: dict) -> dict | None:
        with self.transaction() as conn:
            run = self._get(conn, "runs", run_id)
            if run.get("kind") != "assistance" or run["status"] != "generating":
                return None
            conversation = self._conversation(conn, run["conversation_id"])
            if not conversation["active_run"] or conversation["active_run"]["run_id"] != run_id:
                return None
            run["steps"].append(step)
            from .storage import now
            run.update(version=run["version"] + 1, updated_at=now())
            self._save_run(conn, run)
            return run

    def finish_assistance(self, run_id: str, result: dict) -> dict | None:
        from .assistance_domain import ArtifactDraft, TeachingResponse
        from .storage import encode, now
        with self.transaction() as conn:
            run = self._get(conn, "runs", run_id)
            if run.get("kind") != "assistance" or run["status"] != "generating":
                return None
            conversation = self._conversation(conn, run["conversation_id"])
            if not conversation["active_run"] or conversation["active_run"]["run_id"] != run_id:
                return None
            turn = next(t for t in conversation["turns"] if t["turn_id"] == run["turn_id"])
            if turn["run_id"] != run_id:
                return None
            response = TeachingResponse.model_validate(result["response"]).model_dump()
            drafts = [ArtifactDraft.model_validate(a).model_dump() for a in result["artifacts"]]
            if len(drafts) > 1:
                raise AppError("artifact_limit", "一次教学轮次只保存一个产物", 422, True)
            requested = run["input"].get("requested_artifacts") or []
            if requested and not any(a["kind"] == requested[0] for a in drafts):
                raise AppError("artifact_missing", "未生成你点名的教学产物", 422, True)
            refused = run["input"].get("forbidden_artifacts") or []
            if any(a["kind"] in refused for a in drafts):
                raise AppError("artifact_forbidden", "你已明确不要这类产物，本轮不保存", 422, True)
            artifacts = []
            for draft in drafts:
                if draft["kind"] == "whiteboard":
                    draft["data"]["cursor"] = -1
                    draft["data"]["steps"] = [{**step, "step_id": uid("step")}
                                                for step in draft["data"]["steps"]]
                artifact = {**draft, "artifact_id": uid("artifact"),
                            "conversation_id": run["conversation_id"], "turn_id": run["turn_id"], "version": 1}
                conn.execute("INSERT INTO assistance_artifacts VALUES (?,?,?)",
                             (artifact["artifact_id"], run["conversation_id"], encode(artifact)))
                artifacts.append(artifact)
            turn.update(response=response, artifacts=artifacts, skill_uses=result["skill_uses"],
                        steps=run["steps"])
            self._save_conversation(conn, conversation)
            run.update(status="ready", error=None, version=run["version"] + 1, updated_at=now())
            self._save_run(conn, run)
            return run

    def get_assistance_artifact(self, artifact_id: str) -> dict:
        with self.transaction() as conn:
            return self._get(conn, "assistance_artifacts", artifact_id)

    def assistance_progress(self, artifact_id: str, data: dict) -> dict:
        from .storage import encode
        def save(conn):
            artifact = self._get(conn, "assistance_artifacts", artifact_id)
            self._version(artifact, data["expected_version"])
            if artifact["kind"] != "whiteboard":
                raise AppError("artifact_conflict", "仅白板支持确认位置", 409)
            cursor, previous = data["cursor"], artifact["data"]["cursor"]
            if not -1 <= cursor < len(artifact["data"]["steps"]):
                raise AppError("invalid_cursor", "白板位置超出步骤范围", 422)
            if cursor not in {previous, previous + 1}:
                raise AppError("invalid_cursor", "确认位置只能逐步前进", 409)
            conversation = self._conversation(conn, artifact["conversation_id"])
            active = conversation["active_run"]
            if cursor != previous and active and active["input"].get("artifact_id"):
                raise AppError("question_active", "回答期间保持原白板位置", 409)
            if cursor != previous:
                artifact["data"]["cursor"] = cursor
                artifact["version"] += 1
                conn.execute("UPDATE assistance_artifacts SET data=? WHERE id=?", (encode(artifact), artifact_id))
                # The conversation snapshot embeds the same current artifact.
                for turn in conversation["turns"]:
                    turn["artifacts"] = [artifact if a["artifact_id"] == artifact_id else a
                                         for a in turn["artifacts"]]
                self._save_conversation(conn, conversation)
            return artifact
        return self.command(data["client_command_id"], {"command": "assistance_progress",
                            "artifact_id": artifact_id, **data}, save, resource_type="artifact")

    def assistance_feedback(self, artifact_id: str, data: dict) -> dict:
        """Record one verdict on a generated artifact.

        Content quality has no other user-side signal, so the verdict is data
        on the artifact itself rather than on the chat message that produced
        it. A repeated identical verdict is not a second data point.
        """
        from .storage import encode, now
        def save(conn):
            artifact = self._get(conn, "assistance_artifacts", artifact_id)
            self._version(artifact, data["expected_version"])
            vote = data["vote"]
            if artifact.get("feedback") == vote:
                return artifact
            artifact.update(feedback=vote, feedback_at=now())
            artifact["version"] += 1
            conn.execute("UPDATE assistance_artifacts SET data=? WHERE id=?", (encode(artifact), artifact_id))
            conversation = self._conversation(conn, artifact["conversation_id"])
            for turn in conversation["turns"]:
                turn["artifacts"] = [artifact if a["artifact_id"] == artifact_id else a
                                     for a in turn["artifacts"]]
            self._save_conversation(conn, conversation)
            return artifact
        return self.command(data["client_command_id"], {"command": "assistance_feedback",
                            "artifact_id": artifact_id, **data}, save, resource_type="artifact")
