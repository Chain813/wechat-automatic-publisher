"""
============================================================
  AI 科普文章生成器 v1.0
  教育风格：生动图解 + 循序渐进 + 零基础友好
============================================================
"""
from loguru import logger

from config import BRAND_NAME, WECHAT_TITLE_MAX_LEN
from core.shared.llm import call_deepseek_with_retry, validate_article_length

SYSTEM_PROMPT = f"""
# 你是谁

你是「{BRAND_NAME}」的 AI 科普专栏作者，一个在 AI 领域深耕多年的技术布道者。你不是在写学术论文——你是在给一群对 AI 充满好奇、但基础参差不齐的普通读者做「知识翻译」。你的人生信条是：没有难懂的技术，只有蹩脚的解释。

你的读者可能是产品经理、设计师、创业者、学生，或者单纯对 AI 感兴趣的职场人。他们不是来看代码的——他们是来「搞懂」的。

# 你的思维习惯

每当你面对一个 AI 概念时，你的第一反应是：
- "怎么用三句话让完全不懂的人明白这是干什么的？"
- "日常生活里有什么类比可以解释这个？"
- "这个概念在整个 AI 知识图谱里处于什么位置？"

你对「类比」有执念——你相信一个好的类比胜过十段技术描述。你会花大量心思找到一个精准的类比，让读者会心一笑：「原来如此！」

# 你的表达方式

你说话像一位耐心的老师：温暖、清晰、有节奏感。你不会用一堆术语砸晕读者，而是像剥洋葱一样一层层展开。

**你的表达原则**：
- **先给直觉，再给定义**：开头一定是一个能让读者「秒懂」的类比或场景，然后才引入正式概念
- **图解思维**：你会用文字引导读者在脑中形成画面——「想象你面前有一排开关…」
- **从上往下讲**：先讲这个东西解决了什么问题（WHY），再讲怎么解决（HOW），最后才是内部细节（WHAT）
- **难度标识**：在关键难点处主动提示读者「这里稍微有点绕，我们慢一点」

**绝对禁止**：
- 禁止堆砌数学公式。如果必须出现数学符号，用文字解释其直观含义
- 禁止使用「众所周知」「显而易见」「显然」——这些词会让你显得傲慢
- 禁止大段粘贴代码。代码片段只在「动手实践」类文章中才允许，且每段不超过 15 行

# 写作铁律

1. 你绝对不会在每段开头用「首先、其次、然后、最后、总之」这些词。你的过渡应该像水面下的桥墩——看不见，但逻辑在流动。
2. 你不会在文章末尾写「欢迎点赞转发」之类的套话。好内容自己会传播。
3. ## 标题和 > 引用前后必须空行。每段不超过 4 句话。

# 重点标注（帮助读者扫读）

## 红色加粗（全文最核心的 3-5 个「顿悟时刻」）
用 **{{你的核心洞察}}** 格式。花括号会被系统转为红色高亮。
这是读者读完会拍大腿的点，是你整篇文章的价值所在。
- **{{注意力机制的本质，是让模型学会「选择性遗忘」——忽略噪音，聚焦关键}}**
- **{{RAG 不是简单的「搜索+生成」，而是给大模型装了一个会自己翻书的外脑}}**

## 黑色加粗（关键概念、重要术语、转折判断）
每段至少 1-2 处。让扫读的读者快速定位关键信息。
- 这个过程叫做 **反向传播**，它本质上就是「猜错了就倒退检查」
- **Transformer 架构** 彻底改变了 NLP 领域，它只做了一件事

# 文章结构

## 1. 开篇钩子（100-150 字）
从一个读者能感知到的场景切入。比如：「你问 ChatGPT 一个问题，它几乎立刻就能回答。但在那零点几秒里，发生了一件极其精妙的事——」

## 2. 直觉先行（200-300 字）
用一个生活化的类比，让读者在脑中建立直觉。这是你文章最重要的段落——如果类比选对了，后面的内容读者自己就能推导出来。

## 3. 逐步深入（1500-2000 字）
用 ## 标题分成 3-5 个小节，从简单到复杂。每个小节都是一个独立的知识单元。
- 每个小节开头先用一句话概括「这个小节能让你理解什么」
- 标题本身要有解读感，不要用干巴巴的术语（比如「注意力是怎么算的」而不是「注意力机制的计算公式」）
- 在关键的地方插入「配图建议」：文中用【此处插入配图：关键词】标记

## 4. 核心要点回顾（100-150 字）
用 > 引用格式，列出 3 个最重要的要点。读者看完这里应该能向朋友复述这篇文章的核心内容。

## 5. 知识地图导航（50-80 字）
告诉读者这个知识点在整个 AI 技能树中的位置，以及下一步可以学什么。这是你作为「路线规划者」的独特价值。

文末：**关注「{BRAND_NAME}」，系统学习 AI 知识体系。**
"""

# AI科普文章的额外要求：技术图表
DIAGRAM_HINTS = """
在文章中，请在需要图解的关键位置插入图表占位符（而非照片配图）。
格式：【此处绘制图表：图表描述】
至少插入 2 个图表占位符，类型建议：
- 核心架构处 → 【此处绘制图表：Transformer编码器-解码器架构图】
- 算法/数据流 → 【此处绘制图表：RAG检索增强生成的完整流程图】
- 概念对比处 → 【此处绘制图表：RNN与Transformer的对比】
- 层次关系 → 【此处绘制图表：AI技术栈层次图：基础层→模型层→应用层】
- 时间线/演进 → 【此处绘制图表：GPT-1到GPT-4的演进时间线】

注意：
- 图表描述要具体，包含节点名称和关系，便于自动生成
- 全文图表不超过 3 个，只放在「不看图就理解不了」的关键处
- 相比照片配图，技术文章中流程图和架构图更有价值
"""


def generate_aikepu_article(topic_info):
    """
    根据技能树节点信息生成 AI 科普文章。
    
    Args:
        topic_info: dict with keys:
            - title: 文章标题
            - tags: 标签列表
            - difficulty: 难度等级 (1-4)
            - summary: 一句话摘要
            - prerequisites: 先修知识点 id 列表
    
    Returns:
        完整的 markdown 文章字符串，或 None
    """
    title = topic_info.get("title", "")
    tags = topic_info.get("tags", [])
    difficulty = topic_info.get("difficulty", 1)
    summary = topic_info.get("summary", "")
    prerequisites = topic_info.get("prerequisites", [])

    difficulty_labels = {1: "入门", 2: "基础", 3: "进阶", 4: "前沿"}
    diff_label = difficulty_labels.get(difficulty, "基础")
    tags_str = " · ".join(tags)

    user_prompt = f"""# 任务：撰写一篇 AI 科普文章

## 文章主题
标题：{title}
摘要：{summary}
难度：{diff_label}（{'⭐' * difficulty}）
领域标签：{tags_str}

## 难度要求
这篇文章的难度等级是 **{diff_label}**，请根据以下规则调整讲解深度：
- 入门（⭐）：假设读者零基础，大量使用类比，避免任何术语
- 基础（⭐⭐）：读者有一定概念认知，可以引入少量术语但必须解释
- 进阶（⭐⭐⭐）：读者已了解前置知识，可以深入技术细节
- 前沿（⭐⭐⭐⭐）：读者是业内人士，可以讨论最新进展和争议

## 写作要求
1. 文章总字数 1800-3000 字
2. 必须包含 3-5 个配图占位符【此处插入配图：关键词】
3. 必须包含至少 3 个 > 引用段落（要点回顾、金句或注意事项）
4. 必须包含至少 3 个 ## 二级标题
5. 在「知识地图导航」部分，提到读者学习完这篇后可以继续学什么

{DIAGRAM_HINTS}

## 特别说明
这篇文章是「AI 全栈技能树」系列的第 N 篇。请在文末的「知识地图导航」中自然地让读者感知到：他们正在沿着一条系统性的学习路线前进，这不是一篇孤立的知识碎片。

请直接输出完整的 Markdown 格式文章，不要有任何前缀解释。"""

    logger.info("🎓 正在生成 AI科普文章: {}", title)
    article = call_deepseek_with_retry(user_prompt, system_content=SYSTEM_PROMPT)

    if not article:
        logger.error("AI科普文章生成失败: {}", title)
        return None

    # 基本校验
    word_count = len(article.replace(" ", "").replace("\n", ""))
    heading_count = article.count("## ")
    quote_count = article.count("> ")
    diagram_placeholders = article.count("【此处绘制图表：")

    print(f"\n📝 AI科普文章生成报告:")
    print(f"   标题: {title}")
    print(f"   字数: {word_count}")
    print(f"   二级标题: {heading_count} 个")
    print(f"   引用段落: {quote_count} 个")
    print(f"   图表占位符: {diagram_placeholders} 个")

    if word_count < 800:
        logger.warning("⚠️ 文章字数不足 800，但保留输出")

    return article


def generate_digest(topic_title, article_text=None):
    """
    为 AI科普文章生成微信摘要。
    
    Args:
        topic_title: 文章标题
        article_text: 文章全文（可选，用于提取精华）
    
    Returns:
        摘要字符串（≤120 字）
    """
    from config import WECHAT_DIGEST_MAX_LEN

    context = ""
    if article_text:
        # 取文章前 500 字作为上下文
        context = f"\n文章开头：{article_text[:500]}\n"

    prompt = (
        f"为以下 AI 科普文章写一条微信摘要（用于推送通知）。\n"
        f"标题：{topic_title}{context}\n"
        f"要求：\n"
        f"- 字数严格 ≤{WECHAT_DIGEST_MAX_LEN} 字\n"
        f"- 必须包含一个「知识钩子」——告诉读者看完能学到什么\n"
        f"- 风格：像一个乐于分享的朋友，让人想点进去看\n"
        f"- 禁止使用「震惊」「重磅」「必看」等标题党词汇\n"
        f"- 直接输出摘要，不要加前缀"
    )

    system = f"你是「{BRAND_NAME}」的编辑。写一条有知识含量的微信推送摘要。只输出摘要，不要解释。"

    res = call_deepseek_with_retry(prompt, system_content=system)
    if res and len(res) > WECHAT_DIGEST_MAX_LEN:
        res = res[:WECHAT_DIGEST_MAX_LEN]
    return res.strip() if res else ""
