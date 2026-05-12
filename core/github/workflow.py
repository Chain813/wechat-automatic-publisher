import os
import time
from datetime import datetime
from loguru import logger

from config import BRAND_NAME, SD_ENABLED, GITHUB_FIXED_COVER
from core.github.collector import fetch_github_trending, generate_code_screenshot, get_repo_code_snippet
from core.github.processor import generate_github_article
from core.shared.article_utils import process_article_content, _print_review_report
from core.shared.llm import validate_title
from utils.image_handler import download_cover_image, download_project_image_for_github, reset_image_cache
from core.shared.runtime import check_cancelled


def _publish_draft_github(publisher, title, html_content, thumb_id, digest_text):
    print("\n🚀 正在同步至微信公众号云端草稿箱...")
    result = publisher.add_draft(title, html_content, thumb_id, digest_text)
    if "media_id" not in result:
        print(f"❌ 同步草稿箱失败：{result}")
        return False

    draft_id = result['media_id']
    print(f"\n{'⭐' * 30}")
    print("  🎉 恭喜！发布成功")
    print(f"  📄 标题：{title}")
    print(f"  🆔 草稿：{draft_id}")
    print(f"{'⭐' * 30}")

    try:
        from config import QYWECHAT_WEBHOOK
        from core.shared.publisher import send_to_qywechat
        send_to_qywechat(QYWECHAT_WEBHOOK, f"【{BRAND_NAME}】《{title}》已就绪，请审核发布。")
    except Exception as e:
        logger.debug("  企微通知发送失败（非关键）: {}", e)

    return True


def _ensure_project_images(projects, publisher):
    """
    确保每个项目都有配图。优先级：
    1. README 中的图片（已在 collector 中处理）
    2. SD 生成的艺术配图（DeepSeek 提示词驱动）
    3. 目录树截图（rich 渲染）
    4. 代码截图（carbon API）
    """
    for p in projects:
        if p.get('image_url'):
            continue  # 已有 README 图片，最优选择

        # ---- 优先尝试 SD 艺术配图 ----
        if SD_ENABLED:
            print(f"  🎨 正在为 [{p['repo']}] 生成 SD 艺术配图 (DeepSeek 提示词)...")
            sd_path = download_project_image_for_github(
                repo_name=p['repo'],
                description=p.get('desc', ''),
                lang=p.get('lang', 'Unknown'),
                topics=p.get('topics', []),
            )
            if sd_path:
                image_url = publisher.upload_news_image(sd_path)
                if image_url:
                    p['image_url'] = image_url
                    print(f"  ✅ SD 配图已上传: {p['repo']}")
                    continue
                else:
                    print(f"  ⚠️ SD 配图上传失败，尝试备选方案...")

        # ---- Fallback: 目录树截图 ----
        local_path = p.get('tree_image_path')
        if local_path and os.path.exists(local_path):
            image_url = publisher.upload_news_image(local_path)
            if image_url:
                p['image_url'] = image_url
                continue

        # ---- Fallback: carbon 代码截图 ----
        code_text, file_name = get_repo_code_snippet(p['repo'])
        if code_text:
            code_img = generate_code_screenshot(code_text, p.get('lang', 'python'))
            if code_img and os.path.exists(code_img):
                image_url = publisher.upload_news_image(code_img)
                if image_url:
                    p['image_url'] = image_url
                    continue


def run_github_workflow(publisher):
    """处理 GitHub Trending 抓取和发布流程。"""
    projects = fetch_github_trending(limit=5)
    check_cancelled()
    if not projects:
        print("📭 今日暂无获取到 GitHub 热门项目。")
        return

    print(f"\n🚀 准备发布 GitHub 热门项目合集，共包含 {len(projects)} 个项目...")

    reset_image_cache()

    # 确保每个项目都有配图
    print("\n🖼️  正在为项目生成配图（目录树/架构图/代码截图）...")
    _ensure_project_images(projects, publisher)

    article_text = generate_github_article(projects)
    check_cancelled()
    if not article_text:
        print("❌ AI 创作失败，跳过。")
        return

    # 后处理：将目录树图片的占位符转为 GITHUB配图 格式
    for p in projects:
        if p.get('tree_image_path') and p.get('image_url'):
            keyword = f"{p['repo'].split('/')[-1]} {p['lang']} project architecture"
            placeholder = f"【此处插入配图：{keyword}】"
            if placeholder in article_text:
                article_text = article_text.replace(
                    placeholder,
                    f"【GITHUB配图：{p['image_url']}】"
                )

    print("\n🎨 正在执行排版优化与配图处理...")
    final_html, review_data = process_article_content(article_text, publisher)

    topic = f"今日 GitHub 最火开源项目盘点 ({datetime.now().strftime('%m月%d日')})"

    # 封面处理：直接使用固定的 GitHub 专题封面
    thumb_id = publisher.upload_image(GITHUB_FIXED_COVER)

    clean_title, title_warnings = validate_title(topic)
    for warning in title_warnings:
        print(f"  ⚠️ 标题警告: {warning}")

    digest = "盘点今日 GitHub 上的火爆开源项目，带你发掘最好玩、最前沿的技术工具。"

    _print_review_report(
        title=clean_title,
        word_count=review_data["word_count"],
        image_count=review_data["image_count"],
        sensitive_words=review_data["sensitive_words"],
        cover_ok=thumb_id is not None,
        digest=digest,
    )

    _publish_draft_github(publisher, clean_title, final_html, thumb_id, digest)
