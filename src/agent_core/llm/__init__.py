"""LLM service contracts and a deterministic mock provider for V0."""

from .base import LLMService
from .mock import MockLLMService, mock_text, mock_tool_call
from .openai import OpenAIService

__all__ = ["LLMService", "MockLLMService", "OpenAIService", "mock_text", "mock_tool_call"]
