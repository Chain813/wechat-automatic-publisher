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
            projects_text += f"- 配图: 无\n"

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
        "   - `### ✨ 核心特性`：以无序列表（`- `）列出该项目的 3-4 个最亮眼的功能或用途，适当加粗关键词。\n"
        "   - `### 🚀 适用场景`：简单介绍这个项目能用来解决什么问题，适合哪些开发者使用（**总计需写 400-600 字**，字数要充实饱满，贴合官方提供的能力图景）。\n"
        "3. **总结互动**：结尾简短互动，呼吁大家点赞或去 GitHub star 对应的项目。\n\n"
        "## 排版规则\n"
        "- 保持段落清晰，善用 emoji 图标增加文章趣味性。\n"
        f"- 文末加上：**关注「{BRAND_NAME}」，每日获取硬核开源情报。**\n\n"
        "## 输出\n"
        "直接输出正文，不要带有任何系统回话或 Markdown 代码块包裹（如 ```markdown）。"
    )

    article = call_deepseek_with_retry(prompt, system_content=f"你是「{BRAND_NAME}」的资深技术布道师，精通各类开源架构与工具库。")
    if not article:
        logger.error("  GitHub 文稿生成失败")
        return ""
        
    return article
