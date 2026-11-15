"""
============================================================
  客户账号画像分析器 — 「零访谈定制」第一步
  自动扒取客户公众号历史文章 → DeepSeek 提炼内容画像

  用法:
    python tools/analyze_account.py --urls "文章链接1,文章链接2,文章链接3"
         --topic "法律" --out data/profile.json
============================================================
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

from core.shared.llm import call_deepseek_with_retry

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
NL = chr(10)

PROFILE_SCHEMA = json.dumps({
    "domain": "内容领域(2-6字)",
    "audience": "目标读者画像(一句话)",
    "tone": "写作风格关键词(逗号分隔)",
    "hook_pattern": "开头钩子特征(一句话)",
    "structure": "文章结构特征(一句话)",
    "common_topics": ["高频主题1", "高频主题2"],
    "taboos": ["明显避免的表达1"],
    "golden_quote_style": "金句/加粗风格(一句话)",
    "image_style": "配图风格偏好(一句话)",
}, ensure_ascii=False, indent=2)


def _clean_html(fragment):
    """HTML 片段转纯文本"""
    fragment = re.sub(r"<script.*?</script>", "", fragment, flags=re.DOTALL)
    fragment = re.sub(r"<style.*?</style>", "", fragment, flags=re.DOTALL)
    fragment = re.sub(r"<br\s*/?>", NL, fragment)
    fragment = re.sub(r"</p>|</div>|</section>|</h[1-6]>|</li>", NL, fragment)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    fragment = fragment.replace("&nbsp;", " ").replace("&#160;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    fragment = re.sub(NL + r"{3,}", NL + NL, fragment)
    return fragment.strip()


def parse_article_html(html):
    """解析公众号文章页 HTML，返回 (标题, 正文纯文本)"""
    title = ""
    m = re.search(r"<h1[^>]*rich_media_title[^>]*>(.*?)</h1>", html, re.DOTALL)
    if m:
        title = _clean_html(m.group(1))
    if not title:
        m = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
        if m:
            title = _clean_html(m.group(1))
    text = ""
    m = re.search(r'<div[^>]*id="js_content"[^>]*>(.*)', html, re.DOTALL)
    if m:
        text = _clean_html(m.group(1))
    return title, text


def fetch_article(url, timeout=15):
    """抓取文章页并解析，返回 (title, text)；失败返回 (None, None)"""
    try:
        import requests
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
        if resp.status_code != 200:
            logger.warning("抓取失败 HTTP {}: {}", resp.status_code, url[:60])
            return None, None
        resp.encoding = resp.apparent_encoding or "utf-8"
        return parse_article_html(resp.text)
    except Exception as e:
        logger.warning("抓取异常 {}: {}", str(e)[:80], url[:60])
        return None, None


def _extract_json(text):
    """从 LLM 输出中提取 JSON"""
    if not text:
        return None
    m = re.search(r"```(?:json)?(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1)
    m = re.search(r"[{].*[}]", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except Exception:
        return None


def analyze_style(articles, topic_hint=""):
    """把 N 篇历史文章样本喂给 DeepSeek，提炼账号内容画像"""
    valid = [(t, b) for t, b in articles if b and len(b) > 100]
    if not valid:
        return None
    samples_text = (NL + NL + "---" + NL + NL).join(
        f"【标题】{t}" + NL + f"【正文节选】{b[:800]}" for t, b in valid[:12]
    )
    topic_block = f"" + NL + f"客户提供的行业提示：{topic_hint}（若与文章内容矛盾，以文章为准）" if topic_hint else ""
    prompt = f"""你是资深公众号内容分析师。以下是某个公众号的 {len(valid)} 篇历史文章样本：

{samples_text}
{topic_block}

请提炼该账号的内容画像，严格输出 JSON：
{PROFILE_SCHEMA}

要求：
- domain：内容领域（2-6字）
- audience：目标读者画像（一句话，含身份+核心关切）
- tone：写作风格关键词（逗号分隔，如"案例驱动,口语化,强冲突"）
- hook_pattern：开头钩子特征（一句话）
- structure：文章结构特征（一句话）
- common_topics：高频主题列表（3-6个）
- taboos：明显避免的内容/表达（2-4条）
- golden_quote_style：金句/加粗风格（一句话）
- image_style：配图风格偏好（一句话）
只输出 JSON，不要其他文字。"""
    res = call_deepseek_with_retry(
        prompt,
        system_content="你是资深内容分析师，严格输出 JSON。",
        max_tokens=2048,
    )
    return _extract_json(res)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="客户账号画像分析器")
    ap.add_argument("--urls", required=True, help="客户历史文章链接（逗号分隔，3-10 篇代表作效果最好）")
    ap.add_argument("--topic", default="", help="行业提示（可选）")
    ap.add_argument("--out", default="data/profile.json", help="画像输出路径")
    args = ap.parse_args()

    urls = [u.strip() for u in args.urls.split(",") if u.strip()]
    print(f"📥 正在抓取 {len(urls)} 篇客户历史文章 ...")
    articles = []
    for i, url in enumerate(urls):
        title, text = fetch_article(url)
        if title or text:
            articles.append((title, text))
            print(f"  [{i + 1}] ✅ {title[:40] or url[:40]} ({len(text)} 字)")
        else:
            print(f"  [{i + 1}] ❌ 抓取失败: {url[:50]}")

    if not articles:
        print("❌ 未能抓取到任何有效文章。请确认链接为 mp.weixin.qq.com 公开文章页")
        sys.exit(1)

    print(f"🧠 正在提炼账号内容画像（{len(articles)} 篇样本）...")
    profile = analyze_style(articles, args.topic)
    if not profile:
        print("❌ 画像分析失败，请重试")
        sys.exit(1)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    print(f"✅ 画像已保存: {args.out}")
    print(json.dumps(profile, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
