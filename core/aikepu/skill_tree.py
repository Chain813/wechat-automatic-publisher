"""
============================================================
  知识体系连载引擎 v2.0 (原 AI 技能树引擎)
  管理知识节点 DAG：加载、先修检查、下一个选题选择
  支持多主题知识库 (data/knowledge_trees/*.json) 与用户自定义导入
============================================================
"""
import json
import os
import sqlite3
import tempfile
import shutil
from contextlib import closing, contextmanager
from pathlib import Path
from urllib.parse import quote
import threading
from datetime import datetime
from loguru import logger

LEGACY_TREE_FILE = os.getenv("AIKEPU_SKILL_TREE", os.path.join("data", "aikepu_skill_tree.json"))
TREES_DIR = os.getenv("KNOWLEDGE_TREES_DIR", os.path.join("data", "knowledge_trees"))
ACTIVE_TREE_FILE = os.path.join(TREES_DIR, "_active.txt")
HISTORY_FILE = os.getenv("AIKEPU_HISTORY", os.path.join("data", "cache", "aikepu", "aikepu_history.json"))

_tree_cache = {}
_tree_lock = threading.Lock()

# 当前批次已选中但尚未发布的节点（防止同批次重复选题）
_reserved_ids = set()
_reserved_lock = threading.Lock()


def get_active_tree_name():
    """返回当前激活的主题包名（WebUI 切换后持久化于 _active.txt）"""
    try:
        if os.path.exists(ACTIVE_TREE_FILE):
            with open(ACTIVE_TREE_FILE, "r", encoding="utf-8") as f:
                saved = f.read().strip()
            if saved:
                return saved
    except Exception:
        pass
    return os.getenv("KNOWLEDGE_TREE", "").strip() or "aikepu"


def set_active_tree(name):
    """切换激活主题包并刷新缓存（持久化到 _active.txt）"""
    global _tree_cache
    name = (name or "aikepu").strip()
    with _tree_lock:
        _tree_cache.pop(name, None)
    _atomic_write(Path(ACTIVE_TREE_FILE), name)
    invalidate_published_ids_cache()
    logger.info("已切换知识体系主题包: {}", name)
    return name


def _tree_path(name):
    """主题包 JSON 路径：优先 data/knowledge_trees/{name}.json，兼容旧文件"""
    if name == "aikepu":
        new_path = os.path.join(TREES_DIR, "aikepu.json")
        if os.path.exists(new_path):
            return new_path
        return LEGACY_TREE_FILE
    return os.path.join(TREES_DIR, f"{name}.json")


def list_knowledge_trees():
    """列出全部主题包: [{name, title, description, node_count}]"""
    packs = []
    try:
        os.makedirs(TREES_DIR, exist_ok=True)
    except Exception:
        pass
    for fn in sorted(os.listdir(TREES_DIR)):
        if not fn.endswith(".json") or fn.startswith("_"):
            continue
        name = fn[:-5]
        try:
            with open(os.path.join(TREES_DIR, fn), "r", encoding="utf-8") as f:
                data = json.load(f)
            meta = data.get("meta") or {}
            packs.append({
                "name": name,
                "title": meta.get("name", name),
                "description": meta.get("description", ""),
                "node_count": len(data.get("nodes", [])),
            })
        except Exception as e:
            logger.warning("主题包 {} 解析失败: {}", fn, e)
    # 旧文件也算一个包（未迁移时）
    if not any(p["name"] == "aikepu" for p in packs) and os.path.exists(LEGACY_TREE_FILE):
        try:
            with open(LEGACY_TREE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            meta = data.get("meta") or {}
            packs.insert(0, {
                "name": "aikepu",
                "title": meta.get("name", "AI 全栈技能树"),
                "description": meta.get("description", ""),
                "node_count": len(data.get("nodes", [])),
            })
        except Exception:
            pass
    return packs


def validate_tree_structure(data):
    """校验用户导入的知识库 JSON 结构，返回 (ok, error)"""
    if not isinstance(data, dict):
        return False, "根节点必须是 JSON 对象"
    nodes = data.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return False, "缺少非空 nodes 数组"
    ids = set()
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            return False, f"第 {i + 1} 个节点不是对象"
        nid = str(node.get("id") or "").strip()
        title = str(node.get("title") or "").strip()
        if not nid or not title:
            return False, f"第 {i + 1} 个节点缺少 id 或 title"
        if nid in ids:
            return False, f"节点 id 重复: {nid}"
        ids.add(nid)
        prereqs = node.get("prerequisites", [])
        if not isinstance(prereqs, list):
            return False, f"节点 {nid} 的 prerequisites 必须是数组"
    return True, ""


def load_skill_tree(tree_name=None):
    """加载知识树 JSON，返回 {nodes: [...], meta: {...}}（按主题包缓存）"""
    global _tree_cache
    name = tree_name or get_active_tree_name()
    cached = _tree_cache.get(name)
    if cached is not None:
        return cached
    with _tree_lock:
        cached = _tree_cache.get(name)
        if cached is not None:
            return cached
        path = _tree_path(name)
        if not os.path.exists(path):
            logger.error("知识库文件不存在: {} (主题包: {})", path, name)
            _tree_cache[name] = {"nodes": [], "meta": {}}
            return _tree_cache[name]
        try:
            with open(path, "r", encoding="utf-8") as f:
                _tree_cache[name] = json.load(f)
            logger.info("知识体系加载成功 [{}]: {} 个节点", name, len(_tree_cache[name].get("nodes", [])))
        except Exception as e:
            logger.error("知识库加载失败 [{}]: {}", name, e)
            _tree_cache[name] = {"nodes": [], "meta": {}}
        return _tree_cache[name]


def _node_by_id(tree, node_id):
    """按 id 查找节点"""
    for node in tree.get("nodes", []):
        if node["id"] == node_id:
            return node
    return None


_history_lock = threading.RLock()


def _atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        temp_path = Path(tmp.name)
    try:
        with temp_path.open("w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _read_history(path):
    try:
        history = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(history, dict) or any(not isinstance(v, list) for v in history.values()):
            raise ValueError("Invalid skill tree history structure")
        return history
    except FileNotFoundError:
        return {}


@contextmanager
def _history_update():
    """Serialize the entire JSON read/modify/replace across CLI and Web workers."""
    path = Path(HISTORY_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _history_lock, closing(sqlite3.connect(str(path) + ".lock", timeout=30)) as lock:
        lock.execute("BEGIN IMMEDIATE")
        try:
            history = _read_history(path)
        except (ValueError, UnicodeError):
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".corrupt.",
                                             delete=False) as backup, path.open("rb") as source:
                shutil.copyfileobj(source, backup)
            logger.error("Damaged skill tree history preserved at {}", backup.name)
            raise
        original = json.dumps(history, ensure_ascii=False, indent=2)
        yield history
        content = json.dumps(history, ensure_ascii=False, indent=2)
        if content != original:
            _atomic_write(path, content)


def invalidate_published_ids_cache():
    """Compatibility hook. Status reads use current JSON and SQLite snapshots."""


def _entries(history, name):
    for entries in history.values():
        for entry in entries:
            if isinstance(entry, dict) and entry.get("tree", "aikepu") == name:
                yield entry


def node_source_url(name, node_id):
    return f"aikepu://tree/{quote(name, safe='')}/node/{quote(node_id, safe='')}"


def _record_node(record, name, nodes):
    for node in nodes:
        nid = node["id"]
        if record.source_url == node_source_url(name, nid):
            return nid
        if name == "aikepu" and record.source_url == f"aikepu://node/{nid}":
            return nid
    if name == "aikepu" and not record.source_url:
        matches = [n["id"] for n in nodes if _match_node_title(n, record.title)]
        if len(matches) == 1:
            return matches[0]
    return None


def _get_wechat_publisher():
    """动态获取微信 Publisher 实例（优先读取最新环境变量）"""
    app_id = os.getenv("WECHAT_APP_ID", "").strip()
    app_secret = os.getenv("WECHAT_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        try:
            from config import WECHAT_APP_ID, WECHAT_APP_SECRET
            app_id = app_id or WECHAT_APP_ID
            app_secret = app_secret or WECHAT_APP_SECRET
        except Exception:
            pass
    if app_id and app_secret:
        try:
            from core.shared.publisher import WeChatPublisher
            return WeChatPublisher(app_id, app_secret)
        except Exception as pe:
            logger.debug("_get_wechat_publisher: 初始化 Publisher 失败: {}", pe)
    return None


def _match_node_title(node, target_title):
    """
    智能匹配：判断目标文章标题（微信线上草稿/发布标题或 SQLite 记录标题）是否对应特定的技能树节点。
    支持 ID 匹配、全标题字串重叠、主标题匹配及显著核心词汇重叠。
    """
    if not node or not target_title:
        return False

    import re
    def _clean(t):
        return re.sub(r'[^\w\u4e00-\u9fff]', '', str(t) or '').replace('_', '').lower()

    clean_target = _clean(target_title)
    if not clean_target:
        return False

    node_id = node.get("id", "")
    node_title = node.get("title", "")
    clean_node_title = _clean(node_title)

    # 1. 节点 ID 精确/包含匹配
    if node_id:
        clean_nid = _clean(node_id)
        if len(clean_nid) >= 4 and clean_nid in clean_target:
            return True

    # 2. 全标题相互包含匹配
    if clean_node_title and (clean_node_title in clean_target or clean_target in clean_node_title):
        return True

    # 3. 拆分主标题（以冒号分割）
    main_t = node_title.split("：")[0].split(":")[0].strip()
    clean_main_t = _clean(main_t)
    if len(clean_main_t) >= 3 and (clean_main_t in clean_target or clean_target in clean_main_t):
        return True

    # 4. 拆分副标题及特色核心词组匹配
    sub_parts = re.split(r'[：:\s,，、—\-]+', node_title)
    for part in sub_parts:
        clean_part = _clean(part)
        if clean_part in ("ai", "原理", "基础", "入门", "详解", "实战", "核心", "指南", "进化史"):
            continue
        if len(clean_part) >= 4 and clean_part in clean_target:
            return True

    return False


def reconcile_history_file(wechat_draft_titles=None):
    """Titles alone cannot prove deletion or distinguish publication from removal."""
    reset_tree_cache()
    return False


def _status_ids(name, published):
    history = _read_history(Path(HISTORY_FILE))
    status = "published" if published else "draft"
    ids = {e["node_id"] for e in _entries(history, name)
           if e.get("node_id") and e.get("status", "published") == status}
    from core.db.manager import db_manager
    from core.db.models import ArticleHistory
    nodes = load_skill_tree(name).get("nodes", [])
    session = db_manager.get_session()
    try:
        records = session.query(ArticleHistory).filter_by(
            source_type="aikepu", success_status=True, is_published=published)
        for record in records:
            nid = _record_node(record, name, nodes)
            if nid:
                ids.add(nid)
    finally:
        db_manager.remove_session()
    return ids


def get_published_ids(force_refresh=False, tree_name=None):
    return sorted(_status_ids(tree_name or get_active_tree_name(), True))


def get_draft_ids(wechat_draft_titles=None, tree_name=None):
    name = tree_name or get_active_tree_name()
    drafts = _status_ids(name, False)
    if wechat_draft_titles:
        # A cloud title carries no tree ID. Resolve only globally unique exact matches.
        candidates = {}
        for pack in list_knowledge_trees():
            pack_name = pack["name"]
            for node in load_skill_tree(pack_name).get("nodes", []):
                candidates.setdefault(node["title"], []).append((pack_name, node["id"]))
        for title in wechat_draft_titles:
            matches = candidates.get(title, [])
            if len(matches) == 1 and matches[0][0] == name:
                drafts.add(matches[0][1])
    return sorted(drafts - set(get_published_ids(tree_name=name)))


def sync_wechat_status():
    """
    与微信公众号 API 同步，刷新技能树状态。

    注意: 个人号的 freepublish/batchget 接口返回 48001 unauthorized，
    因此已群发状态完全依赖本地 JSON 历史 + SQLite is_published 标记。
    微信 API 仅用于获取草稿箱标题列表（draft/batchget 可用）。
    """
    name = get_active_tree_name()
    pub = _get_wechat_publisher()

    wechat_connected = False
    wechat_draft_titles = []

    if pub and pub.access_token:
        try:
            titles = pub.get_draft_titles()
            wechat_connected = titles is not None
            wechat_draft_titles = titles or []
        except Exception as e:
            logger.warning("同步微信公众号 API 失败: {}", e)

    published_ids = get_published_ids(force_refresh=True, tree_name=name)
    draft_ids = get_draft_ids(wechat_draft_titles, name)
    available_nodes = get_available_nodes(published_ids, name, draft_ids)
    stats = get_skill_tree_stats(published_ids, available_nodes, name, draft_ids)

    return {
        "wechat_connected": wechat_connected,
        "draft_titles_count": len(wechat_draft_titles),
        "published_ids": published_ids,
        "draft_ids": draft_ids,
        "stats": stats
    }



def get_available_nodes(published_ids=None, tree_name=None, draft_ids=None):
    """
    找到所有「先修条件已满足」且「未发布/未进入草稿箱」的待撰写节点。
    返回节点列表，按 (出度降序, difficulty 升序) 排列。
    """
    name = tree_name or get_active_tree_name()
    tree = load_skill_tree(name)
    nodes = tree.get("nodes", [])
    if not nodes:
        return []

    if published_ids is None:
        published_ids = get_published_ids(tree_name=name)

    if draft_ids is None:
        draft_ids = get_draft_ids(tree_name=name)
    completed_ids = set(published_ids) | set(draft_ids)

    # 计算每个节点的出度（它解锁了多少后继节点）
    def out_degree(node_id):
        count = 0
        for n in nodes:
            if node_id in n.get("prerequisites", []):
                count += 1
        return count

    available = []
    for node in nodes:
        node_id = node["id"]

        # 跳过已发布或已生成到草稿箱的节点
        if node_id in completed_ids:
            continue

        # 跳过当前批次已选中但尚未完成的节点
        with _reserved_lock:
            if (name, node_id) in _reserved_ids:
                continue

        # 检查先修条件：前置节点只要已完成（已发布或已进草稿箱）即可解锁
        prereqs = node.get("prerequisites", [])
        all_prereqs_met = all(pid in completed_ids for pid in prereqs)

        if all_prereqs_met:
            available.append(node)

    # 排序：出度最高的优先（枢纽节点），同出度按难度升序
    available.sort(key=lambda n: (-out_degree(n["id"]), n.get("difficulty", 999)))

    return available


def select_next_topic(override_node_id=None, tree_name=None):
    name = tree_name or get_active_tree_name()
    if override_node_id is None:
        candidates = get_available_nodes(tree_name=name)
    else:
        node = _node_by_id(load_skill_tree(name), override_node_id)
        candidates = [node] if node else []
    with _reserved_lock:
        for node in candidates:
            key = (name, node["id"])
            if key not in _reserved_ids:
                _reserved_ids.add(key)
                return {
                    "tree_name": name, "node_id": node["id"], "title": node["title"],
                    "tags": node.get("tags", []), "difficulty": node.get("difficulty", 0),
                    "summary": node.get("summary", ""), "prerequisites": node.get("prerequisites", []),
                }
    return None


def mark_published(node_id, title, draft_id=None, status="draft", tree_name=None):
    if not node_id:
        return
    name = tree_name or get_active_tree_name()
    now = datetime.now()
    with _history_update() as history:
        entry = next((e for e in _entries(history, name) if e.get("node_id") == node_id), None)
        if entry is None:
            entry = {"node_id": node_id, "time": now.strftime("%H:%M:%S")}
            history.setdefault(now.date().isoformat(), []).append(entry)
        entry.update(tree=name, title=title, status=status)
        if draft_id:
            entry["draft_id"] = draft_id


def set_node_status(node_id, status="published", tree_name=None):
    from core.db.manager import db_manager
    from core.db.models import ArticleHistory

    name = tree_name or get_active_tree_name()
    nodes = load_skill_tree(name).get("nodes", [])
    node = next((n for n in nodes if n["id"] == node_id), None)
    if not node or status not in {"draft", "published", "reset"}:
        return False

    if status == "reset":
        remove_node_from_history(node_id=node_id, tree_name=name)
    else:
        mark_published(node_id, node["title"], status=status, tree_name=name)
    session = db_manager.get_session()
    try:
        records = session.query(ArticleHistory).filter_by(source_type="aikepu")
        matches = [r for r in records if _record_node(r, name, nodes) == node_id]
        if not matches and status != "reset":
            record = ArticleHistory(source_type="aikepu", title=node["title"],
                                    source_url=node_source_url(name, node_id),
                                    publish_date=datetime.now().date().isoformat())
            session.add(record)
            matches.append(record)
        for record in matches:
            record.success_status = status != "reset"
            record.is_published = status == "published"
            record.status = {"published": "APPROVED", "draft": "DRAFT", "reset": "FAILED"}[status]
        session.commit()
    finally:
        db_manager.remove_session()
    return True


def get_skill_tree_stats(published_ids=None, available_nodes=None, tree_name=None, draft_ids=None):
    """获取技能树统计信息"""
    name = tree_name or get_active_tree_name()
    tree = load_skill_tree(name)
    nodes = tree.get("nodes", [])
    if published_ids is None:
        published_ids = get_published_ids(tree_name=name)
    if draft_ids is None:
        draft_ids = get_draft_ids(tree_name=name)
    if available_nodes is None:
        available_nodes = get_available_nodes(published_ids, name, draft_ids)

    total = len(nodes)
    known = {n["id"] for n in nodes}
    published = len(known.intersection(published_ids))
    draft_count = len(known.intersection(draft_ids).difference(published_ids))
    available = len(available_nodes)

    # 难度分布
    difficulties = {}
    for n in nodes:
        d = n.get("difficulty", 0)
        difficulties[d] = difficulties.get(d, 0) + 1

    return {
        "total_nodes": total,
        "available_count": available,
        "locked_count": max(0, total - published - draft_count - available),
        "next_recommended_topic": available_nodes[0]["title"] if available_nodes else "",
        "total": total,
        "published": published,
        "draft_count": draft_count,
        "total_count": total,
        "published_count": published,
        "available": available,
        "progress_pct": round(published / total * 100, 1) if total > 0 else 0,
        "difficulty_distribution": difficulties,
    }


def release_reserved(node_id=None, tree_name=None):
    name = tree_name or get_active_tree_name()
    with _reserved_lock:
        if node_id:
            _reserved_ids.discard((name, node_id))
        else:
            _reserved_ids.difference_update({key for key in _reserved_ids if key[0] == name})


def reset_tree_cache():
    """Reload tree definitions without discarding reservations held by running tasks."""
    with _tree_lock:
        _tree_cache.clear()


def remove_node_from_history(node_id=None, title=None, tree_name=None):
    name = tree_name or get_active_tree_name()
    removed = set()
    with _history_update() as history:
        for date, entries in list(history.items()):
            keep = []
            for entry in entries:
                if isinstance(entry, dict) and entry.get("tree", "aikepu") == name:
                    match = entry.get("node_id") == node_id if node_id else title and entry.get("title") == title
                    if match:
                        removed.add(entry.get("node_id"))
                        continue
                keep.append(entry)
            if len(keep) < len(entries):
                if keep:
                    history[date] = keep
                else:
                    del history[date]
    for nid in removed:
        if nid:
            release_reserved(nid, name)
    return bool(removed)
