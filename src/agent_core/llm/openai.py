"""OpenAI Chat Completions provider for the V0 LLM contract."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from ..types import AgentContext, AssistantMessage, ToolCall, ToolResultMessage


class OpenAIService:
    """Call an OpenAI or OpenAI-compatible Chat Completions endpoint.

    The official SDK reads credentials from explicit arguments, the environment
    or the local .env. Automatic network retries are disabled by default.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        max_retries: int = 0,
    ) -> None:
        load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.client = self._create_client(
            api_key or os.getenv("OPENAI_API_KEY"),
            base_url or os.getenv("OPENAI_BASE_URL"),
            timeout,
            max_retries,
        )

    def complete(self, context: AgentContext) -> AssistantMessage:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=to_openai_messages(context),
                **({"tools": context.tools} if context.tools else {}),
            )
            return from_openai_response(response, model=self.model)
        except Exception as exc:  # Provider errors stay inside the agent loop.
            return AssistantMessage(
                stop_reason="error",
                model=self.model,
                provider="openai",
                error_message=f"OpenAI request failed: {type(exc).__name__}",
            )

    @staticmethod
    def _create_client(api_key: str | None, base_url: str | None, timeout: float | None,
                       max_retries: int = 0) -> Any:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "OpenAI support requires the 'openai' package; install the project dependencies first"
            ) from exc

        kwargs: dict[str, Any] = {"max_retries": max_retries}
        if api_key is not None:
            kwargs["api_key"] = api_key
        if base_url is not None:
            kwargs["base_url"] = base_url
        if timeout is not None:
            kwargs["timeout"] = timeout
        return OpenAI(**kwargs)


def to_openai_messages(context: AgentContext) -> list[dict[str, Any]]:
    """Convert internal messages to the Chat Completions wire format."""
    messages: list[dict[str, Any]] = []
    if context.system_prompt:
        messages.append({"role": "system", "content": context.system_prompt})

    for message in context.messages:
        if message.role == "user":
            messages.append({"role": "user", "content": message.content})
        elif message.role == "assistant":
            item: dict[str, Any] = {
                "role": "assistant",
                "content": message.content or None,
            }
            if message.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments, ensure_ascii=False),
                        },
                    }
                    for call in message.tool_calls
                ]
            messages.append(item)
        elif message.role == "tool_result":
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": message.content,
                }
            )
    return messages


def from_openai_response(response: Any, *, model: str) -> AssistantMessage:
    """Map one Chat Completions response into the provider-neutral message."""
    model = _field(response, "model") or model
    choices = _field(response, "choices", [])
    if not choices:
        return AssistantMessage(
            stop_reason="error",
            model=model,
            provider="openai",
            error_message="OpenAI response contained no choices",
            usage=_usage(response),
        )

    choice = choices[0]
    message = _field(choice, "message")
    if message is None:
        return AssistantMessage(
            stop_reason="error",
            model=model,
            provider="openai",
            error_message="OpenAI response choice contained no message",
            usage=_usage(response),
        )

    try:
        tool_calls = [_tool_call(call) for call in (_field(message, "tool_calls", []) or [])]
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return AssistantMessage(
            stop_reason="error",
            model=model,
            provider="openai",
            error_message=f"OpenAI returned invalid tool arguments: {exc}",
            usage=_usage(response),
        )

    finish_reason = _field(choice, "finish_reason")
    stop_reason = "tool_use" if tool_calls else _stop_reason(finish_reason)
    return AssistantMessage(
        _field(message, "content") or "",
        tool_calls=tool_calls,
        stop_reason=stop_reason,
        model=model,
        provider="openai",
        usage=_usage(response),
    )


def _tool_call(call: Any) -> ToolCall:
    function = _field(call, "function")
    if function is None:
        raise ValueError("tool call has no function")
    arguments = _field(function, "arguments", "{}")
    if isinstance(arguments, str):
        arguments = json.loads(arguments or "{}")
    if not isinstance(arguments, dict):
        raise ValueError("tool arguments must be a JSON object")
    return ToolCall(
        id=str(_field(call, "id", "")),
        name=str(_field(function, "name", "")),
        arguments=arguments,
    )


def _stop_reason(finish_reason: str | None) -> str:
    if finish_reason == "length":
        return "error"
    if finish_reason in {"content_filter", "function_call"}:
        return "error"
    return "stop"


def _usage(response: Any) -> dict[str, int] | None:
    usage = _field(response, "usage")
    if usage is None:
        return None
    result: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = _field(usage, key)
        if isinstance(value, int):
            result[key] = value
    return result or None


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)
