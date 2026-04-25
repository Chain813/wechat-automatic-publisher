"""
============================================================
  多源舆情采集引擎 v3.0 (Multi-Source Sentiment Crawler)
  支持平台：新浪微博 / 小红书 / 抖音
  适配项目：长春伪满皇宫周边街区多模态微更新决策平台
============================================================
"""
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import pandas as pd
import time
import random
import sys
import os
import urllib.parse

# 强制 UTF-8 输出，防止 Windows GBK 编码崩溃
sys.stdout.reconfigure(encoding='utf-8')

# ==========================================
#  通用基础设施
# ==========================================

def build_stealth_browser(headless=False):
    """构建反检测隐形浏览器（增强版，适配微博/小红书/抖音三平台）"""
    print("🛡️ 正在挂载隐形迷彩...")
    chrome_options = Options()

    # 随机化 User-Agent（降低指纹被锁定的概率）
    ua_list = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
    ]
    user_agent = random.choice(ua_list)
    chrome_options.add_argument(f'user-agent={user_agent}')
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--lang=zh-CN")
    if headless:
        chrome_options.add_argument("--headless=new")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    # 注入多项反检测脚本（抖音对 webdriver 指纹检测尤其严格）
    stealth_js = """
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
        window.chrome = { runtime: {} };
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
            Promise.resolve({state: Notification.permission}) :
            originalQuery(parameters)
        );
    """
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": stealth_js})
    driver.maximize_window()
    return driver


def scroll_page(driver, times=5, wait_range=(2.0, 4.0)):
    """通用页面滚动"""
    for i in range(times):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(random.uniform(*wait_range))


def smart_scroll(driver, max_times=10, wait_range=(2.5, 4.5)):
    """智能滚动：检测页面高度停止增长后自动退出"""
    last_height = 0
    for i in range(max_times):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(random.uniform(*wait_range))
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            print(f"   -> 第 {i+1} 次下潜：页面已触底，结束滚动。")
            break
        last_height = new_height
        print(f"   -> 第 {i+1} 次下潜完成 (页面高度: {new_height})")


def wait_for_login(driver, url, platform_name, countdown=60):
    """通用扫码登录等待器"""
    print(f"\n🔐 正在空降 {platform_name} 主站...")
    driver.get(url)
    time.sleep(3)
    print("\n" + "*" * 50)
    print(f"  ⚠️  请立即使用手机 {platform_name} App 扫码登录！")
    print(f"  ⚠️  登录成功后无需任何操作，系统将自动接管。")
    print("*" * 50)
    for c in range(countdown, 0, -5):
        print(f"  ⏱️  剩余等待时间: {c} 秒...")
        time.sleep(5)
    print(f"🚀 倒计时结束！装甲车接管浏览器，开始 {platform_name} 巡航...\n")


def deduplicate(data_list):
    """去重"""
    seen = set()
    unique = []
    for item in data_list:
        if item["Text"] not in seen:
            seen.add(item["Text"])
            unique.append(item)
    return unique


def save_results(new_data, csv_path="data/CV_NLP_RawData.csv"):
    """将新数据追加合并到已有 CSV（而非覆盖）"""
    new_df = pd.DataFrame(new_data)
    if os.path.exists(csv_path):
        old_df = pd.read_csv(csv_path, encoding='utf-8-sig')
        combined = pd.concat([old_df, new_df], ignore_index=True)
        # 基于 Text 列全局去重
        combined = combined.drop_duplicates(subset=['Text'], keep='first')
    else:
        combined = new_df
    combined.to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f"\n📊 数据已写入 {csv_path}，当前总量: {len(combined)} 条")
    if 'Source' in combined.columns:
        print(combined['Source'].value_counts().to_string())
    return combined


# ==========================================
#  模块 1：新浪微博采集引擎
# ==========================================

WEIBO_KEYWORDS = [
    "长春伪满皇宫", "长春光复路老街", "宽城区 中车老厂", "长春百年客车厂",
    "长春光复路市场 拥堵", "光复路 乱停车", "伪满皇宫周边 破旧",
    "亚泰大街 堵车", "长春铁路线 噪音",
    "宽城区 老旧小区改造", "长春老建筑 拆除", "长春市 工业遗产 保护", "宽城区 步行街 绿化"
]


def extract_weibo(html, keyword):
    """微博搜索结果页提取"""
    soup = BeautifulSoup(html, 'html.parser')
    data = []
    for card in soup.find_all('div', class_='card-wrap'):
        try:
            el = card.find('p', class_='txt')
            text = el.text.strip() if el else ""
            if text and len(text) > 5:
                data.append({"Text": text, "Keyword": keyword, "Source": "新浪微博"})
        except Exception:
            continue
    return data


def run_weibo(driver, max_retries=2):
    """执行微博全量采集（含自动重试）"""
    print("\n" + "=" * 50)
    print("  📱 微博采集引擎启动")
    print("=" * 50)
    all_data = []
    for kw in WEIBO_KEYWORDS:
        url = f"https://s.weibo.com/weibo?q={urllib.parse.quote(kw)}"
        data = []
        for attempt in range(max_retries + 1):
            print(f"\n🚁 空降: {kw}" + (f" (重试 {attempt})" if attempt > 0 else ""))
            driver.get(url)
            time.sleep(random.uniform(2.5, 4.0))
            scroll_page(driver, times=4)
            html = driver.page_source
            data = extract_weibo(html, kw)
            if data:
                break
            print(f"   ⚠️ 未获取到数据，{'重试中...' if attempt < max_retries else '跳过'}")
            time.sleep(random.uniform(3.0, 5.0))
        all_data.extend(data)
        print(f"✅ [{kw}] 获得 {len(data)} 条")
        # 微博反爬间隔：用随机抖动避免固定模式
        time.sleep(random.uniform(5.0, 12.0))

    result = deduplicate(all_data)
    print(f"\n📊 微博采集完毕：共 {len(result)} 条（去重后）")
    return result


# ==========================================
#  模块 2：小红书采集引擎
# ==========================================

XHS_KEYWORDS = [
    "长春伪满皇宫打卡", "长春老街拍照", "长春工业风打卡", "长春小众景点",
    "长春旅游攻略", "长春拍照圣地",
    "长春避雷", "长春光复路", "长春旅游 堵车", "长春老城区",
    "长春吐槽", "长春脏乱差",
    "长春宽城区", "长春老旧小区", "长春改造",
    "长春街道", "长春停车难", "长春绿化"
]


def extract_xhs_search(soup, keyword):
    """Phase A：从搜索结果页提取卡片标题"""
    data = []
    cards = soup.find_all('section', class_='note-item')
    if not cards:
        cards = soup.find_all('div', attrs={'class': lambda c: c and 'note' in c.lower()})
    if not cards:
        cards = soup.find_all(['a', 'span', 'div'], attrs={
            'class': lambda c: c and ('title' in str(c).lower() or 'desc' in str(c).lower())
        })

    for card in cards:
        try:
            title = card.find('a', class_='title') or card.find('span', class_='title') or \
                    card.find('div', attrs={'class': lambda c: c and 'title' in str(c).lower()})
            desc = card.find('span', class_='desc') or \
                   card.find('div', attrs={'class': lambda c: c and 'desc' in str(c).lower()})
            text = f"{title.text.strip() if title else ''} {desc.text.strip() if desc else ''}".strip()
            if text and len(text) > 4:
                data.append({"Text": text, "Keyword": keyword, "Source": "小红书"})
        except Exception:
            continue

    # 暴力扫描兜底
    if len(data) < 3:
        for t in soup.find_all(string=True):
            txt = t.strip()
            if 8 < len(txt) < 500 and keyword[0:2] in txt:
                data.append({"Text": txt, "Keyword": keyword, "Source": "小红书"})
    return data


def extract_xhs_detail(driver, keyword, max_notes=6):
    """Phase B：点击笔记详情页提取正文+评论"""
    data = []
    try:
        links = driver.find_elements('css selector',
            'a[href*="/explore/"], a[href*="/discovery/item/"], section.note-item a, div[class*="note"] a')
        original = driver.current_window_handle
        clicked = 0

        for link in links[:max_notes]:
            try:
                href = link.get_attribute('href')
                if not href or 'javascript' in href:
                    continue
                driver.execute_script("window.open(arguments[0], '_blank');", href)
                time.sleep(random.uniform(2.5, 4.0))
                driver.switch_to.window(driver.window_handles[-1])
                time.sleep(2)

                # 滚动加载评论
                for _ in range(3):
                    driver.execute_script("window.scrollBy(0, 600);")
                    time.sleep(random.uniform(1.0, 2.0))

                dsoup = BeautifulSoup(driver.page_source, 'html.parser')

                # 正文
                body = dsoup.find('div', id='detail-desc') or \
                       dsoup.find('div', attrs={'class': lambda c: c and 'desc' in str(c).lower()})
                if body and len(body.get_text(strip=True)) > 10:
                    data.append({"Text": body.get_text(strip=True)[:500], "Keyword": keyword, "Source": "小红书"})

                # 评论
                for cel in dsoup.find_all(['span', 'div', 'p'], attrs={
                    'class': lambda c: c and ('comment' in str(c).lower() or 'content' in str(c).lower())
                }):
                    ct = cel.get_text(strip=True)
                    if 5 < len(ct) < 500:
                        data.append({"Text": ct, "Keyword": keyword, "Source": "小红书"})

                clicked += 1
                driver.close()
                driver.switch_to.window(original)
                time.sleep(random.uniform(1.0, 2.0))
            except Exception:
                try:
                    if len(driver.window_handles) > 1: driver.close()
                    driver.switch_to.window(original)
                except Exception: pass
                continue
        print(f"   Phase B: 穿透 {clicked} 篇笔记")
    except Exception as e:
        print(f"   Phase B 跳过: {e}")
    return data


def run_xhs(driver):
    """执行小红书全量采集"""
    print("\n" + "=" * 50)
    print("  🍠 小红书深度采集引擎启动")
    print("=" * 50)

    wait_for_login(driver, "https://www.xiaohongshu.com", "小红书")

    all_data = []
    for kw in XHS_KEYWORDS:
        url = f"https://www.xiaohongshu.com/search_result?keyword={urllib.parse.quote(kw)}&source=web_search_result_notes"
        print(f"\n🍠 空降: {kw}")
        driver.get(url)
        time.sleep(4)
        smart_scroll(driver, max_times=10)

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        a_data = extract_xhs_search(soup, kw)
        print(f"   Phase A: {len(a_data)} 条")

        b_data = extract_xhs_detail(driver, kw, max_notes=6)
        all_data.extend(a_data + b_data)
        print(f"✅ [{kw}] 合计 {len(a_data) + len(b_data)} 条")
        time.sleep(random.uniform(5.0, 8.0))

    result = deduplicate(all_data)
    print(f"\n📊 小红书采集完毕：共 {len(result)} 条（去重后）")
    return result


# ==========================================
#  模块 3：抖音采集引擎
# ==========================================

DOUYIN_KEYWORDS = [
    "长春伪满皇宫", "长春旅游攻略", "长春光复路", "长春老街",
    "长春避雷", "长春吐槽", "长春老旧小区改造",
    "长春宽城区", "长春工业遗产", "长春打卡",
    "长春停车难", "长春破旧小区", "长春绿化改造"
]


def extract_douyin_search(soup, keyword):
    """从抖音搜索结果页提取视频标题和描述"""
    data = []

    # 抖音 Web 版搜索结果的视频卡片（多重选择器兼容）
    cards = soup.find_all('div', attrs={'class': lambda c: c and 'video' in str(c).lower()})
    if not cards:
        cards = soup.find_all('li', attrs={'class': lambda c: c and 'result' in str(c).lower()})
    if not cards:
        cards = soup.find_all('div', attrs={'class': lambda c: c and ('card' in str(c).lower() or 'item' in str(c).lower())})

    for card in cards:
        try:
            # 视频标题
            title_el = card.find(['a', 'span', 'p', 'h3'], attrs={
                'class': lambda c: c and ('title' in str(c).lower() or 'desc' in str(c).lower() or 'text' in str(c).lower())
            })
            title = title_el.get_text(strip=True) if title_el else ""

            # 视频描述/副标题
            desc_el = card.find(['span', 'p'], attrs={
                'class': lambda c: c and ('desc' in str(c).lower() or 'info' in str(c).lower())
            })
            desc = desc_el.get_text(strip=True) if desc_el else ""

            text = f"{title} {desc}".strip()
            if text and len(text) > 4:
                data.append({"Text": text, "Keyword": keyword, "Source": "抖音"})
        except Exception:
            continue

    # 暴力扫描兜底：提取页面中所有像视频标题的文本
    if len(data) < 3:
        print(f"   -> 结构化提取不足，启用暴力扫描...")
        for t in soup.find_all(string=True):
            txt = t.strip()
            if 6 < len(txt) < 200 and keyword[0:2] in txt:
                data.append({"Text": txt, "Keyword": keyword, "Source": "抖音"})

    return data


def extract_douyin_comments(driver, keyword, max_videos=5):
    """点击视频详情页提取评论区内容"""
    data = []
    try:
        # 在抖音 Web 版中，视频卡片通常是可点击的 a 标签或 div
        video_links = driver.find_elements('css selector',
            'a[href*="/video/"], a[href*="modal_id"], div[class*="video"] a')

        original = driver.current_window_handle
        clicked = 0

        for vlink in video_links[:max_videos]:
            try:
                href = vlink.get_attribute('href')
                if not href or 'javascript' in href:
                    continue

                driver.execute_script("window.open(arguments[0], '_blank');", href)
                time.sleep(random.uniform(3.0, 5.0))
                driver.switch_to.window(driver.window_handles[-1])
                time.sleep(3)

                # 滚动加载评论区
                for _ in range(4):
                    driver.execute_script("window.scrollBy(0, 500);")
                    time.sleep(random.uniform(1.5, 2.5))

                dsoup = BeautifulSoup(driver.page_source, 'html.parser')

                # 视频描述/正文
                desc_el = dsoup.find(['span', 'div', 'p'], attrs={
                    'class': lambda c: c and ('desc' in str(c).lower() or 'title' in str(c).lower())
                })
                if desc_el and len(desc_el.get_text(strip=True)) > 5:
                    data.append({"Text": desc_el.get_text(strip=True)[:500], "Keyword": keyword, "Source": "抖音"})

                # 评论区
                comment_els = dsoup.find_all(['span', 'p', 'div'], attrs={
                    'class': lambda c: c and ('comment' in str(c).lower() or 'reply' in str(c).lower())
                })
                for cel in comment_els:
                    ct = cel.get_text(strip=True)
                    if 3 < len(ct) < 300:
                        data.append({"Text": ct, "Keyword": keyword, "Source": "抖音"})

                clicked += 1
                driver.close()
                driver.switch_to.window(original)
                time.sleep(random.uniform(1.5, 3.0))

            except Exception:
                try:
                    if len(driver.window_handles) > 1: driver.close()
                    driver.switch_to.window(original)
                except Exception: pass
                continue

        print(f"   Phase B: 穿透 {clicked} 个视频")
    except Exception as e:
        print(f"   Phase B 跳过: {e}")
    return data


def run_douyin(driver):
    """执行抖音全量采集（针对抖音反爬特别优化）"""
    print("\n" + "=" * 50)
    print("  🎵 抖音采集引擎启动")
    print("=" * 50)

    # 抖音 Web 版不强制登录就能搜索，但登录后可看到更多评论
    wait_for_login(driver, "https://www.douyin.com", "抖音", countdown=45)

    all_data = []
    for kw in DOUYIN_KEYWORDS:
        url = f"https://www.douyin.com/search/{urllib.parse.quote(kw)}?type=video"
        print(f"\n🎵 空降: {kw}")
        driver.get(url)
        # 抖音页面加载较重，需更长等待
        time.sleep(random.uniform(4.0, 6.0))

        # 抖音特有：模拟人类滚动行为（非匀速，有停顿）
        for i in range(8):
            scroll_dist = random.randint(400, 900)
            driver.execute_script(f"window.scrollBy(0, {scroll_dist});")
            time.sleep(random.uniform(1.5, 3.5))
            # 偶尔向上回滚一点点，模拟真人浏览
            if random.random() < 0.25:
                driver.execute_script(f"window.scrollBy(0, -{random.randint(50, 150)});")
                time.sleep(random.uniform(0.5, 1.0))

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        a_data = extract_douyin_search(soup, kw)
        print(f"   Phase A: {len(a_data)} 条")

        b_data = extract_douyin_comments(driver, kw, max_videos=4)
        all_data.extend(a_data + b_data)
        print(f"✅ [{kw}] 合计 {len(a_data) + len(b_data)} 条")
        # 抖音间隔故意拉长，避免触发风控
        time.sleep(random.uniform(6.0, 12.0))

    result = deduplicate(all_data)
    print(f"\n📊 抖音采集完毕：共 {len(result)} 条（去重后）")
    return result


# ==========================================
#  Streamlit 可调用的 API 入口（无需 CLI 菜单）
# ==========================================

def run_selected_platforms(platforms, csv_path="data/CV_NLP_RawData.csv"):
    """
    从 Streamlit 页面调用的统一入口。
    platforms: list，可选值 ["weibo", "xhs", "douyin"]
    返回: (bool, str) => (成功与否, 日志摘要)
    """
    platform_names = {"weibo": "新浪微博", "xhs": "小红书", "douyin": "抖音"}
    names = [platform_names.get(p, p) for p in platforms]
    log_lines = [f"🚀 启动采集: {' + '.join(names)}"]

    driver = build_stealth_browser()
    all_results = []

    try:
        if "weibo" in platforms:
            results = run_weibo(driver)
            all_results.extend(results)
            log_lines.append(f"📱 微博采集完成: {len(results)} 条")

        if "xhs" in platforms:
            results = run_xhs(driver)
            all_results.extend(results)
            log_lines.append(f"🍠 小红书采集完成: {len(results)} 条")

        if "douyin" in platforms:
            results = run_douyin(driver)
            all_results.extend(results)
            log_lines.append(f"🎵 抖音采集完成: {len(results)} 条")

        if all_results:
            save_results(all_results, csv_path)
            log_lines.append(f"🎉 采集完毕！共 {len(all_results)} 条新数据已写入 {csv_path}")
            return True, "\n".join(log_lines)
        else:
            log_lines.append("⚠️ 本次未采集到任何数据")
            return False, "\n".join(log_lines)

    except Exception as e:
        log_lines.append(f"❌ 采集异常: {e}")
        return False, "\n".join(log_lines)

    finally:
        driver.quit()
        log_lines.append("💥 浏览器已销毁")


# ==========================================
#  主菜单系统（命令行入口）
# ==========================================

def show_menu():
    print("\n" + "=" * 50)
    print("  🕵️ 多源舆情采集引擎 v3.0")
    print("  长春伪满皇宫周边街区微更新决策平台")
    print("=" * 50)
    print()
    print("  [1] 📱 仅采集 新浪微博    (无需登录, ~3分钟)")
    print("  [2] 🍠 仅采集 小红书       (需扫码, ~8分钟)")
    print("  [3] 🎵 仅采集 抖音         (需扫码, ~6分钟)")
    print("  [4] 📱+🍠 微博 + 小红书   (~12分钟)")
    print("  [5] 📱+🎵 微博 + 抖音     (~10分钟)")
    print("  [6] 🍠+🎵 小红书 + 抖音   (~15分钟)")
    print("  [7] 🌐 全平台采集          (~20分钟)")
    print("  [0] ❌ 退出")
    print()
    return input("  请输入编号 (0-7): ").strip()


if __name__ == "__main__":
    choice = show_menu()

    if choice == "0":
        print("👋 已退出。")
        sys.exit(0)

    # 解析用户选择
    run_map = {
        "1": ["weibo"],
        "2": ["xhs"],
        "3": ["douyin"],
        "4": ["weibo", "xhs"],
        "5": ["weibo", "douyin"],
        "6": ["xhs", "douyin"],
        "7": ["weibo", "xhs", "douyin"],
    }

    platforms = run_map.get(choice, [])
    if not platforms:
        print("⚠️ 无效选择，已退出。")
        sys.exit(1)

    platform_names = {"weibo": "新浪微博", "xhs": "小红书", "douyin": "抖音"}
    print(f"\n🚀 即将启动: {' + '.join([platform_names[p] for p in platforms])}")

    driver = build_stealth_browser()
    all_results = []

    try:
        if "weibo" in platforms:
            all_results.extend(run_weibo(driver))

        if "xhs" in platforms:
            all_results.extend(run_xhs(driver))

        if "douyin" in platforms:
            all_results.extend(run_douyin(driver))

        # 合并保存
        if all_results:
            save_results(all_results)
            print(f"\n🎉 本次采集完毕！新增 {len(all_results)} 条舆情数据。")
        else:
            print("\n⚠️ 本次未采集到任何数据，请检查网络或页面结构。")

    finally:
        print("\n💥 销毁装甲车，抹除内存痕迹...")
        driver.quit()