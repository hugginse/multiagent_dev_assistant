"""记忆检索注入：top-k、阈值、prompt 模板、开关。

architecture.md §4.4：
- 注入格式：``## 仓库约定（长期记忆）`` / ``## 相似历史任务``
- 可开关（--memory off 不注入），供 A/B
- 检索：cosine top-k，默认 k=5、阈值 0.35，低于阈值不注入
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import load_settings
from app.memory.long_term import LongTermMemory, MemoryHit

CONVENTION_HEADER = "## 仓库约定（长期记忆）"
EPISODE_HEADER = "## 相似历史任务"


@dataclass(slots=True)
class InjectionResult:
    """一次注入的结果。"""

    enabled: bool
    text: str = ""
    convention_hits: list[MemoryHit] = field(default_factory=list)
    episode_hits: list[MemoryHit] = field(default_factory=list)
    skipped_reason: str = ""

    @property
    def empty(self) -> bool:
        return not self.text.strip()


def render_injection(
    conventions: list[MemoryHit],
    episodes: list[MemoryHit],
    *,
    max_content_chars: int = 500,
) -> str:
    """按约定模板拼接 prompt 片段。"""
    parts: list[str] = []
    if conventions:
        lines = [CONVENTION_HEADER]
        for i, h in enumerate(conventions, 1):
            content = h.content.strip()
            if len(content) > max_content_chars:
                content = content[:max_content_chars] + "…"
            lines.append(f"{i}. **{h.title}**: {content}")
        parts.append("\n".join(lines))
    if episodes:
        lines = [EPISODE_HEADER]
        for i, h in enumerate(episodes, 1):
            content = h.content.strip()
            if len(content) > max_content_chars:
                content = content[:max_content_chars] + "…"
            lines.append(f"{i}. [{h.score:.2f}] {h.title}: {content}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def inject_memory(
    query: str,
    *,
    repo_id: str,
    enabled: bool = True,
    memory: LongTermMemory | None = None,
    top_k: int | None = None,
    min_score: float | None = None,
    include_episodes: bool = True,
) -> InjectionResult:
    """检索并渲染注入文本。enabled=False 时返回空（A/B off 臂）。"""
    if not enabled:
        return InjectionResult(enabled=False, skipped_reason="memory off")

    settings = load_settings()
    k = top_k if top_k is not None else settings.memory_top_k
    threshold = min_score if min_score is not None else settings.memory_min_score

    mem = memory or LongTermMemory()
    try:
        conv = mem.search(
            query, repo_id=repo_id, kind="convention", top_k=k, min_score=threshold
        )
        eps: list[MemoryHit] = []
        if include_episodes:
            eps = mem.search(
                query, repo_id=repo_id, kind="episode", top_k=k, min_score=threshold
            )
    except Exception as e:  # noqa: BLE001 — 检索失败不阻断主流程
        return InjectionResult(enabled=True, skipped_reason=f"search failed: {e}")

    text = render_injection(conv, eps)
    return InjectionResult(
        enabled=True,
        text=text,
        convention_hits=conv,
        episode_hits=eps,
        skipped_reason="" if text else "no hits above threshold",
    )


def build_memory_context(
    task_prompt: str,
    *,
    repo_id: str,
    enabled: bool = True,
    memory: LongTermMemory | None = None,
    **kwargs: Any,
) -> tuple[str, InjectionResult]:
    """以任务 prompt 为 query；返回 (memory_context, detail)。"""
    result = inject_memory(
        task_prompt, repo_id=repo_id, enabled=enabled, memory=memory, **kwargs
    )
    return result.text, result
