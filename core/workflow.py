"""
Publishing workflow orchestration.
"""
from __future__ import annotations

import os
import re
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

import markdown
from loguru import logger

from config import (
    BRAND_NAME,
    QYWECHAT_WEBHOOK,
    WECHAT_APP_ID,
    WECHAT_APP_SECRET,
    WECHAT_TITLE_MAX_LEN,
)
from core.collector import fetch_all_hotspots, get_source_health_report
from core.processor import (
    filter_sensitive,
    filter_tech_hotspots,
    generate_article,
    generate_digest,
    simplify_keyword,
    validate_title,
)
from core.publisher import WeChatPublisher, send_to_qywechat
from utils.image_handler import download_cover_image, download_image, reset_image_cache

ASSET_RETENTION_DAYS = 5
MAX_TOPICS_PER_RUN = 1
PLACEHOLDER_PATTERN = re.compile(r"【此处插入配图\s*[：:]\s*(.*?)】")


def _download_single_image(keyword):
    """Download one inline image candidate for concurrent use."""
    keyword = keyword.strip()
    if not keyword:
        return keyword, None

    logger.info("正在为段落关键词 '{}' 搜寻最佳配图...", keyword)
    image_path = download_image(keyword)
    if not image_path:
        image_path = download_image(simplify_keyword(keyword))

    return keyword, image_path


def _extract_image_placeholders(article_text):
    """Extract and deduplicate placeholder keywords while preserving order."""
    placeholders = []
    seen = set()
    for match in PLACEHOLDER_PATTERN.findall(article_text or ""):
        keyword = match.strip()
        if keyword and keyword not in seen:
            seen.add(keyword)
            placeholders.append(keyword)
    return placeholders


def _replace_placeholder(html_body, keyword, replacement):
    """Replace all placeholder variants for a specific keyword."""
    pattern = re.compile(rf"【此处插入配图\s*[：:]\s*{re.escape(keyword)}】")
    return pattern.sub(replacement, html_body)


def process_article_content(article_text, publisher):
    """Convert Markdown to HTML and replace image placeholders in parallel."""
    if not article_text:
        return "", {"word_count": 0, "image_count": 0, "sensitive_words": []}

    cleaned = re.sub(r"```\s*markdown\s*\n?", "", article_text)
    cleaned = re.sub(r"```\s*\n?", "", cleaned).strip()

    cleaned, hit_words = filter_sensitive(cleaned)
    if hit_words:
        logger.warning("  检测到敏感词: {}", hit_words)

    placeholders = _extract_image_placeholders(cleaned)
    html_body = markdown.markdown(cleaned, extensions=["extra", "nl2br", "sane_lists"])

    # 移除占位符外层的 <p>，避免后续生成嵌套 <p>
    html_body = re.sub(
        r'<p>\s*(【此处插入配图\s*[：:].*?】)\s*</p>',
        r'\1',
        html_body
    )

    image_results = {}
    if placeholders:
        logger.info("启动并行图片下载引擎 ({} 张)...", len(placeholders))
        with ThreadPoolExecutor(max_workers=min(3, len(placeholders))) as executor:
            futures = {executor.submit(_download_single_image, kw): kw for kw in placeholders}
            for future in as_completed(futures):
                try:
                    keyword, image_path = future.result()
                    image_results[keyword] = image_path
                except Exception as exc:
                    logger.warning("  并行下载异常: {}", exc)

    image_count = 0
    for keyword in placeholders:
        image_path = image_results.get(keyword)
        if image_path:
            image_url = publisher.upload_news_image(image_path)
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
                continue

            html_body = _replace_placeholder(html_body, keyword, "")
            logger.warning("  配图上传失败，已移除占位符: {}", keyword)
            continue

        html_body = _replace_placeholder(html_body, keyword, "")
        logger.info("  最终未匹配到合适配图，已移除占位符")

    # ==========================
    # 微信图文排版后处理 (CSS 注入)
    # ==========================
    # 1. 普通段落：首行缩进两个字符，段落之间留白
    html_body = html_body.replace(
        '<p>', 
        '<p style="text-indent: 2em; margin-bottom: 15px; line-height: 1.8; text-align: justify;">'
    )
    
    # 2. 重点句 (单独成段的加粗文本)：上下增加空格间隔 (margin: 30px)
    html_body = re.sub(
        r'<p style="[^"]*">\s*(<strong>.*?</strong>)\s*</p>',
        r'<p style="margin: 30px 0; text-indent: 2em; line-height: 1.8; text-align: justify;">\1</p>',
        html_body,
        flags=re.DOTALL
    )
    
    # 3. 金句引用块：上下增加空格间隔 (margin: 30px)
    html_body = html_body.replace(
        '<blockquote>', 
        '<blockquote style="margin: 30px 0; padding: 15px 20px; border-left: 4px solid #005A9E; background-color: #f8f9fa; color: #555; border-radius: 4px;">'
    )

    word_count = len(cleaned.replace("\n", "").replace(" ", ""))
    return html_body, {
        "word_count": word_count,
        "image_count": image_count,
        "sensitive_words": hit_words,
    }


def _print_banner():
    print("\n" + "=" * 60)
    print(f"  🚀 「{BRAND_NAME}」全自动 AI 内容工厂 v6.0")
    print("=" * 60 + "\n")


def _print_source_health():
    health = get_source_health_report()
    if not health:
        return
    print("📊 源健康状态:")
    for source, status in health.items():
        print(f"   {source}: {status['status']}")


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


def cleanup_old_assets(base_dir="assets", max_age_days=5):
    """Delete old downloaded assets and empty directories."""
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
            except OSError:
                pass

        for dirname in dirs:
            dirpath = os.path.join(root, dirname)
            try:
                if not os.listdir(dirpath):
                    os.rmdir(dirpath)
                    removed_dirs += 1
            except OSError:
                pass

    if removed_count > 0:
        logger.info(
            "🧹 自动清理：已删除 {} 个过期文件和 {} 个空目录 (>{}天)",
            removed_count,
            removed_dirs,
            max_age_days,
        )


def _fetch_selected_topics():
    raw_data = fetch_all_hotspots()
    if not raw_data:
        print("❌ 数据源扫描失败，请检查网络连接")
        _print_source_health()
        return []

    selected_topics = filter_tech_hotspots(raw_data)
    if not selected_topics:
        print("📭 今日暂无符合品牌调性的重磅 AI/科技话题，任务结束。")
        return []

    return selected_topics[:MAX_TOPICS_PER_RUN]


def _generate_article_assets(topic, publisher):
    reset_image_cache()

    article_text = generate_article(topic)
    if not article_text:
        print("❌ AI 创作失败，跳过。")
        return None

    print("\n🎨 正在执行排版优化与智能图选 (并行加速)...")
    final_html, review_data = process_article_content(article_text, publisher)
    if not final_html:
        print("❌ 内容处理后异常，跳过。")
        return None

    print("\n📸 正在为文章生成门面封面图...")
    cover_path = download_cover_image(topic)
    thumb_id = publisher.upload_image(cover_path)
    if not thumb_id and cover_path:
        print("⚠️ 封面图上传失败，尝试站内图兜底...")
        thumb_id = publisher.upload_image(cover_path)

    return final_html, review_data, thumb_id


def _build_publish_payload(topic, review_data, thumb_id):
    clean_title, title_warnings = validate_title(topic)
    for warning in title_warnings:
        print(f"  ⚠️ 标题警告: {warning}")

    print("\n📝 正在生成微信规格摘要...")
    digest = generate_digest(topic)

    _print_review_report(
        title=clean_title,
        word_count=review_data["word_count"],
        image_count=review_data["image_count"],
        sensitive_words=review_data["sensitive_words"],
        cover_ok=thumb_id is not None,
        digest=digest,
    )

    return clean_title, digest[:120] if digest else ""


def _publish_draft(publisher, title, html_content, thumb_id, digest_text):
    print("\n🚀 正在同步至微信公众号云端草稿箱...")
    result = publisher.add_draft(title, html_content, thumb_id, digest_text)
    if "media_id" not in result:
        print(f"❌ 同步草稿箱失败：{result}")
        return

    print(f"\n{'⭐' * 30}")
    print("  🎉 恭喜！发布成功")
    print(f"  📄 标题：{title}")
    print(f"  🆔 草稿：{result['media_id']}")
    print(f"{'⭐' * 30}")
    send_to_qywechat(QYWECHAT_WEBHOOK, f"【{BRAND_NAME}】《{title}》已就绪，请审核发布。")


def _process_topic(topic, publisher):
    print(f"\n{'━' * 50}")
    print(f"🎯 正在处理核心选题：{topic}")
    print(f"{'━' * 50}")

    print("🔎 正在执行草稿箱内容审计...")
    is_duplicate, old_title = publisher.is_title_duplicate(topic)
    if is_duplicate:
        print(f"  ⚠️ 命中重复！已有相似文章：「{old_title}」")
        print("  ⏭️ 已自动跳过，确保内容独特性。")
        return

    generated = _generate_article_assets(topic, publisher)
    if not generated:
        return

    final_html, review_data, thumb_id = generated
    clean_title, digest_text = _build_publish_payload(topic, review_data, thumb_id)
    _publish_draft(publisher, clean_title, final_html, thumb_id, digest_text)


def run_main():
    _print_banner()
    cleanup_old_assets("assets", max_age_days=ASSET_RETENTION_DAYS)

    try:
        selected_topics = _fetch_selected_topics()
        if not selected_topics:
            return

        publisher = WeChatPublisher(WECHAT_APP_ID, WECHAT_APP_SECRET)
        if not publisher.access_token:
            print("❌ 微信发布组件初始化失败，请检查公众号凭证配置。")
            return

        for topic in selected_topics:
            _process_topic(topic, publisher)

    except Exception as exc:
        print(f"\n💥 系统核心崩溃：{exc}")
        traceback.print_exc()


__all__ = ["run_main", "process_article_content", "cleanup_old_assets"]
