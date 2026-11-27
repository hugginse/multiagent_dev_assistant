"""演示 CLI：python -m orderlib.cli status（供 shell/集成任务扩展）。"""

from __future__ import annotations

import argparse
import sys

from orderlib import OrderService
from orderlib.inventory import Inventory


def build_service() -> OrderService:
    return OrderService(Inventory({"SKU1": 100, "SKU2": 100}))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orderlib", description="orderlib demo CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="show demo inventory status")
    args = parser.parse_args(argv)

    if args.cmd == "status":
        svc = build_service()
        for sku, qty in sorted(svc.inventory.snapshot().items()):
            print(f"{sku}: {qty}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
