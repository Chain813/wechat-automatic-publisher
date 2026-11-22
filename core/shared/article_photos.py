"""为文章选择实图或 AI 示意图，上传后保留各自的来源说明。"""
from concurrent.futures import ThreadPoolExecutor
from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory

from loguru import logger

from core.shared.runtime import WorkflowCancelled, check_cancelled
from utils.image_handler import download_image, generate_default_cover, label_ai_cover, qwen_prompt_context
from utils.source_photos import find_source_photo, prepare_photo_cover


def image_html(url, caption=""):
    return (
        '<p style="text-align:center;margin: 20px 0;">'
        f'<img src="{escape(url, quote=True)}" style="width:100%;max-width:600px;border-radius:12px;'
        'box-shadow: 0 1px 2px rgba(0,0,0,0.03), 0 4px 16px rgba(15,23,42,0.06);">'
        '</p>' + caption
    )


def source_caption(source_url, label="图片来源", title="", creator="", license_name="", license_url=""):
    source = escape(source_url, quote=True)
    parts = [escape(value) for value in (title, creator) if value]
    if license_name and license_url:
        parts.append(f'<a href="{escape(license_url, quote=True)}">{escape(license_name)}</a>')
    # 微信可能限制外链跳转，保留可复制的作品页地址。
    parts.append(f'<a href="{source}">{source}</a>')
    return (
        '<p style="text-align:center;font-size:12px;color:#64748b;line-height:1.5;'
        f'overflow-wrap:anywhere;">{label}：{" · ".join(parts)}</p>'
    )


def _image_result(future, keyword):
    check_cancelled()
    try:
        return future.result()
    except WorkflowCancelled:
        raise
    except Exception as exc:
        logger.warning("配图失败（{}）：{}", keyword, exc)
        return None


def _is_infographic_brief(keyword):
    """判断配图占位符是否为结构化中文信息图主题（含｜分隔符），此类配图直走 AI 信息图生成，不查实拍图库。"""
    return isinstance(keyword, str) and ("｜" in keyword or "|" in keyword)


def _generate_with_context(keyword, directory, article_title="", section_context="", slot_index=0):
    with qwen_prompt_context(
        article_title=article_title,
        section_context=section_context,
        slot_index=slot_index,
    ):
        return download_image(keyword, directory, allow_title_card=False)


def _select_images(slots, directory, use_ai_first, cover_title="", section_contexts=None):
    """按原文顺序匹配实图，结构化信息图或实图空缺的槽位并行生图。返回顺序优先排列实图以供选封面。"""
    images = {}
    seen = set()
    ctx_map = section_contexts or {}
    with ThreadPoolExecutor(max_workers=min(3, len(slots))) as pool:
        if not use_ai_first:
            searches = {
                index: pool.submit(find_source_photo, keyword, directory)
                for index, keyword in slots.items()
                if not _is_infographic_brief(keyword)
            }
            for index, search in searches.items():
                photo = _image_result(search, slots[index])
                if photo and photo.source_url not in seen:
                    seen.add(photo.source_url)
                    images[index] = (photo.path, photo)

        check_cancelled()
        generations = {
            index: pool.submit(
                _generate_with_context,
                keyword,
                directory / str(index),
                cover_title or "",
                ctx_map.get(index, ""),
                index,
            )
            for index, keyword in slots.items() if index not in images
        }
        for index, generation in generations.items():
            path = _image_result(generation, slots[index])
            if path:
                images[index] = (path, None)
    return images


def _upload_cover(path, directory, publisher, *, generated):
    try:
        cover_path = prepare_photo_cover(path, directory)
        if generated:
            label_ai_cover(cover_path)
        return publisher.upload_image(cover_path)
    except WorkflowCancelled:
        raise
    except Exception as exc:
        logger.warning("封面适配或上传失败：{}", exc)
        return None


def prepare_article_photos(keywords, publisher, cover_title=None, *, use_ai_first=False, section_contexts=None):
    figures = {}
    thumb_id = None
    cover_caption = ""
    slots = {}
    slot_contexts = {}
    seen_keywords = set()
    ctx_list = list(section_contexts) if section_contexts else []
    for index, keyword in enumerate(keywords):
        if use_ai_first or keyword not in seen_keywords:
            slots[index] = keyword
            if index < len(ctx_list):
                slot_contexts[index] = ctx_list[index]
        seen_keywords.add(keyword)
    if not slots and cover_title:
        slots[0] = cover_title
    if not slots:
        return figures, thumb_id, cover_caption

    with TemporaryDirectory(prefix="wechat-photos-") as temp:
        directory = Path(temp)
        for index, (path, photo) in _select_images(
            slots, directory, use_ai_first, cover_title=cover_title or "", section_contexts=slot_contexts,
        ).items():
            check_cancelled()
            try:
                cdn_url = publisher.upload_news_image(path) if keywords else None
            except WorkflowCancelled:
                raise
            except Exception as exc:
                logger.warning("配图上传失败（{}）：{}", slots[index], exc)
                continue

            if keywords and not cdn_url:
                continue
            used_as_cover = False
            if cover_title and not thumb_id:
                thumb_id = _upload_cover(path, directory, publisher, generated=photo is None)
                used_as_cover = bool(thumb_id)
            if photo:
                label = "资料图"
                if used_as_cover:
                    label = "封面及正文资料图" if cdn_url else "封面资料图"
                caption = source_caption(photo.source_url, label, photo.title, photo.creator,
                                         photo.license_name, photo.license_url)
            else:
                caption = '<p style="text-align:center;font-size:12px;color:#64748b;">AI 示意图</p>'
            if cdn_url:
                figures[index] = image_html(cdn_url, caption)
            elif used_as_cover:
                cover_caption = caption
        if cover_title and not thumb_id:
            check_cancelled()
            card = generate_default_cover(cover_title, str(Path(directory) / "cover.jpg"))
            if card:
                thumb_id = publisher.upload_image(card)
    return figures, thumb_id, cover_caption
