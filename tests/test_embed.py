"""Embedding 客户端配置与显式失败测试（不打真实网络）。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.llm.embed import EmbedError, create_embed_client


def _settings(**kwargs: object) -> Settings:
    base: dict = {"_env_file": None}
    base.update(kwargs)
    return Settings(**base)  # type: ignore[arg-type]


def test_default_is_ollama_qwen3_embedding() -> None:
    with create_embed_client(_settings()) as c:
        assert c.provider == "ollama"
        assert c.model == "qwen3-embedding:4b"
        assert c.dimensions_hint == 2560


def test_openai_embed_missing_key_explicit_failure() -> None:
    with pytest.raises(EmbedError, match="OPENAI_API_KEY"):
        create_embed_client(
            _settings(embed_provider="openai", openai_api_key="", embed_model="text-embedding-3-small")
        )


def test_empty_model_rejected() -> None:
    with pytest.raises(EmbedError, match="EMBED_MODEL"):
        create_embed_client(_settings(embed_model="  "))


def test_anthropic_not_valid_embed_provider() -> None:
    # Settings 层已拒绝（EMBED_PROVIDER 无 anthropic）
    with pytest.raises(ValidationError, match="EMBED_PROVIDER"):
        _settings(embed_provider="anthropic")


def test_embed_empty_list_returns_empty_without_network() -> None:
    with create_embed_client(_settings()) as c:
        assert c.embed([]) == []
