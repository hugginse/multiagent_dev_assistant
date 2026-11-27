"""生成真实终端演示截图（PNG）到 docs/screenshots/。

用法：uv run python tools/make_screenshots.py
来源：真实 CLI 输出（rich record），PIL 渲染。
字体：优先中文字体（msyh/等线/黑体/Noto Sans SC），避免中文乱码。
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from rich.console import Console

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

# 中文可用字体（Windows）
_CJK_FONTS = (
    "C:/Windows/Fonts/Deng.ttf",  # 等线：接近终端等宽感
    "C:/Windows/Fonts/Dengb.ttf",
    "C:/Windows/Fonts/msyh.ttc",  # 微软雅黑
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/NotoSansSC-VF.ttf",
    "C:/Windows/Fonts/simsun.ttc",
)


def _load_font(size: int = 16):
    from PIL import ImageFont

    for fp in _CJK_FONTS:
        try:
            return ImageFont.truetype(fp, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_width(font, s: str) -> int:
    """近似宽度：CJK 全角按 2 计。"""
    try:
        return font.getlength(s)
    except Exception:
        w = 0
        for ch in s:
            w += 16 if ord(ch) > 0x2E80 else 9
        return w


def _render_png(text: str, path: Path, *, title: str = "") -> None:
    from PIL import Image, ImageDraw

    bg = (12, 16, 24)
    fg = (220, 230, 240)
    accent = (120, 200, 255)
    font = _load_font(15)

    lines = [_strip_ansi(ln) for ln in text.splitlines()] or [""]
    try:
        bbox = font.getbbox("Ag中")
        line_h = (bbox[3] - bbox[1]) + 8
    except Exception:
        line_h = 22

    pad = 18
    header = 30 if title else 0
    # 宽度：按最长行的实际像素宽（CJK 正确计量）
    max_px = 0
    for ln in lines:
        max_px = max(max_px, _text_width(font, ln[:200]))
    w = int(min(1400, max(520, max_px + pad * 2)))
    h = pad * 2 + header + line_h * len(lines)

    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)
    if title:
        draw.text((pad, 8), title, fill=accent, font=font)
    y = pad + header
    for ln in lines:
        # 控制字符剔除
        clean = "".join(ch for ch in ln if ch == "\t" or ch >= " " or ch in "\n")
        draw.text((pad, y), clean[:220], fill=fg, font=font)
        y += line_h

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")
    print("wrote", path)


def _strip_ansi(s: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == "\x1b":
            # ESC [ ... letter
            if i + 1 < len(s) and s[i + 1] == "[":
                j = i + 2
                while j < len(s) and not s[j].isalpha():
                    j += 1
                i = j + 1 if j < len(s) else len(s)
                continue
            # ESC ] ... BEL/ST
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


def _record(fn) -> str:
    buf = io.StringIO()
    rich_con = Console(file=buf, force_terminal=False, width=110, soft_wrap=True)
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
        for e in evs[:40]:
            payload = e.payload
            if e.type.value == "llm_delta":
                brief = repr(payload.get("text", ""))[:48]
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
                brief = str(payload)[:56]
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
        rows = mem.list(kind="convention", limit=12)
        t = Table(title=f"memory list --kind convention ({len(rows)})")
        for c in ("id", "kind", "title", "task_ref"):
            t.add_column(c)
        for m in rows:
            t.add_row(m.id[:20], m.kind, m.title[:40], m.task_ref or "")
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
