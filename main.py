"""
============================================================
  全自动微信公众号推文系统 v4.0 (智界洞察社 终极版)
  集成：全网聚合 + AI深度科普 + 智能图选 + 草稿查重
============================================================
"""
import re
import sys
import logging
import markdown
import traceback

from news_collector import fetch_all_hotspots, get_source_health_report
from llm_processor import (filter_tech_hotspots, generate_article, simplify_keyword,
                           validate_title, filter_sensitive, generate_digest)
from image_handler import download_image, download_cover_image, reset_image_cache
from wechat_api import WeChatPublisher, send_to_qywechat
from config import (WECHAT_APP_ID, WECHAT_APP_SECRET, QYWECHAT_WEBHOOK,
                    BRAND_NAME, WECHAT_TITLE_MAX_LEN)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def process_article_content(article_text, publisher):
    """处理文章内容：转换 HTML 并进行智能配图替换"""
    if not article_text:
        return "", {"word_count": 0, "image_count": 0, "sensitive_words": []}

    # 1. 深度清洗 AI 标记
    cleaned = re.sub(r'```\s*markdown\s*\n?', '', article_text)
    cleaned = re.sub(r'```\s*\n?', '', cleaned)
    cleaned = cleaned.strip()

    # 2. 敏感词过滤
    cleaned, hit_words = filter_sensitive(cleaned)
    if hit_words:
        logger.warning("  检测到敏感词: %s", hit_words)

    # 3. 提取配图占位符关键词
    placeholders = re.findall(r'【此处插入配图[：:](.*?)】', cleaned)

    # 4. Markdown 转 HTML (启用 nl2br 确保空行生效)
    html_body = markdown.markdown(cleaned, extensions=['extra', 'nl2br', 'sane_lists'])

    # 5. 逐一进行智能搜图与替换
    image_count = 0
    for kw in placeholders:
        kw = kw.strip()
        if not kw: continue

        logger.info("正在为段落关键词 '%s' 搜寻最佳配图...", kw)
        img_path = download_image(kw)

        if not img_path:
            sk = simplify_keyword(kw)
            img_path = download_image(sk)

        placeholder_text = f"【此处插入配图：{kw}】"
        placeholder_text_en = f"【此处插入配图:{kw}】"

        if img_path:
            img_url = publisher.upload_news_image(img_path)
            if img_url:
                img_html = (
                    '<p style="text-align:center;margin: 20px 0;">'
                    f'<img src="{img_url}" style="width:100%;max-width:600px;border-radius:12px;box-shadow: 0 4px 12px rgba(0,0,0,0.1);">'
                    '</p>'
                )
                html_body = html_body.replace(placeholder_text, img_html)
                html_body = html_body.replace(placeholder_text_en, img_html)
                image_count += 1
                logger.info("  配图已成功嵌入文章")
            else:
                html_body = html_body.replace(placeholder_text, "")
                html_body = html_body.replace(placeholder_text_en, "")
        else:
            html_body = html_body.replace(placeholder_text, "")
            html_body = html_body.replace(placeholder_text_en, "")
            logger.info("  最终未匹配到合适配图，已移除占位符")

    word_count = len(cleaned.replace('\n', '').replace(' ', ''))
    return html_body, {"word_count": word_count, "image_count": image_count, "sensitive_words": hit_words}


def _print_review_report(title, word_count, image_count, sensitive_words, cover_ok, digest):
    """发布前审核摘要"""
    print(f"\n{'─' * 50}")
    print(f"  📋 发布前审核报告")
    print(f"{'─' * 50}")

    title_ok = len(title) <= WECHAT_TITLE_MAX_LEN
    title_icon = "✅" if title_ok else "⚠️"
    print(f"  标题：{title} ({len(title)} 字 {title_icon})")

    wc_icon = "✅" if 2000 <= word_count <= 4000 else "⚠️"
    print(f"  字数：{word_count:,} 字 ({wc_icon})")

    img_icon = "✅" if image_count >= 3 else "⚠️"
    print(f"  配图：{image_count} 张 ({img_icon})")

    sw_icon = "❌" if sensitive_words else "✅"
    sw_msg = f"命中 {len(sensitive_words)} 词: {sensitive_words}" if sensitive_words else "无"
    print(f"  敏感词：{sw_msg} ({sw_icon})")

    cover_icon = "✅" if cover_ok else "⚠️"
    print(f"  封面图：{'已上传' if cover_ok else '未上传'} ({cover_icon})")

    if digest:
        print(f"  摘要：{digest[:80]}{'...' if len(digest) > 80 else ''}")

    all_ok = title_ok and (2000 <= word_count <= 4000) and image_count >= 3 and not sensitive_words and cover_ok
    print(f"{'─' * 50}")
    if all_ok:
        print(f"  🎉 审核通过，可以发布！")
    else:
        print(f"  ⚠️ 存在警告项，请手动检查后再发布。")
    print(f"{'─' * 50}\n")
    return all_ok


def run_main():
    print("\n" + "=" * 60)
    print(f"  🚀 「{BRAND_NAME}」全自动 AI 内容工厂 v5.0")
    print("=" * 60 + "\n")

    try:
        # 1. 扫描全网热点
        raw_data = fetch_all_hotspots()
        if not raw_data:
            print("❌ 数据源扫描失败，请检查网络连接")
            # 打印源健康状态
            health = get_source_health_report()
            if health:
                print("📊 源健康状态:")
                for src, status in health.items():
                    print(f"   {src}: {status['status']}")
            return

        # 2. AI 深度筛选选题
        selected_topics = filter_tech_hotspots(raw_data)
        if not selected_topics:
            print("📭 今日暂无符合品牌调性的重磅 AI/科技话题，任务结束。")
            return

        # 初始化微信组件
        pub = WeChatPublisher(WECHAT_APP_ID, WECHAT_APP_SECRET)

        # 3. 逐一处理选定的话题
        for topic in selected_topics[:1]:  # 默认每次处理 1 条，确保质量
            print(f"\n{'━' * 50}")
            print(f"🎯 正在处理核心选题：{topic}")
            print(f"{'━' * 50}")

            # 3.0 草稿箱查重
            print("🔎 正在执行草稿箱内容审计...")
            is_dup, old_title = pub.is_title_duplicate(topic)
            if is_dup:
                print(f"  ⚠️ 命中重复！已有相似文章：「{old_title}」")
                print(f"  ⏭️ 已自动跳过，确保内容独特性。")
                continue

            # 3.1 AI 深度长文创作
            reset_image_cache()
            article_text = generate_article(topic)
            if not article_text:
                print("❌ AI 创作失败，跳过。")
                continue

            # 3.2 内容排版与多图配准
            print("\n🎨 正在执行排版优化与智能图选...")
            final_html, review_data = process_article_content(article_text, pub)

            if not final_html:
                print("❌ 内容处理后异常，跳过。")
                continue

            # 3.3 封面图智能选择
            print("\n📸 正在为文章生成门面封面图...")
            cover_path = download_cover_image(topic)
            thumb_id = pub.upload_image(cover_path)

            if not thumb_id:
                print("⚠️ 封面图上传失败，尝试站内图兜底...")
                if cover_path:
                    thumb_id = pub.upload_image(cover_path)

            # 3.4 标题校验
            clean_title, title_warnings = validate_title(topic)
            if title_warnings:
                for w in title_warnings:
                    print(f"  ⚠️ 标题警告: {w}")

            # 3.5 摘要生成
            print("\n📝 正在生成微信规格摘要...")
            digest = generate_digest(topic)

            # 3.6 发布前审核报告
            _print_review_report(
                title=clean_title,
                word_count=review_data["word_count"],
                image_count=review_data["image_count"],
                sensitive_words=review_data["sensitive_words"],
                cover_ok=thumb_id is not None,
                digest=digest
            )

            # 3.7 发布至草稿箱
            print("\n🚀 正在同步至微信公众号云端草稿箱...")
            digest_text = digest[:120] if digest else ""
            res = pub.add_draft(clean_title, final_html, thumb_id, digest_text)

            if "media_id" in res:
                print(f"\n{'⭐' * 30}")
                print(f"  🎉 恭喜！发布成功")
                print(f"  📄 标题：{clean_title}")
                print(f"  🆔 草稿：{res['media_id']}")
                print(f"{'⭐' * 30}")
                send_to_qywechat(QYWECHAT_WEBHOOK, f"【{BRAND_NAME}】《{clean_title}》已就绪，请审核发布。")
            else:
                print(f"❌ 同步草稿箱失败：{res}")

    except Exception as e:
        print(f"\n💥 系统核心崩溃：{e}")
        traceback.print_exc()


if __name__ == "__main__":
    run_main()
