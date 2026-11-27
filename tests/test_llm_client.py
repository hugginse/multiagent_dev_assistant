"""LLM 客户端：显式失败、消息归一化、tool_calls 解析（不打真实网络）。"""

from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.llm.client import (
    LLMError,
    LLMUsage,
    Message,
    ToolCall,
    _merge_tool_call,
    _openai_tools,
    _parse_openai_tool_calls,
    _to_dict,
    create_llm_client,
)


def _settings(**kwargs: object) -> Settings:
    base: dict = {"_env_file": None}
    base.update(kwargs)
    return Settings(**base)  # type: ignore[arg-type]


def test_create_client_defaults_to_ollama_local_model() -> None:
    with create_llm_client(_settings()) as c:
        assert c.provider == "ollama"
        assert c.model == "qwen3.5:9b"


def test_openai_missing_key_raises_explicitly() -> None:
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        create_llm_client(_settings(llm_provider="openai", openai_api_key="", openai_model="gpt-4o"))


def test_anthropic_missing_key_raises_explicitly() -> None:
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        create_llm_client(
            _settings(llm_provider="anthropic", anthropic_api_key="", anthropic_model="claude-x")
        )


def test_openai_missing_model_raises() -> None:
    with pytest.raises(LLMError, match="OPENAI_MODEL"):
        create_llm_client(_settings(llm_provider="openai", openai_api_key="sk-x", openai_model=""))


def test_message_to_dict_roundtrip() -> None:
    m = Message(role="user", content="你好")
    d = _to_dict(m)
    assert d == {"role": "user", "content": "你好"}

    assistant = Message(
        role="assistant",
        content="",
        tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "a.py"})],
    )
    d2 = _to_dict(assistant)
    assert d2["tool_calls"][0]["function"]["name"] == "read_file"
    assert json.loads(d2["tool_calls"][0]["function"]["arguments"]) == {"path": "a.py"}


def test_parse_openai_tool_calls_bad_json_tolerated() -> None:
    calls = _parse_openai_tool_calls(
        [{"id": "1", "function": {"name": "x", "arguments": "{not-json"}}]
    )
    assert len(calls) == 1
    assert "_raw" in calls[0].arguments


def test_openai_tools_wrapper_shape() -> None:
    tools = [
        {
            "name": "grep",
            "description": "search",
            "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
        }
    ]
    wrapped = _openai_tools(tools)
    assert wrapped is not None
    assert wrapped[0]["type"] == "function"
    assert wrapped[0]["function"]["name"] == "grep"


def test_merge_tool_call_fragments() -> None:
    acc: list[ToolCall] = []
    _merge_tool_call(acc, ToolCall(id="a", name="write_file", arguments={"path": "x"}))
    _merge_tool_call(acc, ToolCall(id="a", name="write_file", arguments={"content": "y"}))
    assert len(acc) == 1
    assert acc[0].arguments == {"path": "x", "content": "y"}


def test_usage_add() -> None:
    u = LLMUsage(tokens_in=1, tokens_out=2)
    u.add(LLMUsage(tokens_in=3, tokens_out=4))
    assert (u.tokens_in, u.tokens_out) == (4, 6)


def test_anthropic_provider_requires_model_and_key() -> None:
    with pytest.raises(LLMError):
        create_llm_client(
            _settings(
                llm_provider="anthropic",
                anthropic_api_key="sk-ant-test",
                anthropic_model="",
            )
        )
