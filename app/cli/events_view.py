"""终端事件订阅视图：node/tool/llm_delta/test_result 逐条打印（真流式）。

约定（architecture.md §8.2）：
- llm_delta 逐 token 打印，禁止整段切片伪装
- 先落库（EventStore）再回调本视图
"""

from __future__ import annotations

from rich.console import Console

from app.events import Event, EventType

console = Console()


class TerminalEventSubscriber:
    """订阅 EventStore，按类型渲染到终端。"""

    def __init__(self, *, show_llm_delta: bool = True, console_: Console | None = None) -> None:
        self.show_llm_delta = show_llm_delta
        self.console = console_ or console
        self._delta_open = False

    def __call__(self, event: Event) -> None:
        self.handle(event)

    def handle(self, event: Event) -> None:
        t = event.type
        p = event.payload
        if t is EventType.RUN_STARTED:
            self._close_delta()
            self.console.print(
                f"[bold blue]▶ run_started[/bold blue] task={p.get('task_id')} "
                f"suite={p.get('suite')} provider={p.get('provider')} model={p.get('model')} "
                f"memory={p.get('memory_on')}"
            )
        elif t is EventType.NODE_ENTER:
            self._close_delta()
            self.console.print(
                f"[cyan]◆ node_enter[/cyan] {p.get('node')} "
                f"iter={p.get('iteration')} task={p.get('task_id', '')}"
            )
        elif t is EventType.NODE_EXIT:
            self._close_delta()
            self.console.print(
                f"[cyan]◇ node_exit[/cyan] {p.get('node')} "
                f"iter={p.get('iteration')} status={p.get('status')}"
            )
        elif t is EventType.LLM_DELTA:
            if not self.show_llm_delta:
                return
            # 真流式：不加前缀，直接续写当前行
            text = p.get("text") or ""
            if not self._delta_open:
                self.console.print("[dim]llm:[/dim] ", end="")
                self._delta_open = True
            self.console.print(text, end="", soft_wrap=True)
        elif t is EventType.TOOL_CALL:
            self._close_delta()
            self.console.print(
                f"[magenta]→ tool_call[/magenta] {p.get('name')} "
                f"args={_short(p.get('args') or p.get('arguments') or {})}"
            )
        elif t is EventType.TOOL_RESULT:
            self._close_delta()
            status = "ok" if p.get("ok", True) else "fail"
            style = "green" if p.get("ok", True) else "red"
            self.console.print(
                f"[{style}]← tool_result[/{style}] {p.get('name')} {status} "
                f"{_short(p.get('summary') or p.get('output') or '')}"
            )
        elif t is EventType.TEST_RESULT:
            self._close_delta()
            phase = p.get("phase", "agent")
            ok = p.get("ok", p.get("failed") == 0)
            style = "green" if ok else "red"
            self.console.print(
                f"[{style}]✓ test_result[/{style}] phase={phase} "
                f"passed={p.get('passed')} failed={p.get('failed')} "
                f"rc={p.get('returncode', '')}"
            )
        elif t is EventType.MEMORY_INJECTED:
            self._close_delta()
            self.console.print(
                f"[yellow]◈ memory_injected[/yellow] chars={p.get('chars')}"
            )
        elif t is EventType.ERROR:
            self._close_delta()
            self.console.print(f"[red]✖ error:[/red] {p.get('message')}")
        elif t is EventType.RUN_FINISHED:
            self._close_delta()
            m = p.get("metrics") or {}
            style = "green" if m.get("resolve") else "yellow"
            self.console.print(
                f"[{style}]■ run_finished[/{style}] status={p.get('status')} "
                f"resolve={m.get('resolve')} ratio={m.get('test_pass_ratio')} "
                f"it={m.get('iterations')} wall={m.get('wall_s')}s"
            )
        else:
            self._close_delta()
            self.console.print(f"[dim]{t.value} { _short(p) }[/dim]")

    def _close_delta(self) -> None:
        if self._delta_open:
            self.console.print()  # 结束 llm 行
            self._delta_open = False

    def finish(self) -> None:
        """收尾（换行）。"""
        self._close_delta()


def _short(obj: object, limit: int = 120) -> str:
    s = obj if isinstance(obj, str) else repr(obj)
    s = s.replace("\n", "\\n")
    return s if len(s) <= limit else s[: limit - 1] + "…"
