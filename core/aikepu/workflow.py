"""
============================================================
  AI 科普发布流水线 v1.0
  技能树选题 → 教育风文章生成 → 配图 → 微信草稿箱
============================================================
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from loguru import logger

from config import BRAND_NAME, MAX_AIKEPU_PER_RUN
from core.aikepu.skill_tree import (
    select_next_topic, mark_published, get_skill_tree_stats,
    reset_tree_cache, release_reserved
)
from core.aikepu.processor import generate_aikepu_article, generate_digest
from core.shared.article_utils import process_article_content, _print_review_report
from core.shared.llm import validate_title
from utils.image_handler import download_cover_image, reset_image_cache
from core.shared.runtime import check_cancelled


def _generate_article_assets(topic_info, publisher):
    """
    为单个选题生成完整文章资产：文章 + 封面 + HTML。
    复用 hotspots workflow 的并行模式。
    """
    check_cancelled()
    reset_image_cache()

    topic_title = topic_info["title"]
    node_id = topic_info["node_id"]

    # 封面生成与文章创作并行
    with ThreadPoolExecutor(max_workers=1) as cover_pool:
        cover_future = cover_pool.submit(download_cover_image, topic_title)

        article_text = generate_aikepu_article(topic_info)
        if not article_text:
            cover_future.cancel()
            print("❌ AI科普文章生成失败，跳过。")
            return None

        print("\n🎨 正在执行排版优化与智能配图 (并行加速)...")
        final_html, review_data = process_article_content(
            article_text, publisher, use_ai_first=True
        )
        check_cancelled()
        if not final_html:
            cover_future.cancel()
            print("❌ 内容处理后异常，跳过。")
            return None

        print("\n📸 等待封面图生成...")
        cover_path = cover_future.result()

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
        print("⚠️ 封面图下载失败，将使用无封面模式发布。")

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
                return topic_title, False, "文章生成失败", node_id

            final_html, review_data, thumb_id, article_text = generated

            clean_title, title_warnings = validate_title(topic_title)
            for warning in title_warnings:
                print(f"  ⚠️ 标题警告: {warning}")

            digest = future_digest.result()
            digest_text = digest[:120] if digest else ""

        _print_review_report(
            title=clean_title,
            word_count=review_data["word_count"],
            image_count=review_data["image_count"],
            sensitive_words=review_data["sensitive_words"],
            cover_ok=thumb_id is not None,
            digest=digest_text,
        )

        # 发布到微信草稿箱
        success, result = publisher.publish_and_notify(
            clean_title, final_html, thumb_id, digest_text
        )

        if success:
            draft_id = result["media_id"]
            print(f"\n✅ 「{clean_title}」发布成功 → {draft_id}")
            mark_published(node_id, clean_title, draft_id=draft_id)
            return topic_title, True, None, node_id
        else:
            err = result.get("errmsg", "未知错误")
            print(f"❌ 「{clean_title}」发布失败：{err}")
            release_reserved(node_id)  # 发布失败，释放节点以便重试
            return topic_title, False, err, node_id

    except Exception as exc:
        logger.warning("  AI科普发布异常: {}", exc)
        release_reserved(topic_info.get("node_id", ""))  # 异常时释放节点
        return topic_info.get("title", "未知"), False, str(exc), topic_info.get("node_id", "")


def run_aikepu_workflow(publisher):
    """
    AI 科普发布主流水线：
    1. 从技能树中选择下一个可发布节点
    2. 生成教育风格文章
    3. 智能配图
    4. 发布到微信草稿箱
    5. 标记节点已发布
    """
    reset_tree_cache()

    # 打印技能树统计
    stats = get_skill_tree_stats()
    print(f"\n🌳 AI 技能树状态:")
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
            title, success, error, node_id = future.result()
            if success:
                published_count += 1
            elif error:
                logger.warning("  「{}」发布失败: {}", title)

    # 最终统计
    final_stats = get_skill_tree_stats()
    print(f"\n{'⭐' * 30}")
    print(f"  AI科普本次运行：成功发布 {published_count}/{len(topics)} 篇")
    print(f"  技能树进度：{final_stats['published']}/{final_stats['total']} ({final_stats['progress_pct']}%)")
    print(f"{'⭐' * 30}")
