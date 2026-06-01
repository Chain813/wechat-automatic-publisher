"""
GitHub Trending 采集引擎 v2.0
集成：PyGithub + rich 目录树 + diagrams 架构图 + carbon 代码截图
"""
import os
import re
import io
import time
import requests
from datetime import datetime, timedelta
import json
from loguru import logger
import subprocess
import shutil
from github import Github
from bs4 import BeautifulSoup
from utils.http_client import build_api_session

HTTP_SESSION = build_api_session()
GITHUB_HISTORY_FILE = "github_history.json"

def _load_github_history():
    if os.path.exists(GITHUB_HISTORY_FILE):
        try:
            with open(GITHUB_HISTORY_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception as e:
            logger.warning("  历史记录加载失败: {}", e)
    return set()

def save_github_history(new_repos):
    history = _load_github_history()
    history.update(new_repos)
    # 限制历史记录数量，防止文件过大（保留最新2000条）
    history_list = list(history)[-2000:]
    try:
        with open(GITHUB_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("  历史记录保存失败: {}", e)

# ---- 优先匹配：架构图、流程图、演示截图等 ----
ARCHITECTURE_KEYWORDS = [
    "architecture", "arch", "diagram", "structure", "overview", "workflow",
    "pipeline", "system", "demo", "screenshot", "preview", "banner",
    "flow", "graph", "schema", "design", "framework",
    "架构", "结构", "流程", "演示", "预览", "示意图",
]

LOW_PRIORITY_KEYWORDS = [
    "logo", "icon", "badge", "shield", "travis", "cover", "favicon",
    "avatar", "profile",
]

# ---- 语言 -> diagrams 节点映射 ----
LANG_DIAGRAM_MAP = {
    "Python": ("python", "Python"),
    "JavaScript": ("js", "JavaScript"),
    "TypeScript": ("js", "TypeScript"),
    "Go": ("golang", "Go"),
    "Rust": ("rust", "Rust"),
    "Java": ("java", "Java"),
    "C++": ("cplusplus", "C++"),
    "C": ("c", "C"),
    "Ruby": ("ruby", "Ruby"),
    "PHP": ("php", "PHP"),
    "Swift": ("swift", "Swift"),
    "Kotlin": ("kotlin", "Kotlin"),
    "Scala": ("scala", "Scala"),
    "C#": ("csharp", "C#"),
    "Dart": ("dart", "Dart"),
    "Lua": ("lua", "Lua"),
    "Shell": ("bash", "Shell"),
    "HTML": ("html5", "HTML"),
    "CSS": ("css3", "CSS"),
    "Vue": ("vuejs", "Vue.js"),
    "Svelte": ("svelte", "Svelte"),
}


def _get_github_client():
    """获取 PyGithub 客户端（支持可选 token）"""
    token = os.getenv("GITHUB_TOKEN", "")
    if token:
        return Github(token)
    return Github()


def _find_chinese_readme(repo):
    """
    在仓库根目录下寻找中文 README 文件。
    """
    try:
        contents = repo.get_contents("")
        for item in contents:
            if item.type == "file":
                name_lower = item.name.lower()
                if "readme" in name_lower and any(zh in name_lower for zh in ["zh", "cn", "chinese", "中文"]):
                    return item.path
    except Exception:
        pass
    return None


def _find_other_docs_files(repo):
    """
    寻找其他说明文档，例如 docs/ 目录下的 md 文件，或者根目录下的其他 md 文件。
    """
    docs_files = []
    try:
        root_items = repo.get_contents("")
        for item in root_items:
            if item.type == "file" and item.name.lower().endswith(".md"):
                name_lower = item.name.lower()
                if "readme" not in name_lower and any(kw in name_lower for kw in ["doc", "guide", "tutorial", "index", "intro", "usage", "quickstart"]):
                    docs_files.append(item.path)
            elif item.type == "dir" and item.name.lower() in ["docs", "doc"]:
                try:
                    dir_items = repo.get_contents(item.path)
                    for subitem in dir_items:
                        if subitem.type == "file" and subitem.name.lower().endswith(".md"):
                            docs_files.append(subitem.path)
                except Exception:
                    pass
    except Exception:
        pass
    return docs_files[:3]


# ================================================================
#  Demo URL 多策略检测
# ================================================================
# 已知部署平台域名
_DEPLOY_PLATFORMS = [
    'vercel.app', 'netlify.app', 'github.io', 'onrender.com',
    'fly.dev', 'railway.app', 'herokuapp.com', 'surge.sh',
    'pages.dev', 'workers.dev', 'glitch.me', 'repl.co',
]


def _detect_demo_url(repo, chinese_readme_excerpt, readme_excerpt):
    """
    多策略检测项目的在线 Demo/主页 URL。
    策略优先级：repo.homepage > README 关键词链接 > Badge 链接 > 平台 URL > GitHub Pages
    """
    # 策略 0: GitHub API 提供的 homepage
    homepage_url = repo.homepage
    if homepage_url:
        logger.info(f"  🔍 使用 repo.homepage: {homepage_url}")
        return homepage_url

    readme_text = chinese_readme_excerpt if chinese_readme_excerpt else readme_excerpt
    if not readme_text:
        return None

    # 策略 1: README 中带 Demo 关键词的 Markdown 链接
    demo_matches = re.findall(
        r'\[([^\]]*(?:demo|live|website|preview|homepage|playground|app|try|visit|online|在线)[^\]]*)\]'
        r'\((https?://[^\)]+)\)',
        readme_text, re.IGNORECASE
    )
    if demo_matches:
        homepage_url = demo_matches[0][1]
        logger.info(f"  🔍 从关键词链接提取: {homepage_url}")
        return homepage_url

    # 策略 2: Badge 链接 [![alt](badge-img)](actual-url)
    badge_matches = re.findall(
        r'\[!\[[^\]]*\]\([^\)]*\)\]\((https?://[^\)]+)\)',
        readme_text
    )
    for url in badge_matches:
        if any(p in url.lower() for p in _DEPLOY_PLATFORMS):
            logger.info(f"  🔍 从 Badge 链接提取: {url}")
            return url

    # 策略 3: 裸平台 URL（非 Markdown 链接格式）
    platform_pattern = (
        r'https?://[a-zA-Z0-9_-]+\.'
        r'(?:' + '|'.join(re.escape(p) for p in _DEPLOY_PLATFORMS) + r')'
        r'[^\s\)\]"]*'
    )
    platform_matches = re.findall(platform_pattern, readme_text)
    if platform_matches:
        homepage_url = platform_matches[0]
        logger.info(f"  🔍 从平台 URL 匹配: {homepage_url}")
        return homepage_url

    # 策略 4: GitHub Pages（repo.has_pages = True）
    if repo.has_pages:
        homepage_url = f"https://{repo.owner.login}.github.io/{repo.name}/"
        logger.info(f"  🔍 GitHub Pages 兜底: {homepage_url}")
        return homepage_url

    return None


# ================================================================
#  PyGithub: 获取单项目深度推荐
# ================================================================
def fetch_one_worthy_project():
    """
    使用 GitHub Search API 获取近期热门项目。
    通过随机化查询策略 + 多样性约束确保每次推荐不同类型/语言的项目。
    自动过滤已经抓取过的历史项目。
    """
    import random as _random

    logger.info("正在通过 GitHub Search API 拉取候选池进行 AI 评估...")
    history = _load_github_history()
    candidates = []

    try:
        g = _get_github_client()

        # ---- 随机化搜索策略：每次从不同角度搜索，避免结果雷同 ----
        date_30d = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        date_90d = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        date_180d = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

        # 随机选择语言过滤（50% 概率加语言约束）
        lang_pool = ["Python", "JavaScript", "TypeScript", "Go", "Rust", "Java", "C++", None]
        rand_lang = _random.choice(lang_pool)
        lang_filter = f" language:{rand_lang}" if rand_lang else ""

        # 随机选择时间范围和星数门槛
        query_variants = [
            f"created:>{date_30d} stars:>200{lang_filter}",       # 近 1 月新兴
            f"created:>{date_90d} stars:>500{lang_filter}",       # 近 3 月热门
            f"created:>{date_180d} stars:>1000{lang_filter}",     # 近半年高星
            f"pushed:>{date_30d} stars:>5000{lang_filter}",       # 经典活跃
            f"pushed:>{date_30d} stars:>10000",                    # 顶级项目（不加语言限制）
            f"created:>{date_90d} stars:>100 topic:ai",            # AI 专题
            f"created:>{date_90d} stars:>100 topic:cli",           # CLI 工具
            f"created:>{date_90d} stars:>100 topic:web",           # Web 项目
        ]
        # 每次随机选 2-3 个查询
        num_queries = _random.randint(2, 3)
        selected_queries = _random.sample(query_variants, min(num_queries, len(query_variants)))

        for query in selected_queries:
            logger.info("  搜索: {}", query)
            try:
                # 搜索结果也随机偏移起始位置（避免每次都是前几名）
                offset = _random.randint(0, 10)
                raw_repos = list(g.search_repositories(query=query, sort="stars", order="desc")[offset:offset+20])
                for repo in raw_repos:
                    if repo.full_name not in history:
                        candidates.append(repo)
                        if len(candidates) >= 20:
                            break
            except Exception as e:
                logger.warning("  搜索失败: {} — {}", query, e)
            if len(candidates) >= 20:
                break

        if not candidates:
            return []

        # 去重候选列表
        seen = set()
        unique_candidates = []
        for repo in candidates:
            if repo.full_name not in seen:
                seen.add(repo.full_name)
                unique_candidates.append(repo)
        candidates = unique_candidates[:15]

        # 构造 LLM 评估 prompt（强调多样性）
        eval_text = ""
        for i, repo in enumerate(candidates):
            desc = (repo.description or "无")[:100]
            lang = repo.language or "未知"
            eval_text += f"{i}. {repo.full_name} | {lang} | {repo.stargazers_count}⭐\n   {desc}\n"

        system_prompt = (
            "你是资深开源社区编辑，为中文开发者挑选本周最值得推荐的 GitHub 项目。\n\n"
            "## 核心原则：多样性优先\n"
            "不要总是选同类项目。根据候选列表的实际内容，灵活选择最能给读者带来新鲜感的项目。\n\n"
            "## 评估维度（综合考量，不要过度偏向某一项）\n"
            "1. **实用性**：能解决开发者真实痛点的工具\n"
            "2. **创新性**：技术方案新颖、有话题度\n"
            "3. **可展示性**：有 README 截图/GIF/在线 Demo 的项目优先（方便配图）\n"
            "4. **大众适用**：面向普通开发者，而非极其底层的晦涩项目\n"
            "5. **新鲜感**：如果候选中有多个 AI 项目，选一个非 AI 的换换口味\n\n"
            "请直接输出你挑选的项目编号（纯数字），不要输出任何其他内容。"
        )

        from core.shared.llm import call_deepseek_with_retry
        best_idx_str = call_deepseek_with_retry(eval_text, system_content=system_prompt, max_retries=2)

        best_idx = 0
        try:
            best_idx = int(re.search(r'\d+', best_idx_str).group())
            if best_idx < 0 or best_idx >= len(candidates):
                best_idx = 0
        except Exception:
            best_idx = 0

        best_repo = candidates[best_idx]
        logger.info(f"  🏆 AI 评估选出最佳项目: {best_repo.full_name} | ⭐ {best_repo.stargazers_count}")

        image_url, readme_excerpt, tree_image_path, other_images, readme_file_path, chinese_readme_excerpt = get_readme_info(best_repo.full_name)

        # 提取 GitHub Social Preview 图片（仓库所有者设置的高质量封面）
        social_preview_url = best_repo.raw_data.get("open_graph_image_url")
        if social_preview_url:
            if other_images is None:
                other_images = []
            other_images.insert(0, social_preview_url)
            logger.info(f"  🖼️ 发现 Social Preview 封面图")

        # 多策略提取 Demo/主页 URL
        homepage_url = _detect_demo_url(best_repo, chinese_readme_excerpt, readme_excerpt)

        return [{
            "repo": best_repo.full_name,
            "desc": best_repo.description or "暂无描述",
            "lang": best_repo.language or "Unknown",
            "image_url": image_url,
            "readme_excerpt": readme_excerpt,
            "chinese_readme_excerpt": chinese_readme_excerpt,
            "tree_image_path": tree_image_path,
            "stars": best_repo.stargazers_count,
            "topics": best_repo.get_topics(),
            "homepage": homepage_url,
            "other_images": other_images,
            "readme_file_path": readme_file_path,
            "social_preview_url": social_preview_url,
        }]

    except Exception as e:
        logger.error("  GitHub Search API 失败: {}", e)
        return []


# ================================================================
#  PyGithub: 获取项目信息
# ================================================================
def get_readme_info(repo_name):
    """
    获取项目说明文档的文本和图片，支持识别中文 README 及 docs 目录。
    返回 (image_url, text_excerpt, local_image_path, other_images, readme_file_path, chinese_readme_excerpt)
    """
    try:
        g = _get_github_client()
        repo = g.get_repo(repo_name)

        # 1. 寻找主 README (通常是英文) 和 中文 README
        english_readme_path = None
        chinese_readme_path = _find_chinese_readme(repo)

        # 获取主 README
        english_text = ""
        try:
            readme = repo.get_readme()
            english_readme_path = readme.path
            english_text = readme.decoded_content.decode("utf-8", errors="ignore")
        except Exception:
            # Fallback: list contents to find readme
            try:
                root_items = repo.get_contents("")
                for item in root_items:
                    if item.type == "file" and "readme.md" == item.name.lower():
                        english_readme_path = item.path
                        english_text = item.decoded_content.decode("utf-8", errors="ignore")
                        break
            except Exception:
                pass

        # 获取中文 README
        chinese_text = ""
        if chinese_readme_path:
            try:
                zh_readme = repo.get_contents(chinese_readme_path)
                chinese_text = zh_readme.decoded_content.decode("utf-8", errors="ignore")
            except Exception:
                pass

        # 2. 收集候选图片和扫描其他文档
        candidates = []
        
        # 扫描主 README 的图片
        if english_text:
            for match in re.finditer(r'!\[([^\]]*)\]\(([^\)]+)\)', english_text):
                candidates.append((match.group(2).strip(), match.group(1)))
            for match in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>', english_text):
                img_url = match.group(1).strip()
                alt_match = re.search(r'alt=["\']([^"\']*)["\']', match.group(0))
                alt_text = alt_match.group(1) if alt_match else ""
                candidates.append((img_url, alt_text))

        # 扫描中文 README 的图片
        if chinese_text:
            for match in re.finditer(r'!\[([^\]]*)\]\(([^\)]+)\)', chinese_text):
                candidates.append((match.group(2).strip(), match.group(1)))
            for match in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>', chinese_text):
                img_url = match.group(1).strip()
                alt_match = re.search(r'alt=["\']([^"\']*)["\']', match.group(0))
                alt_text = alt_match.group(1) if alt_match else ""
                candidates.append((img_url, alt_text))

        # 扫描 <video> 标签的 poster 和 <source>（GIF/视频是最高质量配图）
        for text_block in [english_text, chinese_text]:
            if not text_block:
                continue
            for match in re.finditer(r'<video[^>]+poster=["\']([^"\']+)["\'][^>]*>', text_block):
                candidates.append((match.group(1).strip(), "video poster"))
            for match in re.finditer(r'<source[^>]+src=["\']([^"\']+)["\'][^>]*>', text_block):
                src = match.group(1).strip()
                if any(src.lower().endswith(ext) for ext in ['.gif', '.mp4', '.webm', '.mov']):
                    candidates.append((src, "video source"))

        # 扫描其他说明文档的文本与图片
        other_docs_text = ""
        other_docs_paths = _find_other_docs_files(repo)
        for doc_path in other_docs_paths:
            try:
                doc_file = repo.get_contents(doc_path)
                doc_text = doc_file.decoded_content.decode("utf-8", errors="ignore")
                other_docs_text += f"\n--- 文件 {doc_path} ---\n" + doc_text[:1000]
                
                # 提取图片
                for match in re.finditer(r'!\[([^\]]*)\]\(([^\)]+)\)', doc_text):
                    candidates.append((match.group(2).strip(), match.group(1)))
                for match in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>', doc_text):
                    img_url = match.group(1).strip()
                    alt_match = re.search(r'alt=["\']([^"\']*)["\']', match.group(0))
                    alt_text = alt_match.group(1) if alt_match else ""
                    candidates.append((img_url, alt_text))
            except Exception:
                pass

        # 3. 对所有候选图片评分和排序
        scored = []
        default_branch = repo.default_branch or "main"
        for img_url, alt_text in candidates:
            if img_url.startswith("http"):
                if "github.com" in img_url and "/blob/" in img_url:
                    img_url = img_url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
            else:
                rel_path = img_url.lstrip('/')
                rel_path = re.sub(r'^\.+/', '', rel_path)
                img_url = f"https://raw.githubusercontent.com/{repo_name}/{default_branch}/{rel_path}"
            
            score = _score_readme_image(img_url, alt_text)
            if score >= 0:
                scored.append((img_url, score))

        # 4. 提取文本节选
        english_excerpt = _extract_readme_text(english_text)[:1500]
        chinese_excerpt = _extract_readme_text(chinese_text)[:1500] if chinese_text else ""
        
        if other_docs_text:
            english_excerpt += f"\n\n【其他说明文档参考】:\n{other_docs_text[:1500]}"

        # 5. 确定主截图的目标文档路径：中文 README 优先，否则用英文 README
        readme_file_path = chinese_readme_path if chinese_readme_path else english_readme_path

        if not scored:
            tree_path = _generate_tree_fallback(repo_name, repo)
            return None, english_excerpt, tree_path, [], readme_file_path, chinese_excerpt

        # 排序并去重
        scored.sort(key=lambda x: x[1], reverse=True)
        unique_urls = []
        for url, s in scored:
            if url not in unique_urls:
                unique_urls.append(url)

        best_img = unique_urls[0]
        other_imgs = unique_urls[1:8]

        return best_img, english_excerpt, None, other_imgs, readme_file_path, chinese_excerpt

    except Exception as e:
        logger.debug("  PyGithub 获取 README 失败 {}: {}", repo_name, e)
        return None, "", None, [], None, ""


def _extract_readme_text(text):
    """提取 README 纯文本节选"""
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'<[^>]+>', '', text)
    return text[:1500].strip()


def _score_readme_image(img_url, alt_text=""):
    """评分 README 图片，优先选择 GIF 动画 > 视频 > 架构图/流程图"""
    lower_url = img_url.lower()
    lower_alt = alt_text.lower() if alt_text else ""
    combined = lower_url + " " + lower_alt

    for kw in LOW_PRIORITY_KEYWORDS:
        if kw in combined:
            return -1

    score = 0
    for kw in ARCHITECTURE_KEYWORDS:
        if kw in combined:
            score += 10

    # 动画 GIF 是最有价值的配图（几乎都是项目实际运行效果）
    if ".gif" in lower_url:
        score += 25
    # 视频 poster/截图也是高质量素材
    elif any(ext in lower_url for ext in [".mp4", ".webm", ".mov"]):
        score += 20
    elif any(ext in lower_url for ext in [".png", ".svg"]):
        score += 2

    if "raw.githubusercontent.com" in lower_url:
        score += 3
    if "/assets/" in lower_url or "/docs/" in lower_url or "/images/" in lower_url:
        score += 5
    return score


# ================================================================
#  生成项目目录树截图（PyGithub + rich）
# ================================================================
def _generate_tree_fallback(repo_name, repo=None):
    """
    当 README 无图片时，依次尝试：
    1. rich 渲染目录树
    2. diagrams 生成架构图
    """
    # 尝试 rich 目录树
    tree_path = _render_tree_with_rich(repo_name, repo)
    if tree_path:
        return tree_path

    # 尝试 diagrams 架构图
    arch_path = _generate_arch_diagram(repo_name, repo)
    if arch_path:
        return arch_path

    return None


def _render_tree_with_rich(repo_name, repo=None):
    """使用 rich 渲染项目目录树为 PNG 图片"""
    try:
        from rich.tree import Tree
        from rich.console import Console
        from PIL import Image

        save_dir = "assets"
        os.makedirs(save_dir, exist_ok=True)

        # 获取目录树
        if repo is None:
            g = _get_github_client()
            repo = g.get_repo(repo_name)

        tree_data = repo.get_git_tree("HEAD", recursive=False)
        if not tree_data.tree:
            return None

        # 构建 rich Tree
        tree = Tree(f"[bold cyan]📦 {repo_name}[/]")
        for item in sorted(tree_data.tree, key=lambda x: (x.type != "tree", x.path)):
            if item.type == "tree":
                tree.add(f"[bold blue]📁 {item.path}/[/]")
            else:
                tree.add(f"[white]📄 {item.path}[/]")

        # 导出为 SVG
        console = Console(width=80, record=True, force_terminal=True)
        console.print(tree)
        svg_content = console.export_svg(title=f"{repo_name} Structure")

        # SVG 转 PNG
        svg_path = os.path.join(save_dir, f"tree_{repo_name.replace('/', '_')}.svg")
        png_path = os.path.join(save_dir, f"tree_{repo_name.replace('/', '_')}.png")

        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(svg_content)

        # 用 PIL 将 SVG 渲染为 PNG（简化方案：直接用 rich 的文本渲染）
        png_path = _render_tree_text_to_png(repo_name, tree_data.tree, save_dir)

        logger.info("  已生成项目目录树图片 (rich): {}", png_path)
        return png_path

    except Exception as e:
        logger.debug("  rich 目录树渲染失败: {}", e)
        return None


def _render_tree_text_to_png(repo_name, tree_items, save_dir):
    """将目录树文本渲染为高质量 PNG"""
    from PIL import Image, ImageDraw, ImageFont

    # 构建显示内容
    lines = [f"📦 {repo_name}", "━" * 40]
    dirs = [i for i in tree_items if i.type == "tree"]
    files = [i for i in tree_items if i.type != "tree"]

    for d in sorted(dirs, key=lambda x: x.path)[:15]:
        lines.append(f"  📁 {d.path}/")
    for f in sorted(files, key=lambda x: x.path)[:20]:
        lines.append(f"  📄 {f.path}")

    total = len(dirs) + len(files)
    if total > 35:
        lines.append(f"  ... ({total - 35} more items)")

    # 图片参数
    font_size = 15
    line_height = 22
    padding = 25
    max_line_len = max(len(line) for line in lines)
    img_width = min(max(max_line_len * 9 + padding * 2, 400), 900)
    img_height = len(lines) * line_height + padding * 2

    img = Image.new("RGB", (img_width, img_height), color=(24, 24, 32))
    draw = ImageDraw.Draw(img)

    # 加载字体
    font = None
    for fp in ["C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/msyh.ttc"]:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, font_size)
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()

    # 绘制标题
    draw.text((padding, padding), lines[0], fill=(100, 200, 255), font=font)
    draw.text((padding, padding + line_height), lines[1], fill=(60, 60, 80), font=font)

    y = padding + line_height * 2 + 5
    for line in lines[2:]:
        if line.startswith("  📁"):
            color = (100, 200, 255)
        elif line.startswith("  📄"):
            color = (200, 200, 210)
        else:
            color = (150, 150, 160)
        draw.text((padding, y), line, fill=color, font=font)
        y += line_height

    save_path = os.path.join(save_dir, f"tree_{repo_name.replace('/', '_')}.png")
    img.save(save_path, "PNG")
    return save_path


# ================================================================
#  diagrams: 生成架构图
# ================================================================
def _generate_arch_diagram(repo_name, repo=None):
    """使用 diagrams 根据项目技术栈生成架构图"""
    try:
        from diagrams import Diagram, Cluster, Edge
        from diagrams.generic.blank import Blank

        if repo is None:
            g = _get_github_client()
            repo = g.get_repo(repo_name)

        lang = repo.language or "Unknown"
        topics = repo.get_topics() if hasattr(repo, 'get_topics') else []

        save_dir = "assets"
        os.makedirs(save_dir, exist_ok=True)

        safe_name = repo_name.replace("/", "_")
        output_path = os.path.join(save_dir, f"arch_{safe_name}")

        # 根据语言和主题推断架构组件
        components = _infer_components(lang, topics)

        with Diagram(
            f"{repo_name} Architecture",
            filename=output_path,
            outformat="png",
            show=False,
            graph_attr={"bgcolor": "transparent", "pad": "0.5"},
        ):
            # 核心节点
            core = Blank(f"{lang}\nApplication")

            # 数据层
            if components.get("database"):
                with Cluster("Data Layer"):
                    db_nodes = [Blank(s) for s in components["database"][:3]]
                    for db in db_nodes:
                        core >> Edge(color="brown") >> db

            # API 层
            if components.get("api"):
                with Cluster("API Layer"):
                    api_nodes = [Blank(s) for s in components["api"][:3]]
                    for api in api_nodes:
                        api >> Edge(color="blue") >> core

            # 工具/中间件
            if components.get("middleware"):
                for mw in components["middleware"][:3]:
                    mw_node = Blank(mw)
                    core >> Edge(color="green", style="dashed") >> mw_node

        # diagrams 生成的文件会自动加 .png 后缀
        final_path = output_path + ".png"
        if os.path.exists(final_path):
            logger.info("  已生成架构图 (diagrams): {}", final_path)
            return final_path

    except Exception as e:
        logger.debug("  diagrams 架构图生成失败: {}", e)
    return None


def _infer_components(language, topics):
    """根据语言和主题推断架构组件"""
    components = {"database": [], "api": [], "middleware": []}

    # 基于主题推断
    topic_str = " ".join(topics).lower()
    if any(k in topic_str for k in ["database", "sql", "postgres", "mysql", "redis", "mongo"]):
        components["database"].extend(["Database", "Cache"])
    if any(k in topic_str for k in ["api", "rest", "graphql", "grpc", "web"]):
        components["api"].extend(["REST API", "Gateway"])
    if any(k in topic_str for k in ["ml", "ai", "model", "training", "inference"]):
        components["middleware"].extend(["ML Pipeline", "Model Server"])
    if any(k in topic_str for k in ["docker", "kubernetes", "k8s", "container"]):
        components["middleware"].append("Container Runtime")
    if any(k in topic_str for k in ["cli", "terminal", "shell"]):
        components["api"].append("CLI Interface")

    # 基于语言推断补充
    if language == "Python":
        if not components["api"]:
            components["api"].append("Python API")
    elif language in ("JavaScript", "TypeScript"):
        if not components["api"]:
            components["api"].append("Node.js Server")
    elif language == "Go":
        if not components["api"]:
            components["api"].append("Go HTTP Server")

    return components


# ================================================================
#  carbon: 代码截图
# ================================================================
def generate_code_screenshot(code_text, language="python", save_dir="assets"):
    """
    使用 carbon API 生成代码截图。
    返回本地文件路径。
    """
    try:
        os.makedirs(save_dir, exist_ok=True)

        # 使用 carbon API
        url = "https://carbonara.solopov.dev/api/cook"
        payload = {
            "code": code_text[:2000],  # 限制长度
            "language": language.lower(),
            "theme": "one-dark",
            "backgroundColor": "rgba(17, 24, 39, 1)",
            "paddingVertical": "40px",
            "paddingHorizontal": "40px",
        }

        res = requests.post(url, json=payload, timeout=20)
        if res.status_code == 200 and len(res.content) > 5000:
            save_path = os.path.join(save_dir, f"code_{int(time.time())}.png")
            with open(save_path, "wb") as f:
                f.write(res.content)
            logger.info("  已生成代码截图 (carbon): {}", save_path)
            return save_path

    except Exception as e:
        logger.debug("  carbon 代码截图失败: {}", e)
    return None


def get_repo_code_snippet(repo_name, file_path=None):
    """获取项目的代码片段（用于 carbon 截图）"""
    try:
        g = _get_github_client()
        repo = g.get_repo(repo_name)

        # 尝试获取主入口文件
        if file_path is None:
            candidates = [
                "main.py", "app.py", "index.js", "index.ts", "main.go",
                "src/main.py", "src/index.js", "src/main.go", "lib/main.rb",
                "Cargo.toml", "package.json", "setup.py", "pyproject.toml",
            ]
            for candidate in candidates:
                try:
                    content = repo.get_contents(candidate)
                    if content and content.decoded_content:
                        text = content.decoded_content.decode("utf-8", errors="ignore")
                        return text[:2000], candidate
                except Exception:
                    continue

            # 如果没找到入口文件，获取 README 的前几行
            try:
                readme = repo.get_readme()
                text = readme.decoded_content.decode("utf-8", errors="ignore")
                return text[:1000], "README.md"
            except Exception:
                pass
        else:
            content = repo.get_contents(file_path)
            if content and content.decoded_content:
                text = content.decoded_content.decode("utf-8", errors="ignore")
                return text[:2000], file_path

    except Exception as e:
        logger.debug("  获取代码片段失败 {}: {}", repo_name, e)
    return None, None


def take_github_readme_screenshot(repo_name, readme_file_path=None, save_dir="assets"):
    """
    使用无头浏览器截取 GitHub 仓库 README 概览，并裁剪为微信公众号配图比例 (2.35:1)。
    支持指定说明文档路径（例如中文 README），截图对应的渲染页面。
    """
    import os
    import time
    from PIL import Image
    from utils.spider import build_stealth_browser
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    os.makedirs(save_dir, exist_ok=True)
    safe_name = repo_name.replace("/", "_")
    save_path = os.path.join(save_dir, f"readme_raw_{safe_name}.png")
    final_path = os.path.join(save_dir, f"readme_{safe_name}.jpg")

    browser = None
    try:
        browser = build_stealth_browser(headless=True)
        browser.set_window_size(1440, 1080)
        browser.set_page_load_timeout(45)

        if readme_file_path:
            # 获取默认分支以构造正确的文件 URL
            g = _get_github_client()
            repo = g.get_repo(repo_name)
            default_branch = repo.default_branch or "main"
            url = f"https://github.com/{repo_name}/blob/{default_branch}/{readme_file_path}"
        else:
            url = f"https://github.com/{repo_name}#readme"

        logger.info(f"  📸 正在截取文档页面: {url}")
        browser.get(url)

        try:
            element = WebDriverWait(browser, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "article.markdown-body"))
            )
            browser.execute_script("arguments[0].scrollIntoView(true);", element)
            time.sleep(2)
            element.screenshot(save_path)
        except Exception as e:
            logger.warning("  未找到 markdown-body 元素，尝试截取全屏: {}", e)
            browser.save_screenshot(save_path)
            
    except Exception as e:
        logger.error("  截取 README 失败 {}: {}", repo_name, e)
        return None
    finally:
        if browser:
            browser.quit()

    if not os.path.exists(save_path):
        return None

    try:
        with Image.open(save_path) as img:
            w, h = img.size
            target_h = int(w / 2.35)
            crop_h = min(h, target_h)
            cropped = img.crop((0, 0, w, crop_h))
            
            if cropped.mode == 'RGBA':
                bg = Image.new('RGB', cropped.size, (255, 255, 255))
                bg.paste(cropped, mask=cropped.split()[3])
                cropped = bg
            elif cropped.mode != 'RGB':
                cropped = cropped.convert('RGB')
                
            cropped.save(final_path, 'JPEG', quality=95)
        
        try:
            os.remove(save_path)
        except Exception:
            pass

        logger.info("  已生成 README 截图: {}", final_path)
        return final_path
    except Exception as e:
        logger.error("  裁剪 README 截图失败 {}: {}", repo_name, e)
        return save_path

# ================================================================
#  临时部署与 UI 截图
# ================================================================
def take_live_ui_screenshot(repo_name, homepage_url, save_dir="assets"):
    """
    通过无头浏览器直接访问项目的主页/在线 Demo 地址，并截取 UI 截图。
    放弃本地 Clone/部署策略，规避安全风险与依赖构建失败问题。
    """
    import os
    import time
    from PIL import Image
    from utils.spider import build_stealth_browser

    if not homepage_url or not homepage_url.startswith("http"):
        logger.warning(f"  跳过在线 UI 截图：主页地址 '{homepage_url}' 无效")
        return None

    logger.info(f"  🖥️ 正在截取在线 UI 页面: {homepage_url}")
    os.makedirs(save_dir, exist_ok=True)
    safe_name = repo_name.replace("/", "_")
    save_path = os.path.join(save_dir, f"ui_raw_{safe_name}.png")
    final_path = os.path.join(save_dir, f"ui_{safe_name}.jpg")

    browser = None
    try:
        browser = build_stealth_browser(headless=True)
        browser.set_window_size(1440, 900)
        browser.set_page_load_timeout(30)
        browser.get(homepage_url)

        # 智能等待页面渲染完成（替代固定 sleep(5)，快页面省 2-4 秒）
        try:
            from selenium.webdriver.support.ui import WebDriverWait
            WebDriverWait(browser, 8).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except Exception:
            pass  # 超时也继续截图
        browser.save_screenshot(save_path)
        
        with Image.open(save_path) as img:
            if img.mode != 'RGB':
                img = img.convert('RGB')
            img.save(final_path, 'JPEG', quality=90)
            
        try:
            os.remove(save_path)
        except Exception:
            pass
            
        logger.info(f"  ✅ 成功获取在线 UI 截图: {final_path}")
        return final_path
    except Exception as e:
        logger.warning(f"  在线 UI 截图失败 {repo_name}: {e}")
        return None
    finally:
        if browser:
            try:
                browser.quit()
            except Exception:
                pass
__all__ = ["fetch_one_worthy_project", "generate_code_screenshot", "get_repo_code_snippet", "save_github_history", "take_github_readme_screenshot", "take_live_ui_screenshot"]
