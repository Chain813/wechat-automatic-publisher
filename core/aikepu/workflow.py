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
    get_active_tree_name, node_source_url, release_reserved
)
from core.aikepu.processor import generate_aikepu_article, generate_digest
from core.shared.article_utils import process_article_content, _print_review_report
from core.shared.llm import validate_title
from core.pipeline.records import publish_article
from core.pipeline.nodes import run_counted
from core.shared.runtime import WorkflowCancelled, check_cancelled


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
                from tempfile import TemporaryDirectory
                with TemporaryDirectory() as directory:
                    jpeg = os.path.join(directory, "cover.jpg")
                    with PILImage.open(cover_path) as img:
                        img.convert("RGB").save(jpeg, "JPEG", quality=60, optimize=True)
                    thumb_id = publisher.upload_image(jpeg)
            except WorkflowCancelled:
                raise
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
        tree_name = topic_info.get("tree_name") or get_active_tree_name()
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

        # 主编审校门禁与自愈闭环 (Critic & Quality Gate with Auto-Remediation)
        from core.pipeline.critic import evaluate_and_repair_article, format_critic_report
        final_html, review_res = evaluate_and_repair_article(clean_title, final_html, article_type="aikepu")
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
                        source_url=node_source_url(tree_name, node_id),
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
                logger.warning("保存 AI科普 门禁拦截记录异常: {}", e)

            return topic_title, False, err, node_id

        # 发布到微信草稿箱
        import re
        check_cancelled()
        safe_title = re.sub(r'[^\w-]', '_', clean_title)
        ok, error = publish_article(publisher, "aikepu", clean_title, final_html, thumb_id, digest_text, review_res["score"],
                                  source_url=node_source_url(tree_name, node_id), node_id=node_id, tree_name=tree_name,
                                  markdown=article_text, markdown_name=f"{node_id}_{safe_title}.md")
        return topic_title, ok, error, node_id
    except WorkflowCancelled:
        raise
    except Exception as exc:
        logger.warning("  AI科普发布异常: {}", exc)
        return topic_info.get("title", "未知"), False, str(exc), topic_info.get("node_id", "")


def _run(publisher, counts, override_node_id):
    """
    体系连载发布主流水线：
    1. 从技能树中选择下一个可发布节点
    2. 生成教育风格文章
    3. 智能配图
    4. 发布到微信草稿箱
    5. 标记节点已发布
    """
    tree_name = get_active_tree_name()

    # 打印技能树统计
    stats = get_skill_tree_stats(tree_name=tree_name)
    print("\n🌳 AI 技能树状态:")
    print(f"   总节点: {stats['total']}")
    print(f"   已发布: {stats['published']}")
    print(f"   可发布: {stats['available']}")
    print(f"   进度: {stats['progress_pct']}%")

    if not override_node_id and stats["available"] == 0:
        counts.skipped += 1
        if stats["progress_pct"] >= 100:
            print("\n🎉 恭喜！AI 技能树所有节点已发布完毕！")
            print("   你可以向技能树添加新节点，或调整学习路线。")
        else:
            print(f"\n📭 当前无可用节点（{stats['total'] - stats['published']} 个节点的先修条件未满足）")
        return

    # 选择 N 个选题（每次最多 MAX_AIKEPU_PER_RUN 篇，默认 1）
    topics = []
    try:
        for _ in range(1 if override_node_id else MAX_AIKEPU_PER_RUN):
            topic = select_next_topic(override_node_id, tree_name=tree_name)
            if override_node_id and topic and topic["node_id"] != override_node_id:
                release_reserved(topic["node_id"], tree_name=tree_name)
                raise ValueError("Unknown skill node")
            if topic:
                topics.append(topic)
                # 临时标记为「待发布」以解锁后续同级节点
                # 注意：这里不写历史，只在线程内标记以支持一次发布多篇
            else:
                break

        if not topics:
            counts.skipped += 1
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
                    counts.record(success, error)
                    if success:
                        published_count += 1
                    elif error:
                        logger.warning("  「{}」发布失败: {}", title, error)
                except WorkflowCancelled:
                    counts.cancelled = True
                except Exception as exc:
                    counts.record(False, str(exc))
                    t_name = topic_item.get("title", "未知话题") if isinstance(topic_item, dict) else str(topic_item)
                    logger.error("  AI科普话题处理出现未捕获异常 「{}」: {}", t_name, exc)

    finally:
        for topic in topics:
            release_reserved(topic["node_id"], tree_name=tree_name)


def run_aikepu_workflow(publisher, override_node_id=None):
    return run_counted("aikepu", lambda counts: _run(publisher, counts, override_node_id))
