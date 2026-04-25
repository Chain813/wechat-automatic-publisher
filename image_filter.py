"""
============================================================
  智能图片筛选引擎 v5.0 (微信适配版)
  支持：分辨率校验、宽高比审计、文字密度检测、多图评分
  新增：感知哈希去重、微信封面/正文双模式评分、轻量文字检测
============================================================
"""
import os
import hashlib
from io import BytesIO
from dataclasses import dataclass
from PIL import Image, ImageStat, ImageFilter
import numpy as np

from config import IMAGE_RETRY_MAX, IMAGE_DEFAULT_CANDIDATES

from loguru import logger

WECHAT_COVER_WIDTH = 900
WECHAT_COVER_HEIGHT = 383
WECHAT_COVER_RATIO = WECHAT_COVER_WIDTH / WECHAT_COVER_HEIGHT  # ≈ 2.35
WECHAT_BODY_MAX_MB = 2
WECHAT_MATERIAL_MAX_MB = 10

# ---- 评分维度权重 ----
#            分辨率  宽高比  清晰度  文字密度  色彩    文件大小
COVER_WEIGHTS = (0.20, 0.25, 0.20, 0.15, 0.10, 0.10)
BODY_WEIGHTS  = (0.20, 0.20, 0.20, 0.15, 0.15, 0.10)

# ---- 延迟加载 EasyOCR ----
_READER = None
_OCR_STATUS = "PENDING"


def get_ocr_reader():
    """延迟加载 EasyOCR（仅作可选增强）"""
    global _READER, _OCR_STATUS
    if _OCR_STATUS == "DISABLED":
        return None
    if _READER is not None:
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
#  轻量文字密度检测 (Pillow 像素方差法)
# ==========================================
def text_density_light(image_path):
    """
    用 Pillow 像素方差法估算文字密度，零额外依赖。
    原理：文字区域边缘丰富 → 局部方差高 → 文字密度大。
    返回 0.0-1.0 的密度值。
    """
    try:
        img = Image.open(image_path).convert('L')
        # 缩放到统一尺寸加速计算
        img = img.resize((256, 256))
        arr = np.array(img, dtype=np.float32)

        # 局部方差：用 3x3 窗口计算标准差
        h, w = arr.shape
        var_map = np.zeros_like(arr)
        padded = np.pad(arr, 1, mode='edge')
        for i in range(h):
            for j in range(w):
                patch = padded[i:i+3, j:j+3]
                var_map[i, j] = np.std(patch)

        # 高方差区域比例越大 = 文字越多
        high_var_ratio = np.sum(var_map > 15) / var_map.size
        return min(high_var_ratio * 3.0, 1.0)  # 放大并 clamp 到 [0,1]
    except Exception:
        return 0.0


# ==========================================
#  感知哈希 (Perceptual Hash)
# ==========================================
def compute_perceptual_hash(image_path):
    """计算图片的感知哈希 (pHash)，用于相似度去重"""
    try:
        img = Image.open(image_path).convert('L')
        img = img.resize((32, 32), Image.LANCZOS)
        arr = np.array(img, dtype=np.float32)
        # DCT 简化版：用均值哈希
        avg = arr.mean()
        hash_bits = (arr > avg).flatten()
        hash_str = ''.join(['1' if b else '0' for b in hash_bits])
        # 转十六进制缩短
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
        w, h = img.size
        aspect_ratio = w / h if h > 0 else 0
        file_size_kb = os.path.getsize(image_path) / 1024

        # ---- 1. 硬性门槛 ----
        if purpose == "cover":
            # 封面必须够宽
            if w < 600 or h < 200:
                return ImageScore(image_path, 0, w, h, aspect_ratio, file_size_kb, 0, 0, 0, "")
            # 封面文件不能超过 10MB
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

        # 文字密度分 (文字越少分越高)
        text_density = text_density_light(image_path)
        # 再用 EasyOCR 做更精确检测 (如果可用)
        reader = get_ocr_reader()
        ocr_text_count = 0
        if reader:
            try:
                results = reader.readtext(image_path)
                ocr_text_count = len(results)
                if ocr_text_count > 8:
                    return ImageScore(image_path, 0, w, h, aspect_ratio, file_size_kb, 1.0, sharpness, 0, "")
                # EasyOCR 结果修正密度值
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
        color_richness = _compute_color_richness(img)
        if color_richness > 0.5:
            color_score = 100
        elif color_richness > 0.3:
            color_score = 80
        elif color_richness > 0.15:
            color_score = 50
        else:
            color_score = 30

        # 文件大小分 (太小可能质量差，太大浪费流量)
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

        phash = compute_perceptual_hash(image_path)

        return ImageScore(
            path=image_path, score=round(score, 1),
            width=w, height=h, aspect_ratio=round(aspect_ratio, 2),
            file_size_kb=round(file_size_kb, 1),
            text_density=round(text_density, 2),
            sharpness=round(sharpness, 1),
            color_richness=round(color_richness, 2),
            phash=phash
        )
    except Exception:
        return ImageScore(image_path, 0, 0, 0, 0, 0, 0, 0, 0, "")


# ==========================================
#  批量选择
# ==========================================
def pick_best_image(image_paths, purpose="body"):
    """从候选列表中按用途择优录取"""
    if not image_paths:
        return None

    candidates = []
    seen_hashes = set()
    for path in image_paths:
        score = evaluate_image(path, purpose)
        if score.score > 0:
            # 感知哈希去重
            if score.phash and score.phash in seen_hashes:
                continue
            if score.phash:
                seen_hashes.add(score.phash)
            candidates.append(score)

    if not candidates:
        return image_paths[0] if image_paths else None

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
