"""Explicit model tiers sharing the existing OpenAI-compatible protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import os
from pathlib import Path
from threading import Lock
from typing import Literal, Mapping

from dotenv import load_dotenv

from .base import LLMService
from .openai import OpenAIService

ModelTier = Literal["high", "medium", "low"]
TIERS = ("high", "medium", "low")


@dataclass(frozen=True)
class LLMConfig:
    model: str
    api_key: str | None = field(default=None, repr=False)
    base_url: str | None = None
    timeout: float = 120
    provider: str = "openai"
    max_output_tokens: int | None = None

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("model must not be empty")
        if self.provider != "openai":
            raise ValueError("only the openai-compatible protocol is supported")
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("timeout must be a finite positive number")
        if self.max_output_tokens is not None and (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or self.max_output_tokens < 1
        ):
            raise ValueError("max_output_tokens must be a positive integer")


def create_llm_service(config: LLMConfig) -> OpenAIService:
    return OpenAIService(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=config.timeout,
        max_retries=0,
        max_output_tokens=config.max_output_tokens,
    )


class LLMServiceRegistry:
    """Resolve explicitly configured tiers; never silently substitute a model.

    Services are created lazily. The caller owns explicitly supplied services;
    ``close`` only closes SDK clients created by this registry.
    """

    def __init__(self, services: Mapping[ModelTier, LLMService | LLMConfig]) -> None:
        if any(tier not in TIERS for tier in services):
            raise ValueError("model tier must be high, medium, or low")
        self._entries = dict(services)
        self._created: dict[str, OpenAIService] = {}
        self._lock = Lock()

    def has(self, tier: ModelTier) -> bool:
        return tier in self._entries

    def get(self, tier: ModelTier) -> LLMService:
        if tier not in self._entries:
            raise ValueError(f"model tier is not configured: {tier}")
        entry = self._entries[tier]
        if isinstance(entry, LLMConfig):
            with self._lock:
                if tier not in self._created:
                    self._created[tier] = create_llm_service(entry)
                return self._created[tier]
        return entry

    @classmethod
    def from_env(cls) -> "LLMServiceRegistry":
        """Use OPENAI_MODEL for high; other tiers require their own model name."""
        load_dotenv(Path.cwd() / ".env", override=False)
        common = {
            "api_key": os.getenv("OPENAI_API_KEY"),
            "base_url": os.getenv("OPENAI_BASE_URL") or None,
            "timeout": float(os.getenv("AGENT_MODEL_TIMEOUT_SECONDS", "120")),
        }
        entries: dict[ModelTier, LLMConfig] = {}
        for tier in TIERS:
            model = os.getenv(f"AGENT_{tier.upper()}_MODEL")
            if tier == "high" and not model:
                model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            if model:
                output_limit = os.getenv(f"AGENT_{tier.upper()}_MAX_OUTPUT_TOKENS")
                entries[tier] = LLMConfig(
                    model=model,
                    max_output_tokens=int(output_limit) if output_limit else (1024 if tier == "low" else None),
                    **common,
                )
        return cls(entries)

    def close(self) -> None:
        with self._lock:
            for service in self._created.values():
                service.close()
            self._created.clear()

    def __enter__(self) -> "LLMServiceRegistry":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
