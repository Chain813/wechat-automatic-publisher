"""
AI 知识普及管线 — 技能树驱动的系统化 AI 教育内容生产
"""
from core.aikepu.workflow import run_aikepu_workflow
from core.aikepu.skill_tree import (
    load_skill_tree,
    get_available_nodes,
    select_next_topic,
    mark_published,
    get_skill_tree_stats,
)

__all__ = [
    "run_aikepu_workflow",
    "load_skill_tree",
    "get_available_nodes",
    "select_next_topic",
    "mark_published",
    "get_skill_tree_stats",
]
