"""sample_repo 基线：真实执行 pytest，必须全绿。"""

from __future__ import annotations

import sys
from pathlib import Path

from app.sandbox.workspace import run_command

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = REPO_ROOT / "sample_repo"


def test_sample_repo_exists() -> None:
    assert (SAMPLE / "orderlib").is_dir()
    assert (SAMPLE / "tests").is_dir()
    assert (SAMPLE / "README.md").is_file()


def test_sample_repo_pytest_baseline_green() -> None:
    """演示仓库自带测试必须全绿（失败也是数据的前提是基线干净）。"""
    r = run_command(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=SAMPLE,
        timeout_s=120,
    )
    assert not r.timed_out, "sample_repo pytest 超时"
    assert r.returncode == 0, f"sample_repo 基线失败:\n{r.stdout}\n{r.stderr}"
    # -q 模式下用点号表示用例；0 退出码 + 非空输出即收集到测试
    out = (r.stdout + r.stderr).strip()
    assert out, "pytest 无输出"
    assert "error" not in out.lower() or "errors" not in out.lower()


def test_sample_repo_file_count_reasonable() -> None:
    """约 20 个源文件（排除缓存）。"""
    files = [
        p
        for p in SAMPLE.rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and p.suffix in {".py", ".md", ".toml"}
    ]
    assert 15 <= len(files) <= 40, f"unexpected file count: {len(files)}"
