"""episode 沉淀：run 终态 → LLM 压缩 → memories(kind=episode) 落库。

architecture.md §4.4：
- 写入时机：run 终态后自动沉淀
- 内容：任务摘要 → 解法思路 → diff 摘要 → 结果 → 教训
- LLM 压缩，失败时降级为规则摘要（不阻断主流程）
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any

from app.llm.client import LLMClient, Message, create_llm_client
from app.memory.long_term import LongTermMemory

_SYSTEM = (
    "你是研发历史压缩器。根据一次 Agent 任务运行记录，输出简洁 episode（中文）。\n"
    "格式（严格）：\n"
    "TITLE: <不超过20字标题>\n"
    "SUMMARY: <任务与结果 2-3 句>\n"
    "LESSON: <1-2 条可复用教训，无则写 无>\n"
    "只输出这三段，不要其它内容。"
)


@dataclass(slots=True)
class EpisodeResult:
    status: str  # saved | skipped | failed
    memory_id: str | None = None
    title: str | None = None
    error: str | None = None


def _rule_based_title(task_id: str, title: str, resolve: bool) -> str:
    flag = "成功" if resolve else "未解"
    base = (title or task_id)[:16]
    return f"{task_id} {flag}: {base}"


def _rule_based_content(
    *,
    task_id: str,
    title: str,
    prompt: str,
    resolve: bool,
    iterations: int,
    error: str | None,
) -> str:
    result = "隐藏测试全部通过" if resolve else "隐藏测试未全部通过"
    lesson = "按计划分步修改并运行测试" if resolve else "需更仔细对照任务与失败输出"
    return (
        f"任务 {task_id}: {title}\n"
        f"描述: {prompt[:300]}\n"
        f"结果: {result}，迭代 {iterations} 轮"
        + (f"，错误: {error[:200]}" if error else "")
        + f"\n教训: {lesson}"
    )


def _parse_llm_reply(text: str) -> tuple[str, str]:
    """返回 (title, content)。"""
    title = ""
    summary = ""
    lesson = ""
    for line in text.splitlines():
        if line.startswith("TITLE:"):
            title = line.split(":", 1)[1].strip()
        elif line.startswith("SUMMARY:"):
            summary = line.split(":", 1)[1].strip()
        elif line.startswith("LESSON:"):
            lesson = line.split(":", 1)[1].strip()
    if not title:
        return "", ""
    content = summary
    if lesson:
        content = f"{summary}\n教训: {lesson}" if summary else f"教训: {lesson}"
    return title, content.strip()


def save_episode(
    *,
    repo_id: str,
    task_id: str,
    task_title: str,
    prompt: str,
    resolve: bool,
    iterations: int,
    error: str | None = None,
    llm: LLMClient | None = None,
    memory: LongTermMemory | None = None,
    memory_on: bool = True,
) -> EpisodeResult:
    """run 终态沉淀 episode。memory_on=False 时直接 skipped。"""
    if not memory_on:
        return EpisodeResult(status="skipped", error="memory off")

    mem = memory or LongTermMemory()
    owned_llm = False
    title = ""
    content = ""

    if llm is None:
        try:
            llm = create_llm_client()
            owned_llm = True
        except Exception:  # noqa: BLE001 — 无 LLM 时降级规则摘要
            llm = None

    if llm is not None:
        try:
            user = (
                f"task_id={task_id}\ntitle={task_title}\nresolve={resolve}\n"
                f"iterations={iterations}\nerror={error or ''}\n"
                f"prompt={prompt[:2000]}"
            )
            reply = llm.complete(
                [
                    Message(role="system", content=_SYSTEM),
                    Message(role="user", content=user),
                ],
                temperature=0.3,
                max_tokens=800,
            )
            title, content = _parse_llm_reply(reply.content)
        except Exception:  # noqa: BLE001 — LLM 失败降级
            title, content = "", ""
        finally:
            if owned_llm:
                with contextlib.suppress(Exception):
                    llm.close()

    if not title or not content:
        title = _rule_based_title(task_id, task_title, resolve)
        content = _rule_based_content(
            task_id=task_id,
            title=task_title,
            prompt=prompt,
            resolve=resolve,
            iterations=iterations,
            error=error,
        )

    if not memory_on:
        return EpisodeResult(status="skipped", title=title)

    try:
        mem.ensure_repo(repo_id, name=repo_id)
        mid = mem.add(
            repo_id=repo_id,
            kind="episode",
            title=title,
            content=content,
            task_ref=task_id,
        )
        return EpisodeResult(status="saved", memory_id=mid, title=title)
    except Exception as e:  # noqa: BLE001
        return EpisodeResult(status="failed", title=title, error=str(e))


def maybe_save_episode_from_outcome(
    outcome: Any,
    *,
    repo_id: str,
    memory_on: bool,
    llm: LLMClient | None = None,
    memory: LongTermMemory | None = None,
) -> EpisodeResult:
    """从 RunOutcome 沉淀（harness 终态钩子）。"""
    metrics = getattr(outcome, "metrics", None)
    state = getattr(outcome, "final_state", None) or {}
    task = state.get("task") if isinstance(state, dict) else None
    task_title = getattr(task, "title", "") or ""
    prompt = getattr(task, "prompt", "") or ""
    task_id = getattr(outcome, "task_id", "") or getattr(task, "id", "")
    resolve = bool(getattr(metrics, "resolve", False))
    iterations = int(getattr(metrics, "iterations", 0) or 0)
    error = getattr(metrics, "error", None)
    return save_episode(
        repo_id=repo_id,
        task_id=task_id,
        task_title=task_title,
        prompt=prompt,
        resolve=resolve,
        iterations=iterations,
        error=error,
        llm=llm,
        memory=memory,
        memory_on=memory_on,
    )
