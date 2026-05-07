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
from loguru import logger
from github import Github
from bs4 import BeautifulSoup
from utils.http_client import build_api_session

HTTP_SESSION = build_api_session()

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


# ================================================================
#  PyGithub: 获取 Trending 项目
# ================================================================
def fetch_github_trending(limit=5):
    """
    使用 GitHub Search API 获取近期热门项目。
    比爬取 trending 页面更稳定可靠。
    """
    logger.info("正在通过 GitHub Search API 拉取热门趋势...")
    projects = []

    try:
        g = _get_github_client()
        # 近 7 天创建的高星项目，或近期星标增长快的项目
        date_7d = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        date_30d = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        # 优先搜索近 7 天高星新项目
        query_new = f"created:>{date_7d} stars:>100"
        repos_new = list(g.search_repositories(query=query_new, sort="stars", order="desc")[:limit])

        # 如果不够，补充近 30 天高星项目
        if len(repos_new) < limit:
            remaining = limit - len(repos_new)
            existing_names = {r.full_name for r in repos_new}
            query_popular = f"created:>{date_30d} stars:>500"
            for repo in g.search_repositories(query=query_popular, sort="stars", order="desc"):
                if len(repos_new) >= limit:
                    break
                if repo.full_name not in existing_names:
                    repos_new.append(repo)
                    existing_names.add(repo.full_name)

        for repo in repos_new[:limit]:
            logger.info(f"  发现热门项目: {repo.full_name} | ⭐ {repo.stargazers_count} | 分析 README...")
            image_url, readme_excerpt, tree_image_path = get_readme_info(repo.full_name)

            projects.append({
                "repo": repo.full_name,
                "desc": repo.description or "暂无描述",
                "lang": repo.language or "Unknown",
                "image_url": image_url,
                "readme_excerpt": readme_excerpt,
                "tree_image_path": tree_image_path,
                "stars": repo.stargazers_count,
                "topics": repo.get_topics(),
            })

    except Exception as e:
        logger.warning("  GitHub Search API 失败，回退到页面爬取: {}", e)
        projects = _fetch_trending_fallback(limit)

    return projects


def _fetch_trending_fallback(limit=5):
    """回退方案：爬取 GitHub Trending 页面"""
    url = "https://github.com/trending"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    projects = []

    try:
        res = HTTP_SESSION.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")

        for article in soup.find_all("article", class_="Box-row"):
            if len(projects) >= limit:
                break
            h2 = article.find("h2", class_="h3")
            if not h2:
                continue
            a = h2.find("a")
            repo_name = a.text.strip().replace("\n", "").replace(" ", "")

            p = article.find("p", class_="col-9")
            desc = p.text.strip() if p else "暂无描述"

            lang_span = article.find("span", itemprop="programmingLanguage")
            lang = lang_span.text.strip() if lang_span else "Unknown"

            image_url, readme_excerpt, tree_image_path = get_readme_info(repo_name)
            projects.append({
                "repo": repo_name,
                "desc": desc,
                "lang": lang,
                "image_url": image_url,
                "readme_excerpt": readme_excerpt,
                "tree_image_path": tree_image_path,
            })
    except Exception as e:
        logger.error("  GitHub Trending 爬取也失败: {}", e)

    return projects


# ================================================================
#  PyGithub: 获取项目信息
# ================================================================
def get_readme_info(repo_name):
    """
    获取 README 中的最佳图片（优先架构图）和文本节选。
    若无图片，依次尝试：目录树截图 -> 架构图 -> 代码截图。
    返回 (image_url, text_excerpt, local_image_path)
    """
    try:
        g = _get_github_client()
        repo = g.get_repo(repo_name)

        # 获取 README 内容
        try:
            readme = repo.get_readme()
            text = readme.decoded_content.decode("utf-8", errors="ignore")
        except Exception:
            text = ""

        if not text:
            tree_path = _generate_tree_fallback(repo_name, repo)
            return None, "", tree_path

        # 收集候选图片
        candidates = []
        for match in re.finditer(r'!\[([^\]]*)\]\(([^\)]+)\)', text):
            candidates.append((match.group(2).strip(), match.group(1)))
        for match in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>', text):
            img_url = match.group(1).strip()
            alt_match = re.search(r'alt=["\']([^"\']*)["\']', match.group(0))
            alt_text = alt_match.group(1) if alt_match else ""
            candidates.append((img_url, alt_text))

        text_excerpt = _extract_readme_text(text)

        if not candidates:
            tree_path = _generate_tree_fallback(repo_name, repo)
            return None, text_excerpt, tree_path

        # 评分排序
        scored = []
        default_branch = repo.default_branch or "main"
        for img_url, alt_text in candidates:
            score = _score_readme_image(img_url, alt_text)
            if score >= 0:
                if not img_url.startswith("http"):
                    rel_path = img_url.lstrip('/')
                    img_url = f"https://raw.githubusercontent.com/{repo_name}/{default_branch}/{rel_path}"
                scored.append((img_url, score))

        if not scored:
            tree_path = _generate_tree_fallback(repo_name, repo)
            return None, text_excerpt, tree_path

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0], text_excerpt, None

    except Exception as e:
        logger.debug("  PyGithub 获取 README 失败 {}: {}", repo_name, e)
        return None, "", None


def _extract_readme_text(text):
    """提取 README 纯文本节选"""
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'<[^>]+>', '', text)
    return text[:1500].strip()


def _score_readme_image(img_url, alt_text=""):
    """评分 README 图片，优先选择架构图/流程图"""
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
    if any(ext in lower_url for ext in [".png", ".svg", ".gif"]):
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


__all__ = ["fetch_github_trending", "generate_code_screenshot", "get_repo_code_snippet"]
