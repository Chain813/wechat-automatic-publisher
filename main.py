"""Thin entrypoint for the publishing workflow."""

import argparse
import os
import sys

from core.engine import run_main
from core.shared.runtime import WorkflowCancelled, configure_runtime


EXIT_CODE_MAP = {
    "success": 0,
    "skipped": 0,
    "partial_success": 2,
    "failed": 1,
    "cancelled": 130,
}


def _outcome_to_dict(outcome):
    to_dict_fn = getattr(outcome, "to_dict", None)
    if callable(to_dict_fn):
        as_dict = to_dict_fn()
        if isinstance(as_dict, dict):
            return as_dict
    if isinstance(outcome, dict):
        return outcome
    return None


def resolve_exit_code(outcome) -> int:
    """将工作流执行结果（WorkflowOutcome / dict / bool / None）映射为标准 CLI 退出码。"""
    if outcome is None:
        return 0
    if isinstance(outcome, bool):
        return 0 if outcome else 1
    data = _outcome_to_dict(outcome)
    status = data.get("status") if data is not None else getattr(outcome, "status", None)
    if isinstance(status, str):
        return EXIT_CODE_MAP.get(status.strip().lower(), 1)
    return 0


def main(argv=None) -> int:
    configure_runtime()
    parser = argparse.ArgumentParser(description="AutoWeChat AI 内容工厂")
    parser.add_argument(
        "--task",
        choices=["hotspots", "github", "aikepu", "daily_knowledge"],
        default="hotspots",
        help="任务类型: hotspots (热点发布), github (开源项目), aikepu (体系科普) 或 daily_knowledge (每日小知识)",
    )
    args = parser.parse_args(argv)

    try:
        outcome = run_main(task_type=args.task)
    except WorkflowCancelled:
        print("任务已被用户中断 (cancelled)")
        return EXIT_CODE_MAP["cancelled"]
    except Exception as exc:
        print(f"任务执行异常退出: {exc}")
        return EXIT_CODE_MAP["failed"]

    code = resolve_exit_code(outcome)
    data = _outcome_to_dict(outcome)
    status = data.get("status") if data is not None else getattr(outcome, "status", None)
    summary = data.get("summary", "") if data is not None else getattr(outcome, "summary", "")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        normalized = str(status).strip().lower()
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"status={normalized if normalized in EXIT_CODE_MAP else 'unknown'}\n")
    if status:
        print(f"[{str(status).upper()}] {summary}".strip())
    return code


if __name__ == "__main__":
    sys.exit(main())
