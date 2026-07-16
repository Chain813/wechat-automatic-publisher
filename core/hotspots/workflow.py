from datetime import datetime
from loguru import logger
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import MAX_TOPICS_PER_RUN, MAX_TOPIC_CANDIDATES
from core.hotspots.processor import filter_tech_hotspots, generate_article, generate_digest
from core.shared.article_utils import process_article_content, _print_review_report
from core.shared.llm import validate_title
from utils.image_handler import download_cover_image, reset_image_cache
from core.shared.runtime import check_cancelled

from core.pipeline.nodes import BaseNode
from core.pipeline.engine import PipelineEngine
from core.db.manager import db_manager
from core.db.models import ArticleHistory
from core.hotspots.collector import fetch_all_hotspots

# --- 辅助方法 ---

def _save_history(topics):
    session = db_manager.get_session()
    today = datetime.now().strftime("%Y-%m-%d")
    for topic in topics:
        existing = session.query(ArticleHistory).filter_by(title=topic, source_type="hotspots").first()
        if not existing:
            ah = ArticleHistory(title=topic, source_type="hotspots", publish_date=today, success_status=False)
            session.add(ah)
    session.commit()

def _save_publish_result(topic, success, draft_id=None, error=None):
    session = db_manager.get_session()
    existing = session.query(ArticleHistory).filter_by(title=topic, source_type="hotspots").order_by(ArticleHistory.id.desc()).first()
    if existing:
        existing.success_status = success
        existing.media_id = draft_id
        existing.error_log = str(error) if error else None
    else:
        ah = ArticleHistory(title=topic, source_type="hotspots", publish_date=datetime.now().strftime("%Y-%m-%d"), success_status=success, media_id=draft_id, error_log=str(error) if error else None)
        session.add(ah)
    session.commit()

def _get_past_topics(days=7):
    from datetime import timedelta
    session = db_manager.get_session()
    cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    records = session.query(ArticleHistory).filter(ArticleHistory.source_type == "hotspots", ArticleHistory.publish_date >= cutoff_date).all()
    return [r.title for r in records]

def _dedup_topics_against_each_other(topics, threshold=70):
    from core.shared.publisher import _normalize_title
    try:
        from rapidfuzz import fuzz as _fuzz
    except ImportError:
        _fuzz = None
    from difflib import SequenceMatcher

    if not topics:
        return topics
    kept = []
    for topic in topics:
        norm = _normalize_title(topic)
        if not norm:
            continue
        is_similar = False
        for existing in kept:
            norm_existing = _normalize_title(existing)
            if _fuzz:
                sim = max(_fuzz.ratio(norm, norm_existing), _fuzz.token_set_ratio(norm, norm_existing))
            else:
                sim = int(SequenceMatcher(None, norm, norm_existing).ratio() * 100)
            if sim >= threshold:
                is_similar = True
                break
        if not is_similar:
            kept.append(topic)
    return kept


# --- 流水线节点定义 ---

class FetchAndSelectNode(BaseNode):
    def execute(self, context: dict) -> bool:
        publisher = context['publisher']
        check_cancelled()
        raw_data = fetch_all_hotspots()
        if not raw_data:
            print("❌ 数据源扫描失败，请检查网络连接")
            return False

        selected_topics = filter_tech_hotspots(raw_data)
        if selected_topics:
            _save_history(selected_topics)

        if not selected_topics:
            print("📭 今日暂无符合品牌调性的重磅 AI/科技话题，尝试从前几天最新的未发送热点中挑选...")
            past_topics = _get_past_topics(days=7)
            unsent_topics = []
            for topic in past_topics:
                is_dup, _ = publisher.is_title_duplicate(topic)
                if not is_dup:
                    unsent_topics.append(topic)

            if unsent_topics:
                selected_topics = unsent_topics[:MAX_TOPICS_PER_RUN]
                print(f"✅ 成功找到前几天未发送的优质热点：{selected_topics}")
            else:
                print("📭 前几天也无符合条件的未发送热点，任务结束。")
                return False

        candidates = selected_topics[:MAX_TOPIC_CANDIDATES]
        before_count = len(candidates)
        candidates = _dedup_topics_against_each_other(candidates)
        if len(candidates) < before_count:
            print(f"\n🔄 topic 间去重: {before_count} → {len(candidates)}")

        print(f"\n📋 共 {len(candidates)} 个候选话题，正在与微信草稿箱去重...")
        valid_topics = []
        for topic in candidates:
            if len(valid_topics) >= MAX_TOPICS_PER_RUN:
                break
            is_dup, old_title = publisher.is_title_duplicate(topic, extra_existing=valid_topics)
            if is_dup:
                print(f"  ⚠️ 跳过重复：「{topic}」≈「{old_title}」")
            else:
                valid_topics.append(topic)

        if not valid_topics:
            print("\n📭 所有候选话题均已存在，本次无新内容发布。")
            return False

        context['valid_topics'] = valid_topics
        return True


class ParallelPublishNode(BaseNode):
    def _generate_article_assets(self, topic, publisher):
        check_cancelled()
        reset_image_cache()

        with ThreadPoolExecutor(max_workers=1) as cover_pool:
            cover_future = cover_pool.submit(download_cover_image, topic)
            article_text = generate_article(topic)
            if not article_text:
                cover_future.cancel()
                return None

            final_html, review_data = process_article_content(article_text, publisher, use_ai_first=True)
            check_cancelled()
            if not final_html:
                cover_future.cancel()
                return None

            cover_path = cover_future.result()

        thumb_id = None
        if cover_path:
            thumb_id = publisher.upload_image(cover_path)
            if not thumb_id:
                try:
                    from PIL import Image as PILImage
                    with PILImage.open(cover_path) as img:
                        if img.mode != 'RGB':
                            img = img.convert('RGB')
                        img.save(cover_path, 'JPEG', quality=60, optimize=True)
                    thumb_id = publisher.upload_image(cover_path)
                except Exception as e:
                    logger.warning("封面压缩重试失败: {}", e)

        return final_html, review_data, thumb_id

    def _publish_single_topic(self, topic, pub):
        try:
            check_cancelled()
            if not pub.access_token:
                return topic, False, "Token 获取失败"

            print(f"\n{'━' * 50}\n🎯 [并行] 正在处理：{topic}\n{'━' * 50}")

            with ThreadPoolExecutor(max_workers=2) as pool:
                future_assets = pool.submit(self._generate_article_assets, topic, pub)
                future_digest = pool.submit(generate_digest, topic)

                generated = future_assets.result()
                if not generated:
                    return topic, False, "文章生成失败"

                final_html, review_data, thumb_id = generated
                clean_title, title_warnings = validate_title(topic)
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
                digest=digest,
            )

            success, result = pub.publish_and_notify(clean_title, final_html, thumb_id, digest_text)
            if success:
                draft_id = result["media_id"]
                print(f"\n✅ 「{clean_title}」发布成功 → {draft_id}")
                _save_publish_result(clean_title, success=True, draft_id=draft_id)
                return topic, True, None
            else:
                err = result.get("errmsg", "未知错误")
                print(f"❌ 「{clean_title}」发布失败：{err}")
                _save_publish_result(clean_title, success=False, error=err)
                return topic, False, err

        except Exception as exc:
            logger.warning("并行发布异常: {}", exc)
            return topic, False, str(exc)

    def execute(self, context: dict) -> bool:
        valid_topics = context['valid_topics']
        publisher = context['publisher']

        print(f"\n🚀 准备并行发布 {len(valid_topics)} 篇文章...")
        print(f"   候选：{valid_topics}")
        publisher.get_all_active_titles()

        published_count = 0
        with ThreadPoolExecutor(max_workers=len(valid_topics)) as executor:
            futures = {
                executor.submit(self._publish_single_topic, topic, publisher): topic
                for topic in valid_topics
            }
            for future in as_completed(futures):
                topic, success, error = future.result()
                if success:
                    published_count += 1
                elif error:
                    logger.warning("  「{}」发布失败: {}", topic, error)

        print(f"\n{'⭐' * 30}\n  本次运行完成：成功发布 {published_count}/{len(valid_topics)} 篇\n{'⭐' * 30}")
        return True


# --- 主调度 ---

def run_hotspots_workflow(publisher):
    engine = PipelineEngine(name="HotspotsWorkflow")
    engine.add_node(FetchAndSelectNode())
    engine.add_node(ParallelPublishNode())
    
    engine.run({"publisher": publisher})
