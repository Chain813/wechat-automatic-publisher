"""
============================================================
  体系连载发布流水线 v1.0
  技能树选题 → 教育风文章生成 → 图表渲染 → 微信草稿箱
============================================================
"""
import os
import hashlib
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from loguru import logger

from config import MAX_AIKEPU_PER_RUN
from core.aikepu.skill_tree import (
    select_next_topic, mark_published, get_skill_tree_stats,
    reset_tree_cache, release_reserved
)
from core.aikepu.processor import generate_aikepu_article, generate_digest
from core.shared.article_utils import process_article_content, _print_review_report
from core.shared.llm import validate_title
from core.shared.runtime import check_cancelled


def _generate_article_assets(topic_info, publisher):
    """
    为单个选题生成完整文章资产：文章 + 封面 + HTML。
    """
    check_cancelled()

    import os
    
    # 强制固定使用用户指定的 体系连载封面图
    cover_path = os.path.abspath(os.path.join("assets", "default_aikepu_cover.png"))
    if not os.path.exists(cover_path):
        print(f"⚠️ 找不到固定封面图: {cover_path}")
        cover_path = None

    topic_title = topic_info.get("title", "体系连载")
    print(f"\n🎨 正在撰写 体系连载文章: {topic_title}")

    article_text = generate_aikepu_article(topic_info)
    if not article_text:
        print("❌ AI科普文章生成失败，跳过。")
        return None


    print("\n🎨 正在执行排版优化与图表渲染...")
    final_html, review_data = process_article_content(
        article_text, publisher, use_ai_first=False, skip_photo_images=True
    )
    check_cancelled()
    if not final_html:
        print("❌ 内容处理后异常，跳过。")
        return None

    # 封面上传
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
        print("⚠️ 默认封面图不存在，将使用无封面模式发布。")

    return final_html, review_data, thumb_id, article_text


def _publish_single_topic(topic_info, publisher):
    """发布单篇 AI科普文章"""
    try:
        check_cancelled()
        topic_title = topic_info["title"]
        node_id = topic_info["node_id"]

        print(f"\n{'━' * 50}")
        print(f"🎓 [AI科普] 正在处理：{topic_title}")
        print(f"{'━' * 50}")

        # 并行：文章资产 + 摘要
        with ThreadPoolExecutor(max_workers=2) as pool:
            future_assets = pool.submit(_generate_article_assets, topic_info, publisher)
            future_digest = pool.submit(generate_digest, topic_title)

            generated = future_assets.result()
            if not generated:
                release_reserved(node_id)  # 边界条件防护：生成失败也要释放锁
                return topic_title, False, "文章生成失败", node_id

            final_html, review_data, thumb_id, article_text = generated

            clean_title, title_warnings = validate_title(topic_title)
            for warning in title_warnings:
                print(f"  ⚠️ 标题警告: {warning}")

            digest = future_digest.result()
            digest_text = digest[:120] if digest else ""

        all_ok = _print_review_report(
            title=clean_title,
            word_count=review_data["word_count"],
            image_count=review_data["image_count"],
            sensitive_words=review_data["sensitive_words"],
            cover_ok=thumb_id is not None,
            digest=digest_text,
            is_long_article=True,
        )

        # 主编审校门禁 (Critic & Quality Gate)
        from core.pipeline.critic import evaluate_article_quality, format_critic_report
        review_res = evaluate_article_quality(clean_title, final_html)
        print(format_critic_report(review_res))

        if not review_res["passed"] or not all_ok:
            err = f"未通过主编质量门禁 ({review_res['score']}分): {'; '.join(review_res['critic_issues'])}"
            print(f"❌ 门禁拦截发布：「{clean_title}」— {err}")
            try:
                title_hash = hashlib.md5(clean_title.encode('utf-8')).hexdigest()
                os.makedirs(os.path.join("data", "previews"), exist_ok=True)
                with open(os.path.join("data", "previews", f"fail_{title_hash}.html"), "w", encoding="utf-8") as f:
                    f.write(final_html)

                from core.db.manager import db_manager
                from core.db.models import ArticleHistory
                session = db_manager.get_session()
                try:
                    ah = ArticleHistory(
                        title=clean_title,
                        source_type="aikepu",
                        publish_date=datetime.now().strftime("%Y-%m-%d"),
                        success_status=False,
                        media_id=None,
                        error_log=err,
                        quality_score=review_res["score"],
                        source_url=f"aikepu://node/{node_id}",
                        thumb_media_id=thumb_id,
                        status="REJECTED"
                    )
                    session.add(ah)
                    session.commit()
                finally:
                    db_manager.remove_session()
            except Exception as e:
                logger.warning("保存 AI科普 门禁拦截记录异常: {}", e)

            release_reserved(node_id)
            return topic_title, False, err, node_id

        # 发布到微信草稿箱
        success, result = publisher.publish_and_notify(
            clean_title, final_html, thumb_id, digest_text
        )

        if success:
            draft_id = result["media_id"]
            print(f"\n✅ 「{clean_title}」发布成功 → {draft_id}")

            # 保存本地 HTML 预览供 WebUI 人机工作台查看
            try:
                os.makedirs(os.path.join("data", "previews"), exist_ok=True)
                with open(os.path.join("data", "previews", f"{draft_id}.html"), "w", encoding="utf-8") as f:
                    f.write(final_html)
            except Exception as pe:
                logger.debug("保存 AI科普 预览 HTML 异常: {}", pe)

            # 仅在发布成功后保存原始 Markdown 文档到本地
            try:
                import re as _re
                os.makedirs(os.path.join("data", "markdown"), exist_ok=True)
                safe_title = _re.sub(r'[^\w\u4e00-\u9fff\-]', '_', topic_info.get("title", "article"))
                md_filename = f"{topic_info.get('node_id', 'topic')}_{safe_title}.md"
                md_filepath = os.path.join("data", "markdown", md_filename)
                with open(md_filepath, "w", encoding="utf-8") as f:
                    f.write(article_text)
                logger.info("  📄 原始 Markdown 文件已自动保存至: {}", md_filepath)
            except Exception as md_err:
                logger.warning("  保存 Markdown 文件失败: {}", md_err)
            
            # 写入 SQLite 数据库以供 WebUI 历史记录和查重使用
            try:
                from core.db.manager import db_manager
                from core.db.models import ArticleHistory
                session = db_manager.get_session()
                try:
                    ah = ArticleHistory(
                        title=clean_title,
                        source_type="aikepu",
                        publish_date=datetime.now().strftime("%Y-%m-%d"),
                        success_status=True,
                        is_published=False,
                        media_id=draft_id,
                        quality_score=review_res["score"],
                        source_url=f"aikepu://node/{node_id}",
                        thumb_media_id=thumb_id,
                        status="DRAFT"
                    )
                    session.add(ah)
                    session.commit()
                finally:
                    db_manager.remove_session()
            except Exception as db_err:
                logger.warning("写入 SQLite 历史失败: {}", db_err)

            mark_published(node_id, clean_title, draft_id=draft_id, status="draft")
            return topic_title, True, None, node_id
        else:
            err = result.get("errmsg", "未知错误") if isinstance(result, dict) else str(result)
            print(f"❌ 「{clean_title}」发布失败：{err}")
            try:
                title_hash = hashlib.md5(clean_title.encode('utf-8')).hexdigest()
                os.makedirs(os.path.join("data", "previews"), exist_ok=True)
                with open(os.path.join("data", "previews", f"fail_{title_hash}.html"), "w", encoding="utf-8") as f:
                    f.write(final_html)

                from core.db.manager import db_manager
                from core.db.models import ArticleHistory
                session = db_manager.get_session()
                try:
                    ah = ArticleHistory(
                        title=clean_title,
                        source_type="aikepu",
                        publish_date=datetime.now().strftime("%Y-%m-%d"),
                        success_status=False,
                        media_id=None,
                        error_log=err,
                        quality_score=review_res["score"],
                        source_url=f"aikepu://node/{node_id}",
                        thumb_media_id=thumb_id,
                        status="FAILED"
                    )
                    session.add(ah)
                    session.commit()
                finally:
                    db_manager.remove_session()
            except Exception as e:
                logger.warning("保存 AI科普 失败记录异常: {}", e)

            release_reserved(node_id)
            return topic_title, False, err, node_id

    except Exception as exc:
        logger.warning("  AI科普发布异常: {}", exc)
        release_reserved(topic_info.get("node_id", ""))  # 异常时释放节点
        return topic_info.get("title", "未知"), False, str(exc), topic_info.get("node_id", "")


def run_aikepu_workflow(publisher):
    """
    体系连载发布主流水线：
    1. 从技能树中选择下一个可发布节点
    2. 生成教育风格文章
    3. 智能配图
    4. 发布到微信草稿箱
    5. 标记节点已发布
    """
    reset_tree_cache()

    # 打印技能树统计
    stats = get_skill_tree_stats()
    print("\n🌳 AI 技能树状态:")
    print(f"   总节点: {stats['total']}")
    print(f"   已发布: {stats['published']}")
    print(f"   可发布: {stats['available']}")
    print(f"   进度: {stats['progress_pct']}%")

    if stats["available"] == 0:
        if stats["progress_pct"] >= 100:
            print("\n🎉 恭喜！AI 技能树所有节点已发布完毕！")
            print("   你可以向技能树添加新节点，或调整学习路线。")
        else:
            print(f"\n📭 当前无可用节点（{stats['total'] - stats['published']} 个节点的先修条件未满足）")
        return

    # 选择 N 个选题（每次最多 MAX_AIKEPU_PER_RUN 篇，默认 1）
    topics = []
    for _ in range(MAX_AIKEPU_PER_RUN):
        topic = select_next_topic()
        if topic:
            topics.append(topic)
            # 临时标记为「待发布」以解锁后续同级节点
            # 注意：这里不写历史，只在线程内标记以支持一次发布多篇
        else:
            break

    if not topics:
        print("\n📭 无可用选题，任务结束。")
        return

    print(f"\n🚀 AI科普：准备发布 {len(topics)} 篇文章")
    for i, t in enumerate(topics):
        print(f"   {i+1}. [{t['node_id']}] {t['title']}")

    # 预热微信活跃标题缓存
    publisher.get_all_active_titles()

    published_count = 0
    with ThreadPoolExecutor(max_workers=len(topics)) as executor:
        futures = {
            executor.submit(_publish_single_topic, topic, publisher): topic
            for topic in topics
        }
        for future in as_completed(futures):
            topic_item = futures[future]
            try:
                title, success, error, node_id = future.result()
                if success:
                    published_count += 1
                elif error:
                    logger.warning("  「{}」发布失败: {}", title, error)
            except Exception as exc:
                t_name = topic_item.get("title", "未知话题") if isinstance(topic_item, dict) else str(topic_item)
                logger.error("  AI科普话题处理出现未捕获异常 「{}」: {}", t_name, exc)

    # 最终统计
    final_stats = get_skill_tree_stats()
    print(f"\n{'⭐' * 30}")
    print(f"  AI科普本次运行：成功发布 {published_count}/{len(topics)} 篇")
    print(f"  技能树进度：{final_stats['published']}/{final_stats['total']} ({final_stats['progress_pct']}%)")
    print(f"{'⭐' * 30}")
