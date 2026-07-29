"""统一 LLM 调用客户端。

支持 DeepSeek / Qwen / OpenAI 三种模型提供商，
通过环境变量切换，直接使用 httpx 调用 OpenAI 兼容 API。
"""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Self

import httpx

logger = logging.getLogger(__name__)

# ── 环境变量 ──────────────────────────────────────────────────────────────

DEFAULT_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek")

PROVIDER_CONFIG: dict[str, dict[str, str]] = {
    "deepseek": {
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "default_model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    },
    "qwen": {
        "base_url": os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "api_key": os.getenv("QWEN_API_KEY", os.getenv("DASHSCOPE_API_KEY", "")),
        "default_model": os.getenv("QWEN_MODEL", "qwen-plus"),
    },
    "openai": {
        "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "api_key": os.getenv("OPENAI_API_KEY", ""),
        "default_model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    },
}

# USD 每百万 token ── 输入 / 输出
# https://api-docs.deepseek.com/zh-cn/quick_start/pricing
# https://help.aliyun.com/zh/model-studio/getting-started/models
# https://openai.com/api/pricing/
PRICING: dict[str, dict[str, tuple[float, float]]] = {
    "deepseek": {
        "deepseek-chat": (0.27, 1.10),
        "deepseek-reasoner": (0.55, 2.19),
    },
    "qwen": {
        "qwen-turbo": (0.08, 0.16),
        "qwen-plus": (0.11, 0.33),
        "qwen-max": (1.60, 6.40),
    },
    "openai": {
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4o": (2.50, 10.00),
        "gpt-4.1-mini": (0.40, 1.60),
        "gpt-4.1-nano": (0.10, 0.40),
        "gpt-4.1": (2.00, 8.00),
    },
}

DEFAULT_TIMEOUT = 60.0
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0


# ── 数据结构 ──────────────────────────────────────────────────────────────


@dataclass
class Usage:
    """LLM 用量统计。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @property
    def cost(self) -> float | None:
        """预留：成本需结合 provider/model 上下文计算，无上下文返回 None。"""
        return None


@dataclass
class LLMResponse:
    """LLM 调用返回结构。"""

    content: str
    model: str = ""
    usage: Usage = field(default_factory=Usage)
    finish_reason: str = "stop"


# ── 抽象基类 ──────────────────────────────────────────────────────────────


class LLMProvider(ABC):
    """LLM 提供商抽象基类。"""

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """发送对话请求并返回结构化响应。

        Args:
            messages: 消息列表，格式 [{"role": "...", "content": "..."}]。
            model: 模型名称，为 None 时使用默认模型。
            temperature: 采样温度（0-2）。
            max_tokens: 最大输出 token 数。

        Returns:
            LLMResponse 包含回复内容和用量。

        Raises:
            httpx.HTTPError: HTTP 请求失败时抛出。
            ValueError: 缺少 API Key 时抛出。
        """
        ...


# ── 具体实现 ──────────────────────────────────────────────────────────────


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI 兼容 API 的通用实现。

    Args:
        provider: 提供商名称（deepseek / qwen / openai）。
        api_key: API Key，为 None 时从环境变量读取。
        base_url: API 基础地址，为 None 时使用默认配置。
        default_model: 默认模型名，为 None 时使用配置值。
    """

    def __init__(
        self,
        provider: str = "",
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
    ) -> None:
        name = provider or DEFAULT_PROVIDER
        if name not in PROVIDER_CONFIG:
            raise ValueError(
                f"不支持的 provider: {name}，可选: {list(PROVIDER_CONFIG)}"
            )

        cfg = PROVIDER_CONFIG[name]
        self._provider = name
        self.api_key = api_key or cfg["api_key"]
        self.base_url = (base_url or cfg["base_url"]).rstrip("/")
        self.default_model = default_model or cfg["default_model"]

        if not self.api_key:
            raise ValueError(
                f"缺少 API Key：请设置环境变量或传入 api_key 参数 "
                f"（provider={name}）"
            )

        self._client = httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(DEFAULT_TIMEOUT),
        )

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        model_name = model or self.default_model
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        logger.debug(
            "调用 LLM: provider=%s model=%s messages=%d",
            self._provider,
            model_name,
            len(messages),
        )

        try:
            resp = self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(
                "LLM HTTP 错误 %d: %s — %s",
                e.response.status_code,
                self._provider,
                e.response.text[:300],
            )
            raise
        except httpx.TimeoutException:
            logger.error("LLM 请求超时: %s（%.0fs）", self._provider, DEFAULT_TIMEOUT)
            raise
        except httpx.RequestError as e:
            logger.error("LLM 请求异常: %s — %s", self._provider, e)
            raise

        data = resp.json()
        choice = data["choices"][0]
        usage_raw = data.get("usage", {})

        return LLMResponse(
            content=choice["message"]["content"],
            model=data.get("model", model_name),
            usage=Usage(
                prompt_tokens=usage_raw.get("prompt_tokens", 0),
                completion_tokens=usage_raw.get("completion_tokens", 0),
                total_tokens=usage_raw.get("total_tokens", 0),
            ),
            finish_reason=choice.get("finish_reason", "stop"),
        )

    def close(self) -> None:
        """关闭底层 HTTP 客户端。"""
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


# ── 便利函数 ──────────────────────────────────────────────────────────────


def chat_with_retry(
    provider: LLMProvider,
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    max_retries: int = MAX_RETRIES,
    backoff: float = RETRY_BACKOFF,
) -> LLMResponse:
    """带指数退避重试的 LLM 调用。

    Args:
        provider: LLMProvider 实例。
        messages: 消息列表。
        model: 模型名。
        temperature: 采样温度。
        max_tokens: 最大输出 token。
        max_retries: 最大重试次数。
        backoff: 退避基础倍数（秒）。

    Returns:
        LLMResponse。

    Raises:
        httpx.HTTPError: 所有重试均失败时抛出最后一次异常。
    """
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            return provider.chat(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
            last_error = e
            if attempt < max_retries:
                wait = backoff ** attempt
                logger.warning(
                    "LLM 调用失败 (第 %d/%d 次)，%s 秒后重试: %s",
                    attempt,
                    max_retries,
                    wait,
                    e,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "LLM 调用失败，已达最大重试次数 %d: %s", max_retries, e
                )

    raise last_error  # type: ignore[misc]


def estimate_tokens(text: str) -> int:
    """粗略估算文本的 token 数量（按英文 1 token ≈ 4 字符，中文 1 token ≈ 1 字符）。

    该方法是快速估算，实际 token 数取决于模型的分词器，不可用于精确计费。

    Args:
        text: 待估算文本。

    Returns:
        估算的 token 数。
    """
    import unicodedata

    total = 0
    for ch in text:
        if unicodedata.category(ch).startswith(("L", "N")) and ord(ch) > 127:
            total += 1
        else:
            total += 1
    return max(1, total // 3)


def estimate_cost(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float | None:
    """根据 provider / model / token 数估算 USD 成本。

    Args:
        provider: 提供商名称（deepseek / qwen / openai）。
        model: 模型名，用于匹配价格表。
        prompt_tokens: 输入 token 数。
        completion_tokens: 输出 token 数。

    Returns:
        估算的 USD 成本，无法匹配价格时返回 None。
    """
    provider_pricing = PRICING.get(provider)
    if provider_pricing is None:
        logger.warning("未知 provider %s，无法估算成本", provider)
        return None

    price = provider_pricing.get(model)
    if price is None:
        # fallback — 模糊匹配前缀
        for key, val in provider_pricing.items():
            if model.startswith(key):
                price = val
                break

    if price is None:
        logger.warning("未知模型 %s/%s，无法估算成本", provider, model)
        return None

    input_price, output_price = price
    cost = (prompt_tokens / 1_000_000) * input_price + (
        completion_tokens / 1_000_000
    ) * output_price
    return round(cost, 6)


def quick_chat(
    prompt: str,
    system: str = "You are a helpful assistant.",
    provider: LLMProvider | None = None,
    model: str | None = None,
) -> str:
    """一句话调用 LLM 获取回复文本。

    Args:
        prompt: 用户输入。
        system: 系统提示词。
        provider: LLMProvider 实例，为 None 时自动创建默认提供商。
        model: 模型名，为 None 时使用默认模型。

    Returns:
        LLM 回复文本。

    Raises:
        httpx.HTTPError: 请求失败时抛出。
        ValueError: 缺少 API Key 时抛出。
    """
    if provider is None:
        provider = OpenAICompatibleProvider()

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    try:
        response = provider.chat(messages=messages, model=model)
        return response.content
    finally:
        if provider is not None and not isinstance(provider, OpenAICompatibleProvider):
            pass
        elif isinstance(provider, OpenAICompatibleProvider) and provider is not None:
            provider.close()


def _get_provider() -> OpenAICompatibleProvider:
    """内部辅助：创建默认 provider 实例。"""
    return OpenAICompatibleProvider()


# ── 测试 ───────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print("=" * 60)
    print("LLM Model Client — 自检测试")
    print("=" * 60)
    print(f"LLM_PROVIDER = {os.getenv('LLM_PROVIDER', 'deepseek')}")

    try:
        client = OpenAICompatibleProvider()
    except ValueError as e:
        logger.warning("跳过：%s", e)
        print(f"跳过集成测试：{e}")
        print("请设置对应 API Key 后重试。")
        raise SystemExit(0) from e

    print(f"Provider : {client._provider}")
    print(f"Base URL : {client.base_url}")
    print(f"Model    : {client.default_model}")
    print("-" * 60)

    messages = [
        {"role": "user", "content": "用一句话介绍什么是 LLM？"},
    ]

    try:
        response = chat_with_retry(client, messages, max_tokens=128)
        print(f"回复      : {response.content}")
        print(f"模型      : {response.model}")
        print(f"finish    : {response.finish_reason}")
        print(f"Token (p/c/t): {response.usage.prompt_tokens} / "
              f"{response.usage.completion_tokens} / "
              f"{response.usage.total_tokens}")

        cost = estimate_cost(
            provider=client._provider,
            model=response.model,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
        )
        if cost is not None:
            print(f"估算成本  : ${cost:.6f}")
        else:
            print("估算成本  : N/A（未匹配价格表）")

        print(f"估算 tokens: ~{estimate_tokens(response.content)}")

    except (httpx.HTTPError, ValueError, OSError) as e:
        print(f"调用失败: {e}")

    print("-" * 60)

    # quick_chat 测试
    try:
        reply = quick_chat("Say 'hello' in one word.")
        print(f"quick_chat: {reply}")
    except (httpx.HTTPError, ValueError, OSError) as e:
        print(f"quick_chat 失败: {e}")

    print("=" * 60)
    print("测试完成")
