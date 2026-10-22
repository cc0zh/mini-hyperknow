"""LLM service contracts and the real OpenAI-compatible provider."""

from .base import LLMService
from .openai import OpenAIService

__all__ = ["LLMService", "OpenAIService"]
