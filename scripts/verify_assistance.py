"""Opt-in paid verification against a real, independently started HTTP service.

Usage: uv run --frozen python scripts/verify_assistance.py --execute
Never starts a provider substitute or edits application settings/user data.
"""

import argparse
import json
from pathlib import Path
import time
from uuid import uuid4

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Authorize real model calls and their costs")
    parser.add_argument("--resume", action="store_true", help="Read saved run IDs without submitting duplicate turns")
    parser.add_argument("--retry-failed", action="store_true", help="Explicitly retry saved failed/interrupted final runs")
    parser.add_argument("--base-url", default="http://127.0.0.1:8037")
    parser.add_argument("--output", type=Path, default=Path("data/verification/instant-assistance/result.json"))
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required: this verification makes paid model requests")
    evidence = {"base_url": args.base_url, "turns": [], "conversations": [], "artifacts": [], "passed": False}
    if args.resume:
        evidence = json.loads(args.output.read_text(encoding="utf-8"))
        assert evidence["base_url"] == args.base_url
    turn_index = 0
    conversation_index = 0

    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    with httpx.Client(base_url=args.base_url, timeout=20, trust_env=False) as client:
        def get(path):
            response = client.get(path)
            response.raise_for_status()
            return response.json()

        def post(path, body):
            response = client.post(path, json=body)
            response.raise_for_status()
            return response.json()

        def create():
            nonlocal conversation_index
            index = conversation_index
            conversation_index += 1
            if index < len(evidence["conversations"]):
                return evidence["conversations"][index]
            command = {"client_command_id": f"verify-{uuid4()}"}
            conversation = post("/api/assistance/conversations", command)
            assert post("/api/assistance/conversations", command)["conversation_id"] == conversation["conversation_id"]
            evidence["conversations"].append(conversation["conversation_id"])
            save()
            return conversation["conversation_id"]

        def turn(conversation_id, text, expect_kind=None, **extra):
            nonlocal turn_index
            index = turn_index
            turn_index += 1
            path = f"/api/assistance/conversations/{conversation_id}/turns"
            print(f"Starting real turn: {expect_kind or 'teaching'}", flush=True)
            if index < len(evidence["turns"]):
                entry = evidence["turns"][index]
                assert entry["conversation_id"] == conversation_id
            else:
                snapshot = get(f"/api/assistance/conversations/{conversation_id}")
                command = {"client_command_id": f"verify-{uuid4()}", "expected_version": snapshot["version"],
                           "text": text, "action": extra.pop("action", "message"), **extra}
                entry = {"run_id": None, "conversation_id": conversation_id, "text": text,
                         "expect_kind": expect_kind,
                         "status": "unconfirmed", "command": command}
                evidence["turns"].append(entry)
                save()
            if entry["run_id"] is None:
                snapshot = post(path, entry["command"])
                entry["run_id"] = snapshot["turns"][-1]["run_id"]
                replay = post(path, entry["command"])
                assert replay["turns"][-1]["run_id"] == entry["run_id"]
                save()
            run_id = entry["run_id"]
            current_run = get(f"/api/runs/{run_id}")
            if args.retry_failed and current_run["status"] in {"failed", "interrupted", "cancelled"}:
                entry.setdefault("previous_runs", []).append({"run_id": run_id, "status": current_run["status"],
                                                              "error": current_run.get("error")})
                retried = post(f"/api/runs/{run_id}/retry", {
                    "client_command_id": f"verify-retry-{uuid4()}", "expected_version": current_run["version"]})
                run_id = entry["run_id"] = retried["run_id"]
                save()
            deadline = time.monotonic() + 480
            while time.monotonic() < deadline:
                run = get(f"/api/runs/{run_id}")
                if run["status"] not in {"queued", "generating"}:
                    entry.update(status=run["status"], steps=run.get("steps", []), error=run.get("error"))
                    save()
                    assert run["status"] == "ready", f"Real model turn failed: {run.get('error')}"
                    snapshot = get(f"/api/assistance/conversations/{conversation_id}")
                    current = next(t for t in snapshot["turns"] if t["run_id"] == run_id)
                    assert current["run_id"] == run_id and current["status"] == "ready"
                    loaded = [{key: step[key] for key in ("name", "version", "sha256")}
                              for step in run["steps"]
                              if step.get("tool") == "get_skills" and step.get("status") == "ready"]
                    assert current["skill_uses"] == loaded
                    assert all(use == {key: run["input"]["skill_snapshots"][use["name"]][key]
                                       for key in ("name", "version", "sha256")}
                               for use in loaded)
                    entry.update(response=current["response"], skill_uses=current["skill_uses"],
                                 history_selection=run["input"].get("history_selection"))
                    for artifact in current["artifacts"]:
                        assert artifact == get(f"/api/assistance/artifacts/{artifact['artifact_id']}")
                        if not any(a["artifact_id"] == artifact["artifact_id"] for a in evidence["artifacts"]):
                            evidence["artifacts"].append(artifact)
                    # The learner names what they want; the model picks the
                    # tool. A named kind must exist, and no turn may hold two.
                    assert len(current["artifacts"]) <= 1, current["artifacts"]
                    if expect_kind:
                        assert any(a["kind"] == expect_kind for a in current["artifacts"]), current["artifacts"]
                    save()
                    print(f"Ready: {expect_kind or 'teaching'} / {run_id}", flush=True)
                    return current, run
                time.sleep(0.5)
            raise TimeoutError(f"Real run {run_id} did not finish within 480 seconds")

        health = get("/api/health")
        assert health["model"]["configured"], "Real model configuration required"
        assert get("/api/courses")["courses"] == [], "Use an isolated verification database, not user courses"
        evidence["model"] = health["model"]
        try:
            conversation_id = create()
            first, _ = turn(conversation_id,
                "我想理解链式法则。不要一次全讲。先用一个有两个选项的问题确认我的导数基础，"
                "等我回答后按两步计划讲：复合函数的直觉、链式法则的计算。第一轮请只澄清。")
            assert first["response"]["waiting_for"] == "answer" and first["response"]["questions"]
            teaching, _ = turn(conversation_id, "我熟悉导数定义和基本求导。请开始第一步复合函数直觉，讲完等待我继续，不要讲第二步。请提供一个进入第二步的下一步建议。")
            assert teaching["response"]["waiting_for"] == "continue"
            suggestion = next(item for item in teaching["response"]["suggestions"] if item["action"] == "continue")
            evidence["continuation_suggestion"] = suggestion
            save()
            continuation, _ = turn(conversation_id, suggestion["text"], action=suggestion["action"])
            assert continuation["response"]["plan"] == teaching["response"]["plan"]
            assert continuation["response"]["current_step"] == teaching["response"]["current_step"] + 1
            cards, _ = turn(conversation_id, "生成三张链式法则的问答闪卡。", expect_kind="flashcards")
            card = cards["artifacts"][0]
            feedback_body = {"client_command_id": f"verify-{uuid4()}", "expected_version": card["version"], "vote": "up"}
            feedback_path = f"/api/assistance/artifacts/{card['artifact_id']}/feedback"
            feedback = client.put(feedback_path, json=feedback_body)
            feedback.raise_for_status()
            assert client.put(feedback_path, json=feedback_body).json() == feedback.json()
            refreshed = get(f"/api/assistance/conversations/{conversation_id}")
            saved_card = next(a for t in refreshed["turns"] for a in t["artifacts"] if a["artifact_id"] == card["artifact_id"])
            assert saved_card == feedback.json()
            evidence["feedback"] = {"command": feedback_body, "artifact": feedback.json(), "replay_and_refresh_match": True}
            save()
            turn(conversation_id, "出一道关于链式法则的选择题，含明确答案和解释。", expect_kind="quiz")
            turn(conversation_id, "用流程图说明链式法则的计算步骤。", expect_kind="diagram")
            board_turn, _ = turn(conversation_id, "用3步独立白板讲清sin(x²)求导，每步简洁。", expect_kind="whiteboard")
            board = next(a for a in board_turn["artifacts"] if a["kind"] == "whiteboard")
            board = get(f"/api/assistance/artifacts/{board['artifact_id']}")
            progress = {"client_command_id": f"verify-{uuid4()}", "expected_version": board["version"], "cursor": max(0, board["data"]["cursor"])}
            progress_path = f"/api/assistance/artifacts/{board['artifact_id']}/progress"
            response = client.put(progress_path, json=progress)
            response.raise_for_status()
            assert client.put(progress_path, json=progress).json()["data"]["cursor"] == 0
            _, board_run = turn(conversation_id, "请只解释当前白板第一步的含义，不生成新白板，不提前讲后面的步骤。",
                                artifact_id=board["artifact_id"])
            assert len(board_run["input"]["whiteboard"]["steps"]) == 1
            turn(conversation_id,
                 "用简单自包含HTML动画演示内层x²与外层sin的复合，含原生滑块或按钮和文字标注，"
                 "不用外部资源，不联网，不访问父页面，不使用eval。不要过度复杂。", expect_kind="animation")
            other_id = create()
            _, other_run = turn(other_id, "如何计算cos(3x)的导数？只给一个提示，不要给最终答案，不要澄清或生成产物。")
            assert other_run["input"]["history"] == [] and "whiteboard" not in other_run["input"]
            assert get("/api/courses")["courses"] == [], "This verifier must run on an isolated empty-course database"
            evidence["passed"] = True
        finally:
            save()
    print(f"Real assistance evidence: {args.output}; passed={evidence['passed']}", flush=True)


if __name__ == "__main__":
    main()
