"""工程骨架冒烟测试：包可导入、版本一致。"""

import tomllib
from pathlib import Path

import app


def test_package_importable() -> None:
    assert app.__version__


def test_python_version_pinned_to_3_12() -> None:
    assert Path(".python-version").read_text(encoding="utf-8").strip() == "3.12"


def test_pyproject_requires_python_3_12() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert "3.12" in data["project"]["requires-python"]
