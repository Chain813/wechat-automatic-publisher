code = '''
class WeiboPlugin(BaseSourcePlugin):
    @property
    def source_id(self) -> str:
        return "weibo"

    @property
    def display_name(self) -> str:
        return "微博实时热搜"

    def fetch_data(self) -> List[str]:
        if _is_source_disabled(self.source_id):
            return []

        logger.info(f"  正在同步 {self.display_name}...")
        topics = []

        try:
            headers = get_headers(referer="https://weibo.com/")
            res = HTTP_SESSION.get("https://weibo.com/ajax/side/hotSearch", headers=headers, timeout=10)
            res.raise_for_status()
            data = res.json()
            for item in data.get("data", {}).get("realtime", []):
                word = item.get("word", "").strip()
                if word and len(word) > 1 and "公告" not in word:
                    topics.append(word)
            if topics:
                _mark_source_success(self.source_id)
                return topics[:NEWS_MAX_PER_SOURCE]
        except Exception as e:
            logger.warning(f"  微博原生 API 失败: {e}，降级至 60s API")

        try:
            res = HTTP_SESSION.get(f"{API_60S_BASE}/weibo", headers=get_headers(), timeout=10)
            res.raise_for_status()
            data = res.json()
            if data.get("code") == 200:
                for item in data.get("data", []):
                    title = item.get("title", "").strip()
                    if title and len(title) > 1:
                        topics.append(title)
                if topics:
                    _mark_source_success(self.source_id)
                    return topics[:NEWS_MAX_PER_SOURCE]
        except Exception as e:
            logger.warning(f"  微博 60s API 也失败: {e}，降级至 Selenium")
            return self._fetch_weibo_selenium()
        
        return topics

    def _fetch_weibo_selenium(self):
        logger.info("  正在同步 微博 全网热搜 (Selenium 降级)...")
        browser = None
        topics = []
        try:
            from utils.spider import build_stealth_browser
            browser = build_stealth_browser(headless=True)
            browser.get("https://s.weibo.com/top/summary")
            import time
            time.sleep(4)
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(browser.page_source, "html.parser")
            items = soup.select(".td-02 a")
            for item in items:
                t = item.get_text(strip=True)
                if t and t != "公告" and not t.startswith("直播"):
                    topics.append(t)
            _mark_source_success(self.source_id)
        except Exception as e:
            logger.warning(f"  微博 Selenium 抓取也失败: {e}")
            _mark_source_failure(self.source_id)
        finally:
            if browser:
                browser.quit()
        return topics[:NEWS_MAX_PER_SOURCE]
'''

with open('core/plugins/hotspots_sources.py', 'a', encoding='utf-8') as f:
    f.write(code)
