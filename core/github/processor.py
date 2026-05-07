from datetime import datetime
from loguru import logger

from config import BRAND_NAME
from core.shared.llm import call_deepseek_with_retry

def generate_github_article(projects):
    logger.info("DeepSeek 正在创作 GitHub 开源项目推荐长文...")
    
    projects_text = ""
    for idx, p in enumerate(projects, 1):
        projects_text += f"\n【项目{idx}】\n"
        projects_text += f"- 仓库名: {p['repo']}\n"
        projects_text += f"- 主要语言: {p['lang']}\n"
        projects_text += f"- 官方描述: {p['desc']}\n"
        if p.get('readme_excerpt'):
            projects_text += f"- README 详情节选: {p['readme_excerpt']}\n"
        if p.get('image_url'):
            projects_text += f"- 配图链接 (必须在介绍末尾原样输出此占位符): 【GITHUB配图：{p['image_url']}】\n"
        else:
            fallback_keyword = f"{p['repo'].split('/')[-1]} {p['lang']} project architecture"
            projects_text += f"- 配图: 无，请在介绍末尾插入配图占位符：【此处插入配图：{fallback_keyword}】\n"

    today_str = datetime.now().strftime("%Y年%m月%d日")
    
    prompt = (
        f"## 任务\n为微信公众号「{BRAND_NAME}」创作一篇名为《今日 GitHub 最火开源项目盘点》的文章。\n"
        f"**当前真实时间是：{today_str}**。\n\n"
        "## 待介绍项目列表\n"
        f"{projects_text}\n\n"
        "## 核心原则\n"
        "- **面向开发者与技术极客**：语言要极客、专业，同时富有感染力。\n"
        "- **直接干脆**：只需要介绍项目的用途和核心功能，不要过多的废话和无意义的过渡句。\n"
        "- **忠于原生信息**：请参考上面提供的“README 详情节选”，确保你的介绍贴合项目真实的 README 内容，特别是功能演示和架构图所代表的核心逻辑，不要凭空瞎编。\n\n"
        "## 写作要求与排版结构\n"
        "1. **引言**（100字左右）：简单引出今天的开源盘点，点燃读者的极客之魂。\n"
        "2. **项目逐一介绍**：每个项目使用 `## 项目名 (主语言)` 作为大标题。在每个大标题下，需包含以下结构：\n"
        "   - **一句话亮点**：用 `> ` 引用包裹，用一句话概括项目定位和核心卖点。\n"
        "   - **如果你提供了配图链接占位符，必须在这里原样输出该占位符！**\n"
        "   - 核心功能：以无序列表（`- `）列出该项目的 3-4 个最亮眼的功能或用途，适当加粗关键词。此段落前用一个 `## ` 标题概括（如 `## 这个项目能做什么`）。\n"
        "   - 适用场景：用 2-3 个自然段介绍项目能解决什么问题，适合哪些开发者（**总计 400-600 字**）。此段落前用一个 `## ` 标题概括（如 `## 谁会用到它`）。\n"
        "3. **总结互动**：结尾简短互动，呼吁大家点赞或去 GitHub star 对应的项目。\n\n"
        "## 微信排版铁律 (与公众号推文风格统一)\n"
        "1. **极短段落**：每段 2-3 句话（40-60 字），段间空行。\n"
        "2. **视觉呼吸**：## 标题、> 引用、【配图】前后必须有空行。\n"
        "3. **善用 emoji**：在标题和关键位置使用 emoji 图标增加趣味性和视觉层次（如 🚀📦🔧💡🎯 等）。\n"
        "4. **重点分级标注**（全文红色标注不超过 5 处）：\n"
        "   - **红色加粗**：仅用于全文最核心的结论。用 `**{重点}**` 标记（花括号包裹）。\n"
        "   - **黑色加粗**：用于重要论点、关键概念、项目名。用 `**加粗**` 标记（无花括号）。\n"
        "5. **节奏切割**：每 3-4 段用一个 ## 小标题切割，保持阅读节奏。\n"
        '5. **严禁结构性标签**：正文中不得出现"核心特性""适用场景""项目亮点"等结构性标签文字。标题应该是具体、有信息量的概括性语句。\n\n'
        f"文末加上：**关注「{BRAND_NAME}」，每日获取硬核开源情报。**\n\n"
        "## 输出\n"
        "直接输出正文，不要带有任何系统回话或 Markdown 代码块包裹（如 ```markdown）。"
    )

    article = call_deepseek_with_retry(prompt, system_content=f"你是「{BRAND_NAME}」的资深技术布道师，精通各类开源架构与工具库。你的文章面向微信公众号读者，需要遵循公众号排版规范：极短段落、视觉呼吸、重点分级标注。严禁输出结构性标签文字。")
    if not article:
        logger.error("  GitHub 文稿生成失败")
        return ""
        
    return article
