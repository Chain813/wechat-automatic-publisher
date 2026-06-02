"""
============================================================
  智能图片筛选引擎 v5.0 (微信适配版)
  支持：分辨率校验、宽高比审计、文字密度检测、多图评分
  新增：Gemini Vision 智能评分、感知哈希去重、微信封面/正文双模式评分
============================================================
"""
import os
import re
import json
import threading
from dataclasses import dataclass
from PIL import Image
import numpy as np

from loguru import logger
from config import WECHAT_COVER_WIDTH, WECHAT_COVER_HEIGHT, WECHAT_BODY_MAX_MB

WECHAT_COVER_RATIO = WECHAT_COVER_WIDTH / WECHAT_COVER_HEIGHT  # ≈ 2.35
WECHAT_MATERIAL_MAX_MB = 10

# ---- 评分维度权重 ----
#            分辨率  宽高比  清晰度  文字密度  色彩    文件大小
COVER_WEIGHTS = (0.20, 0.25, 0.20, 0.15, 0.10, 0.10)
BODY_WEIGHTS  = (0.20, 0.20, 0.20, 0.15, 0.15, 0.10)

# ---- 延迟加载 EasyOCR ----
_READER = None
_OCR_STATUS = "PENDING"
_OCR_LOCK = threading.Lock()


def get_ocr_reader():
    """延迟加载 EasyOCR（仅作可选增强，线程安全双重检查锁）"""
    global _READER, _OCR_STATUS
    if _OCR_STATUS == "DISABLED":
        return None
    if _READER is not None:
        return _READER
    with _OCR_LOCK:
        if _READER is not None:  # 双重检查：获取锁后再次确认
            return _READER
        try:
            import easyocr
            _READER = easyocr.Reader(['ch_sim', 'en'], gpu=False, verbose=False)
            _OCR_STATUS = "READY"
            return _READER
        except Exception:
            _OCR_STATUS = "DISABLED"
            return None


# ==========================================
#  Ollama 本地视觉模型评分 (优先)
# ==========================================
_OLLAMA_STATUS = "PENDING"
_OLLAMA_MODEL = None
_OLLAMA_DEFAULT_MODEL = None  # 从 config 读取
_OLLAMA_VISION_MODEL = None


def ollama_startup():
    """项目启动：切换到视觉模型"""
    global _OLLAMA_MODEL, _OLLAMA_STATUS, _OLLAMA_DEFAULT_MODEL, _OLLAMA_VISION_MODEL
    from config import OLLAMA_DEFAULT_MODEL, OLLAMA_VISION_MODEL
    _OLLAMA_DEFAULT_MODEL = OLLAMA_DEFAULT_MODEL
    _OLLAMA_VISION_MODEL = OLLAMA_VISION_MODEL
    try:
        import requests
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        models = [m["name"].lower() for m in resp.json().get("models", [])]
        if any(_OLLAMA_VISION_MODEL in m for m in models):
            _OLLAMA_MODEL = _OLLAMA_VISION_MODEL
            _OLLAMA_STATUS = "READY"
            logger.info("  Ollama 视觉模型已切换: {}", _OLLAMA_VISION_MODEL)
        else:
            logger.warning("  未找到 {}，请先运行: ollama pull {}", _OLLAMA_VISION_MODEL, _OLLAMA_VISION_MODEL)
            _OLLAMA_STATUS = "NO_MODEL"
    except Exception:
        _OLLAMA_STATUS = "DISABLED"


def ollama_shutdown():
    """项目结束：恢复默认模型并关闭视觉评估"""
    global _OLLAMA_MODEL, _OLLAMA_STATUS
    _OLLAMA_MODEL = None
    _OLLAMA_STATUS = "PENDING"
    logger.info("  Ollama 已恢复默认: {}", _OLLAMA_DEFAULT_MODEL)


def _detect_ollama_vision_model():
    """返回当前视觉模型状态（由 ollama_startup 设置）"""
    if _OLLAMA_MODEL is not None:
        return "READY"
    return _OLLAMA_STATUS


def evaluate_image_with_ollama(image_path, purpose="body"):
    """
    用本地 Ollama 视觉模型评估图片。
    返回 (score: 0-100, reason: str) 或 None。
    """
    if _detect_ollama_vision_model() != "READY":
        return None

    try:
        import base64, requests

        if purpose == "cover":
            context = "微信公众号文章封面图（推荐宽屏2.35:1）"
        else:
            context = "微信公众号正文配图（推荐横版16:9或4:3）"

        prompt = f"""你是一个图片编辑，为时政科技公众号挑选配图。
这张图用作：{context}

评估这张图，只返回JSON：
{{"watermark":0,"relevance":80,"quality":85,"text_amount":10,"overall":80,"reason":"理由"}}

字段说明：
- watermark: 0或1，是否有水印/版权标记
- relevance: 0-100，与科技时政的相关度
- quality: 0-100，画面清晰度和构图
- text_amount: 0-100，图中文字占比
- overall: 0-100，综合适配度
- reason: 15字内理由
只返回JSON，不要其他文字。"""

        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode()

        resp = requests.post("http://localhost:11434/api/chat", json={
            "model": _OLLAMA_MODEL,
            "messages": [{"role": "user", "content": prompt, "images": [image_b64]}],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 200}
        }, timeout=30)

        text = resp.json().get("message", {}).get("content", "")
        json_match = re.search(r'\{[^}]+\}', text)
        if json_match:
            data = json.loads(json_match.group())

            if data.get("watermark", 0) == 1:
                logger.info("  Ollama Vision: 检测到水印 → 0分")
                return 0, "水印图片"

            text_penalty = max(0, (data.get("text_amount", 0) - 30) * 0.5)
            score = max(0, min(100, data.get("overall", 50) - text_penalty))
            reason = data.get("reason", "")
            logger.info("  Ollama Vision({}): {}分 - {}", _OLLAMA_MODEL, score, reason)
            return score, reason

    except Exception as e:
        logger.debug("  Ollama Vision 评估失败: {}", e)

    return None


# ==========================================
#  Gemini Vision 智能评分 (备用)
# ==========================================
_GEMINI_MODEL = None
_GEMINI_STATUS = "PENDING"


def _get_gemini_client():
    """延迟加载 Gemini 客户端"""
    global _GEMINI_MODEL, _GEMINI_STATUS
    if _GEMINI_STATUS == "DISABLED":
        return None
    if _GEMINI_MODEL is not None:
        return _GEMINI_MODEL
    try:
        from config import GEMINI_API_KEY
        if not GEMINI_API_KEY:
            _GEMINI_STATUS = "NO_KEY"
            return None
        from google import genai
        _GEMINI_MODEL = genai.Client(api_key=GEMINI_API_KEY)
        _GEMINI_STATUS = "READY"
        return _GEMINI_MODEL
    except Exception as e:
        logger.debug("  Gemini Vision 初始化失败: {}", e)
        _GEMINI_STATUS = "DISABLED"
        return None


def evaluate_image_with_gemini(image_path, purpose="body"):
    """
    用 Gemini Vision 评估图片是否适合做微信公众号配图。
    返回 (score: 0-100, reason: str) 或 None（不可用时）。
    """
    client = _get_gemini_client()
    if not client:
        return None

    try:
        from google import genai
        from google.genai import types

        if purpose == "cover":
            context = "微信公众号文章封面图（推荐宽屏 2.35:1 比例）"
        else:
            context = "微信公众号正文配图（推荐横版 16:9 或 4:3）"

        prompt = f"""你是一个专业的图片编辑，正在为一个时政科技类公众号「智界洞察社」挑选配图。

这张图片将用作：{context}

请从以下维度评估这张图片，返回 JSON 格式：

1. watermark（0或1）：是否有水印、版权标记、图库logo？
2. relevance（0-100）：与科技/时政/商业主题的相关度
3. quality（0-100）：画面清晰度、构图质量、色彩表现
4. text_amount（0-100）：图中文字/图表占比（0=纯画面，100=全是文字）
5. overall（0-100）：综合适配度评分
6. reason：一句话说明理由（20字内）

只返回 JSON，不要其他文字。示例：
{{"watermark":0,"relevance":85,"quality":90,"text_amount":10,"overall":85,"reason":"高清科技场景图，构图优秀"}}"""

        with open(image_path, "rb") as f:
            image_bytes = f.read()

        # 根据扩展名判断 mime_type
        ext = os.path.splitext(image_path)[1].lower()
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
        mime_type = mime_map.get(ext, "image/jpeg")

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                types.Content(parts=[
                    types.Part.from_text(text=prompt),
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                ])
            ],
        )

        # 解析 JSON 响应
        text = response.text.strip()
        json_match = re.search(r'\{[^}]+\}', text)
        if json_match:
            data = json.loads(json_match.group())

            if data.get("watermark", 0) == 1:
                logger.info("  Gemini Vision: 检测到水印 → 0分")
                return 0, "水印图片"

            text_penalty = max(0, (data.get("text_amount", 0) - 30) * 0.5)
            score = max(0, min(100, data.get("overall", 50) - text_penalty))
            reason = data.get("reason", "")
            logger.info("  Gemini Vision: {}分 - {}", score, reason)
            return score, reason

    except Exception as e:
        logger.debug("  Gemini Vision 评估失败: {}", e)

    return None


# ==========================================
#  轻量文字密度检测 (Pillow 像素方差法)
# ==========================================
def text_density_light(image_or_path):
    """
    用向量化局部方差估算文字密度，避免逐像素 Python 循环。
    接受文件路径或已打开的 PIL Image 对象。
    返回 0.0-1.0 的密度值。
    """
    try:
        if isinstance(image_or_path, Image.Image):
            img = image_or_path.convert('L').resize((192, 192))
        else:
            with Image.open(image_or_path) as raw:
                img = raw.convert('L').resize((192, 192))
        arr = np.array(img, dtype=np.float32)

        try:
            windows = np.lib.stride_tricks.sliding_window_view(arr, (3, 3))
            local_std = windows.std(axis=(-2, -1))
            high_var_ratio = float(np.mean(local_std > 18))
        except AttributeError:
            gx = np.abs(np.diff(arr, axis=1))
            gy = np.abs(np.diff(arr, axis=0))
            high_var_ratio = float(np.mean(gx > 18) + np.mean(gy > 18)) / 2

        return min(high_var_ratio * 2.5, 1.0)
    except Exception:
        return 0.0


# ==========================================
#  感知哈希 (Perceptual Hash)
# ==========================================
def compute_perceptual_hash(image_or_path):
    """计算图片的感知哈希 (pHash)，用于相似度去重。接受路径或 PIL Image。"""
    try:
        if isinstance(image_or_path, Image.Image):
            img = image_or_path.convert('L').resize((32, 32), Image.LANCZOS)
        else:
            with Image.open(image_or_path) as raw:
                img = raw.convert('L').resize((32, 32), Image.LANCZOS)
        arr = np.array(img, dtype=np.float32)
        avg = arr.mean()
        hash_bits = (arr > avg).flatten()
        hash_str = ''.join(['1' if b else '0' for b in hash_bits])
        hash_hex = hex(int(hash_str, 2))[2:].zfill(256 // 4)
        return hash_hex
    except Exception:
        return ""


def _hamming_distance(h1, h2):
    """计算两个十六进制感知哈希的汉明距离"""
    if not h1 or not h2 or len(h1) != len(h2):
        return 999
    try:
        b1 = int(h1, 16)
        b2 = int(h2, 16)
        return (b1 ^ b2).bit_count()
    except Exception:
        return 999


def is_too_similar(hash1, hash2, threshold=None):
    """
    判断两张图是否过于相似。
    threshold: 汉明距离阈值，默认 10（256-bit 中差异 <10 视为相似）
    """
    if threshold is None:
        threshold = 10
    return _hamming_distance(hash1, hash2) < threshold


# ==========================================
#  清晰度评估
# ==========================================
def _compute_sharpness(img):
    """Laplacian 方差法评估清晰度，返回值越高越清晰"""
    try:
        gray = img.convert('L')
        arr = np.array(gray, dtype=np.float32)
        # 简化的 Laplacian: 与自身做差分
        h_grad = np.abs(np.diff(arr, axis=1))
        v_grad = np.abs(np.diff(arr, axis=0))
        # Pad to same size and average
        h_var = np.var(h_grad) if h_grad.size > 0 else 0
        v_var = np.var(v_grad) if v_grad.size > 0 else 0
        return (h_var + v_var) / 2.0
    except Exception:
        return 0.0


# ==========================================
#  色彩丰富度评估
# ==========================================
def _compute_color_richness(img):
    """评估色彩丰富度 (RGB 三通道标准差均值)"""
    try:
        if img.mode == 'L':
            return 0.0
        arr = np.array(img.convert('RGB'), dtype=np.float32)
        stds = [np.std(arr[:, :, c]) for c in range(3)]
        return np.mean(stds) / 128.0  # 归一化到 0-1
    except Exception:
        return 0.0


# ==========================================
#  综合评分 (微信适配版)
# ==========================================
@dataclass
class ImageScore:
    path: str
    score: float          # 0-100
    width: int
    height: int
    aspect_ratio: float
    file_size_kb: float
    text_density: float
    sharpness: float
    color_richness: float
    phash: str


def evaluate_image(image_path, purpose="body"):
    """
    综合评估一张图片的得分 (0-100)

    purpose: "cover" (封面，偏好 2.35:1 宽屏) | "body" (正文插图，偏好 16:9/4:3)
    """
    try:
        if not os.path.exists(image_path):
            return ImageScore(image_path, 0, 0, 0, 0, 0, 0, 0, 0, "")

        img = Image.open(image_path)
        try:
            w, h = img.size
            aspect_ratio = w / h if h > 0 else 0
            file_size_kb = os.path.getsize(image_path) / 1024

            # ---- 1. 硬性门槛 ----
            if purpose == "cover":
                if w < 600 or h < 200:
                    return ImageScore(image_path, 0, w, h, aspect_ratio, file_size_kb, 0, 0, 0, "")
                if file_size_kb > WECHAT_MATERIAL_MAX_MB * 1024:
                    return ImageScore(image_path, 0, w, h, aspect_ratio, file_size_kb, 0, 0, 0, "")
            else:
                if w < 400 or h < 300:
                    return ImageScore(image_path, 0, w, h, aspect_ratio, file_size_kb, 0, 0, 0, "")
                if aspect_ratio > 3.0 or aspect_ratio < 0.33:
                    return ImageScore(image_path, 0, w, h, aspect_ratio, file_size_kb, 0, 0, 0, "")
                if file_size_kb > WECHAT_BODY_MAX_MB * 1024:
                    return ImageScore(image_path, 0, w, h, aspect_ratio, file_size_kb, 0, 0, 0, "")

            # ---- 2. 计算各维度得分 (百分制) ----
            # 分辨率分
            if w >= 1200:
                res_score = 100
            elif w >= 900:
                res_score = 80
            elif w >= 800:
                res_score = 60
            elif w >= 600:
                res_score = 40
            else:
                res_score = 20

            # 宽高比分
            if purpose == "cover":
                ratio_diff = abs(aspect_ratio - WECHAT_COVER_RATIO) / WECHAT_COVER_RATIO
                if ratio_diff < 0.05:
                    ratio_score = 100
                elif ratio_diff < 0.15:
                    ratio_score = 80
                elif ratio_diff < 0.30:
                    ratio_score = 50
                else:
                    ratio_score = 20
            else:
                if 1.5 <= aspect_ratio <= 1.8:
                    ratio_score = 100
                elif 1.2 <= aspect_ratio <= 2.0:
                    ratio_score = 80
                elif 0.8 <= aspect_ratio <= 2.5:
                    ratio_score = 50
                else:
                    ratio_score = 20

            # 清晰度分
            sharpness = _compute_sharpness(img)
            if sharpness > 200:
                clarity_score = 100
            elif sharpness > 100:
                clarity_score = 80
            elif sharpness > 50:
                clarity_score = 50
            else:
                clarity_score = 20

            # 色彩丰富度分
            color_richness = _compute_color_richness(img)

            # 文字密度分 (文字越少分越高) — 直接传 img 避免重复打开文件
            text_density = text_density_light(img)

            # B4: EasyOCR 智能门控 — 只在边界区间 (0.05-0.30) 才调用 OCR
            ocr_text_count = 0
            if 0.05 <= text_density <= 0.30:
                reader = get_ocr_reader()
                if reader:
                    try:
                        results = reader.readtext(image_path)
                        ocr_text_count = len(results)

                        watermark_keywords = [
                            "版权", "水印", "图库", "视觉中国", "站长素材", "昵图网", "千图网", "包图网",
                            "摄图网", "全景网", "汇图网", "shutterstock", "getty", "alamy", "123rf",
                            "istock", "depositphotos", "素材", "未经允许", "盗图"
                        ]
                        for bbox, text, prob in results:
                            if any(kw in text.lower() for kw in watermark_keywords):
                                logger.info("  检测到水印图片: {}", os.path.basename(image_path))
                                return ImageScore(image_path, 0, w, h, aspect_ratio, file_size_kb, 1.0, sharpness, 0, "")

                        if ocr_text_count > 8:
                            return ImageScore(image_path, 0, w, h, aspect_ratio, file_size_kb, 1.0, sharpness, 0, "")
                        text_density = max(text_density, ocr_text_count / 10.0)
                    except Exception:
                        logger.debug("OCR failed for {}", image_path)

            if purpose == "cover":
                if text_density < 0.05:
                    text_score = 100
                elif text_density < 0.15:
                    text_score = 60
                elif text_density < 0.30:
                    text_score = 30
                else:
                    text_score = 0
            else:
                if text_density < 0.10:
                    text_score = 100
                elif text_density < 0.25:
                    text_score = 70
                elif text_density < 0.40:
                    text_score = 40
                else:
                    text_score = 10

            # 色彩丰富度分
            if color_richness > 0.5:
                color_score = 100
            elif color_richness > 0.3:
                color_score = 80
            elif color_richness > 0.15:
                color_score = 50
            else:
                color_score = 30

            # 文件大小分
            if purpose == "cover":
                if 100 < file_size_kb < 5000:
                    size_score = 100
                elif 50 < file_size_kb < 8000:
                    size_score = 70
                else:
                    size_score = 40
            else:
                if 80 < file_size_kb < 1500:
                    size_score = 100
                elif 50 < file_size_kb < 2000:
                    size_score = 70
                else:
                    size_score = 40

            # ---- 3. 加权合成 ----
            weights = COVER_WEIGHTS if purpose == "cover" else BODY_WEIGHTS
            dims = [res_score, ratio_score, clarity_score, text_score, color_score, size_score]
            score = sum(w * d for w, d in zip(weights, dims))

            phash = compute_perceptual_hash(img)

            return ImageScore(
                path=image_path, score=round(score, 1),
                width=w, height=h, aspect_ratio=round(aspect_ratio, 2),
                file_size_kb=round(file_size_kb, 1),
                text_density=round(text_density, 2),
                sharpness=round(sharpness, 1),
                color_richness=round(color_richness, 2),
                phash=phash
            )
        finally:
            img.close()
    except Exception:
        return ImageScore(image_path, 0, 0, 0, 0, 0, 0, 0, 0, "")


# ==========================================
#  批量选择
# ==========================================
def _vision_score_candidates(candidates, purpose, top_n=3):
    """用视觉模型对 top N 候选做二次评分（Gemini 优先 → Ollama 降级）"""
    for c in candidates[:top_n]:
        result = evaluate_image_with_gemini(c.path, purpose)
        if result is None:
            result = evaluate_image_with_ollama(c.path, purpose)
        if result is not None:
            vision_score, reason = result
            if vision_score == 0:
                logger.info("  视觉否决 {}: {}", os.path.basename(c.path), reason)
                c.score = 0
            else:
                cv_score = c.score
                c.score = round(cv_score * 0.4 + vision_score * 0.6, 1)
                logger.info("  视觉融合 {}: CV={:.0f} → {:.0f}",
                            os.path.basename(c.path), cv_score, c.score)


def pick_best_image(image_paths, purpose="body"):
    """从候选列表中按用途择优录取（CV 评分 + 视觉模型辅助决策）"""
    if not image_paths:
        return None

    candidates = []
    seen_hashes = set()
    for path in image_paths:
        score = evaluate_image(path, purpose)
        if score.score > 0:
            if score.phash and score.phash in seen_hashes:
                continue
            if score.phash:
                seen_hashes.add(score.phash)
            candidates.append(score)

    if not candidates:
        return image_paths[0] if image_paths else None

    candidates.sort(key=lambda x: x.score, reverse=True)
    _vision_score_candidates(candidates, purpose)
    candidates.sort(key=lambda x: x.score, reverse=True)

    best = candidates[0]
    logger.info(
        "  智能图选({}): 从 {} 候选选中 {} ({:.0f}分 {}x{})",
        purpose, len(image_paths),
        os.path.basename(best.path), best.score, best.width, best.height
    )
    return best.path


def pick_cover_image(image_paths):
    """封面专用选择（偏好 2.35:1 宽屏、高分辨率、少文字）"""
    return pick_best_image(image_paths, purpose="cover")


# 向后兼容别名
pick_best_image_cover = pick_cover_image
