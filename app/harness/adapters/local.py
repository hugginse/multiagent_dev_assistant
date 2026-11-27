"""自建套件 adapter：读 suites/<name>/tasks/*.yaml。"""

from __future__ import annotations

from pathlib import Path

from app.harness.loader import load_tasks
from app.harness.schema import TaskDefinition


class LocalSuiteAdapter:
    """local.py（M1）：读 suites/。"""

    name = "local"

    def __init__(self, suite: str = "smoke", root: Path | str | None = None) -> None:
        self.suite = suite
        self.root = Path(root) if root else None

    def load_tasks(self) -> list[TaskDefinition]:
        return load_tasks(self.suite, root=self.root)
