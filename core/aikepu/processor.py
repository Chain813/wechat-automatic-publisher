"""
============================================================
  AI 科普文章生成器 v2.0 (Map-Reduce 架构)
  教育风格：生动图解 + 循序渐进 + 零基础友好
============================================================
"""
import json
import re
from loguru import logger

from config import BRAND_NAME
from core.shared.llm import call_deepseek_with_retry

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
"""

# AI科普文章的额外要求：技术图表
DIAGRAM_HINTS = """
在文章中，请在需要图解的关键位置插入图表占位符（而非照片配图）。
格式：【此处绘制图表：图表描述】

注意：
- 图表描述要具体，包含节点名称和关系，便于自动生成 (比如: 【此处绘制图表：Transformer编码器-解码器架构图】)
- 相比照片配图，技术文章中流程图和架构图更有价值
"""


def extract_json_block(text):
    match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
    if match:
        return match.group(1)
    return text


def generate_aikepu_article(topic_info):
    """
    采用 Map-Reduce 架构生成 20000 字长文
    """
    title = topic_info.get("title", "")
    tags = topic_info.get("tags", [])
    difficulty = topic_info.get("difficulty", 1)
    summary = topic_info.get("summary", "")

    difficulty_labels = {1: "入门", 2: "基础", 3: "进阶", 4: "前沿"}
    diff_label = difficulty_labels.get(difficulty, "基础")
    tags_str = " · ".join(tags)

    logger.info("🎓 [阶段1] 正在生成大纲: {}", title)
    
    outline_prompt = f"""# 任务：为 AI 科普文章生成分段大纲

## 文章主题
标题：{title}
摘要：{summary}
难度：{diff_label}
标签：{tags_str}

## 要求
我们需要生成一篇总字数约 20000 字的极长科普迷你电子书。请为这篇文章设计一个包含 8 个小节的详细大纲。
必须包含开篇场景、直觉类比、逐步深入的原理、代码实战(如适用)、局限与前沿等。

每个小节应该包含：
1. `title`: 小节的二级标题 (不带##)
2. `description`: 该小节要讲的核心内容、要使用的类比、要包含的图表描述、是否包含代码等（详细指导写作的 prompt）。

必须严格返回以下 JSON 格式：
```json
[
  {{"title": "小节标题1", "description": "指导该小节生成的详细描述..."}},
  {{"title": "小节标题2", "description": "指导该小节生成的详细描述..."}}
]
```
不要有任何其他前缀解释。"""
    
    outline_res = call_deepseek_with_retry(outline_prompt, system_content="你是一个专业的技术大纲规划师。严格输出 JSON 数组格式，不要废话。")
    if not outline_res:
        logger.error("大纲生成失败")
        return None
        
    try:
        outline_json = extract_json_block(outline_res)
        sections = json.loads(outline_json)
    except Exception as e:
        logger.error("大纲 JSON 解析失败: {}", e)
        logger.error("原始响应: {}", outline_res[:200])
        return None
        
    if not isinstance(sections, list) or len(sections) == 0:
        logger.error("大纲格式错误，非有效列表")
        return None
        
    logger.info("✅ 大纲生成完毕，共 {} 节", len(sections))
    
    full_article = []
    
    for i, sec in enumerate(sections):
        sec_title = sec.get("title", f"第 {i+1} 节")
        sec_desc = sec.get("description", "")
        
        logger.info("🎓 [阶段2] 正在生成第 {}/{} 节: {}", i+1, len(sections), sec_title)
        
        outline_context = "\n".join([f"{j+1}. {s.get('title')}" for j, s in enumerate(sections)])
        
        section_prompt = f"""# 任务：撰写 AI 科普文章的其中一节

## 全文背景
全文标题：{title}
全文难度：{diff_label}
全文大纲索引：
{outline_context}

## 当前章节任务 (第 {i+1} 节 / 共 {len(sections)} 节)
你需要撰写的是：**{sec_title}**
本节核心指引：
{sec_desc}

## 写作要求（严格遵守！）
1. **本节字数要求 2000 - 2500 字。** 必须极其详实、生动、层层递进。
2. 必须以 `## {sec_title}` 作为本节的开头。
3. 如果本节适合图解，请包含 1 个图表占位符。{DIAGRAM_HINTS}
4. 必须包含至少 2 个 `> ` 引用段落（金句、要点、注意事项）。
5. 难度匹配 {diff_label}。如果是入门，大量使用类比；如果是进阶，深入细节。
6. (如果描述中要求写代码) 给出带详细注释的 Python 代码，单段控制在 25 行内。
7. 不要写任何“欢迎点赞关注”的废话，只输出纯 Markdown 正文。
"""
        sec_content = call_deepseek_with_retry(section_prompt, system_content=SYSTEM_PROMPT, timeout=180)
        if not sec_content:
            logger.warning("第 {} 节生成失败，将导致文章不完整", i+1)
            continue
            
        full_article.append(sec_content.strip())
        
    if not full_article:
        return None
        
    final_article = "\n\n".join(full_article)
    
    # 追加知识地图和关注尾缀
    final_article += f"\n\n## 知识地图导航\n\n学习完这篇内容，你在 AI 技能树上又点亮了一个重要节点。你可以继续探索与此相关的前置或后置知识，构建完整的知识体系。\n\n**关注「{BRAND_NAME}」，系统学习 AI 知识体系。**"
    
    # 统计
    word_count = len(final_article.replace(" ", "").replace("\n", ""))
    heading_count = final_article.count("## ")
    quote_count = final_article.count("> ")
    diagram_placeholders = final_article.count("【此处绘制图表：")

    print(f"\n📝 AI科普长文生成报告:")
    print(f"   标题: {title}")
    print(f"   字数: {word_count}")
    print(f"   二级标题: {heading_count} 个")
    print(f"   引用段落: {quote_count} 个")
    print(f"   图表占位符: {diagram_placeholders} 个")
    
    if word_count < 10000:
        logger.warning("⚠️ 文章字数严重不足 (当前 {})，远低于预期要求", word_count)
        
    return final_article


def generate_digest(topic_title, article_text=None):
    from config import WECHAT_DIGEST_MAX_LEN

    context = ""
    if article_text:
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
