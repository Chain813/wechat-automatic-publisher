import os
import re
import hashlib
from datetime import datetime
from loguru import logger

from daily_knowledge.engine import generate_daily_knowledge
from core.shared.article_utils import process_article_content, _print_review_report
from core.pipeline.records import publish_article
from core.pipeline.nodes import run_counted
from core.shared.runtime import WorkflowCancelled, check_cancelled
from core.shared.llm import validate_title
from utils.image_handler import reset_image_cache
from core.pipeline.critic import evaluate_and_repair_article, format_critic_report

def _normalize_and_cap_placeholders(text: str, max_images: int = 3) -> str:
    """
    统一新旧占位符格式。
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

def _run(publisher, counts):
    """
    全链路推送工作流，将纯文本 Markdown 推送至微信草稿箱。
    上传带出处的资料照片和封面。
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
        counts.record(False, "Daily knowledge generation or review failed")
        return
        
    # 为了便于显示和后续存储，尝试从生成的 Markdown 中提取一级或二级标题作为文章标题
    # 如果没有找到，则使用默认标题
    title_match = re.search(r'#+\s*(.+)', article_text)
    topic_title = title_match.group(1).strip() if title_match else f"每日小知识：{domain_name}"
    
    # 微信限制标题长度，做一个安全截断
    if len(topic_title) > 60:
        topic_title = topic_title[:57] + "..."

    article_text = _normalize_and_cap_placeholders(article_text, max_images=3)
    final_html, review_data = process_article_content(article_text, publisher, cover_title=topic_title)
    check_cancelled()
    thumb_id = review_data.get("thumb_id")
    if not final_html or not thumb_id:
        logger.warning("每日小知识缺少正文或封面，跳过草稿上传")
        counts.record(False, "Daily knowledge generation or review failed")
        return
        
    # 构建简单的摘要
    digest_text = f"{topic_title}｜本期概念：{concept_name}"[:120]

    # 打印排版与安全审查报告
    all_ok = _print_review_report(
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

    if not review_res["passed"] or not all_ok:
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
        except WorkflowCancelled:
            raise
        except Exception as e:
            logger.warning("保存每日小知识门禁拦截记录异常: {}", e)
        counts.record(False, "Daily knowledge generation or review failed")
        return

    # 5. 发布到微信草稿箱
    check_cancelled()
    safe_title = re.sub(r'[^\w-]', '_', clean_title)
    counts.record(*publish_article(publisher, "daily_knowledge", clean_title, final_html, thumb_id, digest_text, review_res["score"],
                                 concept=concept_name, domain=domain_name,
                                 markdown=article_text, markdown_name=f"daily_{safe_title}.md"))


def run_daily_knowledge_workflow(publisher):
    return run_counted("daily_knowledge", lambda counts: _run(publisher, counts))
