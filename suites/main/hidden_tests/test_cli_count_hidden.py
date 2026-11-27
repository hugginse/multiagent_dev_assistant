"""T111 隐藏：CLI count 子命令。"""
from __future__ import annotations

from orderlib.cli import main


def test_count_exit_zero(capsys) -> None:
    code = main(["count"])
    assert code == 0
    out = capsys.readouterr().out
    assert "orders:" in out
    assert "skus:" in out


def test_count_values(capsys) -> None:
    main(["count"])
    out = capsys.readouterr().out
    lines = {
        ln.strip().split(":")[0]: ln.strip().split(":")[1].strip()
        for ln in out.splitlines()
        if ":" in ln
    }
    assert lines["orders"] == "0"
    assert int(lines["skus"]) >= 2
