"""SWE-bench Lite 子集 adapter（≤10 条，本地沙箱执行）。

architecture.md §6.5：
- 读官方 task JSON 字段（instance_id / problem_statement / patch 参考）
- 取 ≤10 条 Python 实例
- 测试执行仍走本地沙箱——**README 必须注明与官方 Docker 执行口径的差异，不冒充官方分数**

数据来源：
1. ``SWE_BENCH_PATH`` 或 ``data/swe_bench/*.json`` 本地文件
2. 内置 ``suites/swe_bench/sample.json`` 演示子集（无网络时可用）

完整 SWE-bench 需要官方 repo 快照 + Docker，本项目 M4 不引入；
本地模式将 instance 映射为可在 sample_repo 沙箱执行的任务，并在 prompt 中标注口径。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.harness.schema import TaskDefinition

MAX_SUBSET = 10
DEFAULT_SAMPLE = Path(__file__).resolve().parents[3] / "suites" / "swe_bench" / "sample.json"

# 口径声明（写入每条任务 prompt 头部，避免冒充官方分数）
EXECUTION_NOTE = (
    "[执行口径说明] 本任务字段来自 SWE-bench Lite 格式子集，"
    "但测试在本地 workspace 沙箱执行，**不等于**官方 Docker 官方分数。"
)


def _load_raw(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if isinstance(data, dict):
        # 可能是 {"instances": [...]} 或单条
        if "instances" in data:
            data = data["instances"]
        elif "task_id" in data or "instance_id" in data:
            data = [data]
        else:
            # dict of id -> instance
            data = [dict(v, instance_id=k) if isinstance(v, dict) else v for k, v in data.items()]
    if not isinstance(data, list):
        raise ValueError(f"SWE-bench 文件格式无法识别: {path}")
    return [x for x in data if isinstance(x, dict)]


def _pick_python(instances: list[dict[str, Any]], limit: int = MAX_SUBSET) -> list[dict[str, Any]]:
    py: list[dict[str, Any]] = []
    for inst in instances:
        repo = str(inst.get("repo") or inst.get("repo_name") or "")
        # 优先标记为 python 的；无信息时若 instance_id 含 py 则收
        iid = str(inst.get("instance_id") or inst.get("task_id") or "")
        if "python" in repo.lower() or iid.lower().startswith("py") or inst.get("language") == "python":
            py.append(inst)
        elif not repo and not inst.get("language"):
            # 无元数据时收进子集（演示文件）
            py.append(inst)
        if len(py) >= limit:
            break
    if not py:
        py = instances[:limit]
    return py[:limit]


def _to_task(inst: dict[str, Any], idx: int) -> TaskDefinition:
    iid = str(inst.get("instance_id") or inst.get("task_id") or f"swe_{idx}")
    # 清洗 id：YAML/CLI 安全
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in iid)[:48]
    problem = str(inst.get("problem_statement") or inst.get("problem") or "").strip()
    if not problem:
        problem = f"SWE-bench instance {iid}：请根据测试失败修复（本地口径）。"
    # 本地执行：映射到 sample_repo（口径已在 prompt 声明）
    prompt = (
        f"{EXECUTION_NOTE}\n"
        f"instance_id={iid}\n"
        f"repo={inst.get('repo', 'sample_repo')}\n\n"
        f"{problem}\n\n"
        "在本地 sample_repo 沙箱中完成修复，使相关测试通过；"
        "运行 `python -m pytest -q` 验证。"
    )
    hidden = inst.get("hidden_tests") or []
    if isinstance(hidden, str):
        hidden = [hidden]
    # 无隐藏测试文件时给一个通用占位路径（评分阶段若不存在则 score 0）
    if not hidden:
        hidden = ["test_swe_hidden.py"]
    return TaskDefinition(
        id=safe_id,
        title=(str(inst.get("title") or iid))[:80],
        repo="sample_repo",
        difficulty="hard",
        prompt=prompt,
        hidden_tests=[str(h) for h in hidden],
        max_iterations=int(inst.get("max_iterations") or 8),
        timeout_s=float(inst.get("timeout_s") or 300),
        tags=["swe_bench", "python"],
    )


class SWEbenchLiteAdapter:
    """swe_bench.py（M4）：≤10 条 Python 实例子集。"""

    name = "swe_bench"

    def __init__(
        self,
        path: Path | str | None = None,
        limit: int = MAX_SUBSET,
    ) -> None:
        self.path = Path(path) if path else None
        self.limit = max(1, min(limit, MAX_SUBSET))

    def _resolve_path(self) -> Path:
        if self.path is not None:
            return self.path
        env = os.environ.get("SWE_BENCH_PATH")
        if env:
            return Path(env)
        if DEFAULT_SAMPLE.exists():
            return DEFAULT_SAMPLE
        data_dir = Path("data/swe_bench")
        if data_dir.is_dir():
            files = sorted(data_dir.glob("*.json"))
            if files:
                return files[0]
        raise FileNotFoundError(
            "未找到 SWE-bench 数据。设置 SWE_BENCH_PATH 指向 JSON，"
            "或放置 suites/swe_bench/sample.json"
        )

    def load_tasks(self) -> list[TaskDefinition]:
        path = self._resolve_path()
        raw = _load_raw(path)
        subset = _pick_python(raw, limit=self.limit)
        return [_to_task(inst, i) for i, inst in enumerate(subset)]
