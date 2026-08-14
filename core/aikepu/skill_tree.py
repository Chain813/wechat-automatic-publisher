"""
============================================================
  AI 技能树引擎 v1.0
  管理知识节点 DAG：加载、先修检查、下一个选题选择
============================================================
"""
import json
import os
import time
import threading
from datetime import datetime
from loguru import logger

SKILL_TREE_FILE = os.getenv("AIKEPU_SKILL_TREE", os.path.join("data", "aikepu_skill_tree.json"))
HISTORY_FILE = os.getenv("AIKEPU_HISTORY", os.path.join("data", "cache", "aikepu", "aikepu_history.json"))

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


# In-memory TTL Cache for published IDs
_published_ids_cache = None
_published_ids_cache_time = 0
PUBLISHED_CACHE_TTL = 45  # 45 seconds TTL

def invalidate_published_ids_cache():
    """使已发表节点缓存失效"""
    global _published_ids_cache, _published_ids_cache_time
    _published_ids_cache = None
    _published_ids_cache_time = 0


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
    """
    自动清理 data/aikepu_history.json 中被用户在微信草稿箱手动删除的草稿记录。

    核心规则:
      - published 状态的历史记录 -> 绝对保留（因为 freepublish API 对个人号不可用，无法验证）
      - draft 状态的历史记录 -> 若提供了 wechat_draft_titles 且该草稿不在其中，则清除
      - 未提供 wechat_draft_titles 时 -> 不做任何清理（防护保全）
    """
    if not os.path.exists(HISTORY_FILE):
        return
    if wechat_draft_titles is None:
        return  # 没有草稿列表就不做清理

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
        if not history:
            return

        tree = load_skill_tree()
        nodes = tree.get("nodes", [])
        draft_title_set = set(t.strip() for t in wechat_draft_titles if t)

        modified = False
        new_history = {}

        for date_key, entries in history.items():
            if not isinstance(entries, list):
                new_history[date_key] = entries
                continue

            filtered = []
            for entry in entries:
                if not isinstance(entry, dict):
                    filtered.append(entry)
                    continue

                status = entry.get("status", "published")

                # 已群发的记录永远保留
                if status == "published":
                    filtered.append(entry)
                    continue

                # 草稿记录：校验是否还在微信草稿箱中
                title = entry.get("title")
                node_id = entry.get("node_id")
                node = next((n for n in nodes if n["id"] == node_id), None) if node_id else None

                is_still_in_drafts = False
                if not draft_title_set:
                    is_still_in_drafts = True  # 草稿箱为空也保留（可能是网络问题）
                else:
                    for dt in draft_title_set:
                        if title and (title.strip() in dt or dt in title.strip()):
                            is_still_in_drafts = True
                            break
                        if node and _match_node_title(node, dt):
                            is_still_in_drafts = True
                            break

                if is_still_in_drafts:
                    filtered.append(entry)
                else:
                    modified = True
                    if node_id:
                        release_reserved(node_id)
                    logger.info("🗑️ 草稿已从微信草稿箱删除，自动清除本地记录: {} (ID: {})", title, node_id)

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


def get_published_ids(force_refresh=False):
    """
    计算已群发的 AI 科普节点 ID 列表（带 TTL 缓存）。

    数据来源（个人公众号 freepublish API 不可用，不依赖它）:
      1. 本地 JSON 历史中 status=="published" 的 node_id
      2. SQLite 中 source_type=='aikepu' 且 is_published==True 的记录（通过标题匹配节点）
    """
    global _published_ids_cache, _published_ids_cache_time
    now = time.time()
    if not force_refresh and _published_ids_cache is not None and (now - _published_ids_cache_time < PUBLISHED_CACHE_TTL):
        return list(_published_ids_cache)

    published_set = set()

    # 1. 从本地 JSON 历史读取 published 记录
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
            for date_key, entries in history.items():
                if isinstance(entries, list):
                    for entry in entries:
                        if isinstance(entry, dict) and entry.get("node_id") and entry.get("status") == "published":
                            published_set.add(entry["node_id"])
        except Exception as e:
            logger.warning("读取 AI科普历史 JSON 失败: {}", e)

    # 2. 从 SQLite 读取 is_published==True 的 aikepu 记录，匹配节点
    try:
        from core.db.manager import db_manager
        from core.db.models import ArticleHistory
        session = db_manager.get_session()
        records = session.query(ArticleHistory).filter(
            ArticleHistory.source_type == 'aikepu',
            ArticleHistory.success_status.is_(True),
            ArticleHistory.is_published.is_(True)
        ).all()
        if records:
            tree = load_skill_tree()
            nodes = tree.get("nodes", [])
            for r in records:
                if r.title:
                    for node in nodes:
                        nid = node.get("id")
                        if nid and nid not in published_set and _match_node_title(node, r.title):
                            published_set.add(nid)
                            break
        db_manager.remove_session()
    except Exception as e:
        logger.debug("读取 SQLite 已发表状态失败: {}", e)

    _published_ids_cache = published_set
    _published_ids_cache_time = now
    return list(published_set)


def get_draft_ids(wechat_draft_titles=None):
    """
    计算处于草稿箱状态的节点 ID 列表。

    数据来源:
      1. 本地 JSON 历史中 status=="draft" 的 node_id
      2. SQLite 中 source_type=='aikepu', success_status==True, is_published==False 的记录
      3. 微信草稿箱标题（通过标题匹配节点）
    已被 get_published_ids 识别的节点不会出现在草稿列表中。
    """
    draft_set = set()
    published_set = set(get_published_ids())

    # 1. 从 JSON 历史获取 draft 记录
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
            for date_key, entries in history.items():
                if isinstance(entries, list):
                    for entry in entries:
                        if isinstance(entry, dict) and entry.get("node_id") and entry.get("status") == "draft":
                            nid = entry["node_id"]
                            if nid not in published_set:
                                draft_set.add(nid)
    except Exception as e:
        logger.debug("读取草稿节点失败: {}", e)

    # 2. 从 SQLite + 微信草稿箱标题匹配
    try:
        db_draft_titles = []
        try:
            from core.db.manager import db_manager
            from core.db.models import ArticleHistory
            session = db_manager.get_session()
            db_records = session.query(ArticleHistory).filter(
                ArticleHistory.source_type == 'aikepu',
                ArticleHistory.success_status.is_(True),
                ArticleHistory.is_published.is_(False)
            ).all()
            db_draft_titles = [r.title.strip() for r in db_records if r.title]
            db_manager.remove_session()
        except Exception as e:
            logger.debug("读取 SQLite 草稿记录失败: {}", e)

        wechat_titles = [t.strip() for t in (wechat_draft_titles or []) if t]
        all_draft_titles = list(set(db_draft_titles + wechat_titles))

        if all_draft_titles:
            tree = load_skill_tree()
            for node in tree.get("nodes", []):
                nid = node.get("id")
                if nid and nid not in published_set and nid not in draft_set:
                    for dt in all_draft_titles:
                        if _match_node_title(node, dt):
                            draft_set.add(nid)
                            break
    except Exception as e:
        logger.debug("动态匹配草稿节点失败: {}", e)

    return list(draft_set)


def sync_wechat_status():
    """
    与微信公众号 API 同步，刷新技能树状态。

    注意: 个人号的 freepublish/batchget 接口返回 48001 unauthorized，
    因此已群发状态完全依赖本地 JSON 历史 + SQLite is_published 标记。
    微信 API 仅用于获取草稿箱标题列表（draft/batchget 可用）。
    """
    invalidate_published_ids_cache()
    pub = _get_wechat_publisher()

    wechat_connected = False
    wechat_draft_titles = []

    if pub and pub.access_token:
        try:
            wechat_draft_titles = pub.get_draft_titles(count=100) or []
            wechat_connected = True
            # 仅用草稿标题做对齐——清理已被用户从微信草稿箱中删除的草稿记录
            reconcile_history_file(wechat_draft_titles=wechat_draft_titles)
        except Exception as e:
            logger.warning("同步微信公众号 API 失败: {}", e)

    published_ids = get_published_ids(force_refresh=True)
    draft_ids = get_draft_ids(wechat_draft_titles=wechat_draft_titles)
    available_nodes = get_available_nodes(published_ids=published_ids)
    stats = get_skill_tree_stats(published_ids=published_ids, available_nodes=available_nodes)

    return {
        "wechat_connected": wechat_connected,
        "draft_titles_count": len(wechat_draft_titles),
        "published_ids": published_ids,
        "draft_ids": draft_ids,
        "stats": stats
    }



def get_available_nodes(published_ids=None):
    """
    找到所有「先修条件已满足」且「未发布/未进入草稿箱」的待撰写节点。
    返回节点列表，按 (出度降序, difficulty 升序) 排列。
    """
    tree = load_skill_tree()
    nodes = tree.get("nodes", [])
    if not nodes:
        return []

    if published_ids is None:
        published_ids = get_published_ids()

    draft_ids = get_draft_ids()
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
            if node_id in _reserved_ids:
                continue

        # 检查先修条件：前置节点只要已完成（已发布或已进草稿箱）即可解锁
        prereqs = node.get("prerequisites", [])
        all_prereqs_met = all(pid in completed_ids for pid in prereqs)

        if all_prereqs_met:
            available.append(node)

    # 排序：出度最高的优先（枢纽节点），同出度按难度升序
    available.sort(key=lambda n: (-out_degree(n["id"]), n.get("difficulty", 999)))

    return available


def select_next_topic(override_node_id=None):
    """
    选择下一个要发布的 AI 科普选题。
    若指定 override_node_id，则直接选中该节点；
    否则从可发布节点中选出度最高（解锁最多后续）的枢纽节点。
    返回 node_id, title, tags, summary 等字典或 None。
    """
    tree = load_skill_tree()
    nodes = tree.get("nodes", [])

    if override_node_id:
        target_node = next((n for n in nodes if n["id"] == override_node_id), None)
        if target_node:
            with _reserved_lock:
                _reserved_ids.add(target_node["id"])
            logger.info("🎯 手动选中技能节点: {}", target_node['title'])
            return {
                "node_id": target_node["id"],
                "title": target_node["title"],
                "tags": target_node.get("tags", []),
                "difficulty": target_node.get("difficulty", 0),
                "summary": target_node.get("summary", ""),
                "prerequisites": target_node.get("prerequisites", []),
            }

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


def mark_published(node_id, title, draft_id=None, status="draft"):
    """
    记录节点状态到 aikepu_history.json。
    status: 'draft' (草稿箱中) 或 'published' (已正式发版)
    """
    if not node_id:
        return

    invalidate_published_ids_cache()
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

    # 查找旧记录并更新状态
    updated = False
    for entries in history.values():
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict) and entry.get("node_id") == node_id:
                    entry["status"] = status
                    if draft_id:
                        entry["draft_id"] = draft_id
                    updated = True

    if not updated:
        entry = {
            "node_id": node_id,
            "title": title,
            "status": status,
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
        logger.info("✅ 节点状态已更新: {} -> {} ({})", node_id, status, title)
    except Exception as e:
        logger.warning("历史记录写入失败: {}", e)


def set_node_status(node_id, status="published"):
    """
    手动设置或干预节点状态: 'published' (已正式发布), 'draft' (草稿箱), 'reset' (彻底重置回未生成状态)
    """
    import re
    def _c(s):
        return re.sub(r'[^\w\u4e00-\u9fff]', '', str(s) or '').replace('_', '').lower()

    tree = load_skill_tree()
    node = next((n for n in tree.get("nodes", []) if n["id"] == node_id), None)
    title = node["title"] if node else node_id

    if status == "reset":
        remove_node_from_history(node_id=node_id)
        try:
            from core.db.manager import db_manager
            from core.db.models import ArticleHistory
            session = db_manager.get_session()
            if node:
                clean_n = _c(node["title"])
                records = session.query(ArticleHistory).filter(ArticleHistory.source_type == 'aikepu').all()
                for r in records:
                    if r.title and (clean_n in _c(r.title) or _c(r.title) in clean_n):
                        r.success_status = False
                        r.is_published = False
                session.commit()
            db_manager.remove_session()
        except Exception as e:
            logger.warning("清理 SQLite 节点记录失败: {}", e)
        invalidate_published_ids_cache()
        return True

    # 1. 更新 JSON 历史
    mark_published(node_id, title, status=status)

    # 2. 更新/插入 SQLite 记录
    try:
        from core.db.manager import db_manager
        from core.db.models import ArticleHistory
        session = db_manager.get_session()
        clean_n = _c(title)
        records = session.query(ArticleHistory).filter(ArticleHistory.source_type == 'aikepu').all()
        matched = False
        is_pub = (status == "published")
        for r in records:
            if r.title and (clean_n in _c(r.title) or _c(r.title) in clean_n):
                r.is_published = is_pub
                r.success_status = True
                matched = True
        if not matched:
            new_record = ArticleHistory(
                source_type='aikepu',
                title=title,
                success_status=True,
                is_published=is_pub
            )
            session.add(new_record)
        session.commit()
        db_manager.remove_session()
    except Exception as e:
        logger.warning("同步 SQLite is_published 状态失败: {}", e)

    invalidate_published_ids_cache()
    return True


def get_skill_tree_stats(published_ids=None, available_nodes=None):
    """获取技能树统计信息"""
    tree = load_skill_tree()
    nodes = tree.get("nodes", [])
    if published_ids is None:
        published_ids = get_published_ids()
    if available_nodes is None:
        available_nodes = get_available_nodes(published_ids=published_ids)

    draft_ids = get_draft_ids()

    total = len(nodes)
    published = len(published_ids)
    draft_count = len(draft_ids)
    available = len(available_nodes)

    # 难度分布
    difficulties = {}
    for n in nodes:
        d = n.get("difficulty", 0)
        difficulties[d] = difficulties.get(d, 0) + 1

    return {
        "total": total,
        "published": published,
        "draft_count": draft_count,
        "total_count": total,
        "published_count": published,
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
            return re.sub(r'[^\w\u4e00-\u9fff]', '', t or '').replace('_', '').lower()

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
