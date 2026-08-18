"""think_stream 流式思考测试：覆盖 llm.call 流式路径的 await 语义。"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import pytest

from app.agents.executor import ExecutorAgent
from app.llm.pool import AICapability

CAP = AICapability(
    id="t1",
    name="Test",
    endpoint="http://localhost:1/v1",
    model="auto",
    api_key="",
    tags=["python"],
    max_context=4096,
)


class FakeLLM:
    def __init__(self):
        self.calls = []

    async def call(self, *args, **kwargs):
        async def gen():
            for piece in ("hello", " world"):
                yield piece

        self.calls.append((args, kwargs))
        return gen()


@pytest.mark.asyncio
async def test_think_stream_awaits_call():
    agent = ExecutorAgent(CAP)
    agent.llm = FakeLLM()
    agent.bind_context("task-stream-1")
    chunks = []
    async for chunk in agent.think_stream():
        chunks.append(chunk)
    assert "".join(chunks) == "hello world"
    assert agent.messages[-1]["role"] == "assistant"
    assert "hello world" in agent.messages[-1]["content"]


@pytest.mark.asyncio
async def test_think_stream_adds_user_message():
    agent = ExecutorAgent(CAP)
    agent.llm = FakeLLM()
    agent.bind_context("task-stream-2")
    async for _ in agent.think_stream(user_message="请输出代码"):
        pass
    assert any(
        m["role"] == "user" and m["content"] == "请输出代码" for m in agent.messages
    )
