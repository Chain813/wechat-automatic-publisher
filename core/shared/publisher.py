"""
============================================================
  微信公众号 API 封装 v4.2
  职责：安全 Token 管理、素材上传、草稿审计、精致排版
============================================================
"""
import hashlib
import os
import json
import re
import time
import threading
import tempfile
from pathlib import Path
from difflib import SequenceMatcher

from loguru import logger

import config
from config import TITLE_DUPLICATE_RATIO
from core.shared.runtime import check_cancelled, WorkflowCancelled
from core.shared.delivery_journal import DeliveryJournal
from utils.http_client import build_api_session

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None


# ==========================================
#  标题查重辅助函数
# ==========================================

def _to_clean_title_str(title) -> str:
    """安全将入参转换为纯字符串标题，防止调用 str.title 内置方法导致类型错误"""
    if isinstance(title, str):
        return title
    if hasattr(title, "title") and isinstance(getattr(title, "title"), str):
        return title.title
    return str(title)


def _normalize_title(title):
    """去除标点/空格，统一小写，用于字符级模糊匹配"""
    title_str = _to_clean_title_str(title)
    return ''.join(c.lower() for c in title_str if c.isalnum())


def _extract_keywords(title):
    """
    提取标题中的核心关键词集合。
    - 英文/数字：按单词提取 (e.g. "GPT", "DeepSeek", "2026")
    - 中文：使用 2~4 字滑动窗口生成 n-gram，弥补无分词器的缺陷
      例如 "脑机接口人体试验" → {"脑机", "机接", "接口", "口人", "脑机接口", ...}
    """
    title_str = _to_clean_title_str(title)
    keywords = set()
    # 英文单词和数字
    for m in re.finditer(r'[a-zA-Z][a-zA-Z0-9]*|[0-9]+', title_str):
        token = m.group().lower()
        if len(token) >= 2:
            keywords.add(token)
    # 中文 n-gram (2~4 字滑动窗口)
    chinese_chunks = re.findall(r'[\u4e00-\u9fff]+', title_str)
    for chunk in chinese_chunks:
        for n in (2, 3, 4):
            for i in range(len(chunk) - n + 1):
                keywords.add(chunk[i:i + n])
    return keywords


def _keyword_overlap_ratio(keywords_a, keywords_b):
    """计算两组关键词的重叠率（以较小集合为基准）"""
    if not keywords_a or not keywords_b:
        return 0.0
        
    min_size = min(len(keywords_a), len(keywords_b))
    # 防误判机制：如果某一方提取出的关键词极少（比如历史遗留的乱码标题只提取出1-2个英文词）
    # 以这么小的基数计算重叠率极易导致 100% 误判。此时直接返回 0，让兜底的 AI 去判断。
    if min_size < 3:
        return 0.0
        
    intersection = keywords_a & keywords_b
    return len(intersection) / min_size if min_size > 0 else 0.0


def _select_semantic_candidates(new_title, existing_titles, max_candidates=15):
    """
    基于本地关键词重叠和低阈值字符模糊匹配，筛选出最可能相似的候选标题，
    避免将成百上千个不相关标题全部传给大模型，节省 token 费用并提高速度。
    """
    new_title_str = _to_clean_title_str(new_title)
    new_keywords = _extract_keywords(new_title_str)
    candidates_with_score = []

    for old in existing_titles:
        old_str = _to_clean_title_str(old)
        old_keywords = _extract_keywords(old_str)
        intersection = new_keywords & old_keywords
        score = len(intersection)

        # 辅助计算粗略字符相似度 (0-100)
        norm_new = _normalize_title(new_title_str)
        norm_old = _normalize_title(old_str)
        if fuzz is not None:
            ratio = fuzz.ratio(norm_new, norm_old)
        else:
            ratio = int(SequenceMatcher(None, norm_new, norm_old).ratio() * 100)

        # 如果有关键词交集，或者字符相似度达到 20%+，或者是极短的标题
        if score > 0 or ratio >= 20 or len(new_title_str) < 8 or len(old_str) < 8:
            candidates_with_score.append((old_str, score, ratio))

    # 排序：优先按关键词交集数量，其次按相似度比例，均降序
    candidates_with_score.sort(key=lambda x: (x[1], x[2]), reverse=True)

    return [item[0] for item in candidates_with_score[:max_candidates]]


# ---- AI 语义查重 (轻量，约 300 tokens) ----
def _ai_semantic_check(new_title, existing_titles):
    """
    调用 DeepSeek 判断新标题是否与已有标题覆盖同一议题。
    使用本地粗筛机制降低输入给大模型的标题规模，提升响应速度并节省 token 资源。
    返回 (is_duplicate: bool, matched_title: str or None)
    """
    new_title_str = _to_clean_title_str(new_title)
    # 1. 本地粗筛最相关的候选标题
    candidates = _select_semantic_candidates(new_title_str, existing_titles, max_candidates=15)
    if not candidates:
        logger.info("  [AI查重粗筛] 未发现任何存在潜在交集的候选标题，直接判定为【不重复】")
        return False, None

    try:
        from core.shared.llm import call_deepseek_with_retry
    except ImportError:
        return False, None

    logger.info("  [AI查重粗筛] 筛选出 {} 个可能相关的历史标题送审 AI 语义查重", len(candidates))
    titles_text = "\n".join(f"{i+1}. {t}" for i, t in enumerate(candidates))
    prompt = (
        f"已发布文章标题列表：\n{titles_text}\n\n"
        f"待发布话题：「{new_title_str}」\n\n"
        "请判断待发布话题是否与列表中某篇文章覆盖了同一个核心事件或议题"
        "（即使措辞、角度不同，只要是同一件事就算重复）。\n"
        "如果重复，请回答：重复|<编号>\n"
        "如果不重复，请回答：不重复\n"
        "只输出上面的格式，不要有其他文字。"
    )
    
    # 强制将 AI 语义查重重载为轻量级 flash 模型（例如将 deepseek-v4-pro 降级为 deepseek-v4-flash）
    from config import LLM_MODEL
    semantic_model = re.sub(r"-pro(?=-|$)", "-flash", LLM_MODEL)
    logger.info("  [AI查重] 使用轻量级模型 {} 进行快速判定...", semantic_model)

    try:
        result = call_deepseek_with_retry(
            prompt,
            system_content="你是一个标题去重审核员。只按指定格式输出，不要解释。",
            max_retries=1,
            backoff_base=0.5,
            model=semantic_model
        )
        if not result:
            return False, None
        result = result.strip()
        if result.startswith("重复"):
            parts = result.split("|")
            if len(parts) >= 2:
                try:
                    idx = int(parts[1].strip()) - 1
                    if 0 <= idx < len(candidates):
                        return True, candidates[idx]
                except (ValueError, IndexError):
                    pass
            # 格式不标准但确认重复
            return True, candidates[0]
        return False, None
    except Exception as exc:
        logger.debug("AI 语义查重异常: {}", exc)
        return False, None


class WeChatPublisher:
    _tokens = {}
    _global_lock = threading.RLock()

    def __init__(self, app_id, app_secret, *, journal=None):
        self.app_id = app_id
        self.app_secret = app_secret
        self._credentials = (app_id, app_secret)
        self.session = build_api_session()
        self.journal = journal if journal is not None else DeliveryJournal()
        self._draft_titles_cache = None
        self.access_token = None
        self._ensure_valid_token()

    @classmethod
    def reset_token_cache(cls):
        with cls._global_lock:
            cls._tokens.clear()

    def _refresh_token(self):
        with self._global_lock:
            self._tokens.pop(self._credentials, None)
            self.access_token = None
            try:
                response = self.session.get(
                    "https://api.weixin.qq.com/cgi-bin/token",
                    params={"grant_type": "client_credential", "appid": self.app_id,
                            "secret": self.app_secret}, timeout=config.WECHAT_API_TIMEOUT).json()
                token = response["access_token"]
                expiry = time.time() + int(response.get("expires_in", 7200)) - 300
                self._tokens[self._credentials] = (token, expiry)
                self.access_token = token
            except Exception as exc:
                logger.warning("WeChat token acquisition failed ({})", type(exc).__name__)

    def _ensure_valid_token(self):
        with self._global_lock:
            token, expiry = self._tokens.get(self._credentials, (None, 0))
            if token and time.time() < expiry:
                self.access_token = token
            else:
                self._refresh_token()

    def upload_image(self, image_path):
        """上传素材，返回 media_id（优先使用永久素材接口以适配草稿箱封面要求）"""
        self._ensure_valid_token()
        if not self.access_token or not image_path or not os.path.exists(image_path):
            return None

        # 安全防爆检查：如果图片大于 1.8MB (如 SD 生图 6-8MB)，自动压缩至 2MB 微信封面限制以内
        try:
            if os.path.getsize(image_path) > 1.8 * 1024 * 1024:
                logger.info("  🖼️ 封面图片文件较重 ({:.2f} MB)，执行 1.8MB 自动优化压缩...", os.path.getsize(image_path)/(1024*1024))
                from utils.image_handler import resize_for_wechat
                image_path = resize_for_wechat(image_path, purpose="cover")
        except Exception as pre_err:
            logger.debug("  封面预处理检查跳过: {}", pre_err)

        mime_type = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"
        if image_path.lower().endswith(".gif"):
            mime_type = "image/gif"
        elif image_path.lower().endswith(".webp"):
            mime_type = "image/webp"

        for attempt in range(2):
            # 1. 优先尝试永久素材接口 (草稿箱封面必须为永久素材，临时素材会报 invalid media_id)
            url_perm = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={self.access_token}&type=thumb"
            try:
                with open(image_path, 'rb') as f:
                    safe_filename = f"cover{os.path.splitext(image_path)[1]}"
                    files = {'media': (safe_filename, f, mime_type)}
                    res = self.session.post(url_perm, files=files, timeout=config.WECHAT_API_TIMEOUT).json()
                
                if "media_id" in res:
                    return res.get("media_id")
                elif "thumb_media_id" in res:
                    return res.get("thumb_media_id")
                
                errcode = res.get("errcode")
                if errcode in (40001, 42001) and attempt == 0:
                    logger.warning("微信永久素材上传遇到 Token 失效 (errcode={})，正在刷新并重试...", errcode)
                    self._refresh_token()
                    continue
                else:
                    logger.debug("  微信永久素材上传响应: {}", res)
            except Exception as e:
                logger.warning("  微信永久素材上传异常: {}", e)

            # 2. 降级尝试临时素材接口
            url_temp = f"https://api.weixin.qq.com/cgi-bin/media/upload?access_token={self.access_token}&type=thumb"
            try:
                with open(image_path, 'rb') as f:
                    safe_filename = f"cover{os.path.splitext(image_path)[1]}"
                    files = {'media': (safe_filename, f, mime_type)}
                    res = self.session.post(url_temp, files=files, timeout=config.WECHAT_API_TIMEOUT).json()
                
                if "thumb_media_id" in res:
                    return res.get("thumb_media_id")
                elif "media_id" in res:
                    return res.get("media_id")
                
                errcode = res.get("errcode")
                if errcode in (40001, 42001) and attempt == 0:
                    logger.warning("微信临时素材上传遇到 Token 失效 (errcode={})，正在刷新并重试...", errcode)
                    self._refresh_token()
                    continue
                else:
                    logger.warning("  微信临时素材上传失败: {}", res)
            except Exception as e:
                logger.warning("  微信临时素材上传异常: {}", e)
            
            break

        return None

    def upload_news_image(self, image_path):
        """上传内容插图，返回 URL"""
        self._ensure_valid_token()
        if not self.access_token or not image_path or not os.path.exists(image_path):
            return None

        # 安全防爆检查：如果正文插图大于 1.8MB (如高清生图 6-8MB)，自动压缩至 1.8MB 以内
        try:
            if os.path.getsize(image_path) > 1.8 * 1024 * 1024:
                logger.info("  🖼️ 正文插图文件较重 ({:.2f} MB)，执行 1.8MB 自动优化压缩...", os.path.getsize(image_path)/(1024*1024))
                from utils.image_handler import resize_for_wechat
                image_path = resize_for_wechat(image_path, purpose="body")
        except Exception as pre_err:
            logger.debug("  正文插图预处理检查跳过: {}", pre_err)

        mime_type = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"
        if image_path.lower().endswith(".gif"):
            mime_type = "image/gif"
        elif image_path.lower().endswith(".webp"):
            mime_type = "image/webp"

        for attempt in range(2):
            url = f"https://api.weixin.qq.com/cgi-bin/media/uploadimg?access_token={self.access_token}"
            try:
                with open(image_path, 'rb') as f:
                    safe_filename = f"image{os.path.splitext(image_path)[1]}"
                    files = {'media': (safe_filename, f, mime_type)}
                    res = self.session.post(url, files=files, timeout=config.WECHAT_API_TIMEOUT).json()
                
                if "url" in res:
                    return res.get("url")
                
                errcode = res.get("errcode")
                if errcode in (40001, 42001) and attempt == 0:
                    logger.warning("微信图片上传遇到 Token 失效 (errcode={})，正在刷新并重试...", errcode)
                    self._refresh_token()
                    continue
                else:
                    logger.warning("  upload_news_image 失败: {} - {}", image_path, res)
            except Exception as e:
                logger.warning("  upload_news_image 异常: {} - {}", image_path, e)
            
            break

        return None

    def _cloud_items(self, endpoint, count=None, *, content=False):
        self._ensure_valid_token()
        if not self.access_token:
            return None
        items = []
        identifiers = set()
        total = None
        refreshed = False
        try:
            while count is None or len(items) < count:
                size = min(20, count - len(items)) if count is not None else 20
                url = f"https://api.weixin.qq.com/cgi-bin/{endpoint}/batchget?access_token={self.access_token}"
                response = self.session.post(url, json={"offset": len(items), "count": size,
                    "no_content": int(not content)}, timeout=config.WECHAT_API_TIMEOUT).json()
                code = response.get("errcode", 0)
                if code in (40001, 42001) and not refreshed:
                    refreshed = True
                    self._refresh_token()
                    if self.access_token:
                        continue
                if code:
                    return None
                current_total = response["total_count"]
                if not isinstance(current_total, int) or current_total < 0:
                    return None
                if total is not None and current_total != total:
                    return None
                total = current_total
                page = response["item"]
                if not isinstance(page, list) or len(page) != min(size, total - len(items)):
                    return None
                for entry in page:
                    key = entry["media_id" if endpoint == "draft" else "article_id"]
                    if not key or key in identifiers:
                        return None
                    identifiers.add(key)
                    news = entry["content"]["news_item"]
                    if not news or not all(n.get("title") for n in news):
                        return None
                items.extend(page)
                if len(items) == total:
                    break
            return items
        except Exception as exc:
            logger.warning("WeChat {} scan incomplete ({})", endpoint, type(exc).__name__)
            return None

    def _titles(self, endpoint, count):
        items = self._cloud_items(endpoint, count)
        if items is None:
            return None
        return [n["title"] for item in items for n in item["content"]["news_item"]]

    def get_draft_titles(self, count=None):
        return self._titles("draft", count)

    def get_published_titles(self, count=None):
        return self._titles("freepublish", count)

    def get_cloud_active_titles(self, count=None):
        drafts = self.get_draft_titles(count=count)
        published = self.get_published_titles(count=count)
        if drafts is None or published is None:
            return None
        return list(set(drafts + published))

    def get_all_active_titles(self):
        """合并拉取微信草稿箱、最近发布记录以及本地 SQLite 历史发布记录，做全量标题查重"""
        if self._draft_titles_cache is not None:
            return self._draft_titles_cache
        
        drafts = self.get_draft_titles() or []
        published = self.get_published_titles() or []
        
        db_titles = []
        try:
            from core.db.manager import db_manager
            from core.db.models import ArticleHistory
            session = db_manager.get_session()
            try:
                records = session.query(ArticleHistory).filter(ArticleHistory.success_status.is_(True)).all()
                db_titles = [r.title for r in records if r.title]
            finally:
                db_manager.remove_session()
        except Exception as e:
            logger.warning("从本地数据库获取历史发布标题失败: {}", e)
            
        all_titles = list(set(drafts + published + db_titles))
        self._draft_titles_cache = all_titles
        logger.info("微信+本地查重标题缓存已建立，共 {} 条 (微信草稿 {}，已发布 {}，本地数据库历史 {})", 
                    len(all_titles), len(drafts), len(published), len(db_titles))
        return all_titles

    def _title_similarity(self, title_a, title_b):
        """字符级模糊相似度 (0-100)"""
        normalized_a = _normalize_title(title_a)
        normalized_b = _normalize_title(title_b)
        if not normalized_a or not normalized_b:
            return 0
        if fuzz is not None:
            return max(
                fuzz.ratio(normalized_a, normalized_b),
                fuzz.partial_ratio(normalized_a, normalized_b),
                fuzz.token_sort_ratio(normalized_a, normalized_b),
                fuzz.token_set_ratio(normalized_a, normalized_b),
            )
        return int(SequenceMatcher(None, normalized_a, normalized_b).ratio() * 100)

    def is_title_duplicate(self, new_title, extra_existing=None):
        """
        多策略查重逻辑（由快到慢）：
        1. 精确匹配
        2. 字符级模糊匹配 (rapidfuzz / SequenceMatcher)
        3. 关键词 n-gram 重叠匹配
        4. AI 语义查重 (DeepSeek，~300 tokens，兜底)
        """
        new_title_str = _to_clean_title_str(new_title)
        raw_existing = self.get_all_active_titles()
        if extra_existing:
            raw_existing = raw_existing + extra_existing
            
        existing = [_to_clean_title_str(t) for t in raw_existing]
        if not existing:
            return False, None

        new_keywords = _extract_keywords(new_title_str)
        for old in existing:
            # 策略 1: 精确匹配
            if new_title_str == old:
                return True, old

            # 策略 2: 字符级模糊匹配
            similarity = self._title_similarity(new_title_str, old)
            if similarity >= TITLE_DUPLICATE_RATIO:
                logger.info("命中相似标题(模糊{}%): {}", similarity, old)
                return True, old

            # 策略 3: 关键词重叠匹配
            old_keywords = _extract_keywords(old)
            overlap = _keyword_overlap_ratio(new_keywords, old_keywords)
            if overlap >= 0.70:
                logger.info("命中相似标题(关键词重叠{:.0f}%): {} | 新={} 旧={}",
                            overlap * 100, old, new_keywords, old_keywords)
                return True, old

        # 策略 4: AI 语义查重（前三层均未命中时，调用一次 AI 兜底）
        logger.info("本地查重未命中，启动 AI 语义查重...")
        is_dup, matched = _ai_semantic_check(new_title_str, existing)
        if is_dup:
            logger.info("命中相似标题(AI语义): {}", matched)
            return True, matched

        return False, None

    def add_draft(self, title, html_content, thumb_media_id, digest="", *, operation_id=None, context=None):
        """Claim a logical operation before sending its non-idempotent draft request."""
        styled_html = (
            '<section style="padding: 15px; font-family: -apple-system, BlinkMacSystemFont, '
            "'Helvetica Neue', 'PingFang SC', 'Microsoft YaHei', Arial, sans-serif; "
            'line-height: 1.8; color: #222; font-size: 17px; word-wrap: break-word;">'
            f'{html_content}'
            '</section>'
        )

        # 校验微信公众号正文体积限制 (不得超过 10M 字节 / 10,485,760 字节)
        content_bytes = len(styled_html.encode('utf-8')) + len('<!--autowechat:-->') + 32
        max_bytes = 10 * 1024 * 1024  # 10MB
        if content_bytes > max_bytes:
            error = f"排版后正文为 {content_bytes:,} 字节，超过 10 MiB 上限（{max_bytes:,} 字节），请缩减正文后重试"
            logger.warning("草稿提交失败: {}", error)
            return {"errcode": -1, "errmsg": error}

        self._ensure_valid_token()
        if not self.access_token:
            return {"errcode": -1, "errmsg": "No Token"}

        if not digest:
            digest = title[:60]

        # 封面素材缺失自愈保护：防止直接向微信接口提交空 thumb_media_id 触发 40007 错误
        if not thumb_media_id:
            logger.warning("  ⚠️ 草稿发布缺少 thumb_media_id，尝试自动上传系统预设封面作为自愈兜底...")
            fallback_covers = [
                os.path.abspath(os.path.join("assets", "default_aikepu_cover.png")),
                os.path.abspath(os.path.join("assets", "default_daily_cover.png")),
                os.path.abspath(os.path.join("static", "images", "github_fixed_cover.png")),
            ]
            for fc in fallback_covers:
                if os.path.exists(fc):
                    uploaded = self.upload_image(fc)
                    if uploaded:
                        thumb_media_id = uploaded
                        logger.info("  ✅ 成功自动补全兜底封面 media_id: {}", thumb_media_id)
                        break

        data = {
            "articles": [{
                "title": title,
                "author": config.ARTICLE_AUTHOR,
                "digest": digest[:120],
                "content": styled_html,
                "thumb_media_id": thumb_media_id,
                "need_open_comment": 1
            }]
        }

        # Legacy callers have no durable article ID. Deduplicate identical payloads.
        if operation_id is None:
            operation_id = hashlib.sha256(json.dumps([title, html_content, digest],
                ensure_ascii=False).encode()).hexdigest()
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError("operation_id must be a nonempty string")
        check_cancelled()
        claim, owner = self.journal.claim(self.app_id, operation_id, title, context or {})
        if not owner:
            return dict(claim, reused=True)
        attempt = claim["attempt_id"]
        try:
            self._write_preview(f"attempt_{attempt}", html_content)
        except OSError as exc:
            return self.journal.resolve(self.app_id, attempt,
                                        rejection=f"Cannot persist preview: {type(exc).__name__}")
        # Sanitizers may strip comments. Missing evidence leaves the attempt uncertain.
        marker = f"<!--autowechat:{attempt}-->"
        data["articles"][0]["content"] += marker
        url_base = "https://api.weixin.qq.com/cgi-bin/draft/add"
        body = json.dumps(data, ensure_ascii=False).encode()
        for index in range(2):
            try:
                try:
                    check_cancelled()
                except WorkflowCancelled:
                    self.journal.resolve(self.app_id, attempt, rejection="Cancelled before draft submission")
                    raise
                response = self.session.post(f"{url_base}?access_token={self.access_token}",
                    data=body, timeout=config.WECHAT_API_TIMEOUT, allow_redirects=False)
                response.raise_for_status()
                result = response.json()
                code = result.get("errcode", 0)
                if not code and isinstance(result.get("media_id"), str) and result["media_id"]:
                    self._draft_titles_cache = None
                    try:
                        return self.journal.resolve(self.app_id, attempt, media_id=result["media_id"])
                    except Exception:
                        try:
                            self.journal.save_fallback_receipt(self.app_id, attempt, result["media_id"])
                        except OSError:
                            logger.error("Failed to persist fallback receipt for attempt {}", attempt)
                        return dict(claim, status="DRAFT_PENDING_RECORD", media_id=result["media_id"],
                                    errmsg="Receipt journal write failed")
                if code in (40001, 42001) and index == 0:
                    self._refresh_token()
                    if self.access_token:
                        continue
                if isinstance(code, int) and code > 0:
                    return self.journal.resolve(self.app_id, attempt,
                        rejection=result.get("errmsg") or str(code)) | {"errcode": code}
            except WorkflowCancelled:
                raise
            except Exception as exc:
                logger.warning("Draft receipt unknown ({})", type(exc).__name__)
            break
        return self.reconcile_delivery(attempt)

    @staticmethod
    def _write_preview(preview_id, content):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", preview_id):
            raise ValueError("Invalid preview identifier")
        directory = Path("data/previews")
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
            temporary = Path(stream.name)
        try:
            temporary.write_text(content, encoding="utf8")
            os.replace(temporary, directory / f"{preview_id}.html")
        finally:
            temporary.unlink(missing_ok=True)

    def restore_delivery_preview(self, attempt_id):
        """Idempotently restore the media preview from the claimed article body."""
        row = self.journal.get(self.app_id, attempt_id)
        source = Path("data/previews") / f"attempt_{row['attempt_id']}.html"
        self._write_preview(row["media_id"], source.read_text(encoding="utf8"))

    def reconcile_delivery(self, attempt_id):
        row = self.journal.get(self.app_id, attempt_id)
        if row["status"] != "CLOUD_UNCERTAIN":
            return row
        receipt = self.journal.fallback_receipt(self.app_id, attempt_id)
        if receipt:
            return self.journal.resolve(self.app_id, attempt_id, media_id=receipt)
        marker = f"<!--autowechat:{attempt_id}-->"
        items = self._cloud_items("draft", content=True)
        matches = [item["media_id"] for item in items or []
                   if any(marker in (n.get("content") or "")
                          for n in item["content"]["news_item"])]
        if len(matches) == 1:
            return self.journal.resolve(self.app_id, attempt_id, media_id=matches[0])
        return self.journal.get(self.app_id, attempt_id)

    def pending_deliveries(self):
        return self.journal.pending(self.app_id)

    def mark_delivery_recorded(self, attempt_id):
        return self.journal.recorded(self.app_id, attempt_id)

    def publish_and_notify(self, title, html_content, thumb_media_id, digest="", *, operation_id=None, context=None):
        """发布草稿并发送企业微信通知，返回 (success, result)"""
        result = self.add_draft(title, html_content, thumb_media_id, digest,
                                operation_id=operation_id, context=context)
        if "media_id" in result:
            draft_id = result["media_id"]
            logger.info("发布成功: {} → {}", title, draft_id)
            
            # 保存本地成功草稿预览文件
            try:
                self.restore_delivery_preview(result["attempt_id"])
            except Exception as pe:
                logger.warning("  保存本地预览 HTML 失败: {}", pe)
                return False, dict(result, errmsg="Local preview write failed")

            if result.get("reused"):
                return True, result

            try:
                from config import QYWECHAT_WEBHOOK, BRAND_NAME
                send_to_qywechat(QYWECHAT_WEBHOOK, f"【{BRAND_NAME}】《{title}》已就绪，请审核发布。")
            except Exception as e:
                logger.debug("  企微通知发送失败（非关键）: {}", e)
            return True, result
        else:
            err_msg = result.get("errmsg", "未知错误")
            logger.warning("发布失败: {} → {}", title, err_msg)
            
            # 保存本地失败草稿预览文件 (使用 title 的 md5 作为 ID)
            import hashlib
            title_hash = hashlib.md5(title.encode('utf-8')).hexdigest()
            try:
                os.makedirs(os.path.join("data", "previews"), exist_ok=True)
                preview_path = os.path.join("data", "previews", f"fail_{title_hash}.html")
                with open(preview_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
            except Exception as pe:
                logger.warning("  保存本地失败预览 HTML 失败: {}", pe)
                
            return False, result

_qywechat_session = None
_qywechat_session_lock = threading.Lock()

def send_to_qywechat(webhook_url, text):
    global _qywechat_session
    if not webhook_url:
        return
    if _qywechat_session is None:
        with _qywechat_session_lock:
            if _qywechat_session is None:
                _qywechat_session = build_api_session()
    try:
        _qywechat_session.post(webhook_url, json={"msgtype": "text", "text": {"content": text}}, timeout=5)
    except Exception as exc:
        logger.warning("企业微信通知失败: {}", exc)
