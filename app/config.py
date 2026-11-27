"""应用配置：pydantic-settings 读取 .env 与环境变量。

约定（architecture.md §9）：
- 默认 LLM 通道 ollama + qwen3.5:9b，Embedding 默认 ollama + qwen3-embedding:4b
- 双通道缺 key 显式失败，禁止静默降级
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

VALID_LLM_PROVIDERS = frozenset({"ollama", "openai", "anthropic"})
VALID_EMBED_PROVIDERS = frozenset({"ollama", "openai"})


class Settings(BaseSettings):
    """项目全部可配置项（env 前缀无，字段名即环境变量，大小写不敏感）。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LLM 双通道 ---
    llm_provider: str = "ollama"
    ollama_host: str = "http://127.0.0.1:11434"
    local_model: str = "qwen3.5:9b"
    ollama_num_ctx: int = Field(default=65536, ge=1024, le=262144)  # 本机 64k 稳定
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = ""
    anthropic_api_key: str = ""
    anthropic_model: str = ""

    # --- Embedding 双通道（无 anthropic）---
    embed_provider: str = "ollama"
    embed_model: str = "qwen3-embedding:4b"

    # --- 存储 ---
    database_url: str = "sqlite:///./data/app.db"
    chroma_dir: str = "./data/chroma"
    workspace_root: str = "./data/workspaces"

    # --- 图与工具 ---
    max_iterations: int = Field(default=8, ge=1, le=64)
    tool_timeout_s: float = Field(default=120.0, gt=0)

    # --- 记忆检索 ---
    memory_top_k: int = Field(default=5, ge=1, le=50)
    memory_min_score: float = Field(default=0.35, ge=0.0, le=1.0)

    @field_validator("llm_provider")
    @classmethod
    def _validate_llm_provider(cls, v: str) -> str:
        norm = v.strip().lower()
        if norm not in VALID_LLM_PROVIDERS:
            raise ValueError(
                f"LLM_PROVIDER 必须是 {sorted(VALID_LLM_PROVIDERS)} 之一，收到 {v!r}"
            )
        return norm

    @field_validator("embed_provider")
    @classmethod
    def _validate_embed_provider(cls, v: str) -> str:
        norm = v.strip().lower()
        if norm not in VALID_EMBED_PROVIDERS:
            raise ValueError(
                f"EMBED_PROVIDER 必须是 {sorted(VALID_EMBED_PROVIDERS)} 之一，收到 {v!r}"
            )
        return norm

    @field_validator("local_model")
    @classmethod
    def _validate_local_model(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("LOCAL_MODEL 不得为空（禁止静默降级到其他模型）")
        return v.strip()

    def resolve_llm_model(self) -> str:
        """按当前 provider 解析将要使用的模型名。"""
        if self.llm_provider == "ollama":
            return self.local_model
        if self.llm_provider == "openai":
            if not self.openai_model.strip():
                raise ValueError("OPENAI_MODEL 未配置：使用 openai 通道时必须显式指定模型")
            return self.openai_model.strip()
        if not self.anthropic_model.strip():
            raise ValueError("ANTHROPIC_MODEL 未配置：使用 anthropic 通道时必须显式指定模型")
        return self.anthropic_model.strip()

    def require_api_key(self) -> None:
        """缺 key 显式失败（openai / anthropic）。"""
        if self.llm_provider == "openai" and not self.openai_api_key.strip():
            raise ValueError(
                "OPENAI_API_KEY 未配置：openai 通道缺 key 必须显式失败，禁止静默降级"
            )
        if self.llm_provider == "anthropic" and not self.anthropic_api_key.strip():
            raise ValueError(
                "ANTHROPIC_API_KEY 未配置：anthropic 通道缺 key 必须显式失败，禁止静默降级"
            )


def load_settings(*, env_file: str | Path | None = None) -> Settings:
    """加载配置；env_file 显式指定时覆盖默认 .env 查找。"""
    if env_file is not None:
        return Settings(_env_file=str(env_file))
    return Settings()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内缓存的默认配置单例（测试可 clear）。"""
    return load_settings()


def reset_settings_cache() -> None:
    """清空配置缓存（测试用）。"""
    get_settings.cache_clear()
