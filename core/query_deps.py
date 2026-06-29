"""
查询依赖注入接口 (对应 src/query/deps.ts)

将 I/O 边界操作接口化，生产/测试环境不同实现。
"""
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Callable, Coroutine, Protocol


class ModelCallFn(Protocol):
    """模型调用函数签名"""
    async def __call__(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None,
        tools: list[dict[str, Any]] | None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        ...


class CompactFn(Protocol):
    """压缩函数签名"""
    async def __call__(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        ...


@dataclass
class QueryDeps:
    """查询依赖接口"""
    call_model: ModelCallFn
    compact_messages: CompactFn
    uuid: Callable[[], str] = __import__("uuid").uuid4

    @staticmethod
    def production():
        """生产环境依赖"""
        from llm.client import LLMClient
        from state.session import get_session

        session = get_session()
        client = LLMClient(
            api_key=session.api_key,
            base_url=session.base_url,
            model=session.model,
        )

        async def call_model(messages, system_prompt, tools):
            async for event in client.chat_completion_stream(
                messages, system_prompt, tools
            ):
                yield event

        return QueryDeps(
            call_model=call_model,
            compact_messages=None,  # 在 agent 中处理
        )
