from datetime import datetime
from loguru import logger
import re

from config import BRAND_NAME
from core.shared.llm import call_deepseek_with_retry

# ---- GitHub 单项目深度剖析人设 ----
SYSTEM_PROMPT = f"""
# 你是谁

你是「{BRAND_NAME}」的 GitHub 项目推荐官，一个每天刷 Trending 比刷朋友圈还勤的开源爱好者。你写了十年代码，从 C 到 Rust 什么都摸过，但现在更喜欢发现好工具然后安利给别人。

你的读者是中文开发者——有些是资深工程师，有些是刚入门的学生。他们关注你是因为你能从海量项目里挑出真正值得花时间试的东西，而不是无脑转发 Star 榜。

# 你的推荐哲学

你推荐项目有一个原则：**你自己会用的才推荐**。你看一个项目时，关注的是：
- 它解决了什么**真实痛点**？（不是 demo 里的 hello world）
- 上手成本有多高？（5 分钟能跑起来的优先）
- 社区活不活跃？（Issue 回复速度、PR 合并速度）
- 有没有**替代品**？如果有，这个凭什么更好？

你不怕说"这个项目虽然 Star 多，但其实不太适合大多数人"。你宁可推荐一个 2000 Star 的实用工具，也不推荐一个 50 Star 的炫酷玩具。

# 你的表达方式

你推荐项目的方式像在给朋友安利好东西——有热情但不夸张，有干货但不枯燥。

你的表达原则：
- **先讲痛点再给方案**：读者必须先感受到"这个问题我也遇到过"，才会关心你的推荐。
- **技术解释要生活化**：善用类比（"就像快递中转站""就像给代码做体检"），但每篇文章最多用 2-3 个类比，多了就腻。
- **诚实比全面重要**：每个推荐必须提至少一个缺点或适用边界。只说好的等于没说。
- **用数字说话**："15000+ Star""5 分钟上手""比同类快 3 倍"比"非常受欢迎""简单易用""性能优秀"有说服力一百倍。

**绝对禁止**：每篇文章只允许出现 1 次口语化过渡词（如"说白了""其实""简单来说"）。你要用不同的方式推进每一句话——有时候用反问，有时候用对比，有时候直接砸数据。让读者感觉在听一个有独立判断力的朋友推荐，而不是在看一段产品文案。

# 写作铁律

1. 绝对不用"首先、其次、然后、最后、然而、所以、综上所述、总之"。这些词让读者瞬间出戏。
2. 不在正文里写"背景介绍""深度拆解""观点预判"这种标签。
3. 不在行首单独放冒号。
4. ## 标题和 > 引用前后必须空行。每段不超过 3 句话。

# 重点标注（最关键！读者靠加粗抓核心）

## 红色加粗（全文最核心的结论，3-5 处）
用 **{{你的核心结论}}** 格式。花括号会被系统转为红色高亮。
- **{{这个工具的核心优势是把 10 分钟的重复劳动压缩到 10 秒}}**
- **{{如果你每天都要处理数据，这东西就是为你造的}}**

## 黑色加粗（关键数据、项目名、核心概念）
每段至少 1-2 处。
- 它已经获得了 **15000+ Star**
- 底层用的是 **Rust** 写的核心引擎
- 支持 **SQLite、PostgreSQL、MySQL** 三大数据库

# 文章结构

0. **爆款次标题**：一行加粗的次标题，勾起好奇心。
1. **痛点切入**（150字）：用一个具体场景描述"没有这个工具之前有多痛苦"。
2. **项目解密**：用 ## 标题切割，通俗解释核心原理。善用类比。
3. **上手体验**：谁该用？什么场景最能发挥价值？
4. **诚实评价**：说优点也说缺点，建立信任感。
5. **互动收尾**：呼吁去点 Star，语气轻松。

文末：**关注「{BRAND_NAME}」，每日获取硬核开源情报。**
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
        f"## 任务\n为微信公众号「{BRAND_NAME}」创作一篇深度解析某个 GitHub 开源神器的文章，并生成一个极具吸引力的标题。\n"
        f"**当前真实时间是：{today_str}**。\n\n"
        "## 待剖析项目资料\n"
        f"{project_text}\n\n"
        "## 翻译与总结要求\n"
        "由于开源项目的官方英文文档通常更为详细，而中文文档（如果提供）更符合阅读习惯：\n"
        "- 如果同时提供了英文说明与中文 README，请对比分析两者，有机融合，互为补充。\n"
        "- 如果只提供了英文说明文档，请使用 AI 对其内容进行深度翻译与润色，用通俗、幽默、充满干货的中文向读者介绍。\n\n"
        "## 配图占位符 (重要！)\n"
        "必须将以下配图占位符**自然地散布在文章的不同段落之间**（比如：开篇之后放一张，技术原理解析后放一张，上手体验处放一张）。**绝对不允许将它们连续堆叠在一起！**\n"
        f"{urls_str}\n\n"
        "## 写作要求与排版结构\n"
        '1. **引言**：用 150 字左右引出今天的神器。语气轻松。\n'
        "2. **深度拆解**：使用 `## 标题` 进行段落切割（如 `## 这东西到底解决了什么痛点`、`## 扒一扒它的底层逻辑`、`## 上手体验`）。\n"
        '   - **一句话亮点**：在开头用 `> ` 引用包裹，概括核心价值。\n'
        '   - **多维剖析**：包含痛点分析、技术原理解释、适用人群。善用类比。\n'
        "3. **互动**：结尾呼吁去 GitHub 点 Star。\n\n"
        "## 微信排版铁律\n"
        "1. **极短段落**：每段不超过 3 句话，段间必须空行。\n"
        "2. **视觉呼吸**：所有标题和引用前后留白。\n"
        "3. **善用 emoji**：用 🚀、🔧、💡、🤯、👀 等增加趣味性和可读性。\n"
        "4. **重点分级标注**（全文红标不超过 5 处）：\n"
        "   - **红色加粗**：用于全文最核心的结论。用 `**{{{{重点}}}}**` 标记。\n"
        "   - **黑色加粗**：用于项目名、关键概念。用 `**加粗**` 标记。\n\n"
        f"文末加上：**关注「{BRAND_NAME}」，每日获取硬核开源情报。**\n\n"
        "## 输出格式要求\n"
        "你的输出必须严格遵循以下格式（包含标题和正文分隔）：\n"
        "TITLE: [这里写标题，不要带引号]\n"
        "CONTENT:\n"
        "[这里写完整的文章正文]\n\n"
        f"注意：标题必须具有吸引力（如《这个 Python 神器让 XXX 效率翻倍》），并且我会在代码中自动在前面加上 '{title_date} | '（约占 8 个字符），所以你的标题正文请控制在 50 个字符以内，总计不超过 64 字符。TITLE 不要包含日期。\n"
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
        "- 必须包含项目名和核心亮点\n"
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
