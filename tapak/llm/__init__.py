"""Local language-model providers for the semantic channel (loopback only, no cloud)."""

from tapak.llm.provider import LLMProvider, get_provider, protected_tokens

__all__ = ["LLMProvider", "get_provider", "protected_tokens"]
