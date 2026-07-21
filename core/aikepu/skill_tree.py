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


def reconcile_history_file():
    """
    根据 SQLite 数据库和微信线上已发表列表，自动清理 data/aikepu_history.json 中被用户完全删除的废弃/草稿记录，
    以保证技能树进度与真实发布/保存状态 100% 对齐。
    """
    if not os.path.exists(HISTORY_FILE):
        return
    try:
        # 1. 加载 JSON 历史
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
        
        # 2. 查询 SQLite 中的所有 AI 科普记录
        db_titles = set()
        from core.db.manager import db_manager
        from core.db.models import ArticleHistory
        try:
            session = db_manager.get_session()
            records = session.query(ArticleHistory).filter(ArticleHistory.source_type == 'aikepu').all()
            for r in records:
                if r.title:
                    db_titles.add(r.title.strip())
            db_manager.remove_session()
        except Exception as e:
            logger.debug("reconcile_history_file: 读取 SQLite 失败: {}", e)
            return  # 数据库异常时不执行清理，防止误删

        # 如果数据库中完全没有 AI 科普的记录，说明可能是纯 legacy 模式或初次部署，不清理历史
        if not db_titles:
            return

        # 3. 查询微信线上已发表标题
        wechat_titles = set()
        try:
            from config import WECHAT_APP_ID, WECHAT_APP_SECRET
            if WECHAT_APP_ID and WECHAT_APP_SECRET:
                from core.shared.publisher import WeChatPublisher
                pub = WeChatPublisher(WECHAT_APP_ID, WECHAT_APP_SECRET)
                titles = pub.get_published_titles(count=100)
                if titles:
                    for t in titles:
                        if t:
                            wechat_titles.add(t.strip())
        except Exception as e:
            logger.debug("reconcile_history_file: 读取微信已发表失败: {}", e)

        # 4. 执行过滤
        modified = False
        new_history = {}
        
        import re
        def _clean(t):
            return re.sub(r'[^\w\u4e00-\u9fff]', '', t or '').lower()

        clean_valid_titles = {_clean(t) for t in (db_titles | wechat_titles)}

        for date_key, entries in history.items():
            if not isinstance(entries, list):
                new_history[date_key] = entries
                continue
            
            filtered = []
            for entry in entries:
                if not isinstance(entry, dict):
                    filtered.append(entry)
                    continue
                
                title = entry.get("title")
                if not title:
                    filtered.append(entry)
                    continue
                
                clean_t = _clean(title)
                # 检查该文章是否依然存在于数据库或微信公众号已发表中
                exists = False
                for valid_t in clean_valid_titles:
                    if clean_t in valid_t or valid_t in clean_t:
                        exists = True
                        break
                
                if exists:
                    filtered.append(entry)
                else:
                    modified = True
                    logger.info("发现已被完全删除的文章记录，已从技能树历史自动同步清除: {} (ID: {})", title, entry.get("node_id"))
            
            if filtered:
                new_history[date_key] = filtered
            else:
                modified = True

        if modified:
            tmp = HISTORY_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(new_history, f, ensure_ascii=False, indent=2)
            import shutil
            shutil.move(tmp, HISTORY_FILE)
            global _tree_cache
            _tree_cache = None
    except Exception as e:
        logger.warning("技能树历史自动对齐清理失败: {}", e)


def get_published_ids():
    """
    从三个源动态计算已发表的 AI 科普节点 id 列表：
    1. 本地 JSON 历史 (data/aikepu_history.json)
    2. SQLite 数据库 (ArticleHistory 表中 is_published == True 的记录)
    3. 微信公众号 API 线上真实群发已发表的文章标题列表
    """
    # 自动对齐和清洗废弃/被完全删除的历史记录
    reconcile_history_file()

    published = set()

    # 1. 从传统 JSON 历史读取
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
            for date_key, entries in history.items():
                if isinstance(entries, list):
                    for entry in entries:
                        if isinstance(entry, dict) and entry.get("node_id"):
                            published.add(entry["node_id"])
        except Exception as e:
            logger.warning("读取 AI科普历史 JSON 失败: {}", e)

    # 2. 从技能树中建立节点标题与 ID 的规则对照表
    tree = load_skill_tree()
    nodes = tree.get("nodes", [])
    if not nodes:
        return list(published)

    import re
    def _clean_title(t):
        return re.sub(r'[^\w\u4e00-\u9fff]', '', t or '').lower()

    node_title_map = {}
    for node in nodes:
        nid = node.get("id")
        ntitle = node.get("title", "")
        if nid and ntitle:
            node_title_map[nid] = _clean_title(ntitle)

    # 3. 从 SQLite 数据库 (ArticleHistory) 获取被标记为 is_published == True 的记录
    db_published_titles = []
    try:
        from core.db.manager import db_manager
        from core.db.models import ArticleHistory
        session = db_manager.get_session()
        records = session.query(ArticleHistory).filter(ArticleHistory.is_published.is_(True)).all()
        for r in records:
            if r.title:
                db_published_titles.append(_clean_title(r.title))
        db_manager.remove_session()
    except Exception as e:
        logger.debug("读取 SQLite 数据库已发表状态失败: {}", e)

    # 4. 从微信公众号 API 线上查询真实群发已发表的标题
    wechat_published_titles = []
    try:
        from config import WECHAT_APP_ID, WECHAT_APP_SECRET
        if WECHAT_APP_ID and WECHAT_APP_SECRET:
            from core.shared.publisher import WeChatPublisher
            pub = WeChatPublisher(WECHAT_APP_ID, WECHAT_APP_SECRET)
            titles = pub.get_published_titles(count=100)
            if titles:
                wechat_published_titles = [_clean_title(t) for t in titles if t]
    except Exception as e:
        logger.debug("获取微信线上已发表标题跳过: {}", e)

    all_published_clean = set(db_published_titles + wechat_published_titles)

    # 匹配节点
    for nid, clean_ntitle in node_title_map.items():
        if nid in published:
            continue
        for clean_pub_t in all_published_clean:
            if not clean_pub_t:
                continue
            if clean_ntitle in clean_pub_t or clean_pub_t in clean_ntitle:
                published.add(nid)
                break

    return list(published)


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
    logger.info("AI技能树 — 可发布节点 ({} 个)", len(available))
    for i, node in enumerate(available[:5]):
        prereq_str = ", ".join(node.get("prerequisites", [])) or "无"
        tags_str = " · ".join(node.get("tags", []))
        logger.info("  {}. [{}] {} (先修: {})", i+1, tags_str, node['title'], prereq_str)

    selected = available[0]

    # 加入当前批次保留集，防止同一批次重复选中
    with _reserved_lock:
        _reserved_ids.add(selected["id"])

    logger.info("选中枢纽节点: {}", selected['title'])
    logger.info("   标签: {}", ', '.join(selected.get('tags', [])))
    logger.info("   解锁后续: {} 个节点", sum(1 for n in load_skill_tree()['nodes'] if selected['id'] in n.get('prerequisites', [])))

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


def remove_node_from_history(node_id=None, title=None):
    """
    从本地 json 历史记录中移除指定节点 ID 或标题的文章记录，实现进度回滚/重置
    """
    if not os.path.exists(HISTORY_FILE):
        return False
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
        
        modified = False
        new_history = {}
        
        import re
        def _clean(t):
            return re.sub(r'[^\w\u4e00-\u9fff]', '', t or '').lower()

        target_title_clean = _clean(title) if title else None

        for date_key, entries in history.items():
            if not isinstance(entries, list):
                new_history[date_key] = entries
                continue
            
            filtered_entries = []
            for entry in entries:
                if not isinstance(entry, dict):
                    filtered_entries.append(entry)
                    continue
                
                match_id = (node_id and entry.get("node_id") == node_id)
                
                entry_title_clean = _clean(entry.get("title")) if entry.get("title") else None
                match_title = False
                if target_title_clean and entry_title_clean:
                    match_title = (target_title_clean in entry_title_clean or entry_title_clean in target_title_clean)

                if match_id or match_title:
                    modified = True
                    logger.info("已从技能树 JSON 历史中移出文章记录: {} (ID: {})", entry.get("title"), entry.get("node_id"))
                    
                    # 释放保留的节点
                    if entry.get("node_id"):
                        release_reserved(entry.get("node_id"))
                    continue
                
                filtered_entries.append(entry)
            
            if filtered_entries:
                new_history[date_key] = filtered_entries
            else:
                modified = True  # 该日期的记录已空，移除日期键

        if modified:
            tmp = HISTORY_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(new_history, f, ensure_ascii=False, indent=2)
            import shutil
            shutil.move(tmp, HISTORY_FILE)
            reset_tree_cache()
            return True
    except Exception as e:
        logger.warning("回滚 AI科普历史记录失败: {}", e)
    return False
