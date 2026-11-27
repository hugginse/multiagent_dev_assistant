"""任务与报告 schema（architecture.md §6）。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from pydantic import BaseModel, Field, field_validator


class TaskDefinition(BaseModel):
    """YAML 任务定义。Agent 只能看到 ``prompt``，看不到 hidden_tests。"""

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    repo: str = "sample_repo"
    difficulty: str = "medium"
    prompt: str = Field(min_length=1)
    hidden_tests: list[str] = Field(default_factory=list)
    max_iterations: int = Field(default=8, ge=1, le=64)
    timeout_s: float = Field(default=300.0, gt=0)
    tags: list[str] = Field(default_factory=list)

    @field_validator("difficulty")
    @classmethod
    def _diff(cls, v: str) -> str:
        norm = v.strip().lower()
        if norm not in {"easy", "medium", "hard"}:
            raise ValueError(f"difficulty 必须是 easy|medium|hard，收到 {v!r}")
        return norm

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("task id 不得为空")
        return v.strip()


@dataclass(slots=True)
class RunMetrics:
    """单次 run 指标。"""

    resolve: bool = False
    test_pass_ratio: float = 0.0
    iterations: int = 0
    max_hit: bool = False
    tool_calls: dict[str, int] = field(default_factory=dict)  # 按 tier
    tokens_in: int = 0
    tokens_out: int = 0
    wall_s: float = 0.0
    status: str = "running"  # success | timeout | error
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Report:
    """一次评测的汇总报告。"""

    eval_id: str
    suite: str
    k: int
    provider: str
    model: str
    memory_on: bool
    items: list[dict[str, Any]] = field(default_factory=list)
    pass_at_k: dict[str, float] = field(default_factory=dict)
    created_at: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
