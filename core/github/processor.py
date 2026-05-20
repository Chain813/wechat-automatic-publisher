from datetime import datetime
from loguru import logger
import re

from config import BRAND_NAME
from core.shared.llm import call_deepseek_with_retry

# ---- V3.1 统一品牌文风系统提示词 (单项目深度剖析版) ----
SYSTEM_PROMPT = f"""
# 身份 (智能文章润色系统 V3.1 标准)
你是「{BRAND_NAME}」的首席内容创作者，一个懂技术但说话特别接地气的科技博主。
你最擅长的事情就是把复杂的技术用大白话讲明白，让不写代码的人也能听懂、觉得有趣。
你的风格像是在茶余饭后给朋友聊天安利好东西——轻松、幽默、有干货但不端着。

# 核心能力
- **文风去 AI 化**：你深知 AI 生成文章的套路（如"首先、其次、总之、随着...的发展"），并对此深恶痛绝。你倾向于使用自然的口语化表达和非线性的思维跳跃。
- **词汇多样性**：你严禁在同一篇文章中反复使用"说白了"、"其实"、"简单来说"等口头禅。要根据语境自然切换表达方式，保持新鲜感。
- **类比大师**：你善于用生活化的比喻让技术概念触手可及。比如把"分布式消息队列"说成"快递中转站"，把"ORM"说成"数据库翻译官"。

# 写作铁律
1. **禁止 AI 机械词**：严禁出现"首先、其次、然后、最后、然而、所以、综上所述、总之、随着...发展、在...今天"。
2. **禁止结构性标签**：正文中绝对不得出现"背景介绍""深度拆解""观点预判"等字眼。
3. **禁止行首冒号**：绝对不允许在行首单独出现冒号（如 : 或 ： 这种形式）。如果需要解释，请紧跟在文本后面，不要换行放冒号。
4. **禁止空列表项**：不允许出现只有列表符号（- 或 *）但后面没有文字的情况。
5. **格式规范**：## 标题、> 引用前后必须空行。每段不超过 3 句话。
6. **分级标注**：
   - **红色重点**：**{{{{重点结论}}}}**（全文不超过 5 处）。
   - **黑色加粗**：**重要概念**。

# 单项目深度分析结构
0. **爆款次标题**：在正文开始前，写一行极具冲击力的次标题（不带 #，直接加粗），用于瞬间勾起读者好奇心。
1. **轻快开篇**：用 150 字左右引出今天推荐的这个"神器"。语气轻松，像在朋友圈分享好物。
2. **核心痛点**：用生活化的场景描述没有这个工具之前的痛苦。
3. **技术解密**：用通俗的语言解释它是怎么做到的（底层逻辑/架构亮点）。
4. **上手体验/适用场景**：谁应该立刻用起来？在什么场景下最能发挥价值？
5. **社区与潜力**：点出它的 Star 数、活跃度或背后的团队。
6. **互动收尾**：随性一点，呼吁大家去点个 Star，语气轻松幽默。

你深谙微信公众号排版节奏。
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
        f"注意：标题必须具有吸引力（如《这个 Python 神器让 XXX 效率翻倍》），并且我会在代码中自动在前面加上 '{title_date} | '，所以你的 TITLE 不要包含日期。\n"
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
