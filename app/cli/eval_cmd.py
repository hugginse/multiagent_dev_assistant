"""eval 子命令：批量评测 + 记忆 A/B + Benchmark adapter。"""

from __future__ import annotations

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback(invoke_without_command=True)
def evaluate(
    ctx: typer.Context,
    suite: str = typer.Option("smoke", "--suite", "-s", help="套件名或 swe_bench"),
    k: int = typer.Option(1, "--k", "-k", min=1, max=16, help="pass@k 采样次数"),
    provider: str | None = typer.Option(None, "--provider", "-p"),
    memory: str = typer.Option("off", "--memory", help="on|off"),
    limit: int | None = typer.Option(None, "--limit", help="仅跑前 N 条任务"),
    ab: bool = typer.Option(
        False,
        "--ab",
        help="记忆 A/B：同套件 memory on/off 双跑并自动 compare（忽略 --memory）",
    ),
    adapter: str = typer.Option(
        "local",
        "--adapter",
        help="任务加载器：local | swe_bench（swe_bench 时忽略 --suite 的 yaml 路径）",
    ),
    data_path: str | None = typer.Option(
        None, "--data-path", help="swe_bench JSON 路径（默认 suites/swe_bench/sample.json）"
    ),
) -> None:
    """批量评测套件并产出报告。"""
    if ctx.invoked_subcommand is not None:
        return
    from app.cli.eval_cmd_impl import execute_eval, execute_memory_ab

    # suite=swe_bench 时自动选 adapter
    if suite in {"swe_bench", "swe", "swebench"} and adapter == "local":
        adapter = "swe_bench"

    if ab:
        code = execute_memory_ab(
            suite=suite, k=k, provider=provider, limit=limit, adapter=adapter, data_path=data_path
        )
        raise typer.Exit(code)

    code, _path = execute_eval(
        suite=suite,
        k=k,
        provider=provider,
        memory=memory,
        limit=limit,
        adapter=adapter,
        data_path=data_path,
    )
    raise typer.Exit(code)
