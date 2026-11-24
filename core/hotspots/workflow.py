import os
import hashlib
from datetime import datetime
from loguru import logger
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import MAX_TOPICS_PER_RUN, MAX_TOPIC_CANDIDATES
from core.hotspots.processor import filter_tech_hotspots, generate_article, generate_digest
from core.shared.article_utils import process_article_content, _print_review_report
from core.shared.llm import validate_title
from utils.image_handler import reset_image_cache
from core.pipeline.records import publish_article
from core.pipeline.nodes import run_counted
from core.shared.runtime import WorkflowCancelled, check_cancelled

from core.shared.publisher import _to_clean_title_str
from core.pipeline.nodes import BaseNode
from core.pipeline.engine import PipelineEngine
from core.db.manager import db_manager
from core.db.models import ArticleHistory

# --- 辅助方法 ---

def _save_history(topics):
    try:
        session = db_manager.get_session()
        today = datetime.now().strftime("%Y-%m-%d")
        for topic in topics:
            raw_title = _to_clean_title_str(topic)
            clean_title, _ = validate_title(raw_title)
            existing = session.query(ArticleHistory).filter(
                ArticleHistory.source_type == "hotspots",
                ArticleHistory.title.in_([clean_title, raw_title])
            ).first()
            if not existing:
                source_url = getattr(topic, "url", "") if hasattr(topic, "url") else ""
                ah = ArticleHistory(
                    title=clean_title,
                    source_type="hotspots",
                    publish_date=today,
                    success_status=False,
                    source_url=source_url,
                    status="PENDING_REVIEW"
                )
                session.add(ah)
        session.commit()
    except WorkflowCancelled:
        raise
    except Exception as e:
        logger.warning("保存历史候选话题异常: {}", e)
    finally:
        db_manager.remove_session()

def _save_publish_result(topic, success, draft_id=None, error=None, quality_score=0.0, source_url="", status=None, preview_html=None, thumb_id=None, fact_check_result=""):
    try:
        session = db_manager.get_session()
        topic_str = _to_clean_title_str(topic)
        clean_title, _ = validate_title(topic_str)
        
        # 1. 保存本地 HTML 预览供 WebUI 人机工作台查看或审批
        if preview_html:
            try:
                title_hash = hashlib.md5(clean_title.encode('utf-8')).hexdigest()
                os.makedirs(os.path.join("data", "previews"), exist_ok=True)
                preview_filename = f"{draft_id}.html" if draft_id else f"fail_{title_hash}.html"
                preview_path = os.path.join("data", "previews", preview_filename)
                with open(preview_path, "w", encoding="utf-8") as f:
                    f.write(preview_html)
            except WorkflowCancelled:
                raise
            except Exception as pe:
                logger.debug("保存预览 HTML 异常: {}", pe)

        existing = session.query(ArticleHistory).filter(
            ArticleHistory.source_type == "hotspots",
            ArticleHistory.media_id.is_(None),
            ArticleHistory.delivery_attempt_id.is_(None),
            ArticleHistory.title.in_([clean_title, topic_str])
        ).order_by(ArticleHistory.id.desc()).first()

        if existing:
            existing.title = clean_title
            existing.success_status = success
            if draft_id:
                existing.media_id = draft_id
            existing.error_log = error if not success else None
            if quality_score:
                existing.quality_score = quality_score
            if source_url:
                existing.source_url = source_url
            if status:
                existing.status = status
            elif not success:
                existing.status = "REJECTED"
            if thumb_id and hasattr(existing, 'thumb_media_id'):
                existing.thumb_media_id = thumb_id
            if fact_check_result and hasattr(existing, 'fact_check_result'):
                existing.fact_check_result = fact_check_result
        else:
            ah = ArticleHistory(
                title=clean_title,
                source_type="hotspots",
                publish_date=datetime.now().strftime("%Y-%m-%d"),
                success_status=success,
                media_id=draft_id,
                error_log=error if not success else None,
                quality_score=quality_score,
                source_url=source_url,
                status=status or ("DRAFT" if success else "REJECTED"),
                fact_check_result=fact_check_result or None
            )
            if thumb_id and hasattr(ah, 'thumb_media_id'):
                ah.thumb_media_id = thumb_id
            session.add(ah)
        session.commit()
    except WorkflowCancelled:
        raise
    except Exception as e:
        logger.warning("保存发布结果异常: {}", e)
    finally:
        db_manager.remove_session()

def _get_past_topics(days=7):
    from datetime import timedelta
    from core.plugins.base import HotspotItem
    try:
        session = db_manager.get_session()
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        records = session.query(ArticleHistory).filter(
            ArticleHistory.source_type == "hotspots",
            ArticleHistory.publish_date >= cutoff_date,
            ArticleHistory.status == "PENDING_REVIEW"
        ).all()
        return [HotspotItem(title=r.title, url=r.source_url or "") for r in records]
    finally:
        db_manager.remove_session()

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
        from core.hotspots.collector import fetch_all_hotspot_items
        hotspot_items = fetch_all_hotspot_items()
        raw_data = hotspot_items
        if not raw_data:
            print("❌ 数据源扫描失败，请检查网络连接")
            return False

        selected_topics = filter_tech_hotspots(raw_data)

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
                print(f"✅ 成功找到前几天未发送的优质热点：{[_to_clean_title_str(t) for t in selected_topics]}")
            else:
                print("📭 前几天也无符合条件的未发送热点，任务结束。")
                context["counts"].skipped += 1
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
            topic_disp = _to_clean_title_str(topic)
            if is_dup:
                print(f"  ⚠️ 跳过重复：「{topic_disp}」≈「{old_title}」")
            else:
                valid_topics.append(topic)

        if not valid_topics:
            print("\n📭 所有候选话题均已存在，本次无新内容发布。")
            context["counts"].skipped += 1
            return False

        _save_history([topic for topic in selected_topics if topic not in candidates])
        context['valid_topics'] = valid_topics
        return True


class ParallelPublishNode(BaseNode):
    def _generate_article_assets(self, topic, publisher):
        check_cancelled()

        topic_str = _to_clean_title_str(topic)
        article_text = generate_article(topic)
        if not article_text:
            return None
        final_html, review_data = process_article_content(article_text, publisher, cover_title=topic_str)
        check_cancelled()
        if not final_html:
            return None
        return final_html, review_data, review_data["thumb_id"]

    def _publish_single_topic(self, topic, pub):
        try:
            check_cancelled()
            if not pub.access_token:
                return _to_clean_title_str(topic), False, "Token 获取失败"

            topic_str = _to_clean_title_str(topic)
            print(f"\n{'━' * 50}\n🎯 [并行] 正在处理：{topic_str}\n{'━' * 50}")

            with ThreadPoolExecutor(max_workers=2) as pool:
                future_assets = pool.submit(self._generate_article_assets, topic, pub)
                future_digest = pool.submit(generate_digest, topic_str)

                generated = future_assets.result()
                if not generated:
                    _save_publish_result(topic, success=False, error="文章生成失败", status="FAILED")
                    return topic_str, False, "文章生成失败"

                final_html, review_data, thumb_id = generated
                clean_title, title_warnings = validate_title(topic_str)
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
                digest=digest,
            )

            # 主编审校门禁与自愈闭环 (Critic & Quality Gate with Auto-Remediation)
            from core.pipeline.critic import evaluate_and_repair_article, format_critic_report
            final_html, review_res = evaluate_and_repair_article(clean_title, final_html, article_type="hotspots")
            print(format_critic_report(review_res))

            source_url = getattr(topic, "url", "") if hasattr(topic, "url") else ""
            fact_check_res = getattr(topic, "fact_check_result", "")

            if not review_res["passed"] or not all_ok:
                err = f"未通过主编质量门禁 ({review_res['score']}分): {'; '.join(review_res['critic_issues'])}"
                print(f"❌ 门禁拦截发布：「{clean_title}」— {err}")
                _save_publish_result(
                    topic,
                    success=False,
                    error=err,
                    quality_score=review_res["score"],
                    source_url=source_url,
                    status="REJECTED",
                    preview_html=final_html,
                    thumb_id=thumb_id,
                    fact_check_result=fact_check_res
                )
                return topic_str, False, err

            check_cancelled()
            ok, error = publish_article(pub, "hotspots", clean_title, final_html, thumb_id, digest_text, review_res["score"],
                                      source_url=source_url, fact=fact_check_res)
            return topic_str, ok, error
        except WorkflowCancelled:
            raise
        except Exception as exc:
            logger.warning("并行发布异常: {}", exc)

            return str(topic), False, str(exc)

    def execute(self, context: dict) -> bool:
        reset_image_cache()
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
                topic_item = futures[future]
                try:
                    topic, success, error = future.result()
                    context["counts"].record(success, error)
                    if success:
                        published_count += 1
                    elif error:
                        logger.warning("  「{}」发布失败: {}", topic, error)
                except WorkflowCancelled:
                    context["counts"].cancelled = True
                except Exception as exc:
                    context["counts"].record(False, str(exc))
                    t_str = _to_clean_title_str(topic_item)
                    logger.error("  热点话题处理出现未捕获异常 「{}」: {}", t_str, exc)

        print(f"\n{'⭐' * 30}\n  本次运行完成：成功发布 {published_count}/{len(valid_topics)} 篇\n{'⭐' * 30}")
        return True


# --- 主调度 ---

def run_hotspots_workflow(publisher):
    engine = PipelineEngine(name="HotspotsWorkflow")
    engine.add_node(FetchAndSelectNode())
    engine.add_node(ParallelPublishNode())
    
    return engine.run_workflow("hotspots", publisher)
