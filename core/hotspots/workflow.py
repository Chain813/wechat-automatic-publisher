import json
import os
from datetime import datetime, timedelta
from loguru import logger
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import BRAND_NAME, QYWECHAT_WEBHOOK, WECHAT_APP_ID, WECHAT_APP_SECRET
from core.shared.publisher import _normalize_title
from core.hotspots.collector import fetch_all_hotspots, get_source_health_report
from core.hotspots.processor import filter_tech_hotspots, generate_article, generate_digest
from core.shared.article_utils import process_article_content, _print_review_report
from core.shared.llm import validate_title
from core.shared.publisher import WeChatPublisher, send_to_qywechat
from utils.image_handler import download_cover_image_for_hotspot, reset_image_cache

try:
    from rapidfuzz import fuzz as _fuzz
except ImportError:
    _fuzz = None
from difflib import SequenceMatcher

MAX_TOPICS_PER_RUN = 3
MAX_TOPIC_CANDIDATES = 5
HISTORY_FILE = "hotspots_history.json"
_history_cache = None


def _dedup_topics_against_each_other(topics, threshold=70):
    """
    对 topic 列表做内部去重，相似度超过 threshold 的只保留第一个。
    """
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
                sim = max(
                    _fuzz.ratio(norm, norm_existing),
                    _fuzz.token_set_ratio(norm, norm_existing),
                )
            else:
                sim = int(SequenceMatcher(None, norm, norm_existing).ratio() * 100)
            if sim >= threshold:
                is_similar = True
                logger.info("  去重: 「{}」≈「{}」({}%), 跳过", topic, existing, sim)
                break
        if not is_similar:
            kept.append(topic)
    return kept

def _print_source_health():
    health = get_source_health_report()
    if not health:
        return
    print("📊 源健康状态:")
    for source, status in health.items():
        print(f"   {source}: {status['status']}")

def _load_history():
    global _history_cache
    if _history_cache is not None:
        return _history_cache
    _history_cache = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                _history_cache = json.load(f)
        except Exception as e:
            logger.warning("  历史记录加载失败，将使用空记录: {}", e)
    return _history_cache

def _flush_history():
    global _history_cache
    if _history_cache is None:
        return
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(_history_cache, f, ensure_ascii=False, indent=2)

def _ensure_today(history):
    today = datetime.now().strftime("%Y-%m-%d")
    old_val = history.get(today)
    if isinstance(old_val, list):
        history[today] = {"topics": old_val, "results": []}
    elif not isinstance(old_val, dict):
        history[today] = {"topics": [], "results": []}
    return today

def _save_history(topics):
    history = _load_history()
    today = _ensure_today(history)
    history[today]["topics"] = topics

def _save_publish_result(topic, success, draft_id=None, error=None):
    history = _load_history()
    today = _ensure_today(history)
    result_entry = {
        "topic": topic,
        "success": success,
        "time": datetime.now().strftime("%H:%M:%S"),
    }
    if draft_id:
        result_entry["draft_id"] = draft_id
    if error:
        result_entry["error"] = str(error)
    history[today]["results"].append(result_entry)

def _get_past_topics(days=7):
    history = _load_history()
    past_topics = []
    for i in range(1, days + 1):
        past_date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        entry = history.get(past_date, [])
        if isinstance(entry, dict):
            past_topics.extend(entry.get("topics", []))
        elif isinstance(entry, list):
            past_topics.extend(entry)
    return past_topics

def _fetch_selected_topics(publisher):
    raw_data = fetch_all_hotspots()
    if not raw_data:
        print("❌ 数据源扫描失败，请检查网络连接")
        _print_source_health()
        return []

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
            return selected_topics
        else:
            print("📭 前几天也无符合条件的未发送热点，任务结束。")
            return []

    candidates = selected_topics[:MAX_TOPIC_CANDIDATES]
    return candidates

def _generate_article_assets(topic, publisher):
    reset_image_cache()

    article_text = generate_article(topic)
    if not article_text:
        print("❌ AI 创作失败，跳过。")
        return None

    print("\n🎨 正在执行排版优化与智能图选 (并行加速)...")
    final_html, review_data = process_article_content(article_text, publisher, use_ai_first=True)
    if not final_html:
        print("❌ 内容处理后异常，跳过。")
        return None

    print("\n📸 正在为文章生成门面封面图...")
    cover_path = download_cover_image_for_hotspot(topic)
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

    return final_html, review_data, thumb_id

def _publish_single_topic(topic, pub):
    try:
        if not pub.access_token:
            return topic, False, "Token 获取失败"

        print(f"\n{'━' * 50}")
        print(f"🎯 [并行] 正在处理：{topic}")
        print(f"{'━' * 50}")

        # 并行：文章资产生成 + 摘要生成（互不依赖）
        with ThreadPoolExecutor(max_workers=2) as pool:
            future_assets = pool.submit(_generate_article_assets, topic, pub)
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

        result = pub.add_draft(clean_title, final_html, thumb_id, digest_text)
        if "media_id" in result:
            draft_id = result["media_id"]
            print(f"\n✅ 「{clean_title}」发布成功 → {draft_id}")
            _save_publish_result(clean_title, success=True, draft_id=draft_id)
            send_to_qywechat(QYWECHAT_WEBHOOK, f"【{BRAND_NAME}】《{clean_title}》已就绪，请审核发布。")
            return topic, True, None
        else:
            err = result.get("errmsg", "未知错误")
            print(f"❌ 「{clean_title}」发布失败：{err}")
            _save_publish_result(clean_title, success=False, error=err)
            return topic, False, err

    except Exception as exc:
        logger.warning("  并行发布异常: {}", exc)
        return topic, False, str(exc)

def run_hotspots_workflow(publisher):
    _load_history()
    try:
        selected_topics = _fetch_selected_topics(publisher)
        if not selected_topics:
            return

        # topic 间内部去重，避免同一批次发布语义重复的文章
        before_count = len(selected_topics)
        selected_topics = _dedup_topics_against_each_other(selected_topics)
        if len(selected_topics) < before_count:
            print(f"\n🔄 topic 间去重: {before_count} → {len(selected_topics)}")

        print(f"\n📋 共 {len(selected_topics)} 个候选话题，正在与微信草稿箱去重...")
        valid_topics = []
        for topic in selected_topics:
            if len(valid_topics) >= MAX_TOPICS_PER_RUN:
                break
            is_dup, old_title = publisher.is_title_duplicate(topic, extra_existing=valid_topics)

            if is_dup:
                print(f"  ⚠️ 跳过重复：「{topic}」≈「{old_title}」")
            else:
                valid_topics.append(topic)

        if not valid_topics:
            print("\n📭 所有候选话题均已存在，本次无新内容发布。")
            return

        print(f"\n🚀 准备并行发布 {len(valid_topics)} 篇文章...")
        print(f"   候选：{valid_topics}")

        # 预热草稿缓存，避免每个 topic 重复拉取
        publisher.get_draft_titles()

        published_count = 0
        with ThreadPoolExecutor(max_workers=len(valid_topics)) as executor:
            futures = {
                executor.submit(_publish_single_topic, topic, publisher): topic
                for topic in valid_topics
            }
            for future in as_completed(futures):
                topic, success, error = future.result()
                if success:
                    published_count += 1
                elif error:
                    logger.warning("  「{}」发布失败: {}", topic, error)

        print(f"\n{'⭐' * 30}")
        print(f"  本次运行完成：成功发布 {published_count}/{len(valid_topics)} 篇")
        print(f"{'⭐' * 30}")
    finally:
        _flush_history()
