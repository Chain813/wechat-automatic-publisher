import os
import time
from datetime import datetime
from loguru import logger

from config import BRAND_NAME
from core.github.collector import fetch_github_trending
from core.github.processor import generate_github_article
from core.shared.article_utils import process_article_content, _print_review_report
from core.shared.llm import validate_title
from utils.image_handler import download_cover_image, reset_image_cache

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
    
    # Try to import and send to qywechat
    try:
        from config import QYWECHAT_WEBHOOK
        from core.shared.publisher import send_to_qywechat
        send_to_qywechat(QYWECHAT_WEBHOOK, f"【{BRAND_NAME}】《{title}》已就绪，请审核发布。")
    except Exception as e:
        logger.debug("  企微通知发送失败（非关键）: {}", e)
        
    return True

def run_github_workflow(publisher):
    """处理 GitHub Trending 抓取和发布流程。"""
    projects = fetch_github_trending(limit=5)
    if not projects:
        print("📭 今日暂无获取到 GitHub 热门项目。")
        return
        
    print(f"\n🚀 准备发布 GitHub 热门项目合集，共包含 {len(projects)} 个项目...")
    
    reset_image_cache()
    article_text = generate_github_article(projects)
    if not article_text:
        print("❌ AI 创作失败，跳过。")
        return
        
    print("\n🎨 正在执行排版优化与配图处理...")
    final_html, review_data = process_article_content(article_text, publisher)
    
    topic = f"今日 GitHub 最火开源项目盘点 ({datetime.now().strftime('%m月%d日')})"
    
    print("\n📸 正在为文章生成门面封面图...")
    cover_path = None
    for p in projects:
        if p.get('image_url'):
            try:
                import requests
                res = requests.get(p['image_url'], timeout=10)
                if res.status_code == 200:
                    tmp_path = os.path.join("assets", f"cover_{int(time.time())}.jpg")
                    with open(tmp_path, 'wb') as f:
                        f.write(res.content)
                    cover_path = tmp_path
                    break
            except Exception as e:
                logger.debug("  GitHub 封面下载失败: {}", e)
                
    if not cover_path:
        cover_path = download_cover_image("GitHub 开源趋势")
        
    thumb_id = None
    if cover_path:
        thumb_id = publisher.upload_image(cover_path)
        if not thumb_id:
            print("⚠️ 封面上传失败，尝试压缩后重试...")
            try:
                from PIL import Image as PILImage
                with PILImage.open(cover_path) as img:
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    img.save(cover_path, 'JPEG', quality=60, optimize=True)
                thumb_id = publisher.upload_image(cover_path)
            except Exception as e:
                logger.warning("  封面压缩重试失败: {}", e)

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
