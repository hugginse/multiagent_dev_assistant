"""仓库 onboarding：扫描仓库 → LLM 抽取约定 → convention 记忆落库。

CLI：``devassist memory onboarding --path sample_repo``
流程（architecture.md §4.4）：
1. 扫描仓库树 + README + 关键文件（限制体积）
2. LLM 产出约定初稿（结构化 markdown）
3. 落库 memories(kind=convention) + 向量
4. 更新 repos.onboarding_status
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from pathlib import Path

from app.llm.client import LLMClient, Message, create_llm_client
from app.memory.long_term import LongTermMemory

# 扫描时跳过的目录
_SKIP_DIRS = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    ".mypy_cache",
    "data",
    "chroma",
}
# 优先读取的关键文件名（小写匹配）
_KEY_FILES = (
    "readme.md",
    "pyproject.toml",
    "claude.md",
    "contributing.md",
)
_MAX_FILE_CHARS = 4_000
_MAX_TOTAL_CHARS = 24_000
_MAX_FILES = 30


@dataclass(slots=True)
class OnboardingResult:
    repo_id: str
    status: str  # done | failed
    conventions: list[dict[str, str]] = field(default_factory=list)  # {title, content}
    memory_ids: list[str] = field(default_factory=list)
    error: str | None = None
    scanned_files: int = 0


def scan_repo(path: Path | str) -> tuple[str, str, int]:
    """返回 (repo_id, corpus, file_count)。repo_id = 目录名。"""
    root = Path(path).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"仓库路径不存在: {root}")
    repo_id = root.name

    # 目录树
    tree_lines: list[str] = []
    files: list[Path] = []
    for p in sorted(root.rglob("*")):
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            tree_lines.append(rel)
            files.append(p)

    # 关键文件优先
    prioritized: list[Path] = []
    for name in _KEY_FILES:
        for f in files:
            if f.name.lower() == name:
                prioritized.append(f)
    # 其余按路径短的优先
    rest = sorted((f for f in files if f not in prioritized), key=lambda p: len(str(p)))
    ordered = prioritized + rest

    parts: list[str] = [f"# 仓库树（{repo_id}）\n```\n" + "\n".join(tree_lines[:200]) + "\n```\n"]
    total = sum(len(x) for x in parts)
    count = 0
    for f in ordered:
        if count >= _MAX_FILES or total >= _MAX_TOTAL_CHARS:
            break
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(text) > _MAX_FILE_CHARS:
            text = text[:_MAX_FILE_CHARS] + "\n...[truncated]...\n"
        rel = f.relative_to(root).as_posix()
        parts.append(f"\n## 文件 {rel}\n```\n{text}\n```\n")
        total += len(parts[-1])
        count += 1

    return repo_id, "\n".join(parts), count


_SYSTEM = (
    "你是仓库约定抽取器。根据提供的仓库文件内容，抽取对 AI 编码助手有用的**仓库约定**。\n"
    "输出格式（严格遵守，不要额外解释）：\n"
    "CONVENTION: <简短标题>\n"
    "<约定正文，1-4 句，可含示例>\n"
    "CONVENTION: <下一标题>\n"
    "<正文>\n"
    "至少输出 3 条、最多 12 条。关注：分层/目录、命名、错误处理、测试风格、"
    "禁用模式、金额/类型约定、公共 API。不要输出与仓库无关的通用建议。"
)


def _parse_conventions(text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    title: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        if line.startswith("CONVENTION:"):
            if title is not None:
                out.append({"title": title, "content": "\n".join(buf).strip()})
            title = line.split(":", 1)[1].strip()
            buf = []
        elif title is not None:
            buf.append(line)
    if title is not None:
        out.append({"title": title, "content": "\n".join(buf).strip()})
    # 过滤空
    return [c for c in out if c["title"] and c["content"]]


def run_onboarding(
    path: Path | str,
    *,
    llm: LLMClient | None = None,
    memory: LongTermMemory | None = None,
    memory_onboarding: bool = True,
) -> OnboardingResult:
    """扫描 + LLM 抽取 + 落库。llm=None 时抛错（需显式注入或创建）。"""
    try:
        repo_id, corpus, n_files = scan_repo(path)
    except FileNotFoundError as e:
        return OnboardingResult(repo_id=str(path), status="failed", error=str(e))

    result = OnboardingResult(repo_id=repo_id, status="failed", scanned_files=n_files)
    mem = memory or LongTermMemory()

    owned_llm = False
    if llm is None:
        try:
            llm = create_llm_client()
            owned_llm = True
        except Exception as e:  # noqa: BLE001
            result.error = f"LLM 客户端创建失败: {e}"
            return result

    try:
        messages = [
            Message(role="system", content=_SYSTEM),
            Message(role="user", content=corpus),
        ]
        reply = llm.complete(messages, temperature=0.2, max_tokens=3000)
        conventions = _parse_conventions(reply.content)
        if not conventions:
            result.error = "LLM 未产出任何 CONVENTION 段"
            return result
        result.conventions = conventions

        if memory_onboarding:
            mem.ensure_repo(repo_id, name=repo_id, path=str(Path(path).resolve()))
            for c in conventions:
                mid = mem.add(
                    repo_id=repo_id,
                    kind="convention",
                    title=c["title"],
                    content=c["content"],
                )
                result.memory_ids.append(mid)
            mem.set_onboarding_status(repo_id, "done")
        result.status = "done"
        return result
    except Exception as e:  # noqa: BLE001
        result.error = str(e)
        with contextlib.suppress(Exception):
            mem.set_onboarding_status(repo_id, "failed")
        return result
    finally:
        if owned_llm:
            with contextlib.suppress(Exception):
                llm.close()
