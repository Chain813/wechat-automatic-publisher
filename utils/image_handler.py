"""
============================================================
  图片检索引擎 v8.0 (微信适配版)
  策略：本地 Stable Diffusion 生图 -> 尺寸适配
============================================================
"""
import os
import re
import time
import threading
from PIL import Image, ImageDraw, ImageFont

# 屏蔽 icrawler/OpenCV 的损坏图片警告
os.environ["OPENCV_LOG_LEVEL"] = "SILENT"
try:
    import cv2
    cv2.setLogLevel(0)  # 0=SILENT, 屏蔽 imread 失败的 WARN
except (ImportError, AttributeError):
    pass

from config import SD_TIMEOUT, SD_STEPS, SD_MAX_RETRIES, WECHAT_COVER_WIDTH, WECHAT_COVER_HEIGHT, WECHAT_BODY_WIDTH, WECHAT_BODY_HEIGHT, WECHAT_BODY_MAX_MB

from loguru import logger

# ---- 微信图片规格 ----
WECHAT_COVER_SIZE = (WECHAT_COVER_WIDTH, WECHAT_COVER_HEIGHT)
WECHAT_BODY_SIZE = (WECHAT_BODY_WIDTH, WECHAT_BODY_HEIGHT)
LOCAL_FALLBACK_IMAGE = "assets/default_cover.jpg"

# ---- 线程安全的哈希去重集合 ----
_downloaded_hashes = set()
_hashes_lock = threading.Lock()

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

            # 对于图表/架构图/纵向长图，禁止强行中心切头切尾
            is_diagram = purpose in ("diagram", "diagram_body") or "diagram" in os.path.basename(img_path).lower()
            if is_diagram or (purpose == "body" and orig_ratio < 0.9):
                # 保持图像完整性，等比例缩放并居中补白
                img = Image.new("RGB", (tw, th), (255, 255, 255))
                scale = min(tw / orig_w, th / orig_h)
                nw, nh = int(orig_w * scale), int(orig_h * scale)
                resized_raw = raw.resize((nw, nh), Image.LANCZOS)
                if resized_raw.mode == 'RGBA':
                    bg = Image.new('RGB', (nw, nh), (255, 255, 255))
                    bg.paste(resized_raw, mask=resized_raw.split()[3])
                    resized_raw = bg
                img.paste(resized_raw, ((tw - nw) // 2, (th - nh) // 2))
            else:
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

        # 检查文件大小：超高分辨率/SD生图 (6-8MB) 严格压缩至 1.8MB 以内 (符合微信封面 ≤2MB 限制与移动端体验)
        out_path = img_path
        img.save(out_path, 'JPEG', quality=90, optimize=True)

        file_size_mb = os.path.getsize(out_path) / (1024 * 1024)
        max_mb = 1.8  # 统一所有图片上限为 1.8MB (针对生图 6-8MB 进行自动优化)
        quality = 85
        while file_size_mb > max_mb and quality > 25:
            img.save(out_path, 'JPEG', quality=quality, optimize=True)
            file_size_mb = os.path.getsize(out_path) / (1024 * 1024)
            quality -= 15

        logger.debug("  resize_for_wechat: {} -> {}x{}, {:.2f}MB",
                     os.path.basename(img_path), tw, th, file_size_mb)
        return out_path
    except Exception as e:
        logger.warning("  resize_for_wechat failed: {}", e)
        return img_path


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


# ==========================================
#  Stable Diffusion 本地生图与端口动态探测
# ==========================================
_detected_sd_url = None
_last_sd_check_time = 0

def detect_sd_api_url():
    """
    自动探测本地 Stable Diffusion WebUI 运行的端口和 Host。
    扫描常见端口并测试 /sdapi/v1/sd-models 连通性。
    """
    import requests
    from config import SD_API_URL
    
    candidate_urls = [SD_API_URL] if SD_API_URL else []
    
    # 增加常见端口列表，WebUI默认7860/7861/7862等
    ports = [7860, 7861, 7862, 7863, 7865]
    hosts = ["127.0.0.1", "localhost"]
    for host in hosts:
        for port in ports:
            url = f"http://{host}:{port}"
            if url not in candidate_urls:
                candidate_urls.append(url)
                
    logger.info("🔍 开始探测本地 Stable Diffusion API 端口...")
    for url in candidate_urls:
        try:
            resp = requests.get(f"{url}/sdapi/v1/sd-models", timeout=1.0)
            if resp.status_code == 200:
                logger.info("  ✅ 成功探测到 Stable Diffusion 服务在: {}", url)
                return url
        except Exception:
            continue
            
    logger.warning("  ❌ 未在任何常见端口检测到本地 Stable Diffusion 服务。")
    return None

def get_sd_api_url():
    global _detected_sd_url, _last_sd_check_time
    now = time.time()
    # 如果未探测到，或者探测失败后超过 60 秒，则重新进行探测
    if _detected_sd_url is None and (now - _last_sd_check_time > 60):
        _detected_sd_url = detect_sd_api_url()
        _last_sd_check_time = now
    return _detected_sd_url

def _try_local_sd(keyword, directory, width=1024, height=576, max_retries=None, prompt=None, prefix="local_sd"):
    """
    调用本地 Stable Diffusion WebUI API 生图（唯一生图源）。
    要求 WebUI 启动时带上 --api 参数。
    prompt: 直接传入预构建的 prompt；为 None 时从 keyword 自动生成。
    prefix: 保存文件名前缀。
    支持用户中断（检查 cancel_event）。
    """
    import requests
    import base64
    from core.shared.runtime import cancel_event, WorkflowCancelled

    if max_retries is None:
        max_retries = SD_MAX_RETRIES

    # ---- 1. 健康检查：SD 服务是否存活 ----
    sd_url = get_sd_api_url()
    if not sd_url:
        return None

    try:
        health = requests.get(f"{sd_url}/sdapi/v1/sd-models", timeout=5)
        if health.status_code != 200:
            logger.warning("  本地 SD 服务未就绪 (status={})，跳过 SD 生图", health.status_code)
            return None
    except requests.exceptions.ConnectionError:
        logger.warning("  本地 SD 服务连接断开，重新探测...")
        global _detected_sd_url
        _detected_sd_url = None
        return None
    except Exception:
        logger.warning("  本地 SD 健康检查失败，跳过 SD 生图")
        return None

    if prompt is None:
        prompt = _build_pollinations_prompt(keyword)
    logger.info("  本地 Stable Diffusion 生图中 ({}x{}, steps={}): {}", width, height, SD_STEPS, prompt[:60])

    payload = {
        "prompt": prompt,
        "negative_prompt": "nsfw, nude, naked, suggestive, porn, text, words, letters, logo, watermark, "
                           "lowres, bad anatomy, bad hands, error, missing fingers, extra digit, fewer digits, "
                           "cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, "
                           "username, blurry, human face, portrait, person",
        "steps": SD_STEPS,
        "width": width,
        "height": height,
        "cfg_scale": 7.5,
        "sampler_name": "Euler a",
        "seed": -1
    }

    total_attempts = max_retries + 1  # 首次 + 重试
    for attempt in range(1, total_attempts + 1):
        if cancel_event.is_set():
            raise WorkflowCancelled("SD 生图被用户中断")

        try:
            # ---- 2. 发起生图请求（120s 超时） ----
            resp = requests.post(f"{sd_url}/sdapi/v1/txt2img", json=payload, timeout=SD_TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                if "images" in data and len(data["images"]) > 0:
                    image_data = base64.b64decode(data["images"][0])
                    save_path = os.path.join(directory, f"{prefix}_{int(time.time())}.jpg")
                    os.makedirs(directory, exist_ok=True)
                    with open(save_path, "wb") as f:
                        f.write(image_data)
                    logger.info("  本地 SD 生图成功: {}x{} (第 {} 次)", width, height, attempt)
                    return save_path
                else:
                    logger.warning("  SD 返回空图片 (第 {}/{} 次)", attempt, total_attempts)
            else:
                logger.warning("  SD 请求失败: status={} (第 {}/{} 次)", resp.status_code, attempt, total_attempts)
                # 4xx 错误不重试
                if 400 <= resp.status_code < 500:
                    return None

        except requests.exceptions.ConnectionError:
            # ---- 3. 连接失败不重试（服务已离线） ----
            logger.warning("  SD 服务连接中断，跳过 SD 生图")
            _detected_sd_url = None
            return None
        except requests.exceptions.Timeout:
            logger.warning("  SD 生图超时 ({}s) (第 {}/{} 次)", SD_TIMEOUT, attempt, total_attempts)
        except Exception as e:
            if isinstance(e, WorkflowCancelled):
                raise
            logger.warning("  SD 生图异常: {} (第 {}/{} 次)", e, attempt, total_attempts)

        # ---- 4. 可中断退避等待 ----
        if attempt < total_attempts:
            wait = min(8, 2 ** (attempt - 1))
            logger.info("  等待 {} 秒后重试...", wait)
            if cancel_event.wait(timeout=wait):
                raise WorkflowCancelled("SD 生图被用户中断")

    logger.error("  本地 SD 在 {} 次尝试后仍然失败", total_attempts)
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
#  免费图源降级层 (SD 不可用时自动启用)
# ==========================================
def _save_image_from_url(img_url, target_dir, prefix="free", timeout=15):
    """从 URL 下载图片并保存，返回路径或 None"""
    import requests
    try:
        resp = requests.get(img_url, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        if resp.status_code == 200 and len(resp.content) > 1024:
            ext = ".jpg"
            ct = resp.headers.get("Content-Type", "")
            if "png" in ct:
                ext = ".png"
            elif "webp" in ct:
                ext = ".webp"
            save_path = os.path.join(target_dir, f"{prefix}_{int(time.time())}{ext}")
            with open(save_path, "wb") as f:
                f.write(resp.content)
            # Validate image
            from PIL import Image
            try:
                img = Image.open(save_path)
                img.verify()
                img = Image.open(save_path)
                if img.width >= 200 and img.height >= 150:
                    logger.info("  免费图源下载成功: {} ({}x{})", os.path.basename(save_path), img.width, img.height)
                    return save_path
                else:
                    os.remove(save_path)
            except Exception:
                if os.path.exists(save_path):
                    os.remove(save_path)
    except Exception as e:
        logger.debug("  免费图源下载失败 ({}): {}", img_url[:60], e)
    return None


def _try_pexels_api(keyword, width, height):
    """尝试 Pexels API（需 PEXELS_API_KEY 环境变量）"""
    import requests
    from config import PEXELS_API_KEY
    if not PEXELS_API_KEY:
        return None
    try:
        resp = requests.get("https://api.pexels.com/v1/search", params={
            "query": keyword, "per_page": 3, "orientation": "landscape"
        }, headers={"Authorization": PEXELS_API_KEY}, timeout=10)
        if resp.status_code == 200:
            photos = resp.json().get("photos", [])
            for photo in photos:
                src = photo.get("src", {}).get("large") or photo.get("src", {}).get("original")
                if src:
                    return src
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        logger.debug("  Pexels API 连接异常: {}", e)
        raise e
    except Exception as e:
        logger.debug("  Pexels API 失败: {}", e)
    return None


def _try_unsplash_api(keyword, width, height):
    """尝试 Unsplash 官方 API（需 UNSPLASH_ACCESS_KEY 环境变量）"""
    import requests
    from config import UNSPLASH_ACCESS_KEY
    if not UNSPLASH_ACCESS_KEY:
        return None
    try:
        resp = requests.get("https://api.unsplash.com/search/photos", params={
            "query": keyword, "per_page": 3, "orientation": "landscape"
        }, headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"}, timeout=10)
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            for r in results:
                raw_url = r.get("urls", {}).get("raw")
                if raw_url:
                    return f"{raw_url}&w={width}&h={height}&fit=crop"
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        logger.debug("  Unsplash API 连接异常: {}", e)
        raise e
    except Exception as e:
        logger.debug("  Unsplash API 失败: {}", e)
    return None


def _try_baidu_api(keyword, target_dir, width=900, height=500):
    """尝试百度图片搜索 API (针对中文热点实拍图极其精准高效)"""
    import urllib.parse
    import requests
    clean_kw = _extract_concise_keywords(keyword)
    if not clean_kw:
        return None
    q = urllib.parse.quote(clean_kw)
    url = f"https://image.baidu.com/search/acjson?tn=resultjson_com&ipn=rj&word={q}&pn=0&rn=12"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            res_json = resp.json()
            data = res_json.get("data", [])
            for item in data:
                img_url = item.get("middleURL") or item.get("hoverURL") or item.get("thumbURL")
                if img_url and img_url.startswith("http"):
                    path = _save_image_from_url(img_url, target_dir, prefix="baidu", timeout=6)
                    if path:
                        return path
    except Exception as e:
        logger.debug("  百度图片搜索失败: {}", e)
    return None


def _try_pollinations_api(keyword, target_dir, width=900, height=500):
    """尝试 Pollinations.ai 免费 AI 生图 (无需 API Key，全局可用)，含 retry + 429 退避"""
    import urllib.parse
    import requests
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            prompt_str = _build_pollinations_prompt(keyword)
            encoded_prompt = urllib.parse.quote(prompt_str[:200])
            url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&nologo=true"
            path = _save_image_from_url(url, target_dir, prefix="pollinations", timeout=30)
            if path:
                return path
            logger.debug("  Pollinations 第 {}/{} 次未返回有效图片", attempt, max_attempts)
        except Exception as e:
            logger.debug("  Pollinations AI 生图失败 (第 {}/{}): {}", attempt, max_attempts, e)
        # 退避等待（处理 429 限流）
        if attempt < max_attempts:
            wait = 3 * attempt
            logger.debug("  Pollinations 等待 {}s 后重试...", wait)
            time.sleep(wait)
    return None


def _try_icrawler_bing(keyword, target_dir, max_images=3):
    """通过 icrawler 从 Bing 搜索下载图片（无需 API Key）"""
    try:
        from icrawler.builtin import BingImageCrawler
        import tempfile

        tmp_dir = tempfile.mkdtemp(prefix="aw_img_")
        downloaded = []

        crawler = BingImageCrawler(
            feeder_threads=1,
            parser_threads=1,
            downloader_threads=2,
            storage={"root_dir": tmp_dir}
        )

        original_download = crawler.downloader.download

        def tracking_download(task, *args, **kwargs):
            result = original_download(task, *args, **kwargs)
            if result:
                downloaded.append(result)
            return result

        crawler.downloader.download = tracking_download

        crawler.crawl(
            keyword=keyword,
            max_num=min(max_images, 2),
            min_size=(200, 150),
            file_idx_offset=0
        )

        for root, dirs, files in os.walk(tmp_dir):
            for f in files:
                if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                    src = os.path.join(root, f)
                    dst = os.path.join(target_dir, f"bing_{int(time.time())}_{f}")
                    os.rename(src, dst)
                    from PIL import Image
                    try:
                        img = Image.open(dst)
                        img.verify()
                        img = Image.open(dst)
                        if img.width >= 200 and img.height >= 150:
                            logger.info("  icrawler Bing 下载成功: {} ({}x{})", os.path.basename(dst), img.width, img.height)
                            return dst
                        else:
                            os.remove(dst)
                    except Exception:
                        if os.path.exists(dst):
                            os.remove(dst)

        import shutil
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

    except ImportError:
        logger.debug("  icrawler 不可用")
    except Exception as e:
        logger.debug("  icrawler Bing 下载失败: {}", e)

    return None


def _extract_concise_keywords(keyword):
    """从长句子/标题中提取 2-4 个核心关键字，用于搜索引擎精准检索"""
    if not keyword or not keyword.strip():
        return ""

    clean_text = keyword.strip()

    try:
        import jieba.analyse
        tags = jieba.analyse.extract_tags(clean_text, topK=4)
        if tags:
            return " ".join(tags)
    except Exception:
        pass

    clean_text = re.sub(r'[^\w\s\u4e00-\u9fa5]', ' ', clean_text)
    words = [w for w in clean_text.split() if len(w) > 1]
    return " ".join(words[:4]) if words else clean_text[:20]


# ---- LLM 关键词翻译缓存 ----
_keyword_translation_cache = {}


def _translate_keyword_via_llm(keyword):
    """用 DeepSeek 将中文关键词翻译为适合英文图片搜索的 2-5 个英文词"""
    if keyword in _keyword_translation_cache:
        return _keyword_translation_cache[keyword]

    # 如果关键词本身就是纯英文，直接返回
    if re.match(r'^[a-zA-Z0-9\s\-_.,]+$', keyword.strip()):
        return keyword.strip()

    try:
        from core.shared.llm import call_deepseek_with_retry
        system_prompt = (
            "你是一个翻译引擎。将用户输入的中文关键词/标题翻译为 2-5 个最适合在 "
            "Unsplash/Pexels 等英文图片网站搜索的英文关键词。\n"
            "规则：只输出英文关键词，用空格分隔，不要解释，不要标点。\n"
            "示例：输入'华为发布AI芯片' → 输出'Huawei AI chip technology'"
        )
        result = call_deepseek_with_retry(keyword, system_content=system_prompt)
        if result and len(result.strip()) > 2:
            translated = result.strip().split('\n')[0].strip()
            _keyword_translation_cache[keyword] = translated
            logger.info("  关键词翻译: '{}' → '{}'", keyword, translated)
            return translated
    except Exception as e:
        logger.debug("  LLM 关键词翻译失败: {}", e)

    # Fallback: 使用硬编码映射表
    return _enhance_search_keyword_static(keyword)


def _enhance_search_keyword_static(keyword):
    """将抽象中文概念转为更适合图片搜索的英文关键词（静态映射表兜底）"""
    ai_term_map = {
        "注意力机制": "attention mechanism neural network diagram",
        "Transformer": "transformer architecture deep learning",
        "神经网络": "neural network visualization",
        "深度学习": "deep learning artificial intelligence",
        "机器学习": "machine learning data science",
        "反向传播": "backpropagation neural network",
        "梯度下降": "gradient descent optimization",
        "大模型": "large language model AI",
        "RAG": "retrieval augmented generation architecture",
        "Agent": "AI agent autonomous",
        "嵌入": "word embedding vector representation",
        "Token": "tokenization natural language processing",
        "微调": "fine tuning machine learning",
        "预训练": "pretraining language model",
        "多模态": "multimodal AI vision language",
        "量化": "model quantization optimization",
        "推理": "AI inference engine",
        "卷积": "convolutional neural network",
        "编码器": "encoder transformer architecture",
        "解码器": "decoder transformer architecture",
        "华为": "Huawei technology headquarters",
        "芯片": "semiconductor microchip technology",
        "半导体": "semiconductor manufacturing",
        "中美": "US China technology competition",
        "科技制裁": "technology sanctions global",
        "航天": "space exploration rocket",
        "量子计算": "quantum computing",
        "自动驾驶": "autonomous driving car",
        "机器人": "humanoid robot advanced",
        "网络安全": "cybersecurity digital",
        "数字经济": "digital economy smart city",
        "区块链": "blockchain distributed ledger",
        "新能源": "renewable energy solar wind",
        "元宇宙": "metaverse virtual reality",
        "脑机接口": "brain computer interface neural",
        "5G": "5G network tower connected",
        "数据安全": "data protection encryption",
    }
    for cn, en in ai_term_map.items():
        if cn in keyword:
            return en
    return keyword


def _enhance_search_keyword(keyword):
    """将中文关键词转为适合英文图片搜索的关键词（优先 LLM 翻译，兜底静态映射）"""
    return _translate_keyword_via_llm(keyword)


_image_sources_status = {
    "unsplash_api": {"status": True, "last_check": 0},
    "pexels_api": {"status": True, "last_check": 0},
    "pollinations": {"status": True, "last_check": 0},
    "bing": {"status": True, "last_check": 0}
}


def is_source_available(source_name):
    """检查图源当前是否可用（避免被拉黑或墙掉后重复等待超时）"""
    now = time.time()
    info = _image_sources_status.get(source_name)
    if not info:
        return True
    if not info["status"] and (now - info["last_check"] < 300):
        return False
    return True


def mark_source_failed(source_name):
    """将图源标记为失效"""
    _image_sources_status[source_name] = {
        "status": False,
        "last_check": time.time()
    }
    logger.warning("  ⚠️ 图源 {} 已标记为不可用，将在 5 分钟内跳过，防止请求持续超时", source_name)


def mark_source_success(source_name):
    """标记图源成功"""
    _image_sources_status[source_name] = {
        "status": True,
        "last_check": time.time()
    }


def _download_free_image(keyword, save_dir, purpose="body"):
    """
    免费图源降级下载（SD 不可用时自动启用）。
    优先级（无需 API Key 的源优先）：
    1. Pollinations.ai 免费 AI 生图 (无需 Key, 高质量定制图)
    2. icrawler Bing 搜图 (无需 Key, 实拍高清图)
    3. Unsplash 官方 API (需 UNSPLASH_ACCESS_KEY, 有则用)
    4. Pexels 官方 API (需 PEXELS_API_KEY, 有则用)
    注：百度图片 API 已被反爬封杀 (Forbid spider access)，已移除。
    """
    import requests
    if not keyword or not keyword.strip():
        return None

    width, height = (900, 383) if purpose == "cover" else (900, 500)

    clean_kw = _sanitize_path(keyword)
    target_dir = os.path.join(save_dir, clean_kw)
    os.makedirs(target_dir, exist_ok=True)

    search_keyword = _enhance_search_keyword(keyword)
    concise_keyword = _extract_concise_keywords(keyword)

    logger.info("🖼️  免费图源下载 '{}' (英文检索词: '{}')...", keyword, search_keyword)

    # 1. Pollinations.ai 免费 AI 生图 (无需 API Key，最可靠的无 Key 图源)
    if is_source_available("pollinations"):
        try:
            path = _try_pollinations_api(keyword, target_dir, width, height)
            if path:
                mark_source_success("pollinations")
                return path
            else:
                mark_source_failed("pollinations")
        except Exception as e:
            logger.debug("  Pollinations AI 异常: {}", e)
            mark_source_failed("pollinations")

    # 2. icrawler Bing 搜索 (无需 API Key，使用英文翻译关键词)
    if is_source_available("bing"):
        try:
            # 优先用 LLM 翻译后的英文关键词搜索
            bing_keyword = search_keyword if search_keyword != keyword else concise_keyword
            path = _try_icrawler_bing(bing_keyword, target_dir)
            if path:
                mark_source_success("bing")
                return path
        except Exception:
            mark_source_failed("bing")

    # 3. Unsplash 官方 API（有 Key 才尝试）
    from config import UNSPLASH_ACCESS_KEY
    if UNSPLASH_ACCESS_KEY and is_source_available("unsplash_api"):
        try:
            img_url = _try_unsplash_api(search_keyword, width, height)
            if img_url:
                path = _save_image_from_url(img_url, target_dir, prefix="unsplash")
                if path:
                    mark_source_success("unsplash_api")
                    return path
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            mark_source_failed("unsplash_api")
        except Exception:
            pass

    # 4. Pexels 官方 API（有 Key 才尝试）
    from config import PEXELS_API_KEY
    if PEXELS_API_KEY and is_source_available("pexels_api"):
        try:
            img_url = _try_pexels_api(search_keyword, width, height)
            if img_url:
                path = _save_image_from_url(img_url, target_dir, prefix="pexels")
                if path:
                    mark_source_success("pexels_api")
                    return path
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            mark_source_failed("pexels_api")
        except Exception:
            pass

    logger.warning("  ⚠️ 所有免费图源均失败，'{}' 无配图", keyword)
    return None


# ==========================================
#  文字卡图本地兜底生成
# ==========================================
def generate_default_cover(title, save_path, purpose="cover"):
    """
    用 Pillow 动态生成一个高颜值的文字封面卡片，作为终极兜底。
    - cover 尺寸: 900x383
    - body 尺寸: 900x500
    """
    w, h = (900, 383) if purpose == "cover" else (900, 500)
    
    # 1. 创建渐变色背景 (从深蓝/黑色到深灰)
    base = Image.new("RGB", (w, h), (11, 14, 20))  # #0b0e14
    draw = ImageDraw.Draw(base)
    
    # 绘制对角渐变
    for y in range(h):
        for x in range(w):
            factor = (x / w + y / h) / 2
            r = int(15 + (30 - 15) * factor)
            g = int(23 + (41 - 23) * factor)
            b = int(42 + (59 - 42) * factor)
            base.putpixel((x, y), (r, g, b))
            
    # 2. 绘制装饰边框或网格 (比如左侧画一条渐变色装饰条)
    draw.rectangle([0, 0, 12, h], fill=(59, 130, 246))  # #3b82f6
    draw.rectangle([12, 0, 16, h], fill=(6, 182, 212))  # #06b6d4

    # 3. 写入标题文字
    font_paths = [
        "C:\\Windows\\Fonts\\msyh.ttc",    # 微软雅黑
        "C:\\Windows\\Fonts\\msyhbd.ttc",  # 微软雅黑粗体
        "C:\\Windows\\Fonts\\simhei.ttf",   # 黑体
        "msyh.ttc",
        "arial.ttf"
    ]
    
    font = None
    font_size = 40 if purpose == "cover" else 44
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, font_size)
                break
            except Exception:
                continue
                
    if not font:
        font = ImageFont.load_default()

    # 简单的文字自动换行
    max_char_per_line = 14 if purpose == "cover" else 16
    lines = []
    current_line = ""
    for char in title:
        current_line += char
        if len(current_line) >= max_char_per_line:
            lines.append(current_line)
            current_line = ""
    if current_line:
        lines.append(current_line)
        
    lines = lines[:3]
    
    line_height = font_size + 15
    total_text_height = len(lines) * line_height
    y_offset = (h - total_text_height) // 2
    
    for line in lines:
        draw.text((60, y_offset), line, fill=(241, 245, 249), font=font)  # #f1f5f9
        y_offset += line_height
        
    # 5. 绘制右下角的小标注
    tag_font = None
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                tag_font = ImageFont.truetype(fp, 18)
                break
            except Exception:
                continue
    if not tag_font:
        tag_font = ImageFont.load_default()
        
    draw.text((60, h - 50), "科学科普专栏 • AI AUTOMATION", fill=(100, 116, 139), font=tag_font)  # #64748b

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    base.save(save_path, "JPEG", quality=95)
    logger.info("  [兜底卡图] 已成功绘制并保存本地兜底文字卡片: {}", save_path)
    return save_path


# ==========================================
#  核心下载与图源调度接口
# ==========================================
def download_image(keyword, save_dir="assets"):
    """
    下载正文配图：优先本地 SD，不可用时自动降级到免费图源。
    若全部失效，则自动调用本地 Pillow 引擎绘制高颜值文字卡片配图兜底。
    """
    if not keyword or not keyword.strip():
        return None

    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    clean_keyword = _sanitize_path(keyword)
    specific_dir = os.path.join(save_dir, clean_keyword)
    if not os.path.exists(specific_dir):
        os.makedirs(specific_dir)

    # 1. 高清真实网络图源 (Unsplash / Pexels / Bing)
    logger.info("正在搜寻网络高清实拍图源: '{}'...", keyword)
    best = _download_free_image(keyword, save_dir, purpose="body")
    if best:
        best = _finalize_image(best, "body")
        if best:
            return best

    # 3. 降级到本地 SD 引擎 (弱显卡备选)
    logger.info("搜寻本地 SD 生图: '{}'...", keyword)
    best = _try_local_sd(keyword, specific_dir, width=1024, height=576)
    if best:
        best = _finalize_image(best, "body")
        if best:
            return best

    # 3. 终极兜底：当所有免费图源也失效时，自动在本地绘制文字卡片配图
    logger.warning("  ⚠️ 正文配图图源全部失效，启用本地文字卡片自动兜底机制...")
    fallback_path = os.path.join(specific_dir, f"body_fallback_{int(time.time())}.jpg")
    try:
        generate_default_cover(keyword, fallback_path, purpose="body")
        if os.path.exists(fallback_path):
            return fallback_path
    except Exception as e:
        logger.error("  [兜底配图] 生成兜底配图异常: {}", e)

    return None


def download_cover_image(keyword, save_dir="assets"):
    """
    下载封面图：优先本地 SD，不可用时自动降级到免费图源。
    若全部失效，则自动调用本地 Pillow 引擎绘制高颜值文字卡片封面兜底。
    """
    if not keyword or not keyword.strip():
        return None

    clean_keyword = _sanitize_path(f"{keyword}_cover")
    specific_dir = os.path.join(save_dir, clean_keyword)
    if not os.path.exists(specific_dir):
        os.makedirs(specific_dir)

    # 1. 高清真实网络图源 (Unsplash / Pexels / Bing)
    logger.info("正在搜寻网络高清实拍封面图源: '{}'...", keyword)
    best = _download_free_image(keyword, save_dir, purpose="cover")
    if best:
        best = _finalize_image(best, "cover")
        if best:
            return best

    # 3. 降级到本地 SD 引擎
    logger.info("搜寻本地 SD 封面生图: '{}'...", keyword)
    best = _try_local_sd(keyword, specific_dir, width=1280, height=545)
    if best:
        best = _finalize_image(best, "cover")
        if best:
            return best

    # 3. 终极兜底：当所有免费图源也失效时，自动在本地绘制文字卡片封面
    logger.warning("  ⚠️ 封面图源全部失效，启用本地文字卡片自动兜底机制...")
    fallback_path = os.path.join(specific_dir, f"cover_fallback_{int(time.time())}.jpg")
    try:
        generate_default_cover(keyword, fallback_path, purpose="cover")
        if os.path.exists(fallback_path):
            return fallback_path
    except Exception as e:
        logger.error("  [兜底封面] 生成兜底封面异常: {}", e)

    # 4. 最基础的静态图片兜底 (若上面均失败了)
    if os.path.exists(LOCAL_FALLBACK_IMAGE):
        return LOCAL_FALLBACK_IMAGE

    return None


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

