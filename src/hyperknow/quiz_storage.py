"""Quiz transactions on the existing run, command receipt and activity tables."""

import json

from .domain import AppError, uid
from .quiz_domain import MAX_ELAPSED_MS, materialize_quiz, quiz_context, score_answers


class QuizStorage:
    def _locate_target(self, conn, target_type: str, target_id: str):
        if target_type not in {"practice", "exam"}:
            raise AppError("invalid_target", "未知题组活动类型", 422)
        matches = []
        for row in conn.execute("SELECT data FROM courses"):
            course = json.loads(row["data"])
            for unit in course["units"]:
                targets = ([s for lecture in unit["lectures"] for s in lecture["sessions"]]
                           if target_type == "practice" else unit["exams"])
                key = "session_id" if target_type == "practice" else "exam_id"
                matches.extend((course, unit, target) for target in targets if target[key] == target_id)
        if not matches:
            raise AppError("not_found", "找不到这个练习或考核活动", 404)
        if len(matches) != 1:
            raise AppError("invalid_target", "活动标识不唯一，不能准备或读取题组", 409)
        return matches[0]

    @staticmethod
    def _target_key(target_type: str, target_id: str) -> str:
        return f"{target_type}:{target_id}"

    def _bump_target(self, conn, target_type: str, target_id: str):
        key = self._target_key(target_type, target_id)
        row = conn.execute("SELECT data FROM quiz_states WHERE id=?", (key,)).fetchone()
        state = json.loads(row["data"]) if row else {"version": 1}
        state["version"] += 1
        self._write(conn, "quiz_states", key, state)

    @staticmethod
    def _quiz_for_target(conn, target_type: str, target_id: str) -> dict | None:
        row = conn.execute("SELECT data FROM quizzes WHERE target_type=? AND target_id=?",
                           (target_type, target_id)).fetchone()
        return json.loads(row["data"]) if row else None

    @staticmethod
    def _target_runs(conn, target_type: str, target_id: str) -> list[dict]:
        return [run for row in conn.execute("SELECT data FROM runs ORDER BY rowid")
                if (run := json.loads(row["data"])).get("kind") == "quiz"
                and run.get("target_type") == target_type and run.get("target_id") == target_id]

    def _quiz_target(self, conn, target_type: str, target_id: str) -> dict:
        course, unit, target = self._locate_target(conn, target_type, target_id)
        quiz = self._quiz_for_target(conn, target_type, target_id)
        runs = self._target_runs(conn, target_type, target_id)
        state = conn.execute("SELECT data FROM quiz_states WHERE id=?",
                             (self._target_key(target_type, target_id),)).fetchone()
        attempt = (conn.execute("SELECT data FROM quiz_attempts WHERE quiz_id=? ORDER BY rowid DESC LIMIT 1",
                                (quiz["quiz_id"],)).fetchone() if quiz else None)
        return {"course_id": course["course_id"], "unit_id": unit["unit_id"],
                "target_type": target_type, "target_id": target_id, "title": target["title"],
                "description": target["description"] if target_type == "practice" else target["goal"],
                "quiz": quiz, "generation_run": runs[-1] if runs else None,
                "latest_attempt": json.loads(attempt["data"]) if attempt else None,
                "completed": target_id in self._completed(conn),
                "version": json.loads(state["data"])["version"] if state else 1}

    def get_quiz_target(self, target_type: str, target_id: str) -> dict:
        with self.transaction() as conn:
            return self._quiz_target(conn, target_type, target_id)

    def get_quiz_target_key(self, key: str) -> dict:
        parts = key.split(":", 1)
        if len(parts) != 2:
            raise AppError("invalid_target", "无效题组活动标识", 422)
        return self.get_quiz_target(*parts)

    def prepare_quiz(self, target_type: str, target_id: str, command_id: str,
                     model: str, configured: bool) -> dict:
        def prepare(conn):
            course, unit, target = self._locate_target(conn, target_type, target_id)
            snapshot = self._quiz_target(conn, target_type, target_id)
            if snapshot["quiz"] or snapshot["generation_run"]:
                return snapshot
            scripts = {s["session_id"]: script for lecture in unit["lectures"]
                       for s in lecture["sessions"] if (script := self._script(conn, s["session_id"]))}
            context = quiz_context(course, unit, target, target_type, scripts)
            self._model_configured(configured)
            run = self._new_run(course["goal"], model)
            run.update(kind="quiz", course_id=course["course_id"], target_type=target_type,
                       target_id=target_id, input=context)
            self._save_run(conn, run)
            return self._quiz_target(conn, target_type, target_id)
        return self.command(command_id, {"action": "quiz_prepare", "target_type": target_type,
                            "target_id": target_id}, prepare, resource_type="quiz_target")

    def _quiz_run_changed(self, conn, run: dict):
        self._bump_target(conn, run["target_type"], run["target_id"])

    def _retry_quiz(self, conn, parent: dict, run: dict):
        target_type, target_id = parent["target_type"], parent["target_id"]
        runs = self._target_runs(conn, target_type, target_id)
        if self._quiz_for_target(conn, target_type, target_id) or runs[-1]["run_id"] != parent["run_id"]:
            raise AppError("state_conflict", "题组已存在或已有更新的重试", 409)
        for key in ("kind", "course_id", "target_type", "target_id", "input"):
            run[key] = parent[key]

    def finish_quiz(self, run_id: str, draft) -> dict | None:
        from .storage import encode, now
        with self.transaction() as conn:
            run = self._get(conn, "runs", run_id)
            if run["status"] != "generating" or run.get("kind") != "quiz":
                return None
            target_type, target_id = run["target_type"], run["target_id"]
            if (self._quiz_for_target(conn, target_type, target_id) or
                    self._target_runs(conn, target_type, target_id)[-1]["run_id"] != run_id):
                return None
            quiz = materialize_quiz(draft, run, now())
            conn.execute("INSERT INTO quizzes VALUES (?,?,?,?)",
                         (quiz["quiz_id"], target_type, target_id, encode(quiz)))
            run.update(status="ready", quiz_id=quiz["quiz_id"], error=None,
                       version=run["version"] + 1, updated_at=now())
            self._save_run(conn, run)
            return run

    def _attempt_snapshot(self, conn, attempt_id: str) -> dict:
        attempt = self._get(conn, "quiz_attempts", attempt_id)
        return {"quiz": self._get(conn, "quizzes", attempt["quiz_id"]), "attempt": attempt,
                "course": self._course(conn, attempt["course_id"])}

    def get_attempt(self, attempt_id: str) -> dict:
        with self.transaction() as conn:
            return self._attempt_snapshot(conn, attempt_id)

    def list_attempts(self, quiz_id: str) -> dict:
        with self.transaction() as conn:
            self._get(conn, "quizzes", quiz_id)
            return {"attempts": [json.loads(r["data"]) for r in conn.execute(
                "SELECT data FROM quiz_attempts WHERE quiz_id=? ORDER BY rowid", (quiz_id,))]}

    def create_attempt(self, quiz_id: str, command_id: str) -> dict:
        from .storage import encode, now
        def create(conn):
            quiz = self._get(conn, "quizzes", quiz_id)
            row = conn.execute("SELECT id FROM quiz_attempts WHERE quiz_id=? AND status='in_progress'",
                               (quiz_id,)).fetchone()
            if row:
                return self._attempt_snapshot(conn, row["id"])
            timestamp = now()
            attempt = {"attempt_id": uid("attempt"), "quiz_id": quiz_id,
                       "course_id": quiz["course_id"], "target_type": quiz["target_type"],
                       "target_id": quiz["target_id"], "status": "in_progress", "version": 1,
                       "cursor": 0, "question_started_at": timestamp, "answers": [], "result": None,
                       "created_at": timestamp, "updated_at": timestamp, "submitted_at": None}
            conn.execute("INSERT INTO quiz_attempts VALUES (?,?,?,?)",
                         (attempt["attempt_id"], quiz_id, "in_progress", encode(attempt)))
            self._bump_target(conn, quiz["target_type"], quiz["target_id"])
            return self._attempt_snapshot(conn, attempt["attempt_id"])
        return self.command(command_id, {"action": "create_attempt", "quiz_id": quiz_id}, create,
                            resource_type="attempt")

    def _attempt_anchor(self, conn, attempt_id: str, data: dict):
        snapshot = self._attempt_snapshot(conn, attempt_id)
        attempt = snapshot["attempt"]
        if attempt["version"] != data["expected_version"]:
            raise AppError("version_conflict", "作答记录已更新，请刷新后再试", 409, True,
                           latest_version=attempt["version"])
        return snapshot["quiz"], attempt

    def _save_attempt(self, conn, attempt: dict):
        from .storage import encode, now
        attempt.update(version=attempt["version"] + 1, updated_at=now())
        conn.execute("UPDATE quiz_attempts SET status=?,data=? WHERE id=?",
                     (attempt["status"], encode(attempt), attempt["attempt_id"]))
        self._bump_target(conn, attempt["target_type"], attempt["target_id"])

    def answer_quiz(self, attempt_id: str, data: dict) -> dict:
        from .storage import now
        def answer(conn):
            quiz, attempt = self._attempt_anchor(conn, attempt_id, data)
            question = quiz["questions"][attempt["cursor"]]
            if (attempt["status"] != "in_progress" or data["question_id"] != question["question_id"]
                    or any(a["question_id"] == question["question_id"] for a in attempt["answers"])):
                raise AppError("state_conflict", "只能回答当前尚未判定的题目", 409)
            ids, skipped, elapsed = data["option_ids"], data["skipped"], data["elapsed_ms"]
            if type(elapsed) is not int or not 0 <= elapsed <= MAX_ELAPSED_MS:
                raise AppError("invalid_elapsed", "用时必须是0至86400000的整数毫秒", 422)
            options = {o["id"] for o in question["options"]}
            if (len(set(ids)) != len(ids) or not set(ids) <= options or
                    (skipped and ids) or (not skipped and not ids) or
                    (question["kind"] != "multiple" and len(ids) > 1)):
                raise AppError("invalid_answers", "请选择有效选项，跳过时不选择选项", 422)
            correct = not skipped and set(ids) == set(question["correct_option_ids"])
            saved = {"question_id": question["question_id"], "option_ids": ids, "skipped": skipped,
                     "elapsed_ms": elapsed, "correct": correct, "fast": correct and elapsed <= 10000,
                     "points": 0, "answered_at": now()}
            previous = score_answers(attempt["answers"], len(quiz["questions"]))["total_score"]
            attempt["answers"].append(saved)
            saved["points"] = score_answers(attempt["answers"], len(quiz["questions"]))["total_score"] - previous
            self._save_attempt(conn, attempt)
            return self._attempt_snapshot(conn, attempt_id)
        return self.command(data["client_command_id"], {"action": "quiz_answer", "attempt_id": attempt_id,
                            **data}, answer, resource_type="attempt")

    def next_question(self, attempt_id: str, data: dict) -> dict:
        from .storage import now
        def advance(conn):
            quiz, attempt = self._attempt_anchor(conn, attempt_id, data)
            question = quiz["questions"][attempt["cursor"]]
            if (attempt["status"] != "in_progress" or attempt["cursor"] >= len(quiz["questions"]) - 1
                    or not any(a["question_id"] == question["question_id"] for a in attempt["answers"])):
                raise AppError("state_conflict", "请先保存本题答案，末题需明确提交看结果", 409)
            attempt.update(cursor=attempt["cursor"] + 1, question_started_at=now())
            self._save_attempt(conn, attempt)
            return self._attempt_snapshot(conn, attempt_id)
        return self.command(data["client_command_id"], {"action": "quiz_next", "attempt_id": attempt_id,
                            **data}, advance, resource_type="attempt")

    def submit_quiz(self, attempt_id: str, data: dict) -> dict:
        from .storage import now
        def submit(conn):
            quiz, attempt = self._attempt_anchor(conn, attempt_id, data)
            if attempt["status"] == "submitted":
                return self._attempt_snapshot(conn, attempt_id)
            if len(attempt["answers"]) != len(quiz["questions"]):
                raise AppError("state_conflict", "全部题目作答或跳过后才能看结果", 409)
            attempt.update(status="submitted", result=score_answers(attempt["answers"], len(quiz["questions"])),
                           submitted_at=now())
            self._save_attempt(conn, attempt)
            if attempt["target_id"] not in self._completed(conn):
                self._write(conn, "activity_progress", attempt["target_id"],
                    {"course_id": attempt["course_id"], "type": "session" if attempt["target_type"] == "practice"
                     else "exam", "completed_at": now(), "attempt_id": attempt_id})
                course = self._get(conn, "courses", attempt["course_id"])
                course["version"] += 1
                self._write(conn, "courses", course["course_id"], course)
                if attempt["target_type"] == "practice":
                    self._bump_session(conn, attempt["target_id"], progress={"play_intent": "paused"})
            return self._attempt_snapshot(conn, attempt_id)
        return self.command(data["client_command_id"], {"action": "quiz_submit", "attempt_id": attempt_id,
                            **data}, submit, resource_type="attempt")
