from datetime import datetime
from loguru import logger
import re

from config import ARTICLE_SIGNATURE, BRAND_NAME
from core.shared.llm import call_deepseek_with_retry

# ---- GitHub 单项目深度剖析人设 ----
SYSTEM_PROMPT = f"""
你为「{BRAND_NAME}」的中文开发者解读开源项目。依据所给仓库信息与 README 节选写作。
先说读者手里有什么输入、工具做了什么、输出是什么。能找到文档示例时，挑一个最短可说明用途的例子。
依赖、安装命令、支持平台和限制都以材料为准。节选没写时允许留白。
区分作者自报与独立测量。有性能数据才写对比，并保留基线、硬件与任务条件。
不要虚构自己的使用经历、安装成功、社区响应速度或节省的时间。Star 数只作为仓库元数据。
小标题点明具体功能或适用条件。每段不超过三句话，标题和引用前后留空行。
全文 3–5 处重点用 **{{{{核心结论}}}}**，普通黑色加粗用 **项目名或关键术语**。
落款为 {ARTICLE_SIGNATURE}
"""


def generate_github_article(projects):
    """
    接收一个项目列表（目前限制为 1 个），生成深度分析文章和动态标题。
    返回: (article_text, dynamic_title)
    """
    logger.info("DeepSeek 正在创作 GitHub 单项目深度解析长文...")
    
    if not projects:
        return "", ""
        
    # 取第一个（也是唯一一个）项目
    p = projects[0]
    
    project_text = f"【项目名】: {p['repo']}\n"
    project_text += f"【主要语言】: {p['lang']}\n"
    project_text += f"【Stars】: {p.get('stars', 'N/A')}\n"
    project_text += f"【官方描述】: {p['desc']}\n"
    if p.get('readme_excerpt'):
        project_text += f"【英文 README / 其他说明文档节选】: {p['readme_excerpt'][:1500]}\n"
    if p.get('chinese_readme_excerpt'):
        project_text += f"【中文 README 节选】: {p['chinese_readme_excerpt'][:1500]}\n"
        
    urls_str = ""
    if p.get('image_urls'):
        urls_str = " \n".join([f"【GITHUB配图：{url}】" for url in p['image_urls']])
    elif p.get('image_url'):
        urls_str = f"【GITHUB配图：{p['image_url']}】"
    else:
        fallback_keyword = f"{p['repo'].split('/')[-1]} {p['lang']} project architecture"
        urls_str = f"【此处插入配图：{fallback_keyword}】"

    today_str = datetime.now().strftime("%Y年%m月%d日")
    title_date = datetime.now().strftime("%m月%d日")
    
    prompt = (
        f"## 任务\n为微信公众号「{BRAND_NAME}」创作一篇深度解析某个 GitHub 开源项目的文章，并用项目名和具体用途拟标题。\n"
        f"**当前真实时间是：{today_str}**。\n"
        f"**真实性原则**：不允许胡编乱造，涉及的数据、事实、引用和代码功能必须保证真实性，杜绝幻觉和虚假信息。\n\n"
        "## 待剖析项目资料\n"
        f"{project_text}\n\n"
        "## 翻译与总结要求\n"
        "由于开源项目的官方英文文档通常更为详细，而中文文档（如果提供）更符合阅读习惯：\n"
        "- 如果同时提供了英文说明与中文 README，请对比分析两者，有机融合，互为补充。\n"
        "- 如果只提供了英文说明文档，请使用 AI 对其内容进行深度翻译与润色，用中文准确讲解其中可核对的功能和条件。\n\n"
        "## 配图占位符 (重要！)\n"
        "必须将以下配图占位符**自然地散布在文章的不同段落之间**（比如：开篇之后放一张，技术原理解析后放一张，上手体验处放一张）。**绝对不允许将它们连续堆叠在一起！**\n"
        f"{urls_str}\n\n"
        "## 写作要求与排版结构\n"
        '1. **引言**：从文档支持的具体任务引出项目，交代使用者和操作对象。\n'
        "2. **深度拆解**：使用 `## 标题` 进行段落切割，标题写出本节所解释的一个具体操作、机制或适用条件。\n"
        '   - **一句话亮点**：在开头用 `> ` 引用包裹，概括核心价值。\n'
        '   - **多维剖析**：根据材料交代用途、工作方式与适用人群。文档缺少评测时不要估计性能，只有描述时不要补写实现与运行结果。\n'
        "3. **互动**：结尾呼吁去 GitHub 点 Star。\n\n"
        "## 微信排版铁律\n"
        "1. **极短段落**：每段不超过 3 句话，段间必须空行。\n"
        "2. **视觉呼吸**：所有标题和引用前后留白。\n"
        "3. **善用 emoji**：用 🚀、🔧、💡、🤯、👀 等增加趣味性和可读性。\n"
        "4. **重点分级标注**（全文红标不超过 5 处）：\n"
        "   - **红色加粗**：用于全文最核心的结论。用 `**{{重点}}**` 标记。\n"
        "   - **黑色加粗**：用于项目名、关键概念。用 `**加粗**` 标记。\n\n"
        f"文末加上：{ARTICLE_SIGNATURE}\n\n"
        "## 输出格式要求\n"
        "你的输出必须严格遵循以下格式（包含标题和正文分隔）：\n"
        "TITLE: [这里写标题，不要带引号]\n"
        "CONTENT:\n"
        "[这里写完整的文章正文]\n\n"
        f"注意：标题写出项目实际能做的事，不添加无依据的效率承诺，并且我会在代码中自动在前面加上 '{title_date} | '（约占 8 个字符），所以你的标题正文请控制在 50 个字符以内，总计不超过 64 字符。TITLE 不要包含日期。\n"
    )

    result = call_deepseek_with_retry(prompt, system_content=SYSTEM_PROMPT, timeout=180)
    if not result:
        logger.error("  GitHub 文稿生成失败")
        return "", ""
        
    title = ""
    content = ""
    
    # 解析 TITLE 和 CONTENT
    match = re.search(r'TITLE:\s*(.*?)\s*\nCONTENT:\s*(.*)', result, re.DOTALL | re.IGNORECASE)
    if match:
        title = match.group(1).strip()
        content = match.group(2).strip()
    else:
        # Fallback 解析
        lines = result.split('\n')
        if lines and lines[0].startswith('TITLE:'):
            title = lines[0].replace('TITLE:', '').strip()
            content = '\n'.join(lines[1:]).strip()
        else:
            title = f"{p['repo'].split('/')[-1]} 深度解析"
            content = result.strip()
            
    # 用户要求：标题必须包括日期
    final_title = f"{title_date} | {title}"

    return content, final_title


def generate_github_digest(repo_name, repo_desc):
    """为 GitHub 推文生成动态摘要（替代硬编码），提升推送点击率"""
    prompt = (
        f"项目名：{repo_name}\n"
        f"项目描述：{repo_desc}\n\n"
        "为这个 GitHub 开源项目写一条微信公众号推送摘要（用于通知栏预览）。\n"
        "要求：\n"
        "- 严格不超过 100 字\n"
        "- 包含项目名和描述中能确认的功能；描述未说明的用途或效果不要补写\n"
        "- 像一个开发者朋友在群里分享好东西的语气\n"
        "- 禁止使用'震惊''重磅''速看'等标题党词汇\n"
        "- 直接输出摘要，不要加任何前缀"
    )
    try:
        from core.shared.llm import call_deepseek_with_retry
        res = call_deepseek_with_retry(
            prompt,
            system_content="你是开源项目推荐编辑。只输出摘要文本，不要解释。",
            max_retries=1,
            backoff_base=0.3,
        )
        if res and len(res.strip()) > 10:
            return res.strip()[:100]
    except Exception:
        pass
    # 兜底：用项目信息拼接
    return f"GitHub 热门项目 {repo_name}：{repo_desc[:50]}" if repo_desc else f"GitHub 热门项目 {repo_name} 深度解析"
