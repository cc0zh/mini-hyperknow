"""Explicit real Tavily + model check; missing configuration is blocked, not success."""

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import sys

from hyperknow.config import Settings
from hyperknow.runtime import CourseService, EventHub
from hyperknow.storage import Database


async def verify(goal: str, context: str) -> int:
    settings = Settings.load()
    missing = [name for name, configured in (("OPENAI_API_KEY", settings.api_key),
                                              ("TAVILY_API_KEY", settings.tavily_api_key)) if not configured]
    if missing:
        print("BLOCKED: configure " + ", ".join(missing) + " locally; no paid requests were made.")
        return 2
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3)
    directory = Path("data/validation/research") / stamp
    db = Database(directory / "hyperknow.sqlite3")
    service = CourseService(settings, db, EventHub())
    evidence = {"status": "failed", "started_at": stamp, "scope": "standalone-web-research"}
    service.start()
    code = 1
    try:
        run = await service.research(goal, context, "verify-" + secrets.token_hex(12))
        await asyncio.wait_for(service.queue.join(), timeout=450)
        saved = db.get_run(run["run_id"])
        evidence.update(run_id=run["run_id"], status=saved["status"], error=saved["error"],
                        model_calls=len(db.calls(run["run_id"])), usage=saved["usage"],
                        steps=saved["research"]["steps"], report=saved["research"]["report"],
                        sources=[{k: source[k] for k in ("source_id", "url", "title", "fetched_at",
                                                        "truncated", "content_sha256")}
                                 for source in saved["research"]["sources"]])
        if saved["status"] != "ready":
            raise RuntimeError("real research did not complete")
        await service.close()
        reopened = Database(db.path)
        before = len(reopened.calls(run["run_id"]))
        reopened.interrupt_inflight()
        if reopened.get_run(run["run_id"]) != saved or len(reopened.calls(run["run_id"])) != before:
            raise RuntimeError("stored research changed during read-only reopen")
        evidence.update(status="passed", recovery="saved run reopened unchanged; no additional calls")
        code = 0
    except Exception as exc:
        evidence.update(status="failed", failure_type=type(exc).__name__)
    finally:
        await service.close()
    evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
    path = directory / "evidence.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": evidence["status"], "evidence": str(path),
                      "model_calls": evidence.get("model_calls"), "usage": evidence.get("usage")}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal", default="学习 Python asyncio 的核心概念与任务取消")
    parser.add_argument("--context", default="具备 Python 基础，希望用官方资料规划入门学习顺序。")
    args = parser.parse_args()
    sys.exit(asyncio.run(verify(args.goal, args.context)))
