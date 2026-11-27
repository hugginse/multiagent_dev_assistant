"""CLI 层（typer + rich）——仅展示，不承载核心逻辑。"""

from app.cli.main import app, main

__all__ = ["app", "main"]
