"""Thin entrypoint for the publishing workflow."""

import argparse

from core.shared.runtime import configure_runtime
from core.engine import run_main


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AutoWeChat AI 内容工厂")
    parser.add_argument("--task", choices=["hotspots", "github"], default="hotspots",
                        help="任务类型: hotspots (热点发布) 或 github (GitHub Trending)")
    args = parser.parse_args()

    configure_runtime()
    run_main(task_type=args.task)
