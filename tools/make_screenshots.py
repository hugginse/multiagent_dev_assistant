"""生成固定尺寸终端演示截图（PNG）→ docs/screenshots/。

- 四张图统一 **1280×720**
- 字符网格渲染：ASCII=1 格、CJK/全角=2 格，与 rich 列宽对齐
- 中文字体，避免乱码

用法：uv run python tools/make_screenshots.py
"""

from __future__ import annotations

import io
import sys
import unicodedata
from pathlib import Path

from rich.console import Console

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

# 四张统一尺寸
CANVAS_W = 1280
CANVAS_H = 720
CELL_W = 9  # 每终端列像素宽
LINE_H = 18
PAD_X = 20
PAD_Y = 16
TITLE_H = 28
MAX_COLS = (CANVAS_W - PAD_X * 2) // CELL_W  # ≈137
MAX_ROWS = (CANVAS_H - PAD_Y * 2 - TITLE_H) // LINE_H  # ≈36

_CJK_FONTS = (
    "C:/Windows/Fonts/Deng.ttf",
    "C:/Windows/Fonts/Dengb.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/NotoSansSC-VF.ttf",
    "C:/Windows/Fonts/simsun.ttc",
)


def _load_font(size: int = 14):
    from PIL import ImageFont

    for fp in _CJK_FONTS:
        try:
            return ImageFont.truetype(fp, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _char_cells(ch: str) -> int:
    """终端列宽：全角/宽字符=2，其余=1。"""
    if ch == "\t":
        return 4
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    if ord(ch) < 32:
        return 0
    return 1


def _line_cells(s: str) -> int:
    return sum(_char_cells(c) for c in s)


def _strip_ansi(s: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == "\x1b":
            if i + 1 < len(s) and s[i + 1] == "[":
                j = i + 2
                while j < len(s) and not s[j].isalpha():
                    j += 1
                i = j + 1 if j < len(s) else len(s)
                continue
            if i + 1 < len(s) and s[i + 1] == "]":
                j = i + 2
                while j < len(s) and s[j] not in ("\x07", "\x1b"):
                    j += 1
                i = j + 1
                continue
            i += 2
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


def _fit_line(s: str, max_cells: int) -> str:
    """按终端格截断。"""
    cells = 0
    out: list[str] = []
    for ch in s:
        w = _char_cells(ch)
        if cells + w > max_cells:
            out.append("…")
            break
        out.append(ch)
        cells += w
    return "".join(out)


def _render_png(text: str, path: Path, *, title: str = "") -> None:
    from PIL import Image, ImageDraw

    bg = (12, 16, 24)
    fg = (210, 220, 232)
    accent = (110, 190, 255)
    dim = (140, 150, 165)
    font = _load_font(14)

    raw_lines = [_strip_ansi(ln) for ln in text.splitlines()] or [""]
    # 截到画布能放下的行数
    lines = raw_lines[:MAX_ROWS]
    truncated_rows = len(raw_lines) > MAX_ROWS

    img = Image.new("RGB", (CANVAS_W, CANVAS_H), bg)
    draw = ImageDraw.Draw(img)

    y = PAD_Y
    if title:
        draw.text((PAD_X, y), _fit_line(title, MAX_COLS), fill=accent, font=font)
        y += TITLE_H

    for ln in lines:
        fitted = _fit_line(ln, MAX_COLS)
        # 逐段绘制：按格定位，保证表格竖线对齐
        col = 0
        x = PAD_X
        # 简单按字符画（固定 CELL_W 步进，宽字符跨 2 格）
        for ch in fitted:
            w = _char_cells(ch)
            if w == 0:
                col += 0
                continue
            # 跳过到正确 x：col * CELL_W
            x = PAD_X + col * CELL_W
            color = fg
            if ch in "│├└┌─┐┤┘┬┴┼":
                color = dim  # 边框稍暗
            draw.text((x, y), ch, fill=color, font=font)
            col += w
        y += LINE_H

    if truncated_rows:
        draw.text(
            (PAD_X, CANVAS_H - PAD_Y - LINE_H),
            f"… (+{len(raw_lines) - MAX_ROWS} lines truncated)",
            fill=dim,
            font=font,
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")
    print(f"wrote {path} ({CANVAS_W}x{CANVAS_H})")


def _record(fn) -> str:
    buf = io.StringIO()
    # width 与 MAX_COLS 对齐，让 rich 按同一列数折行
    rich_con = Console(file=buf, force_terminal=False, width=MAX_COLS, soft_wrap=False)
    old_stdout = sys.stdout
    sys.stdout = buf  # type: ignore[assignment]
    try:
        import app.cli.memory_cmd as mc
        import app.harness.report as rep_mod

        old_rep, old_mc = rep_mod.console, mc.console
        rep_mod.console = rich_con
        mc.console = rich_con
        try:
            fn(rich_con)
        finally:
            rep_mod.console = old_rep
            mc.console = old_mc
    finally:
        sys.stdout = old_stdout  # type: ignore[assignment]
    return buf.getvalue()


def main() -> None:
    def _run_events(con: Console) -> None:
        from sqlalchemy import text

        from app.db.session import init_db, session_scope
        from app.events import load_events

        init_db()
        with session_scope() as s:
            rows = s.execute(
                text(
                    "select run_id from run_events group by run_id "
                    "order by max(seq) desc limit 1"
                )
            ).fetchall()
        if not rows:
            con.print("(no events)")
            return
        rid = rows[0][0]
        with session_scope() as s:
            evs = load_events(s, rid)
        con.print(f"devassist runs show {rid} --events")
        for e in evs[:32]:
            payload = e.payload
            if e.type.value == "llm_delta":
                brief = repr(payload.get("text", ""))[:40]
            elif e.type.value in {"node_enter", "node_exit"}:
                brief = f"node={payload.get('node')}"
            elif e.type.value == "tool_call":
                brief = f"tool={payload.get('name')} tier={payload.get('tier', '')}"
            elif e.type.value == "test_result":
                brief = (
                    f"passed={payload.get('passed')} failed={payload.get('failed')} "
                    f"phase={payload.get('phase', 'agent')}"
                )
            else:
                brief = str(payload)[:48]
            con.print(f"  [{e.seq:>4}] {e.type.value:<14} {brief}")

    def _eval_table(con: Console) -> None:
        import glob
        import json

        paths = sorted(glob.glob(str(ROOT / "data/reports/eval_*.json")))
        if not paths:
            con.print("(no reports)")
            return
        d = json.loads(Path(paths[-1]).read_text(encoding="utf-8"))
        from app.harness.report import Report, print_report_table

        rep = Report(
            eval_id=d["eval_id"],
            suite=d["suite"],
            k=d["k"],
            provider=d["provider"],
            model=d["model"],
            memory_on=d["memory_on"],
            items=d["items"],
            pass_at_k=d.get("pass_at_k") or {},
            resolve_rate=d.get("resolve_rate") or 0,
            tool_calls_by_tier=d.get("tool_calls_by_tier") or {},
            max_hit_rate=d.get("max_hit_rate") or 0,
            created_at=d.get("created_at") or "",
            notes=d.get("notes") or "",
        )
        print_report_table(rep)

    def _compare(con: Console) -> None:
        import glob

        from app.cli.report_cmd_impl import compare_reports_paths

        reports = sorted(glob.glob(str(ROOT / "data/reports/eval_*.json")))
        on = next((p for p in reports if "100927" in p), None)
        off = next((p for p in reports if "101510" in p), None)
        if on and off:
            compare_reports_paths(Path(on), Path(off))
        elif len(reports) >= 2:
            compare_reports_paths(Path(reports[-2]), Path(reports[-1]))
        else:
            con.print("(need 2 reports)")

    def _memory_list(con: Console) -> None:
        from rich.table import Table

        from app.memory.long_term import LongTermMemory

        mem = LongTermMemory()
        rows = mem.list(kind="convention", limit=14)
        t = Table(title=f"memory list --kind convention ({len(rows)})")
        for c in ("id", "kind", "title", "task_ref"):
            t.add_column(c)
        for m in rows:
            t.add_row(m.id[:20], m.kind, m.title[:36], m.task_ref or "")
        con.print(t)
        con.print(
            f"total={mem.count()} convention={mem.count(kind='convention')} "
            f"episode={mem.count(kind='episode')}"
        )

    jobs = [
        ("run_events_stream.png", _run_events, "devassist runs show --events"),
        ("eval_report_table.png", _eval_table, "devassist eval - rich report"),
        ("compare_ab.png", _compare, "devassist compare memory ON vs OFF"),
        ("memory_list.png", _memory_list, "devassist memory list --kind convention"),
    ]
    for fname, fn, title in jobs:
        text = _record(fn)
        _render_png(text, OUT / fname, title=title)
    print("done →", OUT)


if __name__ == "__main__":
    main()
