"""
============================================================
  AI 配图与封面生成引擎 (微信适配版)
  策略：Google Gemini Nano Banana 2.1 -> Qwen-Image-3.0 -> 本地 Stable Diffusion -> Pillow 矢量卡片兜底
============================================================
"""
import base64
import io
import os
import re
import json
import time
import threading
import tempfile
from datetime import datetime
from pathlib import Path
import config
from core.shared.runtime import WorkflowCancelled, cancel_event, check_cancelled
from contextlib import contextmanager
from PIL import Image, ImageDraw, ImageFont

# 屏蔽 OpenCV 的损坏图片警告
os.environ["OPENCV_LOG_LEVEL"] = "SILENT"
try:
    import cv2
    cv2.setLogLevel(0)  # 0=SILENT, 屏蔽 imread 失败的 WARN
except (ImportError, AttributeError):
    pass

from config import WECHAT_COVER_WIDTH, WECHAT_COVER_HEIGHT, WECHAT_BODY_WIDTH, WECHAT_BODY_HEIGHT, WECHAT_BODY_MAX_MB

from loguru import logger

from utils.redraw_transport import fetch_public
from utils.key_pool import ApiKeyPool, RateLimiter

# ---- 微信图片规格 ----
WECHAT_COVER_SIZE = (WECHAT_COVER_WIDTH, WECHAT_COVER_HEIGHT)
WECHAT_BODY_SIZE = (WECHAT_BODY_WIDTH, WECHAT_BODY_HEIGHT)
LOCAL_FALLBACK_IMAGE = (
    os.path.join("assets", "default_aikepu_cover.png")
    if os.path.exists(os.path.join("assets", "default_aikepu_cover.png"))
    else (
        os.path.join("assets", "default_daily_cover.png")
        if os.path.exists(os.path.join("assets", "default_daily_cover.png"))
        else os.path.join("static", "images", "github_fixed_cover.png")
    )
)

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
        source = Path(img_path).resolve()
        out_path = img_path
        if (source.suffix.lower() not in {".jpg", ".jpeg"}
                or source.name.lower().startswith("default_")
                or "static" in (part.lower() for part in source.parts)):
            directory = Path("assets") / "_resized"
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=directory, prefix=source.stem[:48] + "_",
                                             suffix="_wechat.jpg", delete=False) as derived:
                out_path = derived.name
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
        return img_path if (img_path and os.path.exists(img_path)) else None


# ==========================================
#  英文生图提示词构建
# ==========================================
def _build_sd_image_prompt(keyword):
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
    except WorkflowCancelled:
        raise
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


# 保持向后兼容别名
_build_image_prompt = _build_sd_image_prompt


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
    if not config.SD_ENABLED:
        return None
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

    check_cancelled()
    if not config.SD_ENABLED:
        return None
    if max_retries is None:
        max_retries = config.SD_MAX_RETRIES

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
        prompt = _build_image_prompt(keyword)
    logger.info("  本地 Stable Diffusion 生图中 ({}x{}, steps={}): {}", width, height, config.SD_STEPS, prompt[:60])

    payload = {
        "prompt": prompt,
        "negative_prompt": "nsfw, nude, naked, suggestive, porn, text, words, letters, logo, watermark, "
                           "lowres, bad anatomy, bad hands, error, missing fingers, extra digit, fewer digits, "
                           "cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, "
                           "username, blurry, human face, portrait, person",
        "steps": config.SD_STEPS,
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
            resp = requests.post(f"{sd_url}/sdapi/v1/txt2img", json=payload, timeout=config.SD_TIMEOUT)
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
            logger.warning("  SD 生图超时 ({}s) (第 {}/{} 次)", config.SD_TIMEOUT, attempt, total_attempts)
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
    except WorkflowCancelled:
        raise
    except Exception as e:
        logger.warning("  DeepSeek 为 GitHub 项目生成 Prompt 失败: {}", e)

    # Fallback: 使用通用的 prompt 构建器
    fallback_keyword = f"{repo_name.split('/')[-1]} {lang} open source project"
    return _build_image_prompt(fallback_keyword)


def download_project_image_for_github(repo_name, description, lang, topics=None, save_dir="assets"):
    """
    为 GitHub 项目生成 SD 艺术配图。
    使用 DeepSeek 将项目信息转化为高质量 SD 提示词，然后调用本地 SD 生图。
    返回本地图片路径。
    """
    check_cancelled()
    if not repo_name or not config.SD_ENABLED:
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
#  网络图片下载与完整性校验工具
# ==========================================
def _save_image_from_url(url, target_dir, prefix="img", timeout=30):
    """从网络 URL 下载图片并保存到 target_dir，包含防盗链头、大小检验及 PIL 完整性校验"""
    if not url:
        return None
    import io
    from PIL import Image
    os.makedirs(target_dir, exist_ok=True)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }
    if "qpic.cn" in url:
        headers["Referer"] = "https://mp.weixin.qq.com/"

    try:
        content = fetch_public(url, timeout=timeout, headers=headers, max_bytes=16 * 1024 * 1024)
        if len(content) >= 512:
            # 严格使用 PIL 校验图片字节流完整性，杜绝 HTML 403 页面伪装为图片
            try:
                with Image.open(io.BytesIO(content)) as test_img:
                    test_img.verify()
                    format_name = (test_img.format or "").lower()
            except Exception as ve:
                logger.debug("  下载内容非有效图片 ({}) : {}", url[:60], ve)
                return None

            ext = ".png" if format_name == "png" else (".webp" if format_name == "webp" else ".jpg")
            filename = f"{prefix}_{int(time.time() * 1000)}{ext}"
            save_path = os.path.join(target_dir, filename)
            with open(save_path, "wb") as f:
                f.write(content)
            return save_path
        else:
            logger.warning("Image too small ({} bytes)", len(content))
    except Exception as e:
        logger.warning("  从 URL 保存图片异常 ({}): {}", url[:60], e)
    return None


_qwen_pool_lock = threading.Lock()
_qwen_key_pool = None
_qwen_image_limiter = None
_qwen_image_sem = None

_qwen_quota_lock = threading.Lock()
_DEFAULT_QWEN_QUOTA_FILE = Path("data") / "qwen_image_quota.json"
_QWEN_QUOTA_FILE = _DEFAULT_QWEN_QUOTA_FILE
_qwen_memory_quota = {}


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _use_memory_quota() -> bool:
    return bool(os.getenv("PYTEST_CURRENT_TEST")) and _QWEN_QUOTA_FILE == _DEFAULT_QWEN_QUOTA_FILE


def _memory_quota_key(today: str) -> tuple:
    test_id = os.getenv("PYTEST_CURRENT_TEST", "").split(" ", 1)[0]
    return (today, test_id)


def _get_qwen_daily_limit() -> int:
    try:
        return max(0, int(getattr(config, "QWEN_IMAGE_DAILY_LIMIT", 6)))
    except (TypeError, ValueError):
        return 6


def _load_qwen_daily_count_unlocked(today: str) -> int:
    if _use_memory_quota():
        return int(_qwen_memory_quota.get(_memory_quota_key(today), 0))
    quota_path = Path(_QWEN_QUOTA_FILE)
    if not quota_path.exists():
        return 0
    try:
        data = json.loads(quota_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("date") == today:
            return max(0, int(data.get("count", 0)))
    except Exception:
        pass
    return 0


def _save_qwen_daily_count_unlocked(today: str, count: int) -> None:
    safe_count = max(0, int(count))
    if _use_memory_quota():
        _qwen_memory_quota[_memory_quota_key(today)] = safe_count
        return
    quota_path = Path(_QWEN_QUOTA_FILE)
    quota_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"date": today, "count": safe_count}, ensure_ascii=False)
    with tempfile.NamedTemporaryFile(
        dir=quota_path.parent, mode="w", encoding="utf-8", delete=False, suffix=".tmp"
    ) as tmp:
        tmp.write(payload)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, quota_path)


def reset_qwen_daily_quota() -> None:
    """重置当日 Qwen-Image 生图计数（测试与运维使用）。"""
    with _qwen_quota_lock:
        _qwen_memory_quota.clear()
        if not _use_memory_quota():
            quota_path = Path(_QWEN_QUOTA_FILE)
            if quota_path.exists():
                try:
                    quota_path.unlink()
                except OSError:
                    _save_qwen_daily_count_unlocked(_today_str(), 0)


def get_qwen_daily_usage() -> dict:
    """返回当日 Qwen-Image 付费生图配额使用情况。"""
    today = _today_str()
    limit = _get_qwen_daily_limit()
    with _qwen_quota_lock:
        used = _load_qwen_daily_count_unlocked(today)
    return {
        "date": today,
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
    }


def is_qwen_quota_exhausted(needed: int = 1) -> bool:
    """判断当日 Qwen-Image 付费生图额度是否已耗尽或被禁用。"""
    limit = _get_qwen_daily_limit()
    if limit <= 0:
        return True
    today = _today_str()
    with _qwen_quota_lock:
        used = _load_qwen_daily_count_unlocked(today)
    return (used + max(1, int(needed))) > limit


def _reserve_qwen_daily_quota(count: int = 1) -> bool:
    """原子预占当日生图配额；超出硬上限时触发成本熔断。"""
    needed = max(1, int(count))
    limit = _get_qwen_daily_limit()
    today = _today_str()
    with _qwen_quota_lock:
        used = _load_qwen_daily_count_unlocked(today)
        if limit <= 0 or (used + needed) > limit:
            logger.warning(
                "  [成本熔断] 今日 Qwen-Image 生图已达上限 ({}/{})，跳过云端付费生图",
                used,
                limit,
            )
            return False
        _save_qwen_daily_count_unlocked(today, used + needed)
        return True


def _release_qwen_daily_quota(count: int = 1) -> None:
    """生图请求未成功返回 HTTP 200 时退还预占配额。"""
    needed = max(1, int(count))
    today = _today_str()
    with _qwen_quota_lock:
        used = _load_qwen_daily_count_unlocked(today)
        _save_qwen_daily_count_unlocked(today, max(0, used - needed))


def _qwen_image_throttle():
    """懒加载生图节流器 + 并发信号量（按 config 可调）"""
    global _qwen_image_limiter, _qwen_image_sem
    with _qwen_pool_lock:
        if _qwen_image_sem is None:
            from config import QWEN_IMAGE_MIN_INTERVAL, QWEN_IMAGE_MAX_CONCURRENCY
            _qwen_image_limiter = RateLimiter(QWEN_IMAGE_MIN_INTERVAL)
            _qwen_image_sem = threading.Semaphore(max(1, QWEN_IMAGE_MAX_CONCURRENCY))
        return _qwen_image_limiter, _qwen_image_sem


def _get_qwen_key_pool():
    """懒加载千问 Key 轮询池（DASHSCOPE_API_KEYS 逗号分隔 > 单 DASHSCOPE_API_KEY）"""
    global _qwen_key_pool
    with _qwen_pool_lock:
        if _qwen_key_pool is None:
            _qwen_key_pool = ApiKeyPool(config.DASHSCOPE_API_KEYS or [config.QWEN_IMAGE_API_KEY])
        return _qwen_key_pool


def reset_qwen_key_pool():
    global _qwen_key_pool
    with _qwen_pool_lock:
        _qwen_key_pool = None


_gemini_pool_lock = threading.Lock()
_gemini_key_pool = None


def _get_gemini_key_pool():
    """懒加载 Gemini Key 轮询池（GEMINI_API_KEYS 逗号分隔 > 单 GEMINI_API_KEY）"""
    global _gemini_key_pool
    with _gemini_pool_lock:
        if _gemini_key_pool is None:
            keys = list(getattr(config, "GEMINI_API_KEYS", []) or [])
            single = (getattr(config, "GEMINI_API_KEY", "") or "").strip()
            _gemini_key_pool = ApiKeyPool(keys or ([single] if single else []))
        return _gemini_key_pool


def reset_gemini_key_pool():
    global _gemini_key_pool
    with _gemini_pool_lock:
        _gemini_key_pool = None


def _is_gemini_image_preferred() -> bool:
    provider = (getattr(config, "IMAGE_PROVIDER", "auto") or "auto").strip().lower()
    if provider == "qwen":
        return False
    if provider == "gemini":
        return True
    active_model = (getattr(config, "IMAGE_GEN_MODEL", "") or "").strip().lower()
    return active_model.startswith("gemini")


def _get_active_gemini_model() -> str:
    active_model = (getattr(config, "IMAGE_GEN_MODEL", "") or "").strip()
    if active_model.lower().startswith("gemini"):
        return active_model
    return (getattr(config, "GEMINI_IMAGE_MODEL", "gemini-nano-banana-2.1") or "gemini-nano-banana-2.1").strip()


def _resolve_gemini_aspect_ratio(purpose: str) -> str:
    if purpose == "cover":
        return (getattr(config, "GEMINI_IMAGE_COVER_ASPECT_RATIO", "21:9") or "21:9").strip()
    return (getattr(config, "GEMINI_IMAGE_BODY_ASPECT_RATIO", "16:9") or "16:9").strip()


def _get_active_qwen_model() -> str:
    active_model = (getattr(config, "IMAGE_GEN_MODEL", "") or "").strip()
    if active_model.lower().startswith(("qwen", "wanx")):
        return active_model
    return (getattr(config, "QWEN_IMAGE_MODEL", "qwen-image-3.0") or "qwen-image-3.0").strip()


def _normalize_gemini_thinking_level(model: str, level: str) -> str:
    norm = (level or "").strip().lower()
    if norm not in ("minimal", "medium", "high"):
        return ""
    low_model = (model or "").strip().lower()
    if low_model == "gemini-3.1-flash-lite-image" and norm == "medium":
        return "minimal"
    return norm


def _load_reference_image_b64(image_path: str) -> tuple[str, str]:
    """读取参考图并转为 Gemini 兼容的 JPEG/PNG Base64；遇到 WebP 等非直传格式自动转为 RGB JPEG。"""
    low = image_path.lower()
    if low.endswith(".png"):
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii"), "image/png"
    if low.endswith((".jpg", ".jpeg")):
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii"), "image/jpeg"
    with Image.open(image_path) as im:
        if im.mode in ("RGBA", "LA", "P"):
            rgba = im.convert("RGBA")
            bg = Image.new("RGB", rgba.size, (255, 255, 255))
            bg.paste(rgba, mask=rgba.split()[3])
            out_im = bg
        else:
            out_im = im.convert("RGB")
        buf = io.BytesIO()
        out_im.save(buf, format="JPEG", quality=92)
    return base64.b64encode(buf.getvalue()).decode("ascii"), "image/jpeg"


def _qwen_post_with_rotation(base_url, body, timeout):
    """千问接口带 Key 轮询的 POST：限流/欠费/被禁自动切 Key 重试。
    返回 (status_code, json_data)，全失败返回 (None, None)。"""
    import requests
    pool = _get_qwen_key_pool()
    if pool.size == 0:
        return None, None
    max_attempts = min(max(2, pool.size), 5)
    for _ in range(max_attempts):
        check_cancelled()
        try:
            limiter, sem = _qwen_image_throttle()
            while not sem.acquire(timeout=0.1):
                check_cancelled()
            try:
                limiter.wait()
                check_cancelled()
                key = pool.get_key()
                if not key:
                    break
                resp = requests.post(
                    base_url,
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
                    json=body, timeout=timeout,
                )
            finally:
                sem.release()
            if resp.status_code == 200:
                pool.report_success(key)
                try:
                    return resp.status_code, resp.json()
                except Exception:
                    return resp.status_code, None
            if resp.status_code in (401, 403, 429, 500, 502, 503):
                if resp.status_code == 429:
                    logger.warning("  千问 429 明细: {}", resp.text[:200])
                elif resp.status_code in (401, 403):
                    body_lower = (resp.text or "").lower()
                    if "quota" in body_lower or "fund" in body_lower or "exhausted" in body_lower:
                        logger.error(
                            "  💸 千问账户免费额度已耗尽或欠费：请到百炼控制台充值/关闭免费档。响应: {}",
                            resp.text[:160],
                        )
                    else:
                        logger.warning("  千问认证失败 {}: {}", resp.status_code, resp.text[:160])
                pool.report_failure(key, cooldown_seconds=120 if resp.status_code == 429 else 300)
                continue
            return resp.status_code, None
        except requests.RequestException as e:
            logger.debug("  千问接口请求异常（切换 Key）: {}", e)
            pool.report_failure(key)
    return None, None


def _try_qwen_image_batch(prompt, target_dir, count, width=900, height=500):
    """一次请求生成 count 张图（n 参数批量，节省 QPM 与额度）。返回本地路径列表。"""
    from config import QWEN_IMAGE_API_BASE, QWEN_IMAGE_MODEL, QWEN_IMAGE_TIMEOUT, QWEN_IMAGE_SIZE
    import base64
    req_count = max(1, int(count))
    if not _reserve_qwen_daily_quota(req_count):
        return []
    body = {
        "model": QWEN_IMAGE_MODEL,
        "input": {
            "messages": [
                {"role": "user", "content": [{"text": prompt}]}
            ]
        },
        "parameters": {"prompt_extend": False, "size": QWEN_IMAGE_SIZE, "n": req_count},
    }
    try:
        status, data = _qwen_post_with_rotation(QWEN_IMAGE_API_BASE, body, QWEN_IMAGE_TIMEOUT)
    except BaseException:
        _release_qwen_daily_quota(req_count)
        raise
    if status != 200 or not data:
        _release_qwen_daily_quota(req_count)
        logger.warning("  批量生图失败 HTTP {}", status)
        return []
    choices = ((data.get("output") or {}).get("choices") or [])
    contents = (choices[0].get("message") or {}).get("content") if choices else []
    paths = []
    for i, item in enumerate(contents or []):
        ref = item.get("image") or ""
        if not ref:
            continue
        try:
            if ref.startswith("data:"):
                b64 = ref.split(",", 1)[1]
                raw = base64.b64decode(b64)
                p = os.path.join(target_dir, f"qwen_batch_{int(time.time())}_{i}.png")
                with open(p, "wb") as f:
                    f.write(raw)
                paths.append(p)
            else:
                p = _save_image_from_url(ref, target_dir, prefix=f"qwen_batch_{i}", timeout=60)
                if p:
                    paths.append(p)
        except Exception as e:
            logger.debug("  批量图解析失败 #{}: {}", i, e)
    logger.info("  批量生图返回 {} 张", len(paths))
    return paths


def generate_article_images_batch(title, article_text, keywords, save_dir="assets", max_images=4):
    """每篇文章一次生图请求：用文章标题+各占位符主题构建分项提示词，一次生成多张配图。
    返回与 keywords 等长的本地路径列表（失败或重复项为 None），调用方回退逐关键词下载。"""
    if not keywords or not _get_qwen_key_pool().size:
        return [None] * len(keywords)
    kws = keywords[:max_images]
    excerpt = re.sub(r"[\n\r\t ]+", " ", article_text or "")[:300]
    
    prompt_parts = [f"图#{i+1}主题：{kw}" for i, kw in enumerate(kws)]
    prompt = (
        f"为公众号文章《{title}》生成一组风格统一但构图与信息焦点各不相同的高清浅色科技编辑信息图。\n"
        f"文章摘要：{excerpt}。\n"
        f"共需 {len(kws)} 张图：\n" + "；".join(prompt_parts) + "\n"
        "要求：纯净浅灰白底色，瑞士网格现代扁平信息图设计，每张图包含 1 句醒目简短简体中文主标题与 2-4 个核心中文要点标签，字体清晰无乱码，四周留白充足，严禁赛博黑底霓虹与水印。"
    )
    clean_title = _sanitize_path(title)[:24] if title else "batch"
    target_dir = os.path.join(save_dir, clean_title or "batch")
    os.makedirs(target_dir, exist_ok=True)
    paths = _try_qwen_image_batch(prompt, target_dir, len(kws))
    
    result = [None] * len(keywords)
    if not paths:
        return result

    from .image_filter import compute_perceptual_hash
    for i in range(min(len(kws), len(paths))):
        p = paths[i]
        if p and os.path.exists(p):
            phash = compute_perceptual_hash(p)
            if phash and not _is_too_similar_to_existing(phash):
                result[i] = p
                _register_hash(phash)
            else:
                logger.debug("  批量生成的第 {} 张图与已有图片高度相似，舍弃并回退独立下载", i + 1)
    return result


_qwen_prompt_tls = threading.local()

_SLOT_LAYOUT_ARCHETYPES = (
    (
        "杂志级单一隐喻主视觉",
        "严格采用 16:9 宽屏横版构图，画面核心视觉主体紧凑居中落在中央横向 70% × 纵向 60% 安全区域内（兼容 2.35:1 封面居中裁切不切主体），四周保留至少 35% 柔和浅灰白纸面留白；用单一、极具叙事张力的概念实体隐喻表达文章核心矛盾，融合《经济学人》编辑插画与 Linear 极简几何雕塑质感，克制低饱和配色（深岩灰主调、少量科技靛蓝与一点珊瑚红/琥珀橙焦点）；严禁任何文字、严禁流程图、严禁箭头连线、严禁卡片分栏。",
    ),
    (
        "视觉张力双主体对照插画",
        "严格采用 16:9 宽屏横版构图，在同一水平视界内以两个具象象征物形成克制的体量/材质/光影视觉对照（如巨石与轻羽、开放之门与厚重屏障），核心主体严格居中落在横向 70% × 纵向 60% 封面安全区内，四周留足纯净浅灰白纸面呼吸空间；纯粹通过构图与物理隐喻传递张力，严禁任何文字、数字、箭头、流程图、对比卡片边框或徽章图标。",
    ),
    (
        "微观焦点留白叙事插画",
        "严格采用 16:9 宽屏横版静物叙事构图，画面中央聚焦单个极具工业设计质感的极简具象主体（哑光陶瓷、磨砂玻璃与纸面微纹理），柔和自然棚拍漫射光，大面积纯净浅色留白，视觉层次一眼可辨；严禁任何文字、标牌、屏幕字样、流程图、箭头或无关科技图标堆砌。",
    ),
)

_NEGATION_CLAUSE_RE = re.compile(
    r"(?:绝对)?(?:严禁|禁止|绝不|切勿|不要|杜绝|无任何|不含|无)[^，。；;\n]{0,48}"
)
_FORBIDDEN_PROMPT_RENDER_RE = re.compile(
    r"主标题|副标题|顶部.*胶囊|三张.*卡片|从左到右.*箭头|流程图|引号内|标注简体中文|写上|印着|显示.*文字"
)
_PURE_VISUAL_GUARDRAIL_TAIL = (
    "100%纯视觉无任何文字字母数字与水印，严禁流程图、箭头连线与多栏卡片，"
    "严格16:9宽屏横版且核心主体居中落在2.35:1封面安全区内，严禁竖版。"
)


def _has_forbidden_render_directive(text: str) -> bool:
    """检查提示词是否包含正向要求画文字或流程图的指令（先剥离否定约束子句防误杀）。"""
    if not text:
        return False
    stripped = _NEGATION_CLAUSE_RE.sub("", text)
    return bool(_FORBIDDEN_PROMPT_RENDER_RE.search(stripped))


@contextmanager
def qwen_prompt_context(article_title="", section_context="", slot_index=0):
    """线程局部生图上下文：在不破坏 download_image 签名的前提下，将文章标题、所在小节正文与图位序号透传给提示词导演。"""
    prev = getattr(_qwen_prompt_tls, "ctx", None)
    _qwen_prompt_tls.ctx = {
        "article_title": (article_title or "").strip(),
        "section_context": (section_context or "").strip(),
        "slot_index": int(slot_index or 0),
    }
    try:
        yield
    finally:
        if prev is None:
            if hasattr(_qwen_prompt_tls, "ctx"):
                delattr(_qwen_prompt_tls, "ctx")
        else:
            _qwen_prompt_tls.ctx = prev


def get_qwen_prompt_context():
    """读取当前线程的生图上下文（若未设置则返回默认空结构）。"""
    ctx = getattr(_qwen_prompt_tls, "ctx", None)
    if not isinstance(ctx, dict):
        return {"article_title": "", "section_context": "", "slot_index": 0}
    return ctx


def _can_use_llm_prompt_director():
    """是否允许调用轻量 DeepSeek 模型为通义万相 3.0 构建杂志级纯视觉隐喻提示词。"""
    if os.getenv("PYTEST_CURRENT_TEST"):
        return False
    if os.getenv("QWEN_IMAGE_LLM_PROMPT", "1").strip().lower() in ("0", "false", "no", "off"):
        return False
    from config import LLM_API_KEY, LLM_API_KEYS
    return bool(LLM_API_KEY or LLM_API_KEYS)


def _build_editorial_illustration_prompt(keyword, article_title="", slot_index=0):
    """本地确定性杂志级纯视觉概念插画提示词（零文字、无流程图、兼容 2.35:1 封面安全区）。"""
    raw = re.sub(r"\s+", " ", (keyword or "").strip())
    # 剥离结构化分隔符与箭头，仅保留干净的主题意象短语，绝不让模型渲染文字
    raw = re.sub(r"[｜|→=>]+", " ", raw)
    raw = re.sub(r"\bvs\b", " 与 ", raw, flags=re.IGNORECASE)
    subject = re.sub(r"\s+", " ", raw).strip(" ：:，,。")[:40]
    if not subject:
        subject = (article_title or "前沿科技与产业博弈").strip()[:28]

    archetype_name, archetype_desc = _SLOT_LAYOUT_ARCHETYPES[int(slot_index or 0) % len(_SLOT_LAYOUT_ARCHETYPES)]

    return (
        f"一幅16:9宽屏横版高端科技商业杂志纯视觉概念插画（{archetype_name}），"
        f"融合《经济学人》封面编辑插画叙事张力与 Stripe Press / Linear 现代极简立体雕塑质感。"
        f"以单一极具辨识度的物理或建筑视觉隐喻表达主题意象：{subject}。"
        f"{archetype_desc}"
        "画布采用干净柔和的浅灰白微纹理纸面底色，柔和棚拍自然漫射光与细腻投影；"
        "配色高度克制：深岩灰与暖白为主调，仅用少量科技靛蓝与一处珊瑚红/琥珀橙作视觉焦点。"
        "绝对禁止在画面中渲染任何汉字、英文字母、数字、标点、品牌Logo、标签胶囊、印章、水印或屏幕微缩文字（100% 纯视觉无字画面）；"
        "严禁流程图、严禁箭头连线、严禁多栏卡片排版、严禁堆砌晶圆/棱镜/盾牌/机柜等无关科技图标全家桶、"
        "严禁竖版构图、严禁赛博黑底霓虹、严禁写实人脸或会议室照片。"
    )


# 保持向后兼容别名
_build_local_infographic_prompt = _build_editorial_illustration_prompt


def _build_qwen_image_prompt(keyword, context=None, article_title=None, slot_index=None):
    """
    为通义万相 Qwen-Image-3.0 构建杂志级纯视觉无字概念插画提示词。
    优先使用轻量 LLM 结合文章标题与所在小节上下文提炼单一具象视觉隐喻，失败或越界时平滑回退本地纯视觉模板。
    """
    tls_ctx = get_qwen_prompt_context()
    eff_title = (article_title if article_title is not None else tls_ctx.get("article_title", "")) or ""
    eff_section = (context if context is not None else tls_ctx.get("section_context", "")) or ""
    eff_slot = int(slot_index if slot_index is not None else tls_ctx.get("slot_index", 0))

    if not keyword or not keyword.strip():
        return _build_editorial_illustration_prompt(eff_title or "前沿科技洞察", eff_title, eff_slot)

    clean_kw = keyword.strip()
    archetype_name, archetype_desc = _SLOT_LAYOUT_ARCHETYPES[eff_slot % len(_SLOT_LAYOUT_ARCHETYPES)]

    if _can_use_llm_prompt_director():
        try:
            from config import LLM_MODEL
            from core.shared.llm import call_deepseek_with_retry

            system_prompt = (
                "你是顶级商业与科技媒体（对标《经济学人》、Stripe Press、Linear）的首席插画艺术总监，"
                "专门为高端 AI 图像生成模型编写 16:9 宽屏横版【纯视觉无字】概念插画提示词。\n"
                "必须严格遵守以下视觉可读性与零文字铁律：\n"
                "1. **100% 纯视觉无字画面（最高铁律）**：\n"
                "   - 画面中**严禁出现任何汉字、英文字母、数字、标点、引号、标签胶囊、标题栏、图表刻度或水印**。\n"
                "   - 提示词中绝对不要出现“主标题”“副标题”“标注”“写着”等要求渲染文字的描述，也不要使用双引号包裹任何文案。\n"
                "2. **严禁流程图与图标堆砌**：\n"
                "   - **绝对禁止画流程图、步骤条、箭头连线、三联卡片、双栏对比卡片或信息图排版**。\n"
                "   - 只设计 **1 个**（最多 2 个形成对比张力的）具体、克制、富有电影感与雕塑感的物理/空间隐喻（例如：天平与巨石、玻璃门与老式红电话、悬在半空的金属齿轮、一束光穿过窄缝），禁止堆砌芯片晶圆、发光大脑、盾牌锁、服务器机柜等刻板科技图标全家桶。\n"
                "3. **构图与封面裁切安全区（手机端一眼可读）**：\n"
                "   - **16:9 宽屏横版构图**，所有核心主体紧凑居中落在画面中央 `70% × 60%` 安全区域内（兼容 2.35:1 封面居中裁切不裁断主体），四周保留至少 `35%` 纯净浅灰白纸面留白。\n"
                "   - 融合《经济学人》编辑插画的巧思与极简工业模型质感（哑光陶瓷、磨砂玻璃、金属与纸面微纹理），柔和棚拍漫射光，深岩灰主调 + 少量科技靛蓝 + 一点珊瑚红/琥珀橙焦点。\n"
                "4. **黑名单**：严禁文字、严禁流程图/箭头/卡片、严禁竖版、严禁赛博黑底霓虹、严禁写实人脸或会议室照片、严禁色号代码。\n"
                "5. **输出格式**：直接输出一段 120–220 字的完整简体中文纯画面描写提示词，不要标题、解释、编号或 Markdown 代码块。"
            )
            user_prompt = (
                f"文章标题：{eff_title or '未提供'}\n"
                f"核心意象线索：{clean_kw}\n"
                f"构图原型：{archetype_name}（{archetype_desc}）\n"
                f"所在小节正文摘录：\n{eff_section[:500] if eff_section else '（无额外摘录，请紧扣主题设计一个单一物理视觉隐喻）'}\n\n"
                "请据此写出一段直接发给 Qwen-Image-3.0 的 16:9 纯视觉无字概念插画中文提示词："
                "只描述具象物体、材质、光影与留白构图，绝不渲染任何文字、数字、箭头、流程图或分栏卡片。"
            )
            enhanced = call_deepseek_with_retry(
                user_prompt,
                system_content=system_prompt,
                model=LLM_MODEL,
                reasoning_effort="none",
                max_tokens=500,
            )
            cleaned = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", (enhanced or "").strip()).strip()
            if len(cleaned) >= 50 and not _has_forbidden_render_directive(cleaned):
                cleaned = re.sub(r'[“”"]', "", cleaned)
                if "严禁流程图" not in cleaned or "严禁竖版" not in cleaned:
                    cleaned = f"{cleaned} {_PURE_VISUAL_GUARDRAIL_TAIL}"
                return cleaned
            if cleaned:
                logger.info("  视觉导演提示词含禁用文字/流程图指令，自动回退纯视觉安全模板")
        except WorkflowCancelled:
            raise
        except Exception as e:
            logger.warning("  LLM 视觉导演生成 Qwen-Image 提示词失败，回退本地纯视觉模板: {}", e)

    return _build_editorial_illustration_prompt(clean_kw, eff_title, eff_slot)


def _parse_qwen_image_response(data, target_dir, prefix):
    """解析 Qwen-Image 生成结果（content[].image 为 URL 或 base64 data URI），返回本地路径"""
    import base64
    choices = ((data.get("output") or {}).get("choices") or [])
    contents = (choices[0].get("message") or {}).get("content") if choices else []
    for item in contents or []:
        image_ref = item.get("image") or ""
        if not image_ref:
            continue
        try:
            if image_ref.startswith("data:"):
                b64 = image_ref.split(",", 1)[1]
                raw = base64.b64decode(b64)
                path = os.path.join(target_dir, f"{prefix}_{int(time.time())}.png")
                with open(path, "wb") as f:
                    f.write(raw)
                return path
            path = _save_image_from_url(image_ref, target_dir, prefix=prefix, timeout=60)
            if path:
                return path
        except Exception as e:
            logger.debug("  Qwen-Image 结果解析失败: {}", e)
    return None


def _build_editorial_prompt_for_purpose(keyword, purpose="body"):
    """按用途（正文 16:9 / 封面 21:9）微调杂志级纯视觉无字提示词。"""
    prompt = _build_qwen_image_prompt(keyword)
    if purpose == "cover":
        aspect = _resolve_gemini_aspect_ratio("cover")
        if aspect == "21:9":
            prompt = prompt.replace("16:9宽屏横版", "21:9宽银幕横版", 1)
    return prompt


def _has_gemini_backend() -> bool:
    service_url = (getattr(config, "GEMINI_IMAGE_SERVICE_URL", "") or "").strip()
    return bool(service_url) or _get_gemini_key_pool().size > 0


def _gemini_service_post(payload: dict, timeout: int):
    """向私有 239020 生图微服务发起请求（仅传 X-Proxy-Token，不携带 GEMINI_API_KEY），返回 (status_code, content_type, raw_bytes)。"""
    import requests

    service_url = (getattr(config, "GEMINI_IMAGE_SERVICE_URL", "") or "").strip()
    if not service_url:
        return None, "", b""
    proxy_token = (getattr(config, "GEMINI_PROXY_TOKEN", "") or "").strip()
    headers = {"Content-Type": "application/json", "User-Agent": "AutoWeChat/2.0"}
    if proxy_token:
        headers["X-Proxy-Token"] = proxy_token

    try:
        limiter, sem = _qwen_image_throttle()
        while not sem.acquire(timeout=0.1):
            check_cancelled()
        try:
            limiter.wait()
            check_cancelled()
            resp = requests.post(service_url, headers=headers, json=payload, timeout=timeout)
        finally:
            sem.release()
        ctype = (resp.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        return resp.status_code, ctype, (resp.content or b"")
    except requests.RequestException as e:
        logger.warning("  Gemini 私有生图服务请求异常: {}", e)
        return None, "", b""


def _gemini_post_with_rotation(path, body, timeout):
    """Gemini Interactions REST POST（支持多 Key 轮询与反代 X-Proxy-Token 鉴权）。"""
    import requests

    pool = _get_gemini_key_pool()
    if pool.size == 0:
        return None, None
    api_base = (getattr(config, "GEMINI_API_BASE", "https://generativelanguage.googleapis.com") or "https://generativelanguage.googleapis.com").strip().rstrip("/")
    url = f"{api_base}{path}"
    proxy_token = (getattr(config, "GEMINI_PROXY_TOKEN", "") or "").strip()

    max_attempts = min(max(2, pool.size), 5)
    for _ in range(max_attempts):
        check_cancelled()
        key = ""
        try:
            limiter, sem = _qwen_image_throttle()
            while not sem.acquire(timeout=0.1):
                check_cancelled()
            try:
                limiter.wait()
                check_cancelled()
                key = pool.get_key()
                if not key:
                    break
                headers = {
                    "Content-Type": "application/json",
                    "Api-Revision": "2026-05-20",
                    "x-goog-api-key": key,
                }
                if proxy_token:
                    headers["X-Proxy-Token"] = proxy_token
                resp = requests.post(url, headers=headers, json=body, timeout=timeout)
            finally:
                sem.release()

            if resp.status_code == 200:
                pool.report_success(key)
                try:
                    return resp.status_code, resp.json()
                except Exception:
                    return resp.status_code, None

            if resp.status_code in (401, 403, 429, 500, 502, 503):
                logger.warning("  Gemini 生图接口 HTTP {}: {}", resp.status_code, (resp.text or "")[:200])
                pool.report_failure(key, cooldown_seconds=120 if resp.status_code == 429 else 300)
                continue

            logger.warning("  Gemini 生图请求失败 HTTP {}: {}", resp.status_code, (resp.text or "")[:240])
            return resp.status_code, None
        except requests.RequestException as e:
            logger.debug("  Gemini 生图请求异常（切换 Key）: {}", e)
            if key:
                pool.report_failure(key)
    return None, None


def _save_verified_image_bytes(raw_bytes: bytes, target_dir: str, prefix: str):
    """校验图片字节流有效性并落地到 target_dir，返回文件路径。"""
    if not raw_bytes or len(raw_bytes) < 512:
        return None
    try:
        with Image.open(io.BytesIO(raw_bytes)) as test_img:
            test_img.verify()
        with Image.open(io.BytesIO(raw_bytes)) as info_img:
            fmt = (info_img.format or "jpeg").lower()
    except Exception as exc:
        logger.warning("  Gemini 返回图片字节校验失败: {}", exc)
        return None

    ext = ".png" if fmt == "png" else (".webp" if fmt == "webp" else ".jpg")
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, f"{prefix}_{int(time.time() * 1000)}{ext}")
    with open(path, "wb") as f:
        f.write(raw_bytes)
    return path


def _parse_gemini_image_response(data, target_dir, prefix="gemini"):
    """解析 Gemini Interactions REST 响应中的最后一张图片（兼容 steps / outputs / output_image）。"""
    if not isinstance(data, dict):
        return None

    candidates = []
    steps = data.get("steps")
    if isinstance(steps, list):
        for step in reversed(steps):
            if not isinstance(step, dict):
                continue
            content = step.get("content")
            if not isinstance(content, list):
                continue
            for block in reversed(content):
                if isinstance(block, dict) and block.get("type") == "image" and block.get("data"):
                    candidates.append(block.get("data"))

    outputs = data.get("outputs")
    if not candidates and isinstance(outputs, list):
        for item in reversed(outputs):
            if isinstance(item, dict) and item.get("type") == "image" and item.get("data"):
                candidates.append(item.get("data"))

    output_image = data.get("output_image")
    if not candidates and isinstance(output_image, dict) and output_image.get("data"):
        candidates.append(output_image.get("data"))

    for b64_payload in candidates:
        if not isinstance(b64_payload, str):
            continue
        raw_b64 = b64_payload.split(",", 1)[1] if b64_payload.startswith("data:") and "," in b64_payload else b64_payload
        try:
            raw_bytes = base64.b64decode(raw_b64)
        except Exception as exc:
            logger.debug("  Gemini base64 解码失败: {}", exc)
            continue
        saved = _save_verified_image_bytes(raw_bytes, target_dir, prefix)
        if saved:
            return saved
    return None


def _try_gemini_image_gen(keyword, target_dir, purpose="body", width=900, height=500):
    """Google Gemini Nano Banana 2.1 文本生图（支持 239020 私有生图微服务或直连 Interactions REST，共享每日配额熔断器）。"""
    if not _has_gemini_backend():
        return None
    if not _reserve_qwen_daily_quota(1):
        return None

    model = _get_active_gemini_model()
    aspect_ratio = _resolve_gemini_aspect_ratio(purpose)
    image_size = (getattr(config, "GEMINI_IMAGE_SIZE", "1K") or "1K").strip().upper()
    if image_size not in ("1K", "2K", "4K"):
        image_size = "1K"
    timeout = int(getattr(config, "GEMINI_IMAGE_TIMEOUT", 120) or 120)
    thinking_level = _normalize_gemini_thinking_level(
        model, getattr(config, "GEMINI_IMAGE_THINKING_LEVEL", "minimal")
    )

    prompt = _build_editorial_prompt_for_purpose(keyword, purpose=purpose)
    logger.info("  [Gemini Prompt] (model={}, ratio={}, size={}) {}", model, aspect_ratio, image_size, prompt[:130])

    service_url = (getattr(config, "GEMINI_IMAGE_SERVICE_URL", "") or "").strip()
    if service_url:
        svc_payload = {
            "model": model,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
            "mime_type": "image/jpeg",
        }
        if thinking_level and any(
            tag in model.lower() for tag in ("nano-banana", "3-pro", "3.1-flash")
        ):
            svc_payload["thinking_level"] = thinking_level

        try:
            status, ctype, raw_bytes = _gemini_service_post(svc_payload, timeout)
        except BaseException:
            _release_qwen_daily_quota(1)
            raise

        if status != 200 or not raw_bytes:
            _release_qwen_daily_quota(1)
            err_preview = raw_bytes.decode("utf-8", errors="ignore")[:200] if raw_bytes else ""
            logger.warning("  Gemini 私有生图服务失败 HTTP {} {}", status, err_preview)
            return None

        if ctype.startswith("image/"):
            path = _save_verified_image_bytes(raw_bytes, target_dir, "gemini")
        else:
            try:
                path = _parse_gemini_image_response(json.loads(raw_bytes.decode("utf-8")), target_dir, "gemini")
            except Exception:
                path = None
        if not path:
            logger.warning("  Gemini 私有生图服务返回 HTTP 200 但未解析到有效图片")
        return path

    body = {
        "model": model,
        "input": prompt,
        "response_format": {
            "type": "image",
            "mime_type": "image/jpeg",
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
        },
    }
    if thinking_level and any(
        tag in model.lower() for tag in ("nano-banana", "3-pro", "3.1-flash")
    ):
        body["generation_config"] = {"thinking_level": thinking_level}

    try:
        status, data = _gemini_post_with_rotation("/v1beta/interactions", body, timeout)
    except BaseException:
        _release_qwen_daily_quota(1)
        raise

    if status != 200 or not data:
        _release_qwen_daily_quota(1)
        logger.warning("  Gemini 生图失败 HTTP {}", status)
        return None

    path = _parse_gemini_image_response(data, target_dir, "gemini")
    if not path:
        logger.warning("  Gemini 返回 HTTP 200 但未提取到有效图片")
    return path


def _try_gemini_image_redraw(image_path, instruction, target_dir, width=900, height=500):
    """基于参考图使用 Gemini Nano Banana 进行合规二次创作重绘。"""
    if not image_path or not os.path.exists(image_path) or not _has_gemini_backend():
        return None
    if not _reserve_qwen_daily_quota(1):
        return None

    model = _get_active_gemini_model()
    image_size = (getattr(config, "GEMINI_IMAGE_SIZE", "1K") or "1K").strip().upper()
    if image_size not in ("1K", "2K", "4K"):
        image_size = "1K"
    timeout = int(getattr(config, "GEMINI_IMAGE_TIMEOUT", 120) or 120)

    b64_img, mime = _load_reference_image_b64(image_path)

    prompt = (
        f"{instruction}。要求：生成一幅全新原创画面，保持参考图的主题与构图，"
        "去除图中所有水印、logo、任何汉字英文字母与数字标识（纯视觉无字画面），"
        "严格16:9宽屏横版构图，四周留白充分，适合微信公众号配图。"
    )
    aspect_ratio = _resolve_gemini_aspect_ratio("body")
    service_url = (getattr(config, "GEMINI_IMAGE_SERVICE_URL", "") or "").strip()
    if service_url:
        svc_payload = {
            "model": model,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
            "mime_type": "image/jpeg",
            "reference_image": {"data": b64_img, "mime_type": mime},
        }
        try:
            status, ctype, raw_bytes = _gemini_service_post(svc_payload, timeout)
        except BaseException:
            _release_qwen_daily_quota(1)
            raise
        if status != 200 or not raw_bytes:
            _release_qwen_daily_quota(1)
            logger.warning("  Gemini 私有服务重绘失败 HTTP {}", status)
            return None
        if ctype.startswith("image/"):
            return _save_verified_image_bytes(raw_bytes, target_dir, "gemini_redraw")
        try:
            return _parse_gemini_image_response(json.loads(raw_bytes.decode("utf-8")), target_dir, "gemini_redraw")
        except Exception:
            return None

    body = {
        "model": model,
        "input": [
            {"type": "text", "text": prompt},
            {"type": "image", "data": b64_img, "mime_type": mime},
        ],
        "response_format": {
            "type": "image",
            "mime_type": "image/jpeg",
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
        },
    }
    try:
        status, data = _gemini_post_with_rotation("/v1beta/interactions", body, timeout)
    except BaseException:
        _release_qwen_daily_quota(1)
        raise

    if status != 200 or not data:
        _release_qwen_daily_quota(1)
        logger.warning("  Gemini 重绘失败 HTTP {}", status)
        return None

    return _parse_gemini_image_response(data, target_dir, "gemini_redraw")


def redraw_reference_image(image_path, instruction, target_dir, width=900, height=500):
    """参考图合规重绘统一入口：优先 Gemini，失败时按配置自动降级 Qwen-Image Pro。"""
    if _is_gemini_image_preferred() and _has_gemini_backend():
        out = _try_gemini_image_redraw(image_path, instruction, target_dir, width=width, height=height)
        if out:
            return out
        if getattr(config, "GEMINI_IMAGE_FALLBACK_TO_QWEN", True) and _get_qwen_key_pool().size > 0:
            logger.info("  Gemini 重绘未返回结果，自动降级至 Qwen-Image 重绘")
            return _try_qwen_image_redraw(image_path, instruction, target_dir, width=width, height=height)
        return None
    if _get_qwen_key_pool().size > 0:
        return _try_qwen_image_redraw(image_path, instruction, target_dir, width=width, height=height)
    if _has_gemini_backend():
        return _try_gemini_image_redraw(image_path, instruction, target_dir, width=width, height=height)
    return None


def _try_qwen_image_gen(keyword, target_dir, width=900, height=500):
    """通义万相 Qwen-Image-3.0 文本生图（DashScope/百炼，国内直连）"""
    from config import QWEN_IMAGE_API_BASE, QWEN_IMAGE_TIMEOUT, QWEN_IMAGE_SIZE
    qwen_model = _get_active_qwen_model()
    if not _reserve_qwen_daily_quota(1):
        return None
    prompt = _build_qwen_image_prompt(keyword)
    # 强制关闭云端 prompt_extend 以防 DashScope 自动改写提示词并往画面里塞随机汉字/流程图
    force_extend = os.getenv("QWEN_IMAGE_FORCE_PROMPT_EXTEND", "").strip().lower() in ("1", "true", "yes")
    use_prompt_extend = bool(force_extend)
    logger.info("  [Qwen-Image Prompt] (model={}, extend={}) {}", qwen_model, use_prompt_extend, prompt[:140])
    body = {
        "model": qwen_model,
        "input": {
            "messages": [
                {"role": "user", "content": [{"text": prompt}]}
            ]
        },
        "parameters": {"prompt_extend": use_prompt_extend, "size": QWEN_IMAGE_SIZE},
    }
    try:
        status, data = _qwen_post_with_rotation(QWEN_IMAGE_API_BASE, body, QWEN_IMAGE_TIMEOUT)
    except BaseException:
        _release_qwen_daily_quota(1)
        raise
    if status != 200 or not data:
        _release_qwen_daily_quota(1)
        logger.warning("  Qwen-Image 生图失败 HTTP {}", status)
        return None
    return _parse_qwen_image_response(data, target_dir, "qwen")


def _try_qwen_image_redraw(image_path, instruction, target_dir, width=900, height=500):
    """基于参考图重绘（Qwen-Image 图生图）：合规二次创作，生成全新原创画面"""
    from config import QWEN_IMAGE_API_BASE, QWEN_IMAGE_REDRAW_MODEL, QWEN_IMAGE_TIMEOUT, QWEN_IMAGE_SIZE
    if not image_path or not os.path.exists(image_path):
        return None
    if not _reserve_qwen_daily_quota(1):
        return None
    import base64
    mime = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"
    with open(image_path, "rb") as f:
        data_uri = f"data:{mime};base64," + base64.b64encode(f.read()).decode()
    prompt = (
        f"{instruction}。要求：生成一幅全新原创画面，保持参考图的主题与构图，"
        "去除图中所有水印、logo、任何汉字英文字母与数字标识（纯视觉无字画面），画质高清、风格统一，适合微信公众号配图。"
    )
    body = {
        "model": QWEN_IMAGE_REDRAW_MODEL,
        "input": {
            "messages": [
                {"role": "user", "content": [{"image": data_uri}, {"text": prompt}]}
            ]
        },
        "parameters": {"size": QWEN_IMAGE_SIZE},
    }
    try:
        status, data = _qwen_post_with_rotation(QWEN_IMAGE_API_BASE, body, QWEN_IMAGE_TIMEOUT)
    except BaseException:
        _release_qwen_daily_quota(1)
        raise
    if status != 200 or not data:
        _release_qwen_daily_quota(1)
        logger.warning("  Qwen-Image 重绘失败 HTTP {}", status)
        return None
    return _parse_qwen_image_response(data, target_dir, "qwen_redraw")


def scrape_article_images(article_url, limit=10):
    """抓取公众号文章内的图片 URL 列表（供参考图/合规重绘使用）"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        }
        html = fetch_public(article_url, headers=headers, timeout=15, max_bytes=2 * 1024 * 1024).decode("utf-8", errors="replace")
        urls = re.findall(r'data-src="(https?://mmbiz\.qpic\.cn/[^"]+)"', html)
        if not urls:
            urls = re.findall(r'<img[^>]+src="(https?://[^"]+)"', html)
        out, seen = [], set()
        for u in urls:
            u = u.replace("&amp;", "&")
            if u in seen:
                continue
            seen.add(u)
            out.append(u)
            if len(out) >= limit:
                break
        return out
    except Exception as e:
        logger.debug("抓取文章图片失败: {}", e)
        return []


_image_sources_status = {
    "gemini": {"status": True, "last_check": 0},
    "qwen": {"status": True, "last_check": 0},
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


def _download_free_image(keyword, save_dir, purpose="body", max_retries=3):
    """
    AI 生图引擎调度（全线采用 AI 文本生图，禁用免费搜索网络爬虫）。
    默认主引擎：Google Gemini Nano Banana 2.1；自动降级：通义万相 Qwen-Image-3.0。
    内置重试、冷却与每日生图配额硬熔断机制。
    """
    from core.shared.runtime import WorkflowCancelled, cancel_event, check_cancelled

    if not keyword or not keyword.strip():
        return None

    provider_cfg = (getattr(config, "IMAGE_PROVIDER", "auto") or "auto").strip().lower()
    selected_model = (getattr(config, "IMAGE_GEN_MODEL", "") or "").strip().lower()
    if provider_cfg == "auto" and selected_model == "sd-local":
        logger.info("  [图源路由] 当前首选模型设为 sd-local，跳过云端 AI 生图直接交由本地 SD 处理: '{}'", keyword)
        return None

    has_gemini = _has_gemini_backend()
    has_qwen = _get_qwen_key_pool().size > 0
    providers = []
    if _is_gemini_image_preferred() and has_gemini:
        providers.append("gemini")
        if getattr(config, "GEMINI_IMAGE_FALLBACK_TO_QWEN", True) and has_qwen:
            providers.append("qwen")
    elif provider_cfg != "gemini" and has_qwen:
        providers.append("qwen")
    elif has_gemini:
        providers.append("gemini")

    if not providers:
        return None

    if is_qwen_quota_exhausted():
        logger.info("  [成本熔断] 当日云端 AI 生图额度已满或已禁用，跳过生图: '{}'", keyword)
        return None

    width, height = (900, 383) if purpose == "cover" else (900, 500)

    clean_kw = _sanitize_path(keyword)
    target_dir = os.path.join(save_dir, clean_kw)
    os.makedirs(target_dir, exist_ok=True)

    for provider in providers:
        if not is_source_available(provider):
            continue
        attempts = max(1, min(max_retries, 2)) if provider == "gemini" else max(1, max_retries)
        label = f"Gemini ({_get_active_gemini_model()})" if provider == "gemini" else f"通义万相 ({_get_active_qwen_model()})"
        logger.info("正在使用 {} AI 生图 [{}]: '{}'...", label, purpose, keyword)

        for attempt in range(1, attempts + 1):
            check_cancelled()
            if is_qwen_quota_exhausted():
                return None
            try:
                if provider == "gemini":
                    path = _try_gemini_image_gen(keyword, target_dir, purpose=purpose, width=width, height=height)
                else:
                    path = _try_qwen_image_gen(keyword, target_dir, width, height)
                if path:
                    mark_source_success(provider)
                    return path

                logger.warning(
                    "  {} AI 生图第 {}/{} 次未返回图片: '{}'{}",
                    label,
                    attempt,
                    attempts,
                    keyword,
                    f"（将在 {attempt * 2}s 后发起重试）" if attempt < attempts else "（已耗尽当前引擎重试次数）",
                )
                if attempt < attempts:
                    cancel_event.wait(attempt * 2)
            except WorkflowCancelled:
                raise
            except Exception as e:
                logger.warning("  {} AI 生图第 {}/{} 次尝试异常: {}", label, attempt, attempts, e)
                if attempt < attempts:
                    cancel_event.wait(attempt * 2)

        mark_source_failed(provider)
        if provider == "gemini" and "qwen" in providers:
            logger.warning("  Gemini 生图暂不可用，自动降级至通义万相 Qwen-Image 兜底: '{}'", keyword)

    logger.warning("  所有已配置的云端 AI 生图引擎均未成功: '{}'", keyword)
    return None


# ==========================================
#  文字卡图本地兜底生成
# ==========================================
def _chinese_cover_font(size):
    for name in (
        "C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc", "msyh.ttc",
    ):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return None


def label_ai_cover(image_path):
    """把标识写入封面像素，单独展示缩略图时也能识别。"""
    label = "AI 示意图"
    font = _chinese_cover_font(22)
    if font is None:
        raise OSError("无法加载封面标识所需的中文字体")
    with Image.open(image_path) as original:
        cover = original.convert("RGB")
    draw = ImageDraw.Draw(cover)
    x, y = cover.width // 2, cover.height - 28
    left, top, right, bottom = draw.textbbox((x, y), label, font=font, anchor="mm")
    draw.rounded_rectangle((left - 11, top - 6, right + 11, bottom + 6), radius=6, fill="#27303d")
    draw.text((x, y), label, font=font, anchor="mm", fill="white")
    cover.save(image_path, "JPEG", quality=90)


def generate_default_cover(title, save_path, purpose="cover"):
    """
    用 Pillow 动态生成 Linear Modern Light 现代极简风格的文字封面/插图卡片，作为终极兜底。
    - cover 尺寸: 900x383
    - body 尺寸: 900x500
    """
    w, h = (900, 383) if purpose == "cover" else (900, 500)
    
    # 1. 创建优雅纵向浅色微光底色 (#FFFFFF 渐变到 #F1F3F7)
    base = Image.new("RGB", (w, h), (248, 249, 251))
    draw = ImageDraw.Draw(base)
    
    for y in range(h):
        factor = y / max(h - 1, 1)
        r = int(255 - (255 - 241) * factor)
        g = int(255 - (255 - 243) * factor)
        b = int(255 - (255 - 247) * factor)
        draw.line([(0, y), (w, y)], fill=(r, g, b))
        
    # 2. 绘制左侧 Linear Indigo 主题装饰条
    draw.rectangle([0, 0, 8, h], fill=(79, 91, 213))   # #4F5BD5
    draw.rectangle([8, 0, 11, h], fill=(99, 102, 241)) # #6366F1

    # 3. 顶边 Specular 高光与微弱边框
    draw.rectangle([0, 0, w - 1, h - 1], outline=(226, 230, 235), width=1) # #E2E6EB
    draw.line([(12, 0), (w - 1, 0)], fill=(255, 255, 255))

    # 4. 加载中文字体
    font_size = 36 if purpose == "cover" else 40
    font = _chinese_cover_font(font_size) or ImageFont.load_default()
    badge_font = _chinese_cover_font(13) or font
    tag_font = _chinese_cover_font(14) or font

    # 5. 绘制顶部分类/主题标签胶囊
    badge_y1 = 44 if purpose == "cover" else 52
    badge_y2 = badge_y1 + 26
    badge_width = draw.textlength(config.BRAND_NAME, font=badge_font) + 32
    draw.rounded_rectangle([60, badge_y1, 60 + badge_width, badge_y2], radius=13, fill=(238, 242, 255), outline=(199, 210, 254), width=1)
    draw.text((76, badge_y1 + 5), config.BRAND_NAME, fill=(79, 91, 213), font=badge_font)

    # 6. 文字自适应换行与垂直居中排版 (高对比度墨黑 #0C0D0E)
    max_char_per_line = 15 if purpose == "cover" else 17
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
    
    line_height = font_size + 14
    total_text_height = len(lines) * line_height
    available_top = badge_y2 + 16
    available_bottom = h - 60
    y_offset = available_top + (available_bottom - available_top - total_text_height) // 2
    
    for line in lines:
        draw.text((60, y_offset), line, fill=(12, 13, 14), font=font)  # #0C0D0E
        y_offset += line_height
        
    # 7. 绘制底部规范标注 (高清深灰 #5E6470)
    draw.text((60, h - 48), f"{config.BRAND_NAME} • AI AUTOMATION", fill=(94, 100, 112), font=tag_font)  # #5E6470

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    base.save(save_path, "JPEG", quality=95)
    logger.info("  [兜底卡图] 已成功绘制并保存 Linear Modern Light 兜底文字卡片: {}", save_path)
    return save_path


# ==========================================
#  核心下载与图源调度接口
# ==========================================
def download_image(keyword, save_dir="assets", *, allow_title_card=True):
    """
    下载正文配图：100% AI 生图架构。
    1. 优先 Google Gemini Nano Banana 2.1 AI 生图（失败自动降级通义万相 Qwen-Image-3.0）；
    2. 备选本地 Stable Diffusion AI 生图；
    3. 兜底本地高颜值卡片。
    已彻底禁用 Bing 搜索引擎网络爬虫。
    """
    from core.shared.runtime import check_cancelled

    check_cancelled()
    if not keyword or not keyword.strip():
        return None

    clean_keyword = _sanitize_path(keyword)
    specific_dir = os.path.join(save_dir, clean_keyword)
    os.makedirs(specific_dir, exist_ok=True)

    # 1. 优先云端 AI 生图（Gemini -> Qwen 自动降级）
    active_name = (
        "sd-local"
        if (getattr(config, "IMAGE_PROVIDER", "auto") or "auto").strip().lower() == "auto"
        and (getattr(config, "IMAGE_GEN_MODEL", "") or "").strip().lower() == "sd-local"
        else (_get_active_gemini_model() if _is_gemini_image_preferred() else _get_active_qwen_model())
    )
    logger.info("正在发起 AI 配图生成 ({}): '{}'...", active_name, keyword)
    best = _download_free_image(keyword, save_dir, purpose="body")
    if best:
        best = _finalize_image(best, "body")
        if best:
            return best

    # 2. 备选本地 Stable Diffusion AI 生图
    check_cancelled()
    logger.info("🎨 正在发起本地 Stable Diffusion AI 配图生成: '{}'...", keyword)
    best = _try_local_sd(keyword, specific_dir, width=1024, height=576) if config.SD_ENABLED else None
    if best:
        best = _finalize_image(best, "body")
        if best:
            return best

    if not allow_title_card:
        return None

    # 3. 兜底本地高颜值文字卡片
    logger.warning("  ⚠️ AI 生图服务未就绪，启用本地高颜值卡片兜底: '{}'", keyword)
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
    下载封面图：100% AI 生图架构。
    1. 优先 Google Gemini Nano Banana 2.1（21:9 宽银幕）AI 封面生图（失败自动降级通义万相 Qwen-Image-3.0）；
    2. 备选本地 Stable Diffusion AI 封面生图；
    3. 兜底本地高颜值卡片。
    已彻底禁用 Bing 搜索引擎网络爬虫。
    """
    if not keyword or not keyword.strip():
        return None

    clean_keyword = _sanitize_path(f"{keyword}_cover")
    specific_dir = os.path.join(save_dir, clean_keyword)
    if not os.path.exists(specific_dir):
        os.makedirs(specific_dir)

    # 1. 优先云端 AI 封面生图（Gemini -> Qwen 自动降级）
    active_name = (
        "sd-local"
        if (getattr(config, "IMAGE_PROVIDER", "auto") or "auto").strip().lower() == "auto"
        and (getattr(config, "IMAGE_GEN_MODEL", "") or "").strip().lower() == "sd-local"
        else (_get_active_gemini_model() if _is_gemini_image_preferred() else _get_active_qwen_model())
    )
    logger.info("正在发起 AI 封面图生成 ({}): '{}'...", active_name, keyword)
    best = _download_free_image(keyword, save_dir, purpose="cover")
    if best:
        best = _finalize_image(best, "cover")
        if best:
            return best

    # 2. 备选本地 Stable Diffusion AI 封面生图
    logger.info("🎨 正在发起本地 Stable Diffusion AI 封面生成: '{}'...", keyword)
    best = _try_local_sd(keyword, specific_dir, width=1280, height=545)
    if best:
        best = _finalize_image(best, "cover")
        if best:
            return best

    # 3. 兜底本地高颜值文字卡片
    logger.warning("  ⚠️ AI 封面生图服务未就绪，启用本地高颜值卡片封面兜底: '{}'", keyword)
    fallback_path = os.path.join(specific_dir, f"cover_fallback_{int(time.time())}.jpg")
    try:
        generate_default_cover(keyword, fallback_path, purpose="cover")
        if os.path.exists(fallback_path):
            return fallback_path
    except Exception as e:
        logger.error("  [兜底封面] 生成兜底封面异常: {}", e)

    # 4. 最基础的静态图片兜底 (若上面均失败了)
    for fallback in [
        LOCAL_FALLBACK_IMAGE,
        os.path.join("assets", "default_aikepu_cover.png"),
        os.path.join("assets", "default_daily_cover.png"),
        os.path.join("static", "images", "github_fixed_cover.png"),
    ]:
        if fallback and os.path.exists(fallback):
            return os.path.abspath(fallback)

    return None


def _finalize_image(img_path, purpose):
    """后处理：尺寸适配 + 去重检查 + 哈希登记"""
    if not img_path or not os.path.exists(img_path):
        return None
    from .image_filter import compute_perceptual_hash
    phash = compute_perceptual_hash(img_path)
    if phash and _is_too_similar_to_existing(phash):
        logger.debug("  跳过相似图片: {}", os.path.basename(img_path))
        return None

    result = resize_for_wechat(img_path, purpose)
    if result:
        _register_hash(phash)
    return result

