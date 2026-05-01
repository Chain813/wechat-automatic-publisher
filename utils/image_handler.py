"""
============================================================
  图片检索引擎 v6.0 (微信适配版)
  策略：免费图库 -> 多源搜索 -> 智能评分 -> 择优录取 -> 尺寸适配
  新增：Pexels/Unsplash 免费图库、线程安全、并行采集
============================================================
"""
import os
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image

# 屏蔽 icrawler/OpenCV 的损坏图片警告
os.environ["OPENCV_LOG_LEVEL"] = "SILENT"
try:
    import cv2
    cv2.setLogLevel(0)  # 0=SILENT, 屏蔽 imread 失败的 WARN
except (ImportError, AttributeError):
    pass

from config import IMAGE_DEFAULT_CANDIDATES, IMAGE_RETRY_MAX

from loguru import logger

# ---- 微信图片规格 ----
WECHAT_COVER_SIZE = (900, 383)     # 封面推荐尺寸
WECHAT_BODY_SIZE = (900, 500)      # 正文插图推荐尺寸
WECHAT_BODY_MAX_MB = 2             # 正文图片 2MB 限制
LOCAL_FALLBACK_IMAGE = "assets/default_cover.jpg"

# ---- 线程安全的哈希去重集合 ----
_downloaded_hashes = set()
_hashes_lock = threading.Lock()

# ---- 免费图库 API (Pexels) ----
# Pexels 免费 API key，无需付费即可使用（每月 200 次免费）
# 若需更多配额，替换为自己的 key: https://www.pexels.com/api/
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")


def _is_too_similar_to_existing(phash):
    """检查感知哈希是否与已下载图片相似（线程安全）"""
    if not phash:
        return False
    from .image_filter import is_too_similar
    with _hashes_lock:
        for existing in _downloaded_hashes:
            if is_too_similar(phash, existing):
                return True
    return False


def _register_hash(phash):
    """注册已使用的哈希（线程安全）"""
    if phash:
        with _hashes_lock:
            _downloaded_hashes.add(phash)


def reset_image_cache():
    """重置下载缓存（线程安全）"""
    global _downloaded_hashes
    with _hashes_lock:
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
        with Image.open(img_path) as raw:
            orig_w, orig_h = raw.size

            tw, th = target_size
            target_ratio = tw / th
            orig_ratio = orig_w / orig_h

            if orig_ratio > target_ratio:
                new_w = int(orig_h * target_ratio)
                new_h = orig_h
                left = (orig_w - new_w) // 2
                img = raw.crop((left, 0, left + new_w, new_h))
            else:
                new_w = orig_w
                new_h = int(orig_w / target_ratio)
                top = (orig_h - new_h) // 2
                img = raw.crop((0, top, new_w, new_h))

            img = img.resize(target_size, Image.LANCZOS)

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
#  免费图库搜索 (Pexels API)
# ==========================================
def _search_pexels(keyword, max_num=3):
    """
    通过 Pexels 免费 API 搜索高质量免版权图片。
    返回图片 URL 列表。
    """
    if not PEXELS_API_KEY:
        return []

    try:
        import requests
        headers = {"Authorization": PEXELS_API_KEY}
        params = {"query": keyword, "per_page": max_num, "orientation": "landscape"}
        res = requests.get(
            "https://api.pexels.com/v1/search",
            headers=headers, params=params, timeout=15
        )
        res.raise_for_status()
        data = res.json()
        urls = []
        for photo in data.get("photos", []):
            url = photo.get("src", {}).get("large", "")
            if url:
                urls.append(url)
        return urls
    except Exception as e:
        logger.debug("  Pexels 搜索失败: {}", e)
        return []


def _download_from_url(url, save_path):
    """从 URL 下载图片到本地路径"""
    try:
        import requests
        res = requests.get(url, timeout=15, stream=True)
        res.raise_for_status()
        with open(save_path, 'wb') as f:
            for chunk in res.iter_content(8192):
                f.write(chunk)
        if os.path.getsize(save_path) > 5000:
            return save_path
    except Exception:
        pass
    return None


def _try_pexels(keyword, directory, max_num=3):
    """
    尝试从 Pexels 免费图库下载，评分后返回最优图片。
    版权安全，优先使用。
    """
    urls = _search_pexels(keyword, max_num)
    if not urls:
        return None

    from .image_filter import pick_best_image
    candidates = []
    for i, url in enumerate(urls):
        save_path = os.path.join(directory, f"pexels_{i}.jpg")
        result = _download_from_url(url, save_path)
        if result:
            candidates.append(result)

    if candidates:
        best = pick_best_image(candidates, "body")
        if best:
            logger.info("  Pexels 免费图库命中: {}", os.path.basename(best))
            return best
    return None


# ==========================================
#  搜索 query 构建
# ==========================================
def _build_search_query(keyword, scene="auto"):
    """
    根据场景分类构建搜索 query，过滤低质量来源。
    scene 分类：人物/产品/趋势/科普/auto
    """
    base = f"{keyword}"
    negative = " -封面 -海报 -PPT -二维码 -logo -图标 -水印 -素材 -版权 -图库"

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
    智能图片搜索（免费图库优先 -> 多源搜索 -> 评分筛选 -> 微信尺寸适配）
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

    # ---- 策略 0：Pexels 免费图库（版权安全，优先） ----
    best = _try_pexels(keyword, specific_dir, max_num)
    if best:
        best = _finalize_image(best, "body")
        if best:
            return best

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
    """封面专用下载（Pexels 优先 -> Bing -> 百度 -> 兜底）"""
    if not keyword or not keyword.strip():
        return _get_fallback_image(save_dir)

    clean_keyword = re.sub(r'[\\/:*?"<>|]', '', keyword.strip())[:30]
    specific_dir = os.path.join(save_dir, f"{clean_keyword}_cover")
    if not os.path.exists(specific_dir):
        os.makedirs(specific_dir)

    logger.info("正在为封面 '{}' 搜索宽屏素材...", keyword)

    max_num = IMAGE_DEFAULT_CANDIDATES + 3

    # ---- 策略 0：Pexels 免费图库 ----
    best = _try_pexels(keyword, specific_dir, max_num)
    if best:
        best = _finalize_image(best, "cover")
        if best:
            return best

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
    """尝试从指定引擎抓取，返回最优图片路径。每个引擎使用独立子目录。"""
    engine_dir = os.path.join(directory, engine)
    os.makedirs(engine_dir, exist_ok=True)
    _clean_dir(engine_dir)
    query = _build_search_query(keyword, scene)
    for attempt in range(1, IMAGE_RETRY_MAX + 1):
        try:
            if engine == "bing":
                from icrawler.builtin import BingImageCrawler
                crawler = BingImageCrawler(storage={'root_dir': engine_dir}, log_level=50)
                bing_filters = {'size': 'large'}
                if purpose == "cover":
                    bing_filters['layout'] = 'wide'
                crawler.crawl(keyword=query, max_num=max_num, overwrite=True, filters=bing_filters)
            else:
                from icrawler.builtin import BaiduImageCrawler
                crawler = BaiduImageCrawler(storage={'root_dir': engine_dir}, log_level=50)
                crawler.crawl(keyword=query, max_num=max_num, overwrite=True)

            candidates = _get_all_candidates(engine_dir)
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


def _try_crawl_parallel(keyword, directory, max_num, scene="auto", purpose="body"):
    """
    Bing 和百度并行抓取，返回最先成功的最优图片。
    比串行快 30-50%。
    """
    bing_dir = os.path.join(directory, "bing")
    baidu_dir = os.path.join(directory, "baidu")
    os.makedirs(bing_dir, exist_ok=True)
    os.makedirs(baidu_dir, exist_ok=True)

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_bing = executor.submit(_try_crawl, "bing", keyword, bing_dir, max_num, scene, purpose)
        f_baidu = executor.submit(_try_crawl, "baidu", keyword, baidu_dir, max(3, max_num // 2), scene, purpose)

        for future in as_completed([f_bing, f_baidu]):
            try:
                result = future.result()
                if result:
                    return result
            except Exception as e:
                logger.debug("  并行抓取子任务异常: {}", e)

    return None


def _try_crawl_to_dir(engine, keyword, directory, max_num, scene="auto"):
    """抓取图片到目录（不评分，批量模式用）"""
    query = _build_search_query(keyword, scene)
    try:
        if engine == "bing":
            from icrawler.builtin import BingImageCrawler
            crawler = BingImageCrawler(storage={'root_dir': directory}, log_level=50)
            bing_filters = {'size': 'large'}
            crawler.crawl(keyword=query, max_num=max_num, overwrite=True, filters=bing_filters)
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
    _register_hash(phash)
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
