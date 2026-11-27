"""双通道 Embedding 客户端（ollama | openai，**无 anthropic**）。

默认：``EMBED_PROVIDER=ollama`` + ``qwen3-embedding:4b``（architecture.md §0、§2）。
缺 key / 非法 provider 显式失败，禁止静默降级。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.llm.client import LLMError

VALID_EMBED_PROVIDERS = frozenset({"ollama", "openai"})


class EmbedError(LLMError):
    """Embedding 通道错误（配置或 HTTP）。"""


class EmbedClient:
    """统一 embedding 接口：``embed(texts) -> list[list[float]]``。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.provider = self.settings.embed_provider
        if self.provider not in VALID_EMBED_PROVIDERS:
            raise EmbedError(
                f"EMBED_PROVIDER 必须是 {sorted(VALID_EMBED_PROVIDERS)} 之一，"
                f"收到 {self.provider!r}（无 anthropic 通道）"
            )
        self.model = self.settings.embed_model
        if not self.model.strip():
            raise EmbedError("EMBED_MODEL 不得为空（禁止静默降级）")

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.provider == "ollama":
            self._base_url = self.settings.ollama_host.rstrip("/")
        else:
            if not self.settings.openai_api_key.strip():
                raise EmbedError(
                    "OPENAI_API_KEY 未配置：openai embedding 通道缺 key 必须显式失败"
                )
            self._base_url = self.settings.openai_base_url.rstrip("/")
            headers["Authorization"] = f"Bearer {self.settings.openai_api_key}"
        self._headers = headers
        self._client = httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0))

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> EmbedClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def dimensions_hint(self) -> int | None:
        """已知模型的维度提示（qwen3-embedding:4b → 2560）；未知返回 None。"""
        name = self.model.lower()
        if "qwen3-embedding:4b" in name:
            return 2560
        return None

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """批量文本向量；空列表返回空。"""
        if not texts:
            return []
        if self.provider == "ollama":
            return self._embed_ollama(list(texts))
        return self._embed_openai(list(texts))

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    # ------------------------------------------------------------------ #
    def _embed_ollama(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        try:
            for t in texts:
                resp = self._client.post(
                    f"{self._base_url}/api/embed",
                    json={"model": self.model, "input": t},
                    headers=self._headers,
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("error"):
                    raise EmbedError(f"ollama embedding 错误: {data['error']}")
                embeddings = data.get("embeddings") or []
                if not embeddings:
                    raise EmbedError("ollama embedding 返回空结果")
                out.append([float(x) for x in embeddings[0]])
        except httpx.HTTPError as e:
            raise EmbedError(f"ollama embedding 请求失败: {e}") from e
        return out

    def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        try:
            resp = self._client.post(
                f"{self._base_url}/embeddings",
                json={"model": self.model, "input": texts},
                headers=self._headers,
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise EmbedError(f"openai embedding 请求失败: {e}") from e
        data: dict[str, Any] = resp.json()
        if data.get("error"):
            err = data["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise EmbedError(f"openai embedding 错误: {msg}")
        items = data.get("data") or []
        if len(items) != len(texts):
            raise EmbedError(
                f"openai embedding 数量不匹配: 期望 {len(texts)}，收到 {len(items)}"
            )
        # 按 index 排序保证顺序
        items_sorted = sorted(items, key=lambda x: int(x.get("index") or 0))
        return [[float(x) for x in item["embedding"]] for item in items_sorted]


def create_embed_client(settings: Settings | None = None) -> EmbedClient:
    """工厂：按配置创建 embedding 客户端。"""
    return EmbedClient(settings)
