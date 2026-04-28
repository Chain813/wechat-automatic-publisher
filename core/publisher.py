"""
============================================================
  微信公众号 API 封装 v4.0
  职责：安全 Token 管理、素材上传、草稿审计、精致排版
============================================================
"""
import os
import json
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


def _normalize_title(title):
    return ''.join(c.lower() for c in title if c.isalnum())

class WeChatPublisher:
    def __init__(self, app_id, app_secret):
        self.app_id = app_id
        self.app_secret = app_secret
        self.session = build_api_session()
        self.access_token = self._get_access_token()

    def _get_access_token(self):
        """获取并验证微信调用凭证"""
        url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={self.app_id}&secret={self.app_secret}"
        try:
            res = self.session.get(url, timeout=WECHAT_API_TIMEOUT).json()
            if "access_token" in res:
                return res["access_token"]
            else:
                raise Exception(f"Token 授权失败: {res}")
        except Exception as e:
            print(f"❌ 微信凭证获取失败: {e}")
            return None

    def upload_image(self, image_path):
        """上传素材，返回 media_id"""
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
        """获取最近草稿标题列表（查重用）"""
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
        return titles

    def _title_similarity(self, title_a, title_b):
        normalized_a = _normalize_title(title_a)
        normalized_b = _normalize_title(title_b)
        if not normalized_a or not normalized_b:
            return 0
        if fuzz is not None:
            return max(
                fuzz.ratio(normalized_a, normalized_b),
                fuzz.partial_ratio(normalized_a, normalized_b),
                fuzz.token_sort_ratio(normalized_a, normalized_b),
            )
        return int(SequenceMatcher(None, normalized_a, normalized_b).ratio() * 100)

    def is_title_duplicate(self, new_title):
        """模糊查重逻辑"""
        existing = self.get_draft_titles()
        for old in existing:
            if new_title == old:
                return True, old
            similarity = self._title_similarity(new_title, old)
            if similarity >= TITLE_DUPLICATE_RATIO:
                logger.info("命中相似标题: {} ({}%)", old, similarity)
                return True, old
        return False, None

    def add_draft(self, title, html_content, thumb_media_id, digest=""):
        """同步草稿箱，带高级容器样式"""
        if not self.access_token: return {"errcode": -1, "errmsg": "No Token"}
        url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={self.access_token}"

        # 极致阅读感的 HTML 包装
        styled_html = (
            '<section style="padding: 15px; font-family: -apple-system, BlinkMacSystemFont, '
            "'Helvetica Neue', 'PingFang SC', 'Microsoft YaHei', Arial, sans-serif; "
            'line-height: 1.8; color: #222; font-size: 17px; word-wrap: break-word;">'
            f'{html_content}'
            '</section>'
        )

        # 摘要默认为标题截断
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
        try:
            return self.session.post(
                url,
                data=json.dumps(data, ensure_ascii=False).encode('utf-8'),
                timeout=WECHAT_API_TIMEOUT
            ).json()
        except Exception as e:
            return {"errcode": -1, "errmsg": str(e)}

def send_to_qywechat(webhook_url, text):
    if not webhook_url:
        return
    session = build_api_session()
    try:
        session.post(webhook_url, json={"msgtype": "text", "text": {"content": text}}, timeout=5)
    except Exception as exc:
        logger.warning("企业微信通知失败: {}", exc)
