from __future__ import annotations

from typing import Optional

from .llm_client import BaseLLMClient, OpenAICompatibleClient, GeminiClient


def create_llm_client(
    provider: str,
    model_name: str,
    api_key: str,
    base_url: Optional[str] = None,
    default_timeout: float = 120.0,
    default_max_tokens: Optional[int] = None,
    default_max_retries: int = 2,
) -> BaseLLMClient:
    provider = provider.lower()

    if provider in {"openai", "gpt", "deepseek", "proxy", "openai_compatible"}:
        return OpenAICompatibleClient(
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            default_timeout=default_timeout,
            default_max_tokens=default_max_tokens,
            default_max_retries=default_max_retries,
        )

    if provider == "gemini":
        return GeminiClient(
            model_name=model_name,
            api_key=api_key,
            default_timeout=default_timeout,
            default_max_tokens=default_max_tokens,
            default_max_retries=default_max_retries,
        )

    raise ValueError(f"不支持的 provider: {provider}")
