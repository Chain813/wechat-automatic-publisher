"""
============================================================
  图片检索引擎 v5.0 (微信适配版)
  策略：多源搜索 -> 智能评分 -> 择优录取 -> 尺寸适配
  新增：微信尺寸裁剪、感知哈希去重、本地兜底、重试机制
============================================================
"""
import os
import re
import time
from PIL import Image

from config import IMAGE_DEFAULT_CANDIDATES, IMAGE_RETRY_MAX

from loguru import logger

# ---- 微信图片规格 ----
WECHAT_COVER_SIZE = (900, 383)     # 封面推荐尺寸
WECHAT_BODY_SIZE = (900, 500)      # 正文插图推荐尺寸
WECHAT_BODY_MAX_MB = 2             # 正文图片 2MB 限制
LOCAL_FALLBACK_IMAGE = "assets/default_cover.jpg"

# 已下载图片的感知哈希集合（真正用于去重）
_downloaded_hashes = set()


def _get_all_candidates(directory):
    """从目录中获取所有合法的图片路径"""
    if not os.path.exists(directory):
        return []
    candidates = []
    for f in os.listdir(directory):
        fpath = os.path.join(directory, f)
        if os.path.isfile(fpath) and os.path.getsize(fpath) > 5000:
            candidates.append(os.path.abspath(fpath))
    return candidates


def _clean_dir(directory):
    """清空目录"""
    if os.path.exists(directory):
        for f in os.listdir(directory):
            fpath = os.path.join(directory, f)
            if os.path.isfile(fpath):
                try:
                    os.remove(fpath)
                except OSError:
                    pass


def _is_too_similar_to_existing(phash):
    """检查感知哈希是否与已下载图片相似"""
    if not phash:
        return False
    from .image_filter import is_too_similar
    for existing in _downloaded_hashes:
        if is_too_similar(phash, existing):
            return True
    return False


# ==========================================
#  微信尺寸适配
# ==========================================
def resize_for_wechat(img_path, purpose="body"):
    """
    将图片裁剪/缩放到微信推荐尺寸。
    - cover: 900x383 (2.35:1)
    - body:  900x500 (16:9 变体)
    返回新文件路径（覆盖原文件或生成新文件）。
    """
    try:
        target_size = WECHAT_COVER_SIZE if purpose == "cover" else WECHAT_BODY_SIZE
        img = Image.open(img_path)
        orig_w, orig_h = img.size

        tw, th = target_size
        target_ratio = tw / th
        orig_ratio = orig_w / orig_h

        if orig_ratio > target_ratio:
            # 原图更宽：裁剪左右
            new_w = int(orig_h * target_ratio)
            new_h = orig_h
            left = (orig_w - new_w) // 2
            img = img.crop((left, 0, left + new_w, new_h))
        else:
            # 原图更高：裁剪上下
            new_w = orig_w
            new_h = int(orig_w / target_ratio)
            top = (orig_h - new_h) // 2
            img = img.crop((0, top, new_w, new_h))

        img = img.resize(target_size, Image.LANCZOS)

        # 如果原图是 RGBA，转为 RGB
        if img.mode == 'RGBA':
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # 检查文件大小：超过微信限制则压缩
        out_path = img_path
        img.save(out_path, 'JPEG', quality=92)

        # 如果文件还是太大，降低质量
        file_size_mb = os.path.getsize(out_path) / (1024 * 1024)
        max_mb = WECHAT_BODY_MAX_MB if purpose == "body" else 10
        quality = 85
        while file_size_mb > max_mb and quality > 30:
            img.save(out_path, 'JPEG', quality=quality)
            file_size_mb = os.path.getsize(out_path) / (1024 * 1024)
            quality -= 15

        logger.debug("  resize_for_wechat: {} -> {}x{}, {:.1f}MB",
                     os.path.basename(img_path), tw, th, file_size_mb)
        return out_path
    except Exception as e:
        logger.warning("  resize_for_wechat failed: {}", e)
        return img_path


# ==========================================
#  搜索 query 构建
# ==========================================
def _build_search_query(keyword, scene="auto"):
    """
    根据场景分类构建搜索 query，过滤低质量来源。
    scene 分类：人物/产品/趋势/科普/auto
    """
    base = f"{keyword}"
    negative = " -封面 -海报 -PPT -二维码 -logo -图标"

    if scene == "人物":
        return f"{base} 高清照片 特写{negative}"
    elif scene == "产品":
        return f"{base} 产品细节 实物拍摄{negative}"
    elif scene == "趋势":
        return f"{base} 概念图 科技 未来{negative}"
    elif scene == "科普":
        return f"{base} 示意图 原理 数据可视化{negative}"
    else:
        return f"{base} 实拍 高清{negative}"


# ==========================================
#  核心下载函数
# ==========================================
def download_image(keyword, save_dir="assets"):
    """
    智能图片搜索（多图采样 + 评分筛选 + 微信尺寸适配）
    """
    if not keyword or not keyword.strip():
        return None

    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    clean_keyword = re.sub(r'[\\/:*?"<>|]', '', keyword.strip())[:30]
    specific_dir = os.path.join(save_dir, clean_keyword)
    if not os.path.exists(specific_dir):
        os.makedirs(specific_dir)

    logger.info("正在为 '{}' 启动智能采样筛选...", keyword)

    max_num = IMAGE_DEFAULT_CANDIDATES

    # ---- 策略 1：Bing 采样 ----
    best = _try_crawl("bing", keyword, specific_dir, max_num, purpose="body")
    if best:
        best = _finalize_image(best, "body")
        if best:
            return best

    # ---- 策略 2：百度采样 ----
    best = _try_crawl("baidu", keyword, specific_dir, max(3, max_num // 2), purpose="body")
    if best:
        best = _finalize_image(best, "body")
        if best:
            return best

    # ---- 兜底：本地默认图 ----
    return _get_fallback_image(specific_dir)


def download_cover_image(keyword, save_dir="assets"):
    """封面专用下载（偏好 2.35:1 宽屏）"""
    if not keyword or not keyword.strip():
        return _get_fallback_image(save_dir)

    clean_keyword = re.sub(r'[\\/:*?"<>|]', '', keyword.strip())[:30]
    specific_dir = os.path.join(save_dir, f"{clean_keyword}_cover")
    if not os.path.exists(specific_dir):
        os.makedirs(specific_dir)

    logger.info("正在为封面 '{}' 搜索宽屏素材...", keyword)

    max_num = IMAGE_DEFAULT_CANDIDATES + 3  # 封面需要更多候选

    best = _try_crawl("bing", keyword, specific_dir, max_num, scene="趋势", purpose="cover")
    if best:
        best = _finalize_image(best, "cover")
        if best:
            return best

    best = _try_crawl("baidu", keyword, specific_dir, max(3, max_num // 2), scene="趋势", purpose="cover")
    if best:
        best = _finalize_image(best, "cover")
        if best:
            return best

    return _get_fallback_image(specific_dir)


def download_images(keyword, save_dir="assets", max_num=None):
    """返回多张候选图片列表（用于多图文配图）"""
    if max_num is None:
        max_num = IMAGE_DEFAULT_CANDIDATES
    if not keyword or not keyword.strip():
        return []

    clean_keyword = re.sub(r'[\\/:*?"<>|]', '', keyword.strip())[:30]
    specific_dir = os.path.join(save_dir, clean_keyword)
    if not os.path.exists(specific_dir):
        os.makedirs(specific_dir)

    logger.info("正在批量搜索 '{}' ({} 张)...", keyword, max_num)
    results = []

    for source in ["bing", "baidu"]:
        n = max_num if source == "bing" else max(2, max_num // 2)
        _try_crawl_to_dir(source, keyword, specific_dir, n)
        candidates = _get_all_candidates(specific_dir)
        from .image_filter import evaluate_image, ImageScore
        for c in candidates:
            score = evaluate_image(c, "body")
            if score.score >= 50 and not _is_too_similar_to_existing(score.phash):
                c = _finalize_image(c, "body")
                if c:
                    results.append(c)
                    if score.phash:
                        _downloaded_hashes.add(score.phash)
        if len(results) >= max_num:
            break

    return results[:max_num]


# ==========================================
#  内部辅助
# ==========================================
def _try_crawl(engine, keyword, directory, max_num, scene="auto", purpose="body"):
    """尝试从指定引擎抓取，返回最优图片路径"""
    _clean_dir(directory)
    query = _build_search_query(keyword, scene)
    for attempt in range(1, IMAGE_RETRY_MAX + 1):
        try:
            if engine == "bing":
                from icrawler.builtin import BingImageCrawler
                crawler = BingImageCrawler(storage={'root_dir': directory}, log_level=50)
                crawler.crawl(keyword=query, max_num=max_num, overwrite=True)
            else:
                from icrawler.builtin import BaiduImageCrawler
                crawler = BaiduImageCrawler(storage={'root_dir': directory}, log_level=50)
                crawler.crawl(keyword=query, max_num=max_num, overwrite=True)

            candidates = _get_all_candidates(directory)
            if candidates:
                from .image_filter import pick_best_image
                best = pick_best_image(candidates, purpose)
                if best:
                    return best
        except Exception as e:
            logger.warning("  {} 第 {}/{} 次抓取失败: {}", engine, attempt, IMAGE_RETRY_MAX, e)
            if attempt < IMAGE_RETRY_MAX:
                time.sleep(1)
    return None


def _try_crawl_to_dir(engine, keyword, directory, max_num, scene="auto"):
    """抓取图片到目录（不评分，批量模式用）"""
    query = _build_search_query(keyword, scene)
    try:
        if engine == "bing":
            from icrawler.builtin import BingImageCrawler
            crawler = BingImageCrawler(storage={'root_dir': directory}, log_level=50)
            crawler.crawl(keyword=query, max_num=max_num, overwrite=True)
        else:
            from icrawler.builtin import BaiduImageCrawler
            crawler = BaiduImageCrawler(storage={'root_dir': directory}, log_level=50)
            crawler.crawl(keyword=query, max_num=max_num, overwrite=True)
    except Exception as e:
        logger.warning("  批量抓取 {} 失败: {}", engine, e)


def _finalize_image(img_path, purpose):
    """后处理：尺寸适配 + 去重检查 + 哈希登记"""
    from .image_filter import compute_perceptual_hash
    phash = compute_perceptual_hash(img_path)
    if _is_too_similar_to_existing(phash):
        logger.debug("  跳过相似图片: {}", os.path.basename(img_path))
        return None

    result = resize_for_wechat(img_path, purpose)
    if phash:
        _downloaded_hashes.add(phash)
    return result


def _get_fallback_image(directory):
    """获取兜底图片（优先本地默认图，其次随机在线图）"""
    import random
    if not os.path.exists(directory):
        os.makedirs(directory)

    fpath = os.path.join(directory, "fallback.jpg")

    # 优先本地默认图
    if os.path.exists(LOCAL_FALLBACK_IMAGE):
        logger.info("  使用本地默认封面作为兜底")
        try:
            img = Image.open(LOCAL_FALLBACK_IMAGE)
            img.save(fpath, 'JPEG', quality=92)
            return os.path.abspath(fpath)
        except Exception as e:
            logger.warning("  本地默认图读取失败: {}", e)

    # 其次在线随机图
    try:
        import requests
        logger.info("  使用在线随机图兜底...")
        res = requests.get(
            f"https://picsum.photos/1200/800?random={random.randint(1, 999)}",
            timeout=10
        )
        with open(fpath, "wb") as f:
            f.write(res.content)
        return os.path.abspath(fpath)
    except Exception as e:
        logger.warning("  在线兜底图获取失败: {}", e)
        return None


def reset_image_cache():
    """重置下载缓存"""
    global _downloaded_hashes
    _downloaded_hashes = set()
