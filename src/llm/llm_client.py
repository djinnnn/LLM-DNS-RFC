from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union


class LLMError(Exception):
    """LLM 调用基类异常"""
    pass


class LLMRequestError(LLMError):
    """请求阶段异常：网络、认证、限流、参数错误等"""
    pass

class LLMResponseError(LLMError):
    """响应阶段异常：空响应、非 JSON、内容格式不符合预期等"""
    pass

import os
from typing import Any, Dict, Optional

import yaml


class LLMConfigError(Exception):
    pass


def load_llm_endpoints(config_path: str = "config.yaml") -> Dict[str, Any]:
    if not os.path.exists(config_path):
        raise LLMConfigError(f"配置文件不存在: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise LLMConfigError("配置文件顶层必须是 dict")

    if "providers" not in data or not isinstance(data["providers"], dict):
        raise LLMConfigError("配置文件缺少 providers 字段，或 providers 不是 dict")

    return data


def resolve_llm_endpoint(
    provider_name: Optional[str] = None,
    config_path: str = "config.yaml",
) -> Dict[str, Any]:
    config = load_llm_endpoints(config_path)

    if provider_name is None:
        provider_name = config.get("default_provider")

    if not provider_name:
        raise LLMConfigError("未指定 provider_name，且配置文件中缺少 default_provider")

    providers = config["providers"]
    if provider_name not in providers:
        available = ", ".join(sorted(providers.keys()))
        raise LLMConfigError(
            f"未知 provider: {provider_name}。可用 provider: {available}"
        )

    endpoint = dict(providers[provider_name])

    api_key_env = endpoint.get("api_key_env")
    if not api_key_env:
        raise LLMConfigError(f"provider={provider_name} 缺少 api_key_env")

    api_key = os.getenv(api_key_env)
    if not api_key:
        raise LLMConfigError(
            f"provider={provider_name} 需要环境变量 {api_key_env}，但当前未设置"
        )

    endpoint["api_key"] = api_key
    endpoint["provider_name"] = provider_name
    return endpoint

PromptLike = Union[str, List[Dict[str, str]]]
# 扩展了prompt的格式，以支持后面的few-shot部分的工作



class BaseLLMClient(ABC):
    """
    LLM 客户端抽象基类
    """

    @abstractmethod
    def generate(
        self,
        prompt: PromptLike,
        system_prompt: str = "",
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
        max_retries: int = 2,
    ) -> str:
        """
        统一生成接口。

        prompt 支持两种形式：
        1. str
        2. List[{"role": "...", "content": "..."}]
        """
        raise NotImplementedError

    def generate_json(
        self,
        prompt: PromptLike,
        system_prompt: str = "",
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
        max_retries: int = 2,
    ) -> Dict[str, Any]:
        """
        统一 JSON 生成接口。
        """
        text = self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            max_retries=max_retries,
        )
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMResponseError(f"模型未返回合法 JSON:\n{text}") from e

    def _normalize_prompt(
        self,
        prompt: PromptLike,
        system_prompt: str = "",
    ) -> List[Dict[str, str]]:
        """
        将 str / messages 统一规范成 messages 列表。
        """
        messages: List[Dict[str, str]] = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if isinstance(prompt, str):
            messages.append({"role": "user", "content": prompt})
            return messages

        if isinstance(prompt, list):
            for item in prompt:
                if not isinstance(item, dict):
                    raise LLMRequestError(f"prompt 列表项必须为 dict，实际为: {type(item)}")
                if "role" not in item or "content" not in item:
                    raise LLMRequestError(f"prompt message 缺少 role/content 字段: {item}")
                messages.append({
                    "role": str(item["role"]),
                    "content": str(item["content"]),
                })
            return messages

        raise LLMRequestError(f"不支持的 prompt 类型: {type(prompt)}")


class OpenAICompatibleClient(BaseLLMClient):
    """
    OpenAI 兼容客户端。
    支持：
    - 原生 GPT
    - DeepSeek
    - 遵循 OpenAI API 规范的中转 / 代理 API
    """

    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: Optional[str] = None,
        default_timeout: float = 120.0,
        default_max_tokens: Optional[int] = None,
        default_max_retries: int = 2,
    ):
        try:
            from openai import OpenAI
        except ImportError as e:
            raise ImportError("请安装 openai 依赖: pip install openai") from e

        self.model_name = model_name
        self.base_url = base_url
        self.default_timeout = default_timeout
        self.default_max_tokens = default_max_tokens
        self.default_max_retries = default_max_retries

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=default_timeout,
            max_retries=0,  # 我们自己做外层重试，避免策略叠加失控
        )

    def generate(
        self,
        prompt: PromptLike,
        system_prompt: str = "",
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
        max_retries: int = 2,
    ) -> str:
        messages = self._normalize_prompt(prompt, system_prompt=system_prompt)

        effective_max_tokens = max_tokens if max_tokens is not None else self.default_max_tokens
        effective_timeout = timeout if timeout is not None else self.default_timeout
        effective_retries = max_retries if max_retries is not None else self.default_max_retries

        kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "timeout": effective_timeout,
        }

        if effective_max_tokens is not None:
            kwargs["max_tokens"] = effective_max_tokens

        last_error: Optional[Exception] = None

        for attempt in range(effective_retries + 1):
            try:
                response = self.client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content
                if not content:
                    raise LLMResponseError("模型返回为空。")
                return content

            except Exception as e:
                last_error = e
                if attempt == effective_retries:
                    raise LLMRequestError(
                        f"OpenAI-compatible 调用失败: "
                        f"model={self.model_name}, base_url={self.base_url}, "
                        f"attempts={effective_retries + 1}, error_type={type(e).__name__}, error={e}"
                    ) from e
                time.sleep(min(2 ** attempt, 8))

        raise LLMRequestError("OpenAI-compatible 调用失败，且未捕获到具体异常。") from last_error


class GeminiClient(BaseLLMClient):
    """
    Gemini 原生客户端。
    """

    def __init__(
        self,
        model_name: str,
        api_key: str,
        default_timeout: float = 120.0,
        default_max_tokens: Optional[int] = None,
        default_max_retries: int = 2,
    ):
        try:
            import google.generativeai as genai
        except ImportError as e:
            raise ImportError(
                "请安装 google-generativeai 依赖: pip install google-generativeai"
            ) from e

        self.genai = genai
        self.model_name = model_name
        self.default_timeout = default_timeout
        self.default_max_tokens = default_max_tokens
        self.default_max_retries = default_max_retries

        self.genai.configure(api_key=api_key)
        self.model = self.genai.GenerativeModel(model_name=model_name)

    def _build_gemini_prompt(
        self,
        prompt: PromptLike,
        system_prompt: str = "",
    ) -> str:
        """
        Gemini 在这里先统一拼成单字符串。
        这样最简单稳妥，后面你想换成 contents 结构也很方便。
        """
        if isinstance(prompt, str):
            if system_prompt:
                return f"[System Instruction]\n{system_prompt}\n\n[User Prompt]\n{prompt}"
            return prompt

        parts: List[str] = []
        if system_prompt:
            parts.append(f"[System Instruction]\n{system_prompt}")

        for m in prompt:
            role = m.get("role", "user")
            content = m.get("content", "")
            parts.append(f"[{role.upper()}]\n{content}")

        return "\n\n".join(parts)

    def generate(
        self,
        prompt: PromptLike,
        system_prompt: str = "",
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
        max_retries: int = 2,
    ) -> str:
        effective_max_tokens = max_tokens if max_tokens is not None else self.default_max_tokens
        effective_timeout = timeout if timeout is not None else self.default_timeout
        effective_retries = max_retries if max_retries is not None else self.default_max_retries

        request_text = self._build_gemini_prompt(prompt, system_prompt=system_prompt)

        generation_config: Dict[str, Any] = {
            "temperature": temperature,
            "response_mime_type": "application/json",
        }
        if effective_max_tokens is not None:
            generation_config["max_output_tokens"] = effective_max_tokens

        model = self.model
        if system_prompt:
            model = self.genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=system_prompt,
            )

        last_error: Optional[Exception] = None

        for attempt in range(effective_retries + 1):
            try:
                response = model.generate_content(
                    request_text,
                    generation_config=generation_config,
                    request_options={"timeout": effective_timeout},
                )
                text = getattr(response, "text", None)
                if not text:
                    raise LLMResponseError("Gemini 返回为空。")
                return text

            except Exception as e:
                last_error = e
                if attempt == effective_retries:
                    raise LLMRequestError(
                        f"Gemini 调用失败: model={self.model_name}, attempts={effective_retries + 1}"
                    ) from e
                time.sleep(min(2 ** attempt, 8))

        raise LLMRequestError("Gemini 调用失败，且未捕获到具体异常。") from last_error
