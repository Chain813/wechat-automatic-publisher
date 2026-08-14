import os
import re
from datetime import datetime
from loguru import logger
from concurrent.futures import ThreadPoolExecutor

from daily_knowledge.engine import generate_daily_knowledge
from core.shared.article_utils import process_article_content, _print_review_report
from core.shared.runtime import check_cancelled

def run_daily_knowledge_workflow(publisher):
    """
    全链路推送工作流，将纯文本 Markdown 推送至微信草稿箱。
    保持高度解耦，仅引用必要的核心公共服务组件。
    """
    check_cancelled()
    
    pass # 延迟到标题生成后再绘制封面图

    print("\n💡 正在撰写 每日小知识 文章...")

    # 1. 生成高质量的 Markdown 文章
    domain_name = "人工智能底层算法"
    article_text, concept_name = generate_daily_knowledge(domain=domain_name)
    
    if not article_text:
        print("❌ 每日小知识文章生成失败，跳过。")
        return False
        
    # 为了便于显示和后续存储，尝试从生成的 Markdown 中提取一级或二级标题作为文章标题
    # 如果没有找到，则使用默认标题
    title_match = re.search(r'#+\s*(.+)', article_text)
    topic_title = title_match.group(1).strip() if title_match else f"每日小知识：{domain_name}"
    
    # 微信限制标题长度，做一个安全截断
    if len(topic_title) > 60:
        topic_title = topic_title[:57] + "..."

    # 优先寻找静态默认封面图 assets/default_daily_cover.png
    cover_path = os.path.abspath(os.path.join("assets", "default_daily_cover.png"))
    if os.path.exists(cover_path):
        logger.info(f"✅ 找到默认动态封面图: {cover_path}")
    else:
        # 如果静态默认封面图不存在，动态生成占位封面图
        import time
        cover_filename = f"daily_cover_{int(time.time())}.png"
        cover_path = os.path.abspath(os.path.join("assets", cover_filename))
        logger.info(f"正在自动绘制动态封面图占位符: {cover_path}")
        try:
            os.makedirs(os.path.dirname(cover_path), exist_ok=True)
            from PIL import Image as PILImage, ImageDraw, ImageFont
            img = PILImage.new('RGB', (900, 383), color=(30, 41, 59))
            draw = ImageDraw.Draw(img)
            draw.rectangle([(50, 50), (850, 333)], outline=(56, 189, 248), width=4)
            try:
                # 尝试加载中文字体，Windows 环境常用 msyh.ttc
                font = ImageFont.truetype("msyh.ttc", 40)
            except Exception:
                font = ImageFont.load_default()
            
            display_text = "封面占位\n\n(请后续在微信公众平台手动替换)\n\n" + topic_title[:15] + ("..." if len(topic_title)>15 else "")
            draw.text((450, 191), display_text, fill=(255,255,255), font=font, anchor="mm", align="center")
            img.save(cover_path, 'PNG')
            print("✅ 动态封面图占位符生成成功。")
        except Exception as e:
            logger.warning(f"自动绘制封面图失败: {e}")
            cover_path = None

    # 兼容性处理：将大模型偶尔生成的【此处插入配图】统一替换为【此处绘制图表】
    # 因为 skip_photo_images=True 会将前者强制删除，改为后者则会渲染为美观的占位卡片供人工替换
    article_text = re.sub(r'【\s*此处插入配图\s*[：:](.*?)\s*】', r'【此处绘制图表：\1】', article_text)

    print("\n🎨 正在执行排版优化与图表渲染...")
    # 2. 调用主项目公共排版方法，处理图表占位符和 HTML 转换
    final_html, review_data = process_article_content(
        article_text, publisher, use_ai_first=False, skip_photo_images=True
    )
    check_cancelled()
    
    if not final_html:
        print("❌ 内容格式化与渲染异常，跳过。")
        return False

    # 3. 封面图上传
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
    else:
        print("❌ 严重警告：封面图不存在且生成失败，微信接口将拒绝发布草稿！")
        return False
        
    # 构建简单的摘要
    digest_text = f"今天的【{domain_name}】小知识，为你讲透底层原理。"

    # 打印排版与安全审查报告
    _print_review_report(
        title=topic_title,
        word_count=review_data["word_count"],
        image_count=review_data["image_count"],
        sensitive_words=review_data["sensitive_words"],
        cover_ok=thumb_id is not None,
        digest=digest_text,
        ignore_word_count=True,
    )

    # 4. 发布到微信草稿箱
    success, result = publisher.publish_and_notify(
        topic_title, final_html, thumb_id, digest_text
    )

    if success:
        draft_id = result["media_id"]
        print(f"\n✅ 「{topic_title}」发布成功 → {draft_id}")

        # 发布成功后，记录该概念到本地数据库防止后续重复
        try:
            from daily_knowledge.database import record_concept
            record_concept(concept_name, domain_name)
            logger.info(f"✅ 已将概念 '{concept_name}' 正式写入防重数据库")
        except Exception as e:
            logger.warning(f"  概念入库失败: {e}")

        # 将生成的原始 MD 备份到共享的 markdown 文件夹中
        try:
            os.makedirs(os.path.join("data", "markdown"), exist_ok=True)
            safe_title = re.sub(r'[^\w\u4e00-\u9fff\-]', '_', topic_title)
            md_filepath = os.path.join("data", "markdown", f"daily_{safe_title}.md")
            with open(md_filepath, "w", encoding="utf-8") as f:
                f.write(article_text)
        except Exception as md_err:
            logger.warning("  保存 Markdown 文件失败: {}", md_err)
            
        # 5. 写入主数据库的 ArticleHistory 表（为了 WebUI 的 History 页面显示）
        try:
            from core.db.manager import db_manager
            from core.db.models import ArticleHistory
            session = db_manager.get_session()
            ah = ArticleHistory(
                title=topic_title,
                source_type="daily_knowledge",
                publish_date=datetime.now().strftime("%Y-%m-%d"),
                success_status=True,
                is_published=False,
                media_id=draft_id
            )
            session.add(ah)
            session.commit()
            db_manager.remove_session()
        except Exception as db_err:
            logger.warning("写入 SQLite 历史记录失败: {}", db_err)
            
        return True
    else:
        err = result.get("errmsg", "未知错误")
        print(f"❌ 「{topic_title}」发布失败：{err}")
        return False
