"""Real provider calls, typed content and one bounded schema repair."""

import json
from threading import Event
from time import monotonic

from pydantic import ValidationError

from agent_core.llm.openai import OpenAIService
from agent_core.types import AgentContext, UserMessage

from .config import Settings
from .domain import AppError, Clarification, CourseDraft
from .storage import Database, now


def parse_json(text: str):
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    return json.loads(text)


class Generator:
    def __init__(self, settings: Settings, db: Database):
        self.settings, self.db = settings, db
        self.stopping = Event()

    def require_active(self, run_id: str, phase: str):
        if self.stopping.is_set() or self.db.get_run(run_id)["status"] != phase:
            raise AppError("run_inactive", "任务已取消或中断，未发起后续模型调用", 409)

    def generate(self, run: dict, phase: str):
        schema = Clarification if phase == "clarifying" else CourseDraft
        if phase == "clarifying":
            instruction = (
                "你是课程需求澄清助手。根据本次学习目标，生成2-4个真正影响课程内容的短问题，"
                "询问基础、目标、时间等必要维度。提供易懂的选项和后果说明，不机械套同一组问题。"
                "id和option id使用短英文标识。所有展示文字用简体中文。"
            )
            user = {"goal": run["goal"]}
        else:
            instruction = (
                "你是Hyperknow课程设计者。依据原始需求及澄清答案生成一门可逐课学习的具体学科课程。"
                "结构为课程→单元→讲座→白板课时，单元可包含客观题考核以及适用的项目阶段。"
                "只设计目录和课时大纲，不生成整门讲义。标题和要点必须是具体知识，不用通用模板换主题。"
                "根据基础、时间、目标决定规模，不固定5单元20课。优先简洁完整、避免无必要的碎片课。"
                "每课outline说明要解释的知识、例子或推导，key_points写实际概念。"
                "项目仅在适合主题时生成；project_key关联项目与阶段，每个项目至少一个阶段。"
                "无需任何项目时projects和project_stages为空。考核目标具体。"
                "预计分钟数是估计，不能全部固定45。所有展示文字用简体中文，language为zh-CN。"
            )
            user = {"goal": run["goal"], "questions": run["questions"],
                    "answers": run["answers"], "clarification_skipped": run["skipped"]}
        system = instruction + "\n仅输出符合下述JSON Schema的JSON对象，不输出Markdown或解释：\n" + json.dumps(schema.model_json_schema(), ensure_ascii=False)
        messages = [UserMessage(json.dumps(user, ensure_ascii=False))]
        for attempt in range(2):
            self.require_active(run["run_id"], phase)
            context = AgentContext(system, messages.copy())
            started = monotonic()
            provider = OpenAIService(model=run["model"], api_key=self.settings.api_key,
                                     base_url=self.settings.base_url, timeout=self.settings.timeout,
                                     max_retries=0)
            try:
                self.require_active(run["run_id"], phase)
                response = provider.complete(context)
            finally:
                provider.client.close()
            record = {"phase": phase, "attempt": attempt + 1,
                      "model": response.model or run["model"], "requested_model": run["model"],
                      "provider": response.provider, "provider_error": response.error_message,
                      "prompt_version": "course-v1", "schema_version": 1,
                      "system_prompt": system, "messages": [m.content for m in messages],
                      "response": response.content, "usage": response.usage,
                      "elapsed_ms": int((monotonic() - started) * 1000), "created_at": now(),
                      "stop_reason": response.stop_reason}
            if response.stop_reason != "stop" or not response.content.strip():
                record["error"] = "model_request_failed"
                self.db.record_call(run["run_id"], record)
                raise AppError("model_request_failed", "模型请求失败或未返回完整内容，请检查配置、额度或网络后重试", 502, True)
            try:
                result = schema.model_validate(parse_json(response.content))
            except (ValueError, ValidationError) as exc:
                record["error"] = "content_validation_failed"
                self.db.record_call(run["run_id"], record)
                if attempt:
                    raise AppError("content_validation_failed", "模型内容在一次修复后仍不符合课程结构，本次未创建课程", 502, True) from exc
                self.require_active(run["run_id"], phase)
                messages.append(UserMessage("上次结果未通过结构校验，请仅修复结构并返回完整JSON。原结果：\n"
                                            + response.content + "\n校验错误：\n" + str(exc)[:6000]))
            else:
                record["validated"] = True
                self.db.record_call(run["run_id"], record)
                return result
        raise RuntimeError("unreachable generation state")
