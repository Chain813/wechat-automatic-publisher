import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import markdown
import requests
from loguru import logger

from config import BRAND_NAME, WECHAT_TITLE_MAX_LEN
from core.shared.llm import filter_sensitive, simplify_keyword, call_deepseek_with_retry
from utils.image_handler import download_image

ASSET_RETENTION_DAYS = 5
PLACEHOLDER_PATTERN = re.compile(r"【\s*此处插入配图\s*[：:]\s*(.*?)\s*】")
GITHUB_IMAGE_PATTERN = re.compile(r"【\s*GITHUB配图\s*[：:]\s*(https?://.*?)\s*】")

# 预编译结构性标签清理正则（避免每篇文章重复编译 30 个正则）
_STRUCTURAL_LABELS = [
    "事件钩子", "拆解博弈", "技术逻辑", "预判观点", "互动收尾",
    "核心特性", "适用场景", "项目亮点", "技术/产业逻辑", "技术与产业深挖",
]
_STRUCTURAL_LABEL_PATTERNS = []
for _label in _STRUCTURAL_LABELS:
    _escaped = re.escape(_label)
    _STRUCTURAL_LABEL_PATTERNS.append(re.compile(rf'#+\s*{_escaped}\s*[:：]?\s*\n?'))
    _STRUCTURAL_LABEL_PATTERNS.append(re.compile(rf'\*\*{_escaped}\*\*\s*[:：]?\s*'))
    _STRUCTURAL_LABEL_PATTERNS.append(re.compile(rf'{_escaped}[：:]\s*'))


def _optimize_image_keyword_with_llm(original_keyword):
    """
    当常规搜索无法找到高质量图片时，调用 LLM 将抽象的政策/技术术语
    转化为更具视觉表现力的搜索词。
    例如：'AI 监管政策' -> '科技感天平 电路纹理 蓝色光效'
    仅在 simplify_keyword 也失败后触发，token 消耗极低 (~100 tokens)。
    """
    if not original_keyword or len(original_keyword) < 2:
        return ""
    prompt = (
        f"原始关键词：{original_keyword}\n\n"
        "请将这个关键词转化为一个适合在图片搜索引擎中使用的、具有强烈视觉画面感的搜索词。\n"
        "要求：\n"
        "- 输出 3-5 个中文关键词，用空格分隔\n"
        "- 关键词要具象化、有画面感（如'芯片电路板特写'、'数据流光效'）\n"
        "- 避免抽象概念词（如'政策'、'监管'、'趋势'）\n"
        "- 直接输出关键词，不要有其他文字"
    )
    try:
        result = call_deepseek_with_retry(
            prompt,
            system_content="你是一个图片搜索优化专家。只输出优化后的搜索关键词。",
            max_retries=1,
            backoff_base=0.3,
        )
        if result:
            optimized = result.strip().split('\n')[0].strip()
            logger.info("  LLM 图像关键词优化: '{}' -> '{}'", original_keyword, optimized)
            return optimized
    except Exception as e:
        logger.debug("  LLM 图像关键词优化失败: {}", e)
    return ""


def _download_and_upload(keyword, publisher, use_ai_first=False):
    """下载图片并立即上传到微信，合并为单步操作（供并行调用）"""
    keyword = keyword.strip()
    if not keyword:
        return keyword, None

    # 根据场景选择下载函数（仅解析一次）
    if use_ai_first:
        from utils.image_handler import download_image_for_hotspot as _dl
    else:
        from utils.image_handler import download_image as _dl

    logger.info("正在为段落关键词 '{}' 搜寻最佳配图...", keyword)
    image_path = _dl(keyword)

    # 降级：简化关键词重试
    if not image_path:
        simplified = simplify_keyword(keyword)
        if simplified and simplified.strip():
            image_path = _dl(simplified)

    # LLM 关键词优化兜底：将抽象概念转化为视觉化搜索词
    if not image_path:
        optimized = _optimize_image_keyword_with_llm(keyword)
        if optimized:
            image_path = _dl(optimized)

    if not image_path:
        return keyword, None

    image_url = publisher.upload_news_image(image_path)
    return keyword, image_url

def _extract_image_placeholders(article_text):
    placeholders = []
    seen = set()
    for match in PLACEHOLDER_PATTERN.findall(article_text or ""):
        keyword = match.strip()
        if keyword and keyword not in seen:
            seen.add(keyword)
            placeholders.append(keyword)
    return placeholders

def _replace_placeholder(html_body, keyword, replacement):
    # 使用正则表达式进行不区分空格的替换
    pattern = re.compile(rf"【\s*此处插入配图\s*[：:]\s*{re.escape(keyword)}\s*】")
    return pattern.sub(replacement, html_body)

def process_article_content(article_text, publisher, use_ai_first=False):
    if not article_text:
        return "", {"word_count": 0, "image_count": 0, "sensitive_words": []}

    cleaned = re.sub(r"```\s*markdown\s*\n?", "", article_text)
    cleaned = re.sub(r"```\s*\n?", "", cleaned).strip()

    # 移除残留的结构性标签文字（LLM 可能仍会输出）
    for pattern in _STRUCTURAL_LABEL_PATTERNS:
        cleaned = pattern.sub('', cleaned)

    # ---- 粗体兜底：如果 LLM 未输出足够粗体，自动标注关键语句 ----
    bold_count = len(re.findall(r'\*\*[^*]+\*\*', cleaned))
    if bold_count < 5:
        # 自动加粗：带单位的数字（如 3400 亿美元、50%、10 倍）
        cleaned = re.sub(
            r'(?<!\*)\b(\d[\d,.]*\s*(?:亿|万|千|百|倍|%|美元|元|人民币|欧元|英镑|日元|亿美元|万元))\b(?!\*)',
            r'**\1**', cleaned
        )
        # 自动加粗：引号内的关键短句（3-15 字的引用）
        cleaned = re.sub(
            r'(?<!\*)["“]([^"”]{3,15})["”](?!\*)',
            r'**"\1"**', cleaned
        )

    # 重点分级：识别红字重点，自动剥离可能存在的多层花括号 (Anti-Brace-Overflow)
    cleaned = re.sub(r'\*\*\{+(.*?)\}+\*\*', r'<redbold>\1</redbold>', cleaned)

    # ---- 修复低级格式错误 (Anti-Low-Level-Errors V2) ----
    # 1. 修复冒号出现在行首的问题：将行首的冒号合并到上一行末尾
    #    负向前瞻 (?!\d) 避免破坏时间戳（如 10:30）和比例（如 3:1）
    cleaned = re.sub(r'\n\s*[:：](?!\d)', '：', cleaned)

    # 1b. 修复加粗文本后换行再跟冒号的情况（如 **概念**\n：解释）
    cleaned = re.sub(r'(\*\*[^*]+\*\*)\s*\n\s*[:：](?!\d)', r'\1：', cleaned)
    
    # 2. 修复空列表项：移除只有列表符号但没内容的行（含空白字符）
    cleaned = re.sub(r'^\s*[-*+]\s*$', '', cleaned, flags=re.MULTILINE)
    
    # 2b. 修复列表符号后只有空格/标点但无实质内容的行
    cleaned = re.sub(r'^\s*[-*+]\s*[：:。，,]\s*$', '', cleaned, flags=re.MULTILINE)
    
    # 3. 修复列表项内部的换行问题：如果列表符号后面紧跟换行，则合并
    #    使用 [ \t]* 而非 \s* 避免吞噬列表项之间的空行导致合并不同列表项
    cleaned = re.sub(r'([-*+]\s*)\n[ \t]*', r'\1', cleaned)

    # 4. 移除多余的空行（连续 3 个及以上合并为 2 个）
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    
    # 5. 修复标题后紧跟冒号的问题（如 ## 标题：）
    cleaned = re.sub(r'^(#{1,4}\s+[^\n]+)[:：]\s*$', r'\1', cleaned, flags=re.MULTILINE)
    # ---------------------------------------------

    cleaned, hit_words = filter_sensitive(cleaned)
    if hit_words:
        logger.warning("  检测到敏感词: {}", hit_words)

    placeholders = _extract_image_placeholders(cleaned)
    
    github_images = []
    seen_gh = set()
    for match in GITHUB_IMAGE_PATTERN.findall(cleaned or ""):
        url = match.strip()
        if url and url not in seen_gh:
            seen_gh.add(url)
            github_images.append(url)

    html_body = markdown.markdown(cleaned, extensions=["extra", "nl2br", "sane_lists"])

    # 更加鲁棒地移除占位符周围的 P 标签
    html_body = re.sub(
        r'<p>\s*(【\s*此处插入配图\s*[：:].*?\s*】)\s*</p>',
        r'\1',
        html_body,
        flags=re.DOTALL
    )
    html_body = re.sub(
        r'<p>\s*(【\s*GITHUB配图\s*[：:].*?\s*】)\s*</p>',
        r'\1',
        html_body,
        flags=re.DOTALL
    )

    image_results = {}
    if placeholders:
        logger.info("启动并行图片下载+上传引擎 ({} 张)...", len(placeholders))
        with ThreadPoolExecutor(max_workers=min(3, len(placeholders))) as executor:
            futures = {executor.submit(_download_and_upload, kw, publisher, use_ai_first): kw for kw in placeholders}
            for future in as_completed(futures):
                try:
                    keyword, image_url = future.result()
                    image_results[keyword] = image_url
                except Exception as exc:
                    logger.warning("  并行图片处理异常: {}", exc)

    image_count = 0
    for keyword in placeholders:
        image_url = image_results.get(keyword)
        if image_url:
            image_html = (
                '<p style="text-align:center;margin: 20px 0;">'
                f'<img src="{image_url}" style="width:100%;max-width:600px;border-radius:12px;'
                'box-shadow: 0 4px 12px rgba(0,0,0,0.1);">'
                "</p>"
            )
            html_body = _replace_placeholder(html_body, keyword, image_html)
            image_count += 1
            logger.info("  配图已成功嵌入文章")
        else:
            html_body = _replace_placeholder(html_body, keyword, "")
            logger.info("  最终未匹配到合适配图，已移除占位符")

    # GitHub 配图并行下载上传
    if github_images:
        def _process_gh_image(gh_url):
            tmp_path = None
            try:
                logger.info("正在下载 GitHub 配图: {}", gh_url)
                res = requests.get(gh_url, timeout=10)
                if res.status_code == 200:
                    tmp_path = os.path.join("assets", f"gh_{int(time.time()*1000)}_{id(gh_url)}.jpg")
                    with open(tmp_path, 'wb') as f:
                        f.write(res.content)
                    image_url = publisher.upload_news_image(tmp_path)
                    return gh_url, image_url
            except Exception as e:
                logger.warning("  GitHub 配图处理失败: {}", e)
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
            return gh_url, None

        logger.info("并行处理 {} 张 GitHub 配图...", len(github_images))
        with ThreadPoolExecutor(max_workers=min(3, len(github_images))) as gh_pool:
            gh_results = list(gh_pool.map(_process_gh_image, github_images))

        for gh_url, image_url in gh_results:
            pattern = re.compile(rf"【GITHUB配图：\s*{re.escape(gh_url)}】")
            if image_url:
                image_html = (
                    '<p style="text-align:center;margin: 20px 0;">'
                    f'<img src="{image_url}" style="width:100%;max-width:600px;border-radius:12px;'
                    'box-shadow: 0 4px 12px rgba(0,0,0,0.1);">'
                    "</p>"
                )
                html_body = pattern.sub(image_html, html_body)
                image_count += 1
                logger.info("  GitHub 配图已成功嵌入文章")
            else:
                html_body = pattern.sub("", html_body)

    # 统一增加段落缩进和间距
    html_body = html_body.replace(
        '<p>', 
        '<p style="margin-bottom: 15px; line-height: 1.8; text-align: justify; font-size: 16px; color: #333;">'
    )
    
    # 优化引用块样式
    html_body = html_body.replace(
        '<blockquote>', 
        '<blockquote style="margin: 20px 0; padding: 15px 20px; border-left: 5px solid #0366d6; background-color: #f6f8fa; color: #586069; border-radius: 4px; font-size: 15px;">'
    )

    # 优化 H2 标题样式 (GitHub 项目名)
    html_body = re.sub(
        r'<h2>(.*?)</h2>',
        r'<h2 style="margin-top: 35px; margin-bottom: 20px; padding-bottom: 8px; border-bottom: 2px solid #eaecef; font-size: 22px; color: #24292e; font-weight: bold;">\1</h2>',
        html_body
    )

    # 优化 H3 标题样式
    html_body = re.sub(
        r'<h3>(.*?)</h3>',
        r'<h3 style="margin-top: 25px; margin-bottom: 15px; font-size: 18px; color: #0366d6; font-weight: bold; border-left: 4px solid #0366d6; padding-left: 10px;">\1</h3>',
        html_body
    )

    # 优化无序列表样式
    html_body = html_body.replace(
        '<ul>',
        '<ul style="margin-bottom: 20px; padding-left: 25px; line-height: 1.8; color: #333;">'
    )

    # 重点分级样式：红色加粗（最核心结论） → 黑色加粗（重要论点）
    html_body = html_body.replace(
        '<redbold>', '<strong style="color: #d73a49; font-weight: bold;">'
    ).replace(
        '</redbold>', '</strong>'
    )
    html_body = re.sub(
        r'<strong>(.*?)</strong>',
        r'<strong style="color: #1a1a1a; font-weight: bold;">\1</strong>',
        html_body
    )

    # 统一行内代码（英文字体）样式，解决字体不统一问题
    font_stack = "-apple-system, BlinkMacSystemFont, 'Helvetica Neue', 'PingFang SC', 'Microsoft YaHei', Arial, sans-serif"
    html_body = html_body.replace(
        '<code>',
        f'<code style="font-family: {font_stack}; background-color: #f6f8fa; padding: 2px 5px; border-radius: 4px; color: #0366d6; font-size: 0.95em;">'
    )

    word_count = len(cleaned.replace("\n", "").replace(" ", ""))
    return html_body, {
        "word_count": word_count,
        "image_count": image_count,
        "sensitive_words": hit_words,
    }


def cleanup_old_assets(base_dir="assets", max_age_days=ASSET_RETENTION_DAYS):
    if not os.path.exists(base_dir):
        return

    now = time.time()
    cutoff = now - max_age_days * 86400
    removed_count = 0
    removed_dirs = 0

    for root, dirs, files in os.walk(base_dir, topdown=False):
        for filename in files:
            filepath = os.path.join(root, filename)
            try:
                if os.path.getmtime(filepath) < cutoff:
                    os.remove(filepath)
                    removed_count += 1
            except OSError as e:
                logger.debug("  清理文件失败 {}: {}", filepath, e)

        for dirname in dirs:
            dirpath = os.path.join(root, dirname)
            try:
                if not os.listdir(dirpath):
                    os.rmdir(dirpath)
                    removed_dirs += 1
            except OSError as e:
                logger.debug("  清理目录失败 {}: {}", dirpath, e)

    if removed_count > 0:
        logger.info(
            "🧹 自动清理：已删除 {} 个过期文件和 {} 个空目录 (>{}天)",
            removed_count,
            removed_dirs,
            max_age_days,
        )

def _print_banner():
    print("\n" + "=" * 60)
    print(f"  🚀 「{BRAND_NAME}」全自动 AI 内容工厂 v6.0")
    print("=" * 60 + "\n")

def _print_review_report(title, word_count, image_count, sensitive_words, cover_ok, digest):
    print(f"\n{'─' * 50}")
    print("  📋 发布前审核报告")
    print(f"{'─' * 50}")

    title_ok = len(title) <= WECHAT_TITLE_MAX_LEN
    title_icon = "✅" if title_ok else "⚠️"
    print(f"  标题：{title} ({len(title)} 字 {title_icon})")

    wc_icon = "✅" if 2000 <= word_count <= 4000 else "⚠️"
    print(f"  字数：{word_count:,} 字 ({wc_icon})")

    image_icon = "✅" if image_count >= 3 else "⚠️"
    print(f"  配图：{image_count} 张 ({image_icon})")

    sensitive_icon = "❌" if sensitive_words else "✅"
    sensitive_msg = f"命中 {len(sensitive_words)} 词: {sensitive_words}" if sensitive_words else "无"
    print(f"  敏感词：{sensitive_msg} ({sensitive_icon})")

    cover_icon = "✅" if cover_ok else "⚠️"
    print(f"  封面图：{'已上传' if cover_ok else '未上传'} ({cover_icon})")

    if digest:
        print(f"  摘要：{digest[:80]}{'...' if len(digest) > 80 else ''}")

    all_ok = title_ok and (2000 <= word_count <= 4000) and image_count >= 3 and not sensitive_words and cover_ok
    print(f"{'─' * 50}")
    print("  🎉 审核通过，可以发布！" if all_ok else "  ⚠️ 存在警告项，请手动检查后再发布。")
    print(f"{'─' * 50}\n")
    return all_ok
