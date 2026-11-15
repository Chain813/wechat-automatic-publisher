import os
import re
import hashlib
from datetime import datetime
from loguru import logger
from concurrent.futures import ThreadPoolExecutor

from daily_knowledge.engine import generate_daily_knowledge
from core.shared.article_utils import process_article_content, _print_review_report
from core.shared.runtime import check_cancelled
from core.shared.llm import validate_title
from utils.image_handler import download_cover_image, reset_image_cache
from core.pipeline.critic import evaluate_and_repair_article, format_critic_report

def _normalize_and_cap_placeholders(text: str, max_images: int = 3) -> str:
    """
    统一占位符格式并支持通义万相 AI 生图。
    前 max_images 个转为真实配图占位符，多余的保留为图表分析卡片。
    """
    if not text:
        return text
    # 统一图表/配图描述为统一配图占位符
    text = re.sub(
        r'【\s*(?:此处绘制图表|此处绘制示意图|此处绘制架构图|此处绘制流程图|此处绘制)\s*[：:](.*?)\s*】',
        r'【此处插入配图：\1】',
        text
    )
    matches = list(re.finditer(r'【\s*此处插入配图\s*[：:](.*?)\s*】', text))
    if len(matches) > max_images:
        count = 0
        def _repl(m):
            nonlocal count
            count += 1
            if count <= max_images:
                return m.group(0)
            else:
                return f"【此处绘制图表：{m.group(1).strip()}】"
        text = re.sub(r'【\s*此处插入配图\s*[：:](.*?)\s*】', _repl, text)
    return text

def run_daily_knowledge_workflow(publisher):
    """
    全链路推送工作流，将纯文本 Markdown 推送至微信草稿箱。
    接入通义万相 (Qwen-Image) AI 生图 API，生成专属封面与正文插图。
    保持高度解耦，仅引用必要的核心公共服务组件。
    """
    check_cancelled()
    reset_image_cache()

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

    # 规范化配图占位符并限制生图并发上限（默认前 3 张接入 AI 生图 API）
    article_text = _normalize_and_cap_placeholders(article_text, max_images=3)

    # 2. 并行生成封面图与正文排版（含正文逐图 AI 生图）
    cover_keyword = f"每日小知识 {concept_name} {topic_title}"
    logger.info("🎨 正在发起通义万相 (Qwen-Image) AI 封面生成: '{}'...", cover_keyword)

    with ThreadPoolExecutor(max_workers=1) as cover_pool:
        cover_future = cover_pool.submit(download_cover_image, cover_keyword, "assets")

        print("\n🎨 正在执行排版优化与正文配图渲染 (接入通义万相生图 API)...")
        # 调用核心排版方法，use_ai_first=True, skip_photo_images=False 启用 AI 生图 API 逐图生成与上传
        final_html, review_data = process_article_content(
            article_text, publisher, use_ai_first=True, skip_photo_images=False
        )
        check_cancelled()
        
        if not final_html:
            cover_future.cancel()
            print("❌ 内容格式化与渲染异常，跳过。")
            return False

        cover_path = cover_future.result()

    # 3. 封面图上传
    thumb_id = None
    if cover_path and os.path.exists(cover_path):
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

    clean_title, _ = validate_title(topic_title)
    title_hash = hashlib.md5(clean_title.encode('utf-8')).hexdigest()

    # 4. 主编审校门禁与自愈闭环 (Critic & Quality Gate with Auto-Remediation)
    final_html, review_res = evaluate_and_repair_article(clean_title, final_html, article_type="daily_knowledge")
    print(format_critic_report(review_res))

    if not review_res["passed"]:
        err = f"未通过每日小知识质量门禁 ({review_res['score']}分): {'; '.join(review_res['critic_issues'])}"
        print(f"❌ 门禁拦截发布：「{clean_title}」— {err}")
        try:
            os.makedirs(os.path.join("data", "previews"), exist_ok=True)
            with open(os.path.join("data", "previews", f"fail_{title_hash}.html"), "w", encoding="utf-8") as f:
                f.write(final_html)
            from core.db.manager import db_manager
            from core.db.models import ArticleHistory
            session = db_manager.get_session()
            try:
                ah = ArticleHistory(
                    title=clean_title,
                    source_type="daily_knowledge",
                    publish_date=datetime.now().strftime("%Y-%m-%d"),
                    success_status=False,
                    media_id=None,
                    error_log=err,
                    quality_score=review_res["score"],
                    thumb_media_id=thumb_id,
                    status="REJECTED"
                )
                session.add(ah)
                session.commit()
            finally:
                db_manager.remove_session()
        except Exception as e:
            logger.warning("保存每日小知识门禁拦截记录异常: {}", e)
        return False

    # 5. 发布到微信草稿箱
    success, result = publisher.publish_and_notify(
        clean_title, final_html, thumb_id, digest_text
    )

    if success:
        draft_id = result["media_id"]
        print(f"\n✅ 「{clean_title}」发布成功 → {draft_id}")

        # 保存本地 HTML 预览供 WebUI 查看
        try:
            os.makedirs(os.path.join("data", "previews"), exist_ok=True)
            with open(os.path.join("data", "previews", f"{draft_id}.html"), "w", encoding="utf-8") as f:
                f.write(final_html)
        except Exception as pe:
            logger.debug("保存每日小知识预览 HTML 异常: {}", pe)

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
            safe_title = re.sub(r'[^\w\u4e00-\u9fff\-]', '_', clean_title)
            md_filepath = os.path.join("data", "markdown", f"daily_{safe_title}.md")
            with open(md_filepath, "w", encoding="utf-8") as f:
                f.write(article_text)
            logger.info("  📄 原始 Markdown 文件已自动保存至: {}", md_filepath)
        except Exception as md_err:
            logger.warning("  保存 Markdown 文件失败: {}", md_err)
            
        # 写入主数据库的 ArticleHistory 表（为了 WebUI 的 History 页面显示与查重）
        try:
            from core.db.manager import db_manager
            from core.db.models import ArticleHistory
            session = db_manager.get_session()
            try:
                ah = ArticleHistory(
                    title=clean_title,
                    source_type="daily_knowledge",
                    publish_date=datetime.now().strftime("%Y-%m-%d"),
                    success_status=True,
                    is_published=False,
                    media_id=draft_id,
                    thumb_media_id=thumb_id,
                    quality_score=review_res["score"],
                    status="DRAFT"
                )
                session.add(ah)
                session.commit()
            finally:
                db_manager.remove_session()
        except Exception as db_err:
            logger.warning("写入 SQLite 历史记录失败: {}", db_err)
            
        return True
    else:
        err = result.get("errmsg", "未知错误")
        print(f"❌ 「{topic_title}」发布失败：{err}")
        try:
            os.makedirs(os.path.join("data", "previews"), exist_ok=True)
            with open(os.path.join("data", "previews", f"fail_{title_hash}.html"), "w", encoding="utf-8") as f:
                f.write(final_html)
            from core.db.manager import db_manager
            from core.db.models import ArticleHistory
            session = db_manager.get_session()
            try:
                ah = ArticleHistory(
                    title=clean_title,
                    source_type="daily_knowledge",
                    publish_date=datetime.now().strftime("%Y-%m-%d"),
                    success_status=False,
                    media_id=None,
                    error_log=err,
                    quality_score=review_res["score"],
                    thumb_media_id=thumb_id,
                    status="FAILED"
                )
                session.add(ah)
                session.commit()
            finally:
                db_manager.remove_session()
        except Exception as db_err:
            logger.warning("写入 SQLite 失败记录异常: {}", db_err)
        return False
