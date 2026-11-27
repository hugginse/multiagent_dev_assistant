"""共享测试工具：剥离 ANSI，避免 CI 上 rich 颜色导致断言失败。"""

from __future__ import annotations

import re

import pytest

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    """去掉 SGR/ANSI 颜色码。"""
    return _ANSI.sub("", text)


@pytest.fixture()
def plain():
    """把输出剥色：``assert "xx" in plain(r.stdout)``。"""
    return strip_ansi
