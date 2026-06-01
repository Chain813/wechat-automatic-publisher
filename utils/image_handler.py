"""
============================================================
  图片检索引擎 v7.0 (微信适配版)
  策略：免费图库 -> AI 生图 -> 多源搜索 -> 智能评分 -> 择优录取 -> 尺寸适配
  新增：Pollinations.ai 免费 AI 生图（无需 API Key）
============================================================
"""
import os
import re
import time
import random
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image

# 屏蔽 icrawler/OpenCV 的损坏图片警告
os.environ["OPENCV_LOG_LEVEL"] = "SILENT"
try:
    import cv2
    cv2.setLogLevel(0)  # 0=SILENT, 屏蔽 imread 失败的 WARN
except (ImportError, AttributeError):
    pass

from config import IMAGE_DEFAULT_CANDIDATES, IMAGE_RETRY_MAX, SD_ENABLED, SD_API_URL

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
    except Exception as e:
        logger.debug("  下载失败 {}: {}", url[:80], e)
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
#  Pollinations.ai 免费 AI 生图
# ==========================================
def _build_pollinations_prompt(keyword):
    """将中文关键词转为适合 AI 生图的英文 prompt，优先使用 LLM 增强"""
    from core.shared.llm import call_deepseek_with_retry
    
    # 尝试使用 LLM 生成更丰富的 prompt
    system_prompt = (
        "你是一位精通 Midjourney 和 Stable Diffusion 提示词工程的视觉艺术导演。你能够将用户提供的抽象概念或文案，转化为精准、高质量的英文 AI 绘画提示词 (Prompt)。\n"
        "请遵循以下核心公式：主体描述 + 环境场景 + 艺术风格 + 媒介/材质 + 构图镜头 + 光影色彩 + 渲染参数。\n"
        "1. 英文优先：输出必须是高质量的英文 Prompt。\n"
        "2. 细节丰富：精准描述主体的外貌、材质、环境细节，使用专业艺术术语 (如 Cinematic lighting, Photorealistic, 8k resolution)。\n"
        "3. 安全铁律：生成的提示词必须是 Safe For Work (SFW)，严禁包含任何暗示、色情、暴力或不当内容。\n"
        "4. 格式：直接输出英文 Prompt 文本，不要有任何解释、引导词或 Markdown 代码块。"
    )
    
    try:
        enhanced_prompt = call_deepseek_with_retry(keyword, system_content=system_prompt)
        if enhanced_prompt and len(enhanced_prompt.strip()) > 10:
            return enhanced_prompt.strip()
    except Exception as e:
        from loguru import logger
        logger.warning(f"LLM 生成 prompt 失败，使用本地映射: {e}")

    # 常见时政科技关键词 -> 英文 prompt 映射 (Fallback)
    prompt_map = {
        "AI": "artificial intelligence, futuristic digital brain, neon blue circuits",
        "人工智能": "artificial intelligence, futuristic digital brain, neon blue circuits",
        "大模型": "large language model, neural network visualization, data streams",
        "芯片": "microchip, semiconductor wafer, closeup technology photography",
        "半导体": "semiconductor manufacturing, clean room, chip fabrication",
        "华为": "modern Chinese tech headquarters, sleek glass architecture, night",
        "机器人": "humanoid robot, advanced robotics, futuristic design",
        "量子": "quantum computing, quantum bits, abstract physics visualization",
        "航天": "space exploration, rocket launch, cosmic landscape",
        "网络安全": "cybersecurity, digital shield, encrypted data, dark theme",
        "数字经济": "digital economy, holographic charts, smart city",
        "中美": "US-China technology competition, global trade, digital globe",
        "芯片封锁": "semiconductor supply chain, chip sanctions, technology barrier",
        "科技制裁": "technology sanctions, global tech war, digital blockade",
        "数据安全": "data protection, digital lock, encrypted storage",
        "自动驾驶": "autonomous driving, self-car, lidar sensors, smart road",
        "5G": "5G network tower, connected city, fast data transmission",
        "区块链": "blockchain technology, distributed ledger, digital chain",
        "新能源": "renewable energy, solar panels, wind turbines, green tech",
        "元宇宙": "metaverse, virtual reality, immersive digital world",
        "脑机接口": "brain computer interface, neural link, futuristic neuroscience",
    }

    # 尝试最长匹配
    for key in sorted(prompt_map.keys(), key=len, reverse=True):
        if key in keyword:
            return prompt_map[key]

    # 默认：直接用关键词 + 质量修饰词
    return f"{keyword}, technology, professional, cinematic lighting, detailed"


def _try_pollinations(keyword, directory, width=1024, height=576):
    """
    尝试使用 Pollinations.ai 免费 API 生成图片。
    无需 API Key，直接 URL 调用。
    """
    try:
        import requests

        prompt = _build_pollinations_prompt(keyword)
        encoded = urllib.parse.quote(prompt)
        seed = random.randint(1, 99999)

        url = f"https://image.pollinations.ai/prompt/{encoded}?width={width}&height={height}&seed={seed}&nologo=true&safe=true"
        logger.info("  Pollinations AI 生图中: {}", prompt[:60])

        res = requests.get(url, timeout=20)
        if res.status_code == 200 and len(res.content) > 5000:
            save_path = os.path.join(directory, f"pollinations_{seed}.jpg")
            with open(save_path, "wb") as f:
                f.write(res.content)

            # 基础校验：确认是有效图片
            try:
                with Image.open(save_path) as img:
                    img.verify()
                logger.info("  Pollinations 生图成功: {}x{}", width, height)
                return save_path
            except Exception:
                os.remove(save_path)
                logger.debug("  Pollinations 返回的不是有效图片")
        else:
            logger.debug("  Pollinations 请求失败: status={}", res.status_code)
    except Exception as e:
        logger.debug("  Pollinations 生图异常: {}", e)
    return None


# ==========================================
#  Stable Diffusion 本地生图
# ==========================================
def _try_local_sd(keyword, directory, width=1024, height=576, max_retries=5, prompt=None, prefix="local_sd"):
    """
    调用本地 Stable Diffusion WebUI API 生图（唯一生图源）。
    如果 SD 服务暂未启动，会持续等待重试直到成功。
    要求 WebUI 启动时带上 --api 参数。
    prompt: 直接传入预构建的 prompt；为 None 时从 keyword 自动生成。
    prefix: 保存文件名前缀。
    支持用户中断（检查 cancel_event）。
    """
    import requests
    import base64
    from core.shared.runtime import cancel_event, WorkflowCancelled

    if prompt is None:
        prompt = _build_pollinations_prompt(keyword)
    logger.info("  本地 Stable Diffusion 生图中: {}", prompt[:60])

    payload = {
        "prompt": prompt,
        "negative_prompt": "nsfw, nude, naked, suggestive, porn, text, words, letters, logo, watermark, "
                           "lowres, bad anatomy, bad hands, error, missing fingers, extra digit, fewer digits, "
                           "cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, "
                           "username, blurry, human face, portrait, person",
        "steps": 25,
        "width": width,
        "height": height,
        "cfg_scale": 7.5,
        "sampler_name": "Euler a",
        "seed": -1
    }

    for attempt in range(1, max_retries + 1):
        # 每次重试前检查中断信号
        if cancel_event.is_set():
            raise WorkflowCancelled("SD 生图被用户中断")

        try:
            resp = requests.post(f"{SD_API_URL}/sdapi/v1/txt2img", json=payload, timeout=180)
            if resp.status_code == 200:
                data = resp.json()
                if "images" in data and len(data["images"]) > 0:
                    image_data = base64.b64decode(data["images"][0])
                    save_path = os.path.join(directory, f"{prefix}_{int(time.time())}.jpg")
                    os.makedirs(directory, exist_ok=True)
                    with open(save_path, "wb") as f:
                        f.write(image_data)
                    logger.info("  本地 SD 生图成功: {}x{}", width, height)
                    return save_path
            else:
                logger.warning("  本地 SD 请求失败: status={} (第 {}/{} 次)", resp.status_code, attempt, max_retries)
        except requests.exceptions.ConnectionError:
            logger.warning("  本地 SD 服务未连接，等待重试... (第 {}/{} 次)", attempt, max_retries)
        except requests.exceptions.Timeout:
            logger.warning("  本地 SD 生图超时，等待重试... (第 {}/{} 次)", attempt, max_retries)
        except Exception as e:
            # WorkflowCancelled 不应被捕获
            if isinstance(e, WorkflowCancelled):
                raise
            logger.warning("  本地 SD 生图异常: {} (第 {}/{} 次)", e, attempt, max_retries)

        if attempt < max_retries:
            wait = min(10, 2 ** (attempt - 1))
            logger.info("  等待 {} 秒后重试...", wait)
            # 可中断的等待
            for _ in range(wait * 2):
                if cancel_event.is_set():
                    raise WorkflowCancelled("SD 生图被用户中断")
                time.sleep(0.5)

    logger.error("  本地 SD 在 {} 次重试后仍然失败", max_retries)
    return None


# ==========================================
#  GitHub 项目专属 SD 生图
# ==========================================
def _build_github_project_prompt(repo_name, description, lang, topics=None):
    """
    使用 DeepSeek 为 GitHub 项目生成高质量 SD 提示词。
    将项目的仓库名、描述、语言、标签等上下文信息转化为极具极客艺术感的视觉提示词。
    """
    from core.shared.llm import call_deepseek_with_retry

    topics_str = ", ".join(topics) if topics else "N/A"
    system_prompt = (
        "你是一位精通 Stable Diffusion 提示词工程的视觉艺术导演，专注于科技与极客美学。\n"
        "你的任务是根据用户提供的 GitHub 开源项目信息，生成一张能够传达该项目核心气质的艺术插图提示词。\n\n"
        "## 核心公式\n"
        "主体概念可视化 + 科技场景 + 艺术风格 + 光影色彩 + 渲染参数\n\n"
        "## 风格指南\n"
        "- AI/ML 项目 → 赛博朋克神经网络、数字脑、流光粒子\n"
        "- 工具/CLI 项目 → 极简 3D 工具箱、终端界面艺术化、霓虹代码流\n"
        "- Web/前端项目 → 未来主义 UI 界面、玻璃态设计、渐变光效\n"
        "- 系统/底层项目 → 芯片电路板微距、数据中心、矩阵风\n"
        "- 数据/数据库项目 → 数据可视化流光、全息图表、数字宇宙\n"
        "- 安全项目 → 数字盾牌、加密锁链、暗色调网络空间\n"
        "- 通用 → 科技感抽象艺术、代码雨、数字化景观\n\n"
        "## 铁律\n"
        "1. 输出必须是纯英文 Prompt，直接可用于 Stable Diffusion。\n"
        "2. 必须包含质量修饰词：8k, ultra detailed, cinematic lighting, professional。\n"
        "3. 严禁包含文字、logo、人脸、NSFW 内容。\n"
        "4. 直接输出 Prompt 文本，不要有任何解释、引导词或 Markdown 代码块。\n"
        "5. Prompt 长度控制在 50-120 个英文单词之间。"
    )

    user_prompt = (
        f"请为以下 GitHub 开源项目生成一张 Stable Diffusion 艺术配图的提示词：\n\n"
        f"- 仓库名: {repo_name}\n"
        f"- 项目描述: {description}\n"
        f"- 主要语言: {lang}\n"
        f"- 标签: {topics_str}\n\n"
        f"请根据项目的技术领域和核心功能，生成一段能传达其'灵魂'的视觉提示词。"
    )

    try:
        enhanced_prompt = call_deepseek_with_retry(user_prompt, system_content=system_prompt)
        if enhanced_prompt and len(enhanced_prompt.strip()) > 10:
            logger.info("  DeepSeek 为项目 '{}' 生成 SD Prompt 成功", repo_name)
            return enhanced_prompt.strip()
    except Exception as e:
        logger.warning("  DeepSeek 为 GitHub 项目生成 Prompt 失败: {}", e)

    # Fallback: 使用通用的 prompt 构建器
    fallback_keyword = f"{repo_name.split('/')[-1]} {lang} open source project"
    return _build_pollinations_prompt(fallback_keyword)


def download_project_image_for_github(repo_name, description, lang, topics=None, save_dir="assets"):
    """
    为 GitHub 项目生成 SD 艺术配图。
    使用 DeepSeek 将项目信息转化为高质量 SD 提示词，然后调用本地 SD 生图。
    返回本地图片路径。
    """
    if not repo_name:
        return None

    clean_name = _sanitize_path(f"gh_{repo_name.replace('/', '_')}")
    specific_dir = os.path.join(save_dir, clean_name)
    os.makedirs(specific_dir, exist_ok=True)

    logger.info("🎨 正在为 GitHub 项目 '{}' 生成 SD 艺术配图...", repo_name)

    # 使用 DeepSeek 生成专业的 SD prompt
    prompt = _build_github_project_prompt(repo_name, description, lang, topics)
    logger.info("  SD Prompt: {}", prompt[:80])

    # 调用本地 SD 生图
    save_path = _try_local_sd(None, specific_dir, width=1024, height=576, prompt=prompt, prefix="gh_sd")
    if save_path:
        save_path = _finalize_image(save_path, "body")
        if save_path:
            logger.info("  ✅ GitHub 项目 SD 配图生成成功: {}", os.path.basename(save_path))
    return save_path


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


def _sanitize_path(text):
    """清理路径名称，去除 Windows 不支持的字符，并严格去除首尾空格/点"""
    if not text:
        return "default"
    # 去除非法字符
    clean = re.sub(r'[\\/:*?"<>|]', '', text)
    # 去除首尾空格和点（Windows 文件夹不允许以空格或点结尾）
    clean = clean.strip().strip('.')
    if not clean:
        return "default"
    return clean[:50]


# ==========================================
#  核心下载函数
# ==========================================
def download_image(keyword, save_dir="assets"):
    """
    使用本地 Stable Diffusion 生成配图（唯一图源）
    """
    if not keyword or not keyword.strip():
        return None

    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    clean_keyword = _sanitize_path(keyword)
    specific_dir = os.path.join(save_dir, clean_keyword)
    if not os.path.exists(specific_dir):
        os.makedirs(specific_dir)

    logger.info("正在为 '{}' 调用本地 SD 生图...", keyword)

    best = _try_local_sd(keyword, specific_dir, width=1024, height=576)
    if best:
        best = _finalize_image(best, "body")
    return best


def download_cover_image(keyword, save_dir="assets"):
    """封面专用下载（本地 SD 生图）"""
    if not keyword or not keyword.strip():
        return None

    clean_keyword = _sanitize_path(f"{keyword}_cover")
    specific_dir = os.path.join(save_dir, clean_keyword)
    if not os.path.exists(specific_dir):
        os.makedirs(specific_dir)

    logger.info("正在为封面 '{}' 调用本地 SD 生图...", keyword)

    best = _try_local_sd(keyword, specific_dir, width=1280, height=545)
    if best:
        best = _finalize_image(best, "cover")
    return best


def download_image_for_hotspot(keyword, save_dir="assets"):
    """时政热点专用图片（本地 SD 生图）"""
    if not keyword or not keyword.strip():
        return None

    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    clean_keyword = _sanitize_path(keyword)
    specific_dir = os.path.join(save_dir, clean_keyword)
    if not os.path.exists(specific_dir):
        os.makedirs(specific_dir)

    logger.info("正在为热点 '{}' 调用本地 SD 生图...", keyword)

    best = _try_local_sd(keyword, specific_dir, width=1024, height=576)
    if best:
        best = _finalize_image(best, "body")
    return best


def download_cover_image_for_hotspot(keyword, save_dir="assets"):
    """时政热点封面专用（本地 SD 生图）"""
    if not keyword or not keyword.strip():
        return None

    clean_keyword = _sanitize_path(f"{keyword}_cover")
    specific_dir = os.path.join(save_dir, clean_keyword)
    if not os.path.exists(specific_dir):
        os.makedirs(specific_dir)

    logger.info("正在为热点封面 '{}' 调用本地 SD 生图...", keyword)

    best = _try_local_sd(keyword, specific_dir, width=1280, height=545)
    if best:
        best = _finalize_image(best, "cover")
    return best


def download_images(keyword, save_dir="assets", max_num=None):
    """返回多张候选图片列表（用于多图文配图）"""
    if max_num is None:
        max_num = IMAGE_DEFAULT_CANDIDATES
    if not keyword or not keyword.strip():
        return []

    clean_keyword = _sanitize_path(keyword)
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
                        _register_hash(score.phash)
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
        except ImportError:
            logger.debug("  icrawler 未安装，跳过 {} 爬虫", engine)
            return None
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
