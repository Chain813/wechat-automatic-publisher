import os
import time
from datetime import datetime
from loguru import logger

from config import BRAND_NAME, SD_ENABLED, GITHUB_FIXED_COVER
from core.github.collector import fetch_one_worthy_project, generate_code_screenshot, get_repo_code_snippet, save_github_history, take_github_readme_screenshot, take_live_ui_screenshot
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


def _ensure_deep_images(projects, publisher):
    """
    确保单项目有 3+ 张深度配图。
    1. README 概览截图 (优先使用中文文档)
    2. 在线 Demo UI 截图
    3. SD 艺术配图
    4. README 中提取的其他大图 / 代码截图
    """
    for p in projects:
        urls = []
        
        # 1. README 概览截图
        print(f"  📸 正在为 [{p['repo']}] 截取 README 概览...")
        readme_path = take_github_readme_screenshot(p['repo'], p.get('readme_file_path'))
        if readme_path and os.path.exists(readme_path):
            img_url = publisher.upload_news_image(readme_path)
            if img_url:
                urls.append(img_url)
                print(f"  ✅ README 截图已上传: {p['repo']}")

        # 2. 在线 Demo UI 截图
        homepage = p.get('homepage')
        if homepage:
            print(f"  🖥️ 尝试获取在线 Demo/主页 截图: {homepage}...")
            ui_path = take_live_ui_screenshot(p['repo'], homepage)
            if ui_path and os.path.exists(ui_path):
                img_url = publisher.upload_news_image(ui_path)
                if img_url:
                    urls.append(img_url)
                    print(f"  ✅ 在线 UI 截图已上传")
        
        # 3. SD 艺术配图
        if SD_ENABLED:
            print(f"  🎨 正在为 [{p['repo']}] 生成 SD 艺术配图...")
            sd_path = download_project_image_for_github(
                repo_name=p['repo'],
                description=p.get('desc', ''),
                lang=p.get('lang', 'Unknown'),
                topics=p.get('topics', []),
            )
            if sd_path:
                image_url = publisher.upload_news_image(sd_path)
                if image_url:
                    urls.append(image_url)
                    print(f"  ✅ SD 配图已上传")

        # 4. Fallback: README 原图 / 其他说明文档中的大图
        if len(urls) < 3 and p.get('image_url') and p.get('image_url') not in urls:
            urls.append(p.get('image_url'))
            
        if len(urls) < 3:
            for other_img in p.get('other_images', []):
                if len(urls) >= 3:
                    break
                if other_img not in urls:
                    urls.append(other_img)
            
        # 5. Final Fallback: Code 代码截图
        if len(urls) < 3:
            code_text, file_name = get_repo_code_snippet(p['repo'])
            if code_text:
                code_img = generate_code_screenshot(code_text, p.get('lang', 'python'))
                if code_img and os.path.exists(code_img):
                    img_url = publisher.upload_news_image(code_img)
                    if img_url:
                        urls.append(img_url)
                        
        p['image_urls'] = urls
        if urls:
            p['image_url'] = urls[0]


def run_github_workflow(publisher):
    """处理 GitHub 单项目深度推荐抓取和发布流程。"""
    projects = fetch_one_worthy_project()
    check_cancelled()
    if not projects:
        print("📭 今日暂无获取到 GitHub 热门项目。")
        return

    print(f"\n🚀 准备深度解析 GitHub 热门项目: {projects[0]['repo']}")

    reset_image_cache()

    # 确保项目有深度配图
    print("\n🖼️  正在为项目生成深度配图（README/UI/SD）...")
    _ensure_deep_images(projects, publisher)

    article_text, dynamic_title = generate_github_article(projects)
    check_cancelled()
    if not article_text or not dynamic_title:
        print("❌ AI 创作失败，跳过。")
        return

    # 后处理：将旧的占位符统一替换掉
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

    topic = dynamic_title

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

    success = _publish_draft_github(publisher, clean_title, final_html, thumb_id, digest)
    
    # 发布成功后，将项目记入历史，避免下次重复抓取
    if success:
        repo_names = [p['repo'] for p in projects]
        save_github_history(repo_names)
        
        try:
            import json
            record_file = "github_publish_records.json"
            records = []
            if os.path.exists(record_file):
                with open(record_file, "r", encoding="utf-8") as f:
                    records = json.load(f)
            records.append({
                "title": clean_title,
                "repos": repo_names
            })
            with open(record_file, "w", encoding="utf-8") as f:
                json.dump(records[-50:], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("保存 GitHub 发布记录失败: {}", e)
            
        print(f"✅ 已将 {len(repo_names)} 个项目加入历史过滤名单。")
