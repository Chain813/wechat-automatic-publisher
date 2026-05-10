import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import markdown
import requests
from loguru import logger

from config import BRAND_NAME, WECHAT_TITLE_MAX_LEN
from core.shared.llm import filter_sensitive, simplify_keyword
from utils.image_handler import download_image

ASSET_RETENTION_DAYS = 5
PLACEHOLDER_PATTERN = re.compile(r"【\s*此处插入配图\s*[：:]\s*(.*?)\s*】")
GITHUB_IMAGE_PATTERN = re.compile(r"【\s*GITHUB配图\s*[：:]\s*(https?://.*?)\s*】")

def _download_and_upload(keyword, publisher, use_ai_first=False):
    """下载图片并立即上传到微信，合并为单步操作（供并行调用）"""
    keyword = keyword.strip()
    if not keyword:
        return keyword, None

    logger.info("正在为段落关键词 '{}' 搜寻最佳配图...", keyword)
    if use_ai_first:
        from utils.image_handler import download_image_for_hotspot
        image_path = download_image_for_hotspot(keyword)
    else:
        image_path = download_image(keyword)
    if not image_path:
        simplified = simplify_keyword(keyword)
        if simplified and simplified.strip():
            if use_ai_first:
                from utils.image_handler import download_image_for_hotspot
                image_path = download_image_for_hotspot(simplified)
            else:
                image_path = download_image(simplified)

    if not image_path:
        return keyword, None

    image_url = publisher.upload_news_image(image_path)
    return keyword, image_url

def _extract_image_placeholders(article_text):
    placeholders = []
    seen = set()
    for match in PLACEHOLDER_PATTERN.findall(article_text or ""):
        keyword = match.strip()
        if keyword and keyword not in seen:
            seen.add(keyword)
            placeholders.append(keyword)
    return placeholders

def _replace_placeholder(html_body, keyword, replacement):
    # 使用正则表达式进行不区分空格的替换
    pattern = re.compile(rf"【\s*此处插入配图\s*[：:]\s*{re.escape(keyword)}\s*】")
    return pattern.sub(replacement, html_body)

def process_article_content(article_text, publisher, use_ai_first=False):
    if not article_text:
        return "", {"word_count": 0, "image_count": 0, "sensitive_words": []}

    cleaned = re.sub(r"```\s*markdown\s*\n?", "", article_text)
    cleaned = re.sub(r"```\s*\n?", "", cleaned).strip()

    # 移除残留的结构性标签文字（LLM 可能仍会输出）
    structural_labels = [
        "事件钩子", "拆解博弈", "技术逻辑", "预判观点", "互动收尾",
        "核心特性", "适用场景", "项目亮点", "技术/产业逻辑", "技术与产业深挖",
    ]
    for label in structural_labels:
        cleaned = re.sub(rf'#+\s*{re.escape(label)}\s*[:：]?\s*\n?', '', cleaned)
        cleaned = re.sub(rf'\*\*{re.escape(label)}\*\*\s*[:：]?\s*', '', cleaned)
        cleaned = re.sub(rf'{re.escape(label)}[：:]\s*', '', cleaned)

    # 重点分级：**{红色加粗}** → 临时标记，防止 markdown 转换时丢失花括号
    cleaned = re.sub(r'\*\*\{(.*?)\}\*\*', r'<redbold>\1</redbold>', cleaned)

    # ---- 修复低级格式错误 (Anti-Low-Level-Errors) ----
    # 1. 修复冒号出现在行首的问题：将行首的冒号合并到上一行末尾
    cleaned = re.sub(r'\n\s*[:：]', '：', cleaned)
    
    # 2. 修复空列表项：移除只有列表符号但没内容的行
    cleaned = re.sub(r'^\s*[-*+]\s*$', '', cleaned, flags=re.MULTILINE)
    
    # 3. 修复列表项内部的换行问题：如果列表符号后面紧跟换行，则合并
    cleaned = re.sub(r'([-*+]\s*)\n\s*', r'\1', cleaned)

    # 4. 移除多余的空行（连续 3 个及以上合并为 2 个）
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    # ---------------------------------------------

    cleaned, hit_words = filter_sensitive(cleaned)
    if hit_words:
        logger.warning("  检测到敏感词: {}", hit_words)

    placeholders = _extract_image_placeholders(cleaned)
    
    github_images = []
    seen_gh = set()
    for match in GITHUB_IMAGE_PATTERN.findall(cleaned or ""):
        url = match.strip()
        if url and url not in seen_gh:
            seen_gh.add(url)
            github_images.append(url)

    html_body = markdown.markdown(cleaned, extensions=["extra", "nl2br", "sane_lists"])

    # 更加鲁棒地移除占位符周围的 P 标签
    html_body = re.sub(
        r'<p>\s*(【\s*此处插入配图\s*[：:].*?\s*】)\s*</p>',
        r'\1',
        html_body,
        flags=re.DOTALL
    )
    html_body = re.sub(
        r'<p>\s*(【\s*GITHUB配图\s*[：:].*?\s*】)\s*</p>',
        r'\1',
        html_body,
        flags=re.DOTALL
    )

    image_results = {}
    if placeholders:
        logger.info("启动并行图片下载+上传引擎 ({} 张)...", len(placeholders))
        with ThreadPoolExecutor(max_workers=min(3, len(placeholders))) as executor:
            futures = {executor.submit(_download_and_upload, kw, publisher, use_ai_first): kw for kw in placeholders}
            for future in as_completed(futures):
                try:
                    keyword, image_url = future.result()
                    image_results[keyword] = image_url
                except Exception as exc:
                    logger.warning("  并行图片处理异常: {}", exc)

    image_count = 0
    for keyword in placeholders:
        image_url = image_results.get(keyword)
        if image_url:
            image_html = (
                '<p style="text-align:center;margin: 20px 0;">'
                f'<img src="{image_url}" style="width:100%;max-width:600px;border-radius:12px;'
                'box-shadow: 0 4px 12px rgba(0,0,0,0.1);">'
                "</p>"
            )
            html_body = _replace_placeholder(html_body, keyword, image_html)
            image_count += 1
            logger.info("  配图已成功嵌入文章")
        else:
            html_body = _replace_placeholder(html_body, keyword, "")
            logger.info("  最终未匹配到合适配图，已移除占位符")

    for gh_url in github_images:
        tmp_path = None
        try:
            logger.info("正在下载 GitHub 配图: {}", gh_url)
            res = requests.get(gh_url, timeout=10)
            if res.status_code == 200:
                tmp_path = os.path.join("assets", f"gh_{int(time.time()*1000)}.jpg")
                with open(tmp_path, 'wb') as f:
                    f.write(res.content)

                image_url = publisher.upload_news_image(tmp_path)
                if image_url:
                    image_html = (
                        '<p style="text-align:center;margin: 20px 0;">'
                        f'<img src="{image_url}" style="width:100%;max-width:600px;border-radius:12px;'
                        'box-shadow: 0 4px 12px rgba(0,0,0,0.1);">'
                        "</p>"
                    )
                    pattern = re.compile(rf"【GITHUB配图：\s*{re.escape(gh_url)}】")
                    html_body = pattern.sub(image_html, html_body)
                    image_count += 1
                    logger.info("  GitHub 配图已成功嵌入文章")
                    continue
        except Exception as e:
            logger.warning("  GitHub 配图处理失败: {}", e)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

        pattern = re.compile(rf"【GITHUB配图：\s*{re.escape(gh_url)}】")
        html_body = pattern.sub("", html_body)

    # 统一增加段落缩进和间距
    html_body = html_body.replace(
        '<p>', 
        '<p style="margin-bottom: 15px; line-height: 1.8; text-align: justify; font-size: 16px; color: #333;">'
    )
    
    # 优化引用块样式
    html_body = html_body.replace(
        '<blockquote>', 
        '<blockquote style="margin: 20px 0; padding: 15px 20px; border-left: 5px solid #0366d6; background-color: #f6f8fa; color: #586069; border-radius: 4px; font-size: 15px;">'
    )

    # 优化 H2 标题样式 (GitHub 项目名)
    html_body = re.sub(
        r'<h2>(.*?)</h2>',
        r'<h2 style="margin-top: 35px; margin-bottom: 20px; padding-bottom: 8px; border-bottom: 2px solid #eaecef; font-size: 22px; color: #24292e; font-weight: bold;">\1</h2>',
        html_body
    )

    # 优化 H3 标题样式
    html_body = re.sub(
        r'<h3>(.*?)</h3>',
        r'<h3 style="margin-top: 25px; margin-bottom: 15px; font-size: 18px; color: #0366d6; font-weight: bold; border-left: 4px solid #0366d6; padding-left: 10px;">\1</h3>',
        html_body
    )

    # 优化无序列表样式
    html_body = html_body.replace(
        '<ul>',
        '<ul style="margin-bottom: 20px; padding-left: 25px; line-height: 1.8; color: #333;">'
    )

    # 重点分级样式：红色加粗（最核心结论） → 黑色加粗（重要论点）
    html_body = html_body.replace(
        '<redbold>', '<strong style="color: #d73a49; font-weight: bold;">'
    ).replace(
        '</redbold>', '</strong>'
    )
    html_body = re.sub(
        r'<strong>(.*?)</strong>',
        r'<strong style="color: #1a1a1a; font-weight: bold;">\1</strong>',
        html_body
    )

    word_count = len(cleaned.replace("\n", "").replace(" ", ""))
    return html_body, {
        "word_count": word_count,
        "image_count": image_count,
        "sensitive_words": hit_words,
    }


def cleanup_old_assets(base_dir="assets", max_age_days=ASSET_RETENTION_DAYS):
    if not os.path.exists(base_dir):
        return

    now = time.time()
    cutoff = now - max_age_days * 86400
    removed_count = 0
    removed_dirs = 0

    for root, dirs, files in os.walk(base_dir, topdown=False):
        for filename in files:
            filepath = os.path.join(root, filename)
            try:
                if os.path.getmtime(filepath) < cutoff:
                    os.remove(filepath)
                    removed_count += 1
            except OSError as e:
                logger.debug("  清理文件失败 {}: {}", filepath, e)

        for dirname in dirs:
            dirpath = os.path.join(root, dirname)
            try:
                if not os.listdir(dirpath):
                    os.rmdir(dirpath)
                    removed_dirs += 1
            except OSError as e:
                logger.debug("  清理目录失败 {}: {}", dirpath, e)

    if removed_count > 0:
        logger.info(
            "🧹 自动清理：已删除 {} 个过期文件和 {} 个空目录 (>{}天)",
            removed_count,
            removed_dirs,
            max_age_days,
        )

def _print_banner():
    print("\n" + "=" * 60)
    print(f"  🚀 「{BRAND_NAME}」全自动 AI 内容工厂 v6.0")
    print("=" * 60 + "\n")

def _print_review_report(title, word_count, image_count, sensitive_words, cover_ok, digest):
    print(f"\n{'─' * 50}")
    print("  📋 发布前审核报告")
    print(f"{'─' * 50}")

    title_ok = len(title) <= WECHAT_TITLE_MAX_LEN
    title_icon = "✅" if title_ok else "⚠️"
    print(f"  标题：{title} ({len(title)} 字 {title_icon})")

    wc_icon = "✅" if 2000 <= word_count <= 4000 else "⚠️"
    print(f"  字数：{word_count:,} 字 ({wc_icon})")

    image_icon = "✅" if image_count >= 3 else "⚠️"
    print(f"  配图：{image_count} 张 ({image_icon})")

    sensitive_icon = "❌" if sensitive_words else "✅"
    sensitive_msg = f"命中 {len(sensitive_words)} 词: {sensitive_words}" if sensitive_words else "无"
    print(f"  敏感词：{sensitive_msg} ({sensitive_icon})")

    cover_icon = "✅" if cover_ok else "⚠️"
    print(f"  封面图：{'已上传' if cover_ok else '未上传'} ({cover_icon})")

    if digest:
        print(f"  摘要：{digest[:80]}{'...' if len(digest) > 80 else ''}")

    all_ok = title_ok and (2000 <= word_count <= 4000) and image_count >= 3 and not sensitive_words and cover_ok
    print(f"{'─' * 50}")
    print("  🎉 审核通过，可以发布！" if all_ok else "  ⚠️ 存在警告项，请手动检查后再发布。")
    print(f"{'─' * 50}\n")
    return all_ok
