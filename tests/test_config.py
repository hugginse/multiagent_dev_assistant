"""配置加载与显式失败路径测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings, load_settings, reset_settings_cache


def test_default_provider_is_ollama_with_local_model() -> None:
    s = Settings(_env_file=None)
    assert s.llm_provider == "ollama"
    assert s.local_model == "qwen3.5:9b"
    assert s.embed_provider == "ollama"
    assert s.embed_model == "qwen3-embedding:4b"
    assert s.max_iterations == 8


def test_invalid_llm_provider_rejected() -> None:
    with pytest.raises(ValidationError, match="LLM_PROVIDER"):
        Settings(_env_file=None, llm_provider="gemini")


def test_invalid_embed_provider_rejected() -> None:
    with pytest.raises(ValidationError, match="EMBED_PROVIDER"):
        Settings(_env_file=None, embed_provider="anthropic")


def test_empty_local_model_rejected() -> None:
    with pytest.raises(ValidationError, match="LOCAL_MODEL"):
        Settings(_env_file=None, local_model="  ")


def test_openai_requires_key_explicitly() -> None:
    s = Settings(
        _env_file=None,
        llm_provider="openai",
        openai_api_key="",
        openai_model="gpt-4o-mini",
    )
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        s.require_api_key()


def test_anthropic_requires_key_explicitly() -> None:
    s = Settings(
        _env_file=None,
        llm_provider="anthropic",
        anthropic_api_key="",
        anthropic_model="claude-sonnet-4-5",
    )
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        s.require_api_key()


def test_openai_requires_model_name() -> None:
    s = Settings(_env_file=None, llm_provider="openai", openai_api_key="sk-test", openai_model="")
    with pytest.raises(ValueError, match="OPENAI_MODEL"):
        s.resolve_llm_model()


def test_resolve_model_by_provider() -> None:
    assert Settings(_env_file=None).resolve_llm_model() == "qwen3.5:9b"
    s = Settings(
        _env_file=None,
        llm_provider="openai",
        openai_api_key="sk-test",
        openai_model="gpt-4o",
    )
    assert s.resolve_llm_model() == "gpt-4o"


def test_load_settings_without_env_file() -> None:
    s = load_settings(env_file=None)
    assert s.llm_provider == "ollama"
    reset_settings_cache()


def test_ollama_num_ctx_bounds() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ollama_num_ctx=10)
