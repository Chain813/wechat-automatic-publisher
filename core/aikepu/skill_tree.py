"""
============================================================
  AI 技能树引擎 v1.0
  管理知识节点 DAG：加载、先修检查、下一个选题选择
============================================================
"""
import json
import os
import threading
from datetime import datetime
from loguru import logger

SKILL_TREE_FILE = os.getenv("AIKEPU_SKILL_TREE", os.path.join("data", "aikepu_skill_tree.json"))
HISTORY_FILE = os.getenv("AIKEPU_HISTORY", os.path.join("data", "aikepu_history.json"))

_tree_cache = None
_tree_lock = threading.Lock()

# 当前批次已选中但尚未发布的节点（防止同批次重复选题）
_reserved_ids = set()
_reserved_lock = threading.Lock()


def load_skill_tree():
    """加载技能树 JSON，返回 {nodes: [...], meta: {...}}"""
    global _tree_cache
    if _tree_cache is not None:
        return _tree_cache
    with _tree_lock:
        if _tree_cache is not None:
            return _tree_cache
        if not os.path.exists(SKILL_TREE_FILE):
            logger.error("技能树文件不存在: {}", SKILL_TREE_FILE)
            _tree_cache = {"nodes": [], "meta": {}}
            return _tree_cache
        try:
            with open(SKILL_TREE_FILE, "r", encoding="utf-8") as f:
                _tree_cache = json.load(f)
            logger.info("技能树加载成功: {} 个节点", len(_tree_cache.get("nodes", [])))
        except Exception as e:
            logger.error("技能树加载失败: {}", e)
            _tree_cache = {"nodes": [], "meta": {}}
        return _tree_cache


def _node_by_id(tree, node_id):
    """按 id 查找节点"""
    for node in tree.get("nodes", []):
        if node["id"] == node_id:
            return node
    return None


def get_published_ids():
    """从历史记录中获取已发布的节点 id 列表"""
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
        published = []
        for date_key, entries in history.items():
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict) and entry.get("node_id"):
                        published.append(entry["node_id"])
        return list(set(published))
    except Exception as e:
        logger.warning("读取 AI科普历史失败: {}", e)
        return []


def get_available_nodes():
    """
    找到所有「先修条件已满足」的未发布节点。
    返回节点列表，按 (出度降序, difficulty 升序) 排列。
    """
    tree = load_skill_tree()
    nodes = tree.get("nodes", [])
    if not nodes:
        return []

    published_ids = get_published_ids()

    # 计算每个已发布节点的出度（它解锁了多少后继节点）
    def out_degree(node_id):
        count = 0
        for n in nodes:
            if node_id in n.get("prerequisites", []):
                count += 1
        return count

    available = []
    for node in nodes:
        node_id = node["id"]

        # 跳过已发布
        if node_id in published_ids:
            continue

        # 跳过当前批次已选中但尚未发布
        with _reserved_lock:
            if node_id in _reserved_ids:
                continue

        # 检查先修条件
        prereqs = node.get("prerequisites", [])
        all_prereqs_met = all(pid in published_ids for pid in prereqs)

        if all_prereqs_met:
            available.append(node)

    # 排序：出度最高的优先（枢纽节点），同出度按难度升序
    available.sort(key=lambda n: (-out_degree(n["id"]), n.get("difficulty", 999)))

    return available


def select_next_topic():
    """
    选择下一个要发布的 AI 科普选题。
    策略：从可发布节点中选出度最高（解锁最多后续）的枢纽节点，
          同分时优先难度低的（保证循序渐进）。
    返回 (node_id, title, tags, summary) 或 None。
    """
    available = get_available_nodes()

    if not available:
        logger.info("📭 AI技能树：所有节点均已发布或无可用节点")
        return None

    # 打印可发布节点概览
    print("\n📋 AI技能树 — 可发布节点:")
    for i, node in enumerate(available[:5]):
        prereq_str = ", ".join(node.get("prerequisites", [])) or "无"
        tags_str = " · ".join(node.get("tags", []))
        print(f"  {i+1}. [{tags_str}] {node['title']}  (先修: {prereq_str})")

    selected = available[0]

    # 加入当前批次保留集，防止同一批次重复选中
    with _reserved_lock:
        _reserved_ids.add(selected["id"])

    print(f"\n🎯 选中枢纽节点: {selected['title']}")
    print(f"   标签: {', '.join(selected.get('tags', []))}")
    print(f"   解锁后续: {sum(1 for n in load_skill_tree()['nodes'] if selected['id'] in n.get('prerequisites', []))} 个节点")

    return {
        "node_id": selected["id"],
        "title": selected["title"],
        "tags": selected.get("tags", []),
        "difficulty": selected.get("difficulty", 0),
        "summary": selected.get("summary", ""),
        "prerequisites": selected.get("prerequisites", []),
    }


def mark_published(node_id, title, draft_id=None):
    """标记节点为已发布，写入历史记录"""
    history = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            pass

    today = datetime.now().strftime("%Y-%m-%d")
    if today not in history:
        history[today] = []

    entry = {
        "node_id": node_id,
        "title": title,
        "time": datetime.now().strftime("%H:%M:%S"),
    }
    if draft_id:
        entry["draft_id"] = draft_id

    history[today].append(entry)

    try:
        tmp = HISTORY_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        import shutil
        shutil.move(tmp, HISTORY_FILE)
        logger.info("✅ 节点已标记发布: {} ({})", node_id, title)
    except Exception as e:
        logger.warning("历史记录写入失败: {}", e)


def get_skill_tree_stats():
    """获取技能树统计信息"""
    tree = load_skill_tree()
    nodes = tree.get("nodes", [])
    published_ids = get_published_ids()

    total = len(nodes)
    published = len(published_ids)
    available = len(get_available_nodes())

    # 难度分布
    difficulties = {}
    for n in nodes:
        d = n.get("difficulty", 0)
        difficulties[d] = difficulties.get(d, 0) + 1

    return {
        "total": total,
        "published": published,
        "available": available,
        "progress_pct": round(published / total * 100, 1) if total > 0 else 0,
        "difficulty_distribution": difficulties,
    }


def release_reserved(node_id=None):
    """
    释放保留的节点。
    - 传 node_id：仅释放指定节点（发布成功后调用）
    - 不传参数：清空全部保留（批次结束时调用）
    """
    with _reserved_lock:
        if node_id:
            _reserved_ids.discard(node_id)
        else:
            _reserved_ids.clear()


def reset_tree_cache():
    """强制重新加载技能树（用于测试或热更新）"""
    global _tree_cache
    with _tree_lock:
        _tree_cache = None
    release_reserved()  # 同时清空保留集
