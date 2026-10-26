"""OpenAI Chat Completions provider for the synchronous LLM contract."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from dotenv import load_dotenv

from ..types import AgentContext, AssistantMessage, ToolCall
from .sanitize import sanitize_messages


def completion_parameters(max_output_tokens: int | None, base_url: str | None) -> dict:
    """Use the documented token-limit key for a known provider, never both keys."""
    if max_output_tokens is None:
        return {}
    if type(max_output_tokens) is not int or max_output_tokens < 1:
        raise ValueError("max_output_tokens must be a positive integer")
    parameter = "max_tokens" if urlsplit(base_url or "").hostname == "api.deepseek.com" else "max_completion_tokens"
    return {parameter: max_output_tokens}


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
        max_output_tokens: int | None = None,
    ) -> None:
        load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        if max_output_tokens is not None and (
            isinstance(max_output_tokens, bool)
            or not isinstance(max_output_tokens, int)
            or max_output_tokens < 1
        ):
            raise ValueError("max_output_tokens must be a positive integer")
        self.max_output_tokens = max_output_tokens
        self.client = self._create_client(
            api_key or os.getenv("OPENAI_API_KEY"),
            self.base_url,
            timeout,
            max_retries,
        )

    def complete(self, context: AgentContext) -> AssistantMessage:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=to_openai_messages(context),
                **({"tools": context.tools} if context.tools else {}),
                **completion_parameters(self.max_output_tokens, self.base_url),
            )

            return from_openai_response(response, model=self.model)
        except Exception as exc:  # Provider errors stay inside the agent loop.
            return AssistantMessage(
                stop_reason="error",
                model=self.model,
                provider="openai",
                error_message=f"OpenAI request failed: {type(exc).__name__}",
            )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "OpenAIService":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

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

    for message in sanitize_messages(context.messages):
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
        if len({call.id for call in tool_calls}) != len(tool_calls):
            raise ValueError("duplicate tool call ids")
    except (TypeError, ValueError, RecursionError) as exc:
        return AssistantMessage(
            stop_reason="error",
            model=model,
            provider="openai",
            error_message=f"OpenAI returned invalid tool arguments: {exc}",
            usage=_usage(response),
        )

    content = _field(message, "content")
    if content is not None and not isinstance(content, str):
        return AssistantMessage(stop_reason="error", model=model, provider="openai",
                                error_message="OpenAI returned non-text message content", usage=_usage(response))
    finish_reason = _field(choice, "finish_reason")
    # A truncated tool call must never be executed, even if its JSON parses.
    stop_reason = _stop_reason(finish_reason)
    if tool_calls and stop_reason != "error":
        stop_reason = "tool_use"
    if finish_reason == "tool_calls" and not tool_calls:
        stop_reason = "error"
    return AssistantMessage(
        content or "",
        tool_calls=tool_calls,
        stop_reason=stop_reason,
        model=model,
        provider="openai",
        usage=_usage(response),
        error_message=(f"OpenAI response ended with {finish_reason}"
                       if stop_reason == "error" else None),
    )


def _tool_call(call: Any) -> ToolCall:
    function = _field(call, "function")
    if function is None:
        raise ValueError("tool call has no function")
    arguments = _field(function, "arguments", "{}")
    if isinstance(arguments, str):
        arguments = json.loads(arguments or "{}", parse_constant=_reject_json_constant)
    if not isinstance(arguments, dict):
        raise ValueError("tool arguments must be a JSON object")
    _validate_json_arguments(arguments)
    json.dumps(arguments, allow_nan=False)
    call_id, name = _field(call, "id"), _field(function, "name")
    if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
        raise ValueError("tool call requires a non-empty id and function name")
    return ToolCall(id=call_id, name=name, arguments=arguments)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is not permitted: {value}")


def _validate_json_arguments(value: Any) -> None:
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("tool argument keys must be strings")
        for item in value.values():
            _validate_json_arguments(item)
    elif isinstance(value, list):
        for item in value:
            _validate_json_arguments(item)
    elif value is not None and type(value) not in (str, int, float, bool):
        raise ValueError("tool arguments must contain only JSON data")


def _stop_reason(finish_reason: str | None) -> str:
    # A missing/unknown terminal marker cannot authorize tool execution.
    return "stop" if finish_reason in {"stop", "tool_calls"} else "error"


def _usage(response: Any) -> dict[str, int] | None:
    usage = _field(response, "usage")
    if usage is None:
        return None
    result: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = _field(usage, key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            result[key] = value
    return result or None


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)
