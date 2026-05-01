"""
============================================================
  微信公众号 API 封装 v4.2
  职责：安全 Token 管理、素材上传、草稿审计、精致排版
============================================================
"""
import os
import json
import re
import time
from difflib import SequenceMatcher

from loguru import logger

from config import (
    WECHAT_API_TIMEOUT,
    ARTICLE_AUTHOR,
    WECHAT_DRAFT_SCAN_COUNT,
    TITLE_DUPLICATE_RATIO,
)
from utils.http_client import build_api_session

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None


# ==========================================
#  标题查重辅助函数
# ==========================================

def _normalize_title(title):
    """去除标点/空格，统一小写，用于字符级模糊匹配"""
    return ''.join(c.lower() for c in title if c.isalnum())


def _extract_keywords(title):
    """
    提取标题中的核心关键词集合。
    - 英文/数字：按单词提取 (e.g. "GPT", "DeepSeek", "2026")
    - 中文：使用 2~4 字滑动窗口生成 n-gram，弥补无分词器的缺陷
      例如 "脑机接口人体试验" → {"脑机", "机接", "接口", "口人", "脑机接口", ...}
    """
    keywords = set()
    # 英文单词和数字
    for m in re.finditer(r'[a-zA-Z][a-zA-Z0-9]*|[0-9]+', title):
        token = m.group().lower()
        if len(token) >= 2:
            keywords.add(token)
    # 中文 n-gram (2~4 字滑动窗口)
    chinese_chunks = re.findall(r'[\u4e00-\u9fff]+', title)
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


# ---- AI 语义查重 (轻量，约 300 tokens) ----
def _ai_semantic_check(new_title, existing_titles):
    """
    调用 DeepSeek 判断新标题是否与已有标题覆盖同一议题。
    仅在本地策略无法确定时使用，token 消耗极低 (~300 tokens)。
    返回 (is_duplicate: bool, matched_title: str or None)
    """
    if not existing_titles:
        return False, None
    try:
        from core.processor import call_deepseek_with_retry
    except ImportError:
        return False, None

    titles_text = "\n".join(f"{i+1}. {t}" for i, t in enumerate(existing_titles))
    prompt = (
        f"已发布文章标题列表：\n{titles_text}\n\n"
        f"待发布话题：「{new_title}」\n\n"
        "请判断待发布话题是否与列表中某篇文章覆盖了同一个核心事件或议题"
        "（即使措辞、角度不同，只要是同一件事就算重复）。\n"
        "如果重复，请回答：重复|<编号>\n"
        "如果不重复，请回答：不重复\n"
        "只输出上面的格式，不要有其他文字。"
    )
    try:
        result = call_deepseek_with_retry(
            prompt,
            system_content="你是一个标题去重审核员。只按指定格式输出，不要解释。",
            max_retries=1,
            backoff_base=0.5,
        )
        if not result:
            return False, None
        result = result.strip()
        if result.startswith("重复"):
            parts = result.split("|")
            if len(parts) >= 2:
                try:
                    idx = int(parts[1].strip()) - 1
                    if 0 <= idx < len(existing_titles):
                        return True, existing_titles[idx]
                except (ValueError, IndexError):
                    pass
            # 格式不标准但确认重复
            return True, existing_titles[0]
        return False, None
    except Exception as exc:
        logger.debug("AI 语义查重异常: {}", exc)
        return False, None


class WeChatPublisher:
    def __init__(self, app_id, app_secret):
        self.app_id = app_id
        self.app_secret = app_secret
        self.session = build_api_session()
        self.access_token = None
        self._token_expires_at = 0
        self._draft_titles_cache = None
        self._refresh_token()

    def _refresh_token(self):
        """获取并验证微信调用凭证，记录过期时间"""
        url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={self.app_id}&secret={self.app_secret}"
        try:
            res = self.session.get(url, timeout=WECHAT_API_TIMEOUT).json()
            if "access_token" in res:
                self.access_token = res["access_token"]
                # 微信 Token 有效期 7200 秒，提前 300 秒刷新
                self._token_expires_at = time.time() + res.get("expires_in", 7200) - 300
                logger.info("微信 Token 获取成功，有效至 {}", time.strftime("%H:%M:%S", time.localtime(self._token_expires_at)))
            else:
                raise Exception(f"Token 授权失败: {res}")
        except Exception as e:
            logger.error("微信凭证获取失败: {}", e)
            self.access_token = None

    def _ensure_valid_token(self):
        """检查 Token 是否即将过期，自动刷新"""
        if not self.access_token or time.time() >= self._token_expires_at:
            logger.info("Token 已过期或即将过期，正在自动刷新...")
            self._draft_titles_cache = None  # Token 切换后缓存失效
            self._refresh_token()

    def upload_image(self, image_path):
        """上传素材，返回 media_id"""
        self._ensure_valid_token()
        if not self.access_token or not image_path or not os.path.exists(image_path):
            return None
        url = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={self.access_token}&type=image"
        try:
            with open(image_path, 'rb') as f:
                files = {'media': (os.path.basename(image_path), f, 'image/jpeg')}
                res = self.session.post(url, files=files, timeout=WECHAT_API_TIMEOUT).json()
            return res.get("media_id")
        except Exception:
            return None

    def upload_news_image(self, image_path):
        """上传内容插图，返回 URL"""
        self._ensure_valid_token()
        if not self.access_token or not image_path or not os.path.exists(image_path):
            return None
        url = f"https://api.weixin.qq.com/cgi-bin/media/uploadimg?access_token={self.access_token}"
        try:
            with open(image_path, 'rb') as f:
                files = {'media': (os.path.basename(image_path), f, 'image/jpeg')}
                res = self.session.post(url, files=files, timeout=WECHAT_API_TIMEOUT).json()
            return res.get("url")
        except Exception:
            return None

    def get_draft_titles(self, count=WECHAT_DRAFT_SCAN_COUNT):
        """获取最近草稿标题列表（查重用），结果会缓存以避免重复 API 调用"""
        if self._draft_titles_cache is not None:
            return self._draft_titles_cache
        self._ensure_valid_token()
        if not self.access_token:
            return []
        url = f"https://api.weixin.qq.com/cgi-bin/draft/batchget?access_token={self.access_token}"
        data = {"offset": 0, "count": count, "no_content": 1}
        titles = []
        try:
            res = self.session.post(url, json=data, timeout=WECHAT_API_TIMEOUT).json()
            for item in res.get("item", []):
                for news in item.get("content", {}).get("news_item", []):
                    titles.append(news.get("title", ""))
        except Exception as exc:
            logger.warning("获取草稿标题失败: {}", exc)
        self._draft_titles_cache = titles
        logger.info("草稿标题缓存已建立，共 {} 条", len(titles))
        return titles

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

    def is_title_duplicate(self, new_title):
        """
        多策略查重逻辑（由快到慢）：
        1. 精确匹配
        2. 字符级模糊匹配 (rapidfuzz / SequenceMatcher)
        3. 关键词 n-gram 重叠匹配
        4. AI 语义查重 (DeepSeek，~300 tokens，兜底)
        """
        existing = self.get_draft_titles()
        if not existing:
            return False, None

        new_keywords = _extract_keywords(new_title)
        for old in existing:
            # 策略 1: 精确匹配
            if new_title == old:
                return True, old

            # 策略 2: 字符级模糊匹配
            similarity = self._title_similarity(new_title, old)
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
        is_dup, matched = _ai_semantic_check(new_title, existing)
        if is_dup:
            logger.info("命中相似标题(AI语义): {}", matched)
            return True, matched

        return False, None

    def add_draft(self, title, html_content, thumb_media_id, digest=""):
        """同步草稿箱，带高级容器样式和指数退避重试"""
        self._ensure_valid_token()
        if not self.access_token:
            return {"errcode": -1, "errmsg": "No Token"}

        styled_html = (
            '<section style="padding: 15px; font-family: -apple-system, BlinkMacSystemFont, '
            "'Helvetica Neue', 'PingFang SC', 'Microsoft YaHei', Arial, sans-serif; "
            'line-height: 1.8; color: #222; font-size: 17px; word-wrap: break-word;">'
            f'{html_content}'
            '</section>'
        )

        if not digest:
            digest = title[:60]

        data = {
            "articles": [{
                "title": title,
                "author": ARTICLE_AUTHOR,
                "digest": digest[:120],
                "content": styled_html,
                "thumb_media_id": thumb_media_id,
                "need_open_comment": 1
            }]
        }

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={self.access_token}"
                result = self.session.post(
                    url,
                    data=json.dumps(data, ensure_ascii=False).encode('utf-8'),
                    timeout=WECHAT_API_TIMEOUT
                ).json()

                errcode = result.get("errcode", 0)
                # Token 过期 (40001/42001) 或系统繁忙 (-1) 时重试
                if errcode in (40001, 42001, -1):
                    logger.warning("草稿发布失败 (errcode={})，第 {}/{} 次重试", errcode, attempt, max_retries)
                    if errcode in (40001, 42001):
                        self._refresh_token()
                        if not self.access_token:
                            return result
                    time.sleep(1.5 * (2 ** (attempt - 1)))
                    continue

                if "media_id" in result:
                    self._draft_titles_cache = None
                return result

            except Exception as e:
                logger.warning("草稿发布异常: {}，第 {}/{} 次重试", e, attempt, max_retries)
                if attempt < max_retries:
                    time.sleep(1.5 * (2 ** (attempt - 1)))

        return {"errcode": -1, "errmsg": "重试耗尽"}

def send_to_qywechat(webhook_url, text):
    if not webhook_url:
        return
    session = build_api_session()
    try:
        session.post(webhook_url, json={"msgtype": "text", "text": {"content": text}}, timeout=5)
    except Exception as exc:
        logger.warning("企业微信通知失败: {}", exc)
