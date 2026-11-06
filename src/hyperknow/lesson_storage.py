"""Lesson transactions, sharing the database's run and command machinery."""

import json

from pydantic import ValidationError

from .domain import AppError, uid
from .lesson_domain import BoardScript, derive_course, lesson_context, materialize_script, question_context


ACTIVE = {"queued", "generating"}


class LessonStorage:
    # Local imports avoid a storage/lesson_storage import cycle.
    @staticmethod
    def _write(conn, table: str, key: str, data: dict):
        from .storage import encode
        if table == "lesson_interactions":
            conn.execute("UPDATE lesson_interactions SET data=? WHERE id=?", (encode(data), key))
        else:
            conn.execute(f"INSERT OR REPLACE INTO {table}(id,data) VALUES (?,?)", (key, encode(data)))

    @staticmethod
    def _completed(conn) -> set[str]:
        return {row["id"] for row in conn.execute("SELECT id FROM activity_progress")}

    def _course(self, conn, course_id: str) -> dict:
        return derive_course(self._get(conn, "courses", course_id), self._completed(conn))

    def _locate(self, conn, session_id: str):
        for row in conn.execute("SELECT data FROM courses"):
            course = json.loads(row["data"])
            for unit in course["units"]:
                for lecture in unit["lectures"]:
                    for session in lecture["sessions"]:
                        if session["session_id"] == session_id:
                            return course, unit, lecture, session
        raise AppError("not_found", "找不到这个课时", 404)

    def _state(self, conn, session_id: str) -> dict:
        row = conn.execute("SELECT data FROM lesson_states WHERE id=?", (session_id,)).fetchone()
        return json.loads(row["data"]) if row else {
            "version": 1, "progress": {"script_id": None, "cursor": -1, "play_intent": "paused",
                                        "version": 1, "updated_at": self._locate(conn, session_id)[0]["created_at"]}}

    def _bump_session(self, conn, session_id: str, *, progress: dict | None = None):
        from .storage import now
        state = self._state(conn, session_id)
        state["version"] += 1
        if progress is not None:
            state["progress"].update(progress)
            state["progress"]["version"] += 1
            state["progress"]["updated_at"] = now()
        self._write(conn, "lesson_states", session_id, state)

    @staticmethod
    def _script(conn, session_id: str) -> dict | None:
        row = conn.execute("SELECT data FROM lesson_scripts WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            return None
        try:
            return BoardScript.model_validate_json(row["data"]).model_dump()
        except ValidationError as exc:
            raise AppError("lesson_format_unsupported", "现有讲义不符合当前课堂协议，原文已保留；请明确重新生成本课讲义", 409) from exc

    @staticmethod
    def _interactions(conn, session_id: str) -> list[dict]:
        return [json.loads(r["data"]) for r in conn.execute(
            "SELECT data FROM lesson_interactions WHERE session_id=? ORDER BY rowid", (session_id,))]

    @staticmethod
    def _lesson_runs(conn, session_id: str, kind: str) -> list[dict]:
        return [run for row in conn.execute("SELECT data FROM runs ORDER BY rowid")
                if (run := json.loads(row["data"])).get("session_id") == session_id
                and run.get("kind") == kind]

    def _lesson(self, conn, session_id: str) -> dict:
        course, unit, lecture, session = self._locate(conn, session_id)
        state = self._state(conn, session_id)
        completed = session_id in self._completed(conn)
        session["completed"] = completed
        runs = self._lesson_runs(conn, session_id, "lesson")
        format_error = None
        try:
            script = self._script(conn, session_id)
        except AppError as exc:
            if exc.code != "lesson_format_unsupported":
                raise
            script, format_error = None, exc.public()
        interactions = self._interactions(conn, session_id)
        if script:
            interactions = [item for item in interactions if item["script_id"] == script["script_id"]]
        return {"course_id": course["course_id"], "course_title": course["title"],
                "unit_title": unit["title"], "lecture_title": lecture["title"], "session": session,
                "script": script, "format_error": format_error, "progress": state["progress"],
                "interactions": interactions,
                "generation_run": runs[-1] if runs else None, "completed": completed,
                "version": state["version"]}

    def get_lesson(self, session_id: str) -> dict:
        with self.transaction() as conn:
            return self._lesson(conn, session_id)

    @staticmethod
    def _version(progress: dict, expected: int):
        if progress["version"] != expected:
            raise AppError("version_conflict", "课堂位置已更新，请刷新后再试", 409, True,
                           latest_version=progress["version"])

    def _anchor(self, conn, session_id: str, data: dict):
        snapshot = self._lesson(conn, session_id)
        self._version(snapshot["progress"], data["expected_version"])
        if snapshot["format_error"]:
            raise AppError("lesson_format_unsupported", snapshot["format_error"]["message"], 409)
        latest = snapshot["generation_run"]
        if latest and latest.get("regeneration") and latest["status"] in ACTIVE:
            raise AppError("lesson_generation_active", "正在重新生成讲义，请等待或取消后再操作", 409)
        script = snapshot["script"]
        if not script or data["script_id"] != script["script_id"]:
            raise AppError("script_conflict", "讲义不属于当前课时或版本", 409)
        return snapshot, script

    @staticmethod
    def _model_configured(configured: bool):
        if not configured:
            raise AppError("model_not_configured", "尚未配置真实模型，请设置 OPENAI_API_KEY 后重启后端", 503)

    def prepare_lesson(self, session_id: str, command_id: str, model: str, configured: bool) -> dict:
        def prepare(conn):
            course, unit, lecture, session = self._locate(conn, session_id)
            if self._script(conn, session_id) or self._lesson_runs(conn, session_id, "lesson"):
                return self._lesson(conn, session_id)
            self._model_configured(configured)
            run = self._new_run(course["goal"], model)
            run.update(kind="lesson", session_id=session_id, course_id=course["course_id"],
                       input=lesson_context(course, unit, lecture, session))
            self._save_run(conn, run)
            return self._lesson(conn, session_id)
        return self.command(command_id, {"action": "prepare", "session_id": session_id}, prepare,
                            resource_type="session")

    def regenerate_lesson(self, session_id: str, data: dict, model: str, configured: bool) -> dict:
        """Only an explicit command may replace a lesson; keep the old source verbatim."""
        def regenerate(conn):
            course, unit, lecture, session = self._locate(conn, session_id)
            self._version(self._state(conn, session_id)["progress"], data["expected_version"])
            if any(run["status"] in ACTIVE for run in self._lesson_runs(conn, session_id, "lesson")):
                raise AppError("lesson_generation_active", "本课讲义正在生成，请等待或取消后再试", 409)
            if any(item["status"] == "pending" for item in self._interactions(conn, session_id)):
                raise AppError("question_active", "请先等待或取消当前课堂回答", 409)
            self._model_configured(configured)
            previous = conn.execute("SELECT id,data FROM lesson_scripts WHERE session_id=?", (session_id,)).fetchone()
            run = self._new_run(course["goal"], model)
            run.update(kind="lesson", session_id=session_id, course_id=course["course_id"],
                       input=lesson_context(course, unit, lecture, session), regeneration=True,
                       replaces_script_id=previous["id"] if previous else None,
                       previous_script_data=previous["data"] if previous else None)
            self._save_run(conn, run)
            self._bump_session(conn, session_id, progress={"play_intent": "paused"})
            return self._lesson(conn, session_id)
        return self.command(data["client_command_id"], {"action": "regenerate", "session_id": session_id,
                            **data}, regenerate, resource_type="session")

    def save_progress(self, session_id: str, data: dict) -> dict:
        def save(conn):
            snapshot, script = self._anchor(conn, session_id, data)
            cursor = data["cursor"]
            old = snapshot["progress"]
            if not -1 <= cursor < len(script["steps"]):
                raise AppError("invalid_cursor", "课堂位置超出讲义步骤范围", 422)
            if cursor < old["cursor"] or cursor > old["cursor"] + 1:
                raise AppError("invalid_cursor", "确认位置只能逐步前进，回看不改变确认位置", 409)
            if any(i["status"] == "pending" for i in snapshot["interactions"]):
                raise AppError("question_active", "回答期间保持原位置并暂停", 409)
            patch = {key: data[key] for key in ("script_id", "cursor", "play_intent")}
            if any(old[key] != value for key, value in patch.items()):
                self._bump_session(conn, session_id, progress=patch)
            return self._lesson(conn, session_id)
        return self.command(data["client_command_id"], {"action": "progress", "session_id": session_id,
                            **data}, save, resource_type="session")

    def ask_question(self, session_id: str, data: dict, model: str, configured: bool) -> dict:
        from .storage import encode, now
        def ask(conn):
            snapshot, script = self._anchor(conn, session_id, data)
            if data["cursor"] != snapshot["progress"]["cursor"]:
                raise AppError("invalid_cursor", "请先确认当前课堂位置再提问", 409)
            if any(i["status"] == "pending" for i in snapshot["interactions"]):
                raise AppError("question_active", "本课时已有回答等待完成", 409)
            question = data["question"].strip()
            if not 2 <= len(question) <= 2000:
                raise AppError("invalid_question", "问题须为2–2000字", 422)
            course, _, _, session = self._locate(conn, session_id)
            context = question_context(course, session, script, data["cursor"], question,
                                       snapshot["interactions"], anchor_step_id=data.get("anchor_step_id"),
                                       anchor_object_id=data.get("anchor_object_id"))
            self._model_configured(configured)
            run = self._new_run(course["goal"], model)
            interaction_id = uid("interaction")
            run.update(kind="question", session_id=session_id, script_id=script["script_id"],
                       interaction_id=interaction_id, course_id=course["course_id"], input=context)
            interaction = {"interaction_id": interaction_id, "run_id": run["run_id"],
                           "script_id": script["script_id"], "cursor": data["cursor"],
                           "step_id": script["steps"][data["cursor"]]["step_id"] if data["cursor"] >= 0 else None,
                           "anchor_step_id": data.get("anchor_step_id"), "anchor_object_id": data.get("anchor_object_id"),
                           "question": question, "answer": None, "was_playing": data["was_playing"],
                           "status": "pending", "error": None, "created_at": now()}
            conn.execute("INSERT INTO lesson_interactions VALUES (?,?,?)",
                         (interaction_id, session_id, encode(interaction)))
            self._save_run(conn, run)
            self._bump_session(conn, session_id, progress={"play_intent": "paused"})
            return self._lesson(conn, session_id)
        return self.command(data["client_command_id"], {"action": "question", "session_id": session_id,
                            **data}, ask, resource_type="session")

    def complete_lesson(self, session_id: str, data: dict) -> dict:
        from .storage import now
        def complete(conn):
            snapshot, script = self._anchor(conn, session_id, data)
            if snapshot["progress"]["cursor"] != len(script["steps"]) - 1 or script["steps"][-1]["stage"] != "summary":
                raise AppError("lesson_incomplete", "请先完成本课教学并展示最后总结；提前离开只保留进度", 409)
            if any(item["status"] == "pending" for item in snapshot["interactions"]):
                raise AppError("question_active", "请先等待或取消当前课堂回答", 409)
            if not snapshot["completed"]:
                self._write(conn, "activity_progress", session_id,
                            {"course_id": snapshot["course_id"], "type": "session", "completed_at": now()})
                course = self._get(conn, "courses", snapshot["course_id"])
                course["version"] += 1
                self._write(conn, "courses", course["course_id"], course)
                self._bump_session(conn, session_id, progress={"play_intent": "paused"})
                self._bump_target(conn, "practice", session_id)
            return self._lesson(conn, session_id)
        return self.command(data["client_command_id"], {"action": "complete", "session_id": session_id,
                            **data}, complete, resource_type="session")

    def _run_changed(self, conn, run: dict):
        if run.get("kind", "course") == "course":
            return
        if run["kind"] == "question":
            interaction = self._get(conn, "lesson_interactions", run["interaction_id"])
            if interaction["run_id"] != run["run_id"]:
                return
            interaction.update(status="pending" if run["status"] in ACTIVE else run["status"],
                               error=run["error"])
            self._write(conn, "lesson_interactions", interaction["interaction_id"], interaction)
        self._bump_session(conn, run["session_id"])

    def _retry_lesson(self, conn, parent: dict, run: dict):
        from .storage import encode
        session_id = parent["session_id"]
        for key in ("kind", "course_id", "session_id", "script_id", "interaction_id", "input"):
            run[key] = parent[key]
        if run["kind"] == "lesson":
            latest = self._lesson_runs(conn, session_id, "lesson")[-1]
            current = conn.execute("SELECT id FROM lesson_scripts WHERE session_id=?", (session_id,)).fetchone()
            if parent.get("regeneration"):
                for key in ("regeneration", "replaces_script_id", "previous_script_data"):
                    run[key] = parent[key]
                expected = parent["replaces_script_id"]
                unchanged = (current["id"] if current else None) == expected
            else:
                unchanged = current is None
            if not unchanged or latest["run_id"] != parent["run_id"]:
                raise AppError("state_conflict", "该讲义已存在或已有更新的重试", 409)
            if parent.get("regeneration"):
                if any(item["status"] == "pending" for item in self._interactions(conn, session_id)):
                    raise AppError("question_active", "请先等待或取消当前课堂回答", 409)
                self._bump_session(conn, session_id, progress={"play_intent": "paused"})
        else:
            snapshot = self._lesson(conn, session_id)
            if not snapshot["script"] or snapshot["script"]["script_id"] != parent["script_id"]:
                raise AppError("script_conflict", "该问题属于已替换的讲义，不能重试", 409)
            latest = snapshot["generation_run"]
            if latest and latest.get("regeneration") and latest["status"] in ACTIVE:
                raise AppError("lesson_generation_active", "重新生成讲义时不能重试旧问题", 409)
            interaction = self._get(conn, "lesson_interactions", run["interaction_id"])
            if interaction["run_id"] != parent["run_id"]:
                raise AppError("state_conflict", "该互动已有更新的重试", 409)
            if any(i["status"] == "pending" for i in self._interactions(conn, session_id)):
                raise AppError("question_active", "本课时已有回答等待完成", 409)
            interaction.update(run_id=run["run_id"], status="pending", error=None, answer=None)
            conn.execute("UPDATE lesson_interactions SET data=? WHERE id=?",
                         (encode(interaction), interaction["interaction_id"]))
            self._bump_session(conn, session_id, progress={"play_intent": "paused"})

    def finish_lesson(self, run_id: str, result) -> dict | None:
        from .storage import encode, now
        with self.transaction() as conn:
            run = self._get(conn, "runs", run_id)
            if run["status"] != "generating" or run.get("kind") not in {"lesson", "question"}:
                return None
            if run["kind"] == "lesson":
                latest = self._lesson_runs(conn, run["session_id"], "lesson")[-1]
                current = conn.execute("SELECT id FROM lesson_scripts WHERE session_id=?", (run["session_id"],)).fetchone()
                expected = run.get("replaces_script_id") if run.get("regeneration") else None
                if latest["run_id"] != run_id or (current["id"] if current else None) != expected:
                    return None
                script = BoardScript.model_validate(materialize_script(result, run, now())).model_dump()
                if current:
                    conn.execute("UPDATE lesson_scripts SET id=?,data=? WHERE session_id=?",
                                 (script["script_id"], encode(script), run["session_id"]))
                else:
                    conn.execute("INSERT INTO lesson_scripts VALUES (?,?,?)",
                                 (script["script_id"], run["session_id"], encode(script)))
                run["script_id"] = script["script_id"]
                self._bump_session(conn, run["session_id"], progress={
                    "script_id": script["script_id"], "cursor": -1, "play_intent": "paused"})
            else:
                interaction = self._get(conn, "lesson_interactions", run["interaction_id"])
                if interaction["run_id"] != run_id:
                    return None
                interaction["answer"] = result.answer
                self._write(conn, "lesson_interactions", interaction["interaction_id"], interaction)
            run.update(status="ready", error=None, version=run["version"] + 1, updated_at=now())
            self._save_run(conn, run)
            return run
