"""
LLM 客户端 (对应 src/services/api/claude.ts)

支持 OpenAI 兼容 API 的流式调用。
"""
import json
import warnings
from typing import Any, AsyncGenerator, Optional

import httpx
from openai import AsyncOpenAI


class LLMClient:
    """LLM API 客户端"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.anthropic.com/v1",
        model: str = "claude-sonnet-4-6",
        verify_ssl: bool = True,
    ):
        # 判断是否是 Anthropic API (需要特殊处理)
        if "anthropic" in base_url:
            self.provider = "anthropic"
        else:
            self.provider = "openai"

        # 构建 httpx 客户端（内网环境可能需要关闭 SSL 验证）
        http_client_kwargs: dict[str, Any] = {}
        if not verify_ssl:
            http_client_kwargs["verify"] = False
            # 抑制不安全请求警告
            warnings.filterwarnings("ignore", message="Unverified HTTPS request")

        http_client = httpx.AsyncClient(**http_client_kwargs)

        headers: dict[str, str] = {}
        if self.provider == "anthropic":
            headers["anthropic-version"] = "2023-06-01"

        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers=headers,
            http_client=http_client,
        )
        self.model = model

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        system_prompt: Optional[str] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        max_tokens: int = 16000,
        temperature: float = 1.0,
    ) -> dict[str, Any]:
        """非流式调用"""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": self._build_messages(messages, system_prompt),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools

        response = await self.client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        content = choice.message.content or ""

        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "input": args,
                })

        return {
            "content": content,
            "tool_calls": tool_calls,
            "stop_reason": choice.finish_reason,
            "usage": {
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
            },
        }

    async def chat_completion_stream(
        self,
        messages: list[dict[str, Any]],
        system_prompt: Optional[str] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        max_tokens: int = 16000,
        temperature: float = 1.0,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """流式调用 (AsyncGenerator 模式，对应 queryModel)"""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": self._build_messages(messages, system_prompt),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
        kwargs["stream_options"] = {"include_usage": True}

        stream = await self.client.chat.completions.create(**kwargs)

        accumulated_content = ""
        accumulated_tool_calls: dict[int, dict[str, Any]] = {}
        finish_reason = None
        usage: dict[str, Any] = {}

        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            finish_reason = chunk.choices[0].finish_reason or finish_reason

            # Capture usage from last chunk
            if hasattr(chunk, 'usage') and chunk.usage:
                usage = {
                    "input_tokens": chunk.usage.prompt_tokens or 0,
                    "output_tokens": chunk.usage.completion_tokens or 0,
                }

            # 累积文本
            if delta.content:
                accumulated_content += delta.content
                yield {
                    "type": "text_delta",
                    "text": delta.content,
                }

            # 累积工具调用
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in accumulated_tool_calls:
                        accumulated_tool_calls[idx] = {
                            "id": tc.id or "",
                            "name": tc.function.name if tc.function else "",
                            "arguments": "",
                        }
                    if tc.id:
                        accumulated_tool_calls[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            accumulated_tool_calls[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            accumulated_tool_calls[idx]["arguments"] += tc.function.arguments

        # 解析完成的工具调用
        final_tool_calls = []
        for tc in accumulated_tool_calls.values():
            try:
                args = json.loads(tc["arguments"]) if tc["arguments"] else {}
            except json.JSONDecodeError:
                args = {}
            final_tool_calls.append({
                "id": tc["id"],
                "name": tc["name"],
                "input": args,
            })

        yield {
            "type": "final",
            "content": accumulated_content,
            "tool_calls": final_tool_calls,
            "stop_reason": finish_reason,
            "usage": usage,
            "model": self.model,
        }

    def _build_messages(
        self,
        messages: list[dict[str, Any]],
        system_prompt: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """构建 API 请求消息"""
        built: list[dict[str, Any]] = []
        if system_prompt:
            built.append({"role": "system", "content": system_prompt})
        built.extend(messages)
        return built
