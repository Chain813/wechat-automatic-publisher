"""
============================================================
  AI 科普文章生成器 v3.0 (三阶段 Map-Reduce 架构)
  阶段1: 大纲生成
  阶段2: LLM 提示词自优化 (跨节一致性保障)
  阶段3: 串行生成 + 上文衔接
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

0. **真实性铁律**：绝对不允许胡编乱造。所有提及的算法公式、学术概念、技术历史、测试数据必须保证真实、客观、准确，杜绝 AI 幻觉和虚假内容。
1. 你绝对不会在每段开头用「首先、其次、然后、最后、总之」这些词。你的过渡应该像水面下的桥墩——看不见，但逻辑在流动。
2. 你不会在文章末尾写「欢迎点赞转发」之类的套话。好内容自己会传播。
3. ## 标题和 > 引用前后必须空行。每段不超过 4 句话。
4. **配图与图表铁律**：绝对禁止使用 `【此处插入配图：...】` 这种写实照片或 AI 绘画的占位符。本专栏文章必须主要以结构化图表为主，如果需要展示视觉信息或公式，必须且只能使用 `【此处绘制图表：描述】` 占位符。

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

# AI科普文章的额外要求：技术图表与公式/对比卡片
DIAGRAM_HINTS = """
在文章中，请在需要图解或展示数学公式的关键位置插入图表占位符（而非照片配图）。
格式：【此处绘制图表：描述】

注意：
- 图表描述要尽可能详实、具体。可以是：
  1. 流程图/脑图 (例如: 【此处绘制图表：Transformer 自注意力机制的数据流动与节点关系流程图】)
  2. 数学公式推导卡片 (例如: 【此处绘制图表：反向传播中梯度下降核心更新公式及参数说明卡片】)
  3. 概念对比总结卡片 (例如: 【此处绘制图表：深度学习与传统机器学习核心特征及适用场景对比卡片】)
- 这类结构化图文卡片相比普通照片更具科普价值。每节最多包含 1 个图表占位符。
"""


def _extract_json_block(text):
    """从 LLM 响应中提取 JSON 代码块"""
    match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
    if match:
        return match.group(1)
    return text


# ==========================================
#  阶段 1: 大纲生成
# ==========================================
def _generate_outline(title, summary, diff_label, tags_str):
    """
    阶段1: 生成结构化大纲。
    输出 JSON 数组，每节包含 title、description、complexity。
    """
    outline_prompt = f"""# 任务：为 AI 科普长文设计分节大纲

## 文章主题
标题：{title}
摘要：{summary}
难度：{diff_label}
标签：{tags_str}

## 要求
请为这篇文章设计一个包含 **6-8 个小节**的详细大纲。
全文总字数目标：≥ 15000 字（迷你电子书级别的深度科普）。

大纲必须满足：
- 第1节必须是「开篇场景/直觉引入」——用日常类比让零基础读者秒懂这个主题是干什么的
- 中间节层层递进深入原理，难度梯度上升
- 必须包含至少 1 节「动手实践/代码示例」(如适用)
- 必须包含 1 节「局限性与前沿展望」
- 最后 1 节是「全景总结 + 知识图谱定位」
- 全文至少 4 个小节需要配备结构化技术图表（流程图、公式卡片或概念对比卡片），请在 description 中注明该节推荐的图表类型和图表主题

每个小节需包含：
1. `title`: 小节的二级标题 (不带##)
2. `description`: 该小节要讲的核心内容、要使用的类比、是否需要代码、以及推荐的图表类型和图表主题（如"推荐流程图：展示 Transformer 数据流经各层的过程"）
3. `complexity`: 该小节的内容复杂度 (1-5 分)。复杂度高的节应分配更多字数

严格返回以下 JSON 格式，不要有任何其他前缀解释：
```json
[
  {{"title": "小节标题1", "description": "详细描述...", "complexity": 3}},
  {{"title": "小节标题2", "description": "详细描述...", "complexity": 4}}
]
```"""

    outline_res = call_deepseek_with_retry(
        outline_prompt,
        system_content="你是一个专业的技术大纲规划师。严格输出 JSON 数组格式，不要废话。",
    )
    if not outline_res:
        logger.error("阶段1: 大纲生成失败")
        return None

    try:
        outline_json = _extract_json_block(outline_res)
        sections = json.loads(outline_json)
    except Exception as e:
        logger.error("阶段1: 大纲 JSON 解析失败: {}", e)
        logger.debug("原始响应: {}", outline_res[:300])
        return None

    if not isinstance(sections, list) or len(sections) == 0:
        logger.error("阶段1: 大纲格式错误，非有效列表")
        return None

    logger.info("✅ 阶段1完毕: 大纲共 {} 节", len(sections))
    for i, sec in enumerate(sections):
        complexity = sec.get("complexity", 3)
        logger.info("   {}. [复杂度{}] {}", i + 1, complexity, sec.get("title", "?"))
    return sections


# ==========================================
#  阶段 2: LLM 提示词自优化
# ==========================================
def _optimize_section_prompts(title, diff_label, sections):
    """
    阶段2: LLM 自优化提示词。
    将完整大纲交给 LLM 编辑总监，为每节生成高度定制化的写作指令，
    确保跨节一致性、类比不重复、衔接自然。
    """
    sections_overview = json.dumps(sections, ensure_ascii=False, indent=2)

    # 计算推荐字数分配
    total_complexity = sum(sec.get("complexity", 3) for sec in sections)
    min_total = 15000
    word_allocations = []
    for sec in sections:
        c = sec.get("complexity", 3)
        suggested = max(1800, int(min_total * c / total_complexity))
        word_allocations.append(suggested)

    allocation_hint = "\n".join(
        f"  第{i+1}节「{sec.get('title', '?')}」: 复杂度{sec.get('complexity', 3)} → 建议 ≥{wc} 字"
        for i, (sec, wc) in enumerate(zip(sections, word_allocations))
    )

    optimize_prompt = f"""# 任务：为 AI 科普长文的每一节生成高度定制化的写作指令

你是一位资深的科普编辑总监。下面是一篇关于「{title}」（难度：{diff_label}）的 AI 科普长文大纲。

## 完整大纲
{sections_overview}

## 字数分配参考（按复杂度加权，总计 ≥ {min_total} 字）
{allocation_hint}

## 你的任务
请为每一节生成一份**极其详细的写作指令**（`optimized_prompt`），使得 6-8 位不同的"写手"拿到各自的指令后，写出来的文章读起来像一个人一气呵成的。

### 你必须为每一节指定：

1. **`optimized_prompt`**（≥120字的详细写作指令）：
   - 本节的核心论点、展开逻辑和叙事节奏
   - 必须使用的一个**独占核心类比**（不得与其他节重复，如第2节用"厨房"比喻，其他节就不能再用）
   - 如果不是第1节：开头必须如何**承接上一节的结尾**
   - 结尾必须留一个**悬念钩子**（引导读者继续看下一节）
   - 该节推荐的**结构化图表类型**（流程图/公式卡片/对比卡片/无），使用 `【此处绘制图表：描述】` 格式
   - **绝对禁止**在写作指令中建议使用 `【此处插入配图：...】` 等普通照片或 AI 生图占位符。本专栏只使用结构化技术图表

2. **`forbidden_overlaps`**：本节**绝对不能出现**的内容清单（防止与其他节重复）

3. **`min_words`**：该节的最低字数要求

## 输出格式
严格输出 JSON 数组，不要有任何多余解释：
```json
[
  {{
    "title": "原大纲小节标题",
    "optimized_prompt": "极其详细的写作指令...",
    "forbidden_overlaps": "不能出现XXX、不能重复讨论YYY...",
    "min_words": 2500
  }}
]
```"""

    # 强制将自优化重载为轻量级 flash 模型（例如将 deepseek-v4-pro 降级为 deepseek-v4-flash）以加快生成速度并防止超时
    from config import LLM_MODEL
    optimize_model = LLM_MODEL.replace("-pro", "-flash").replace("pro", "flash")
    logger.info("🧠 [阶段2] 提示词自优化中 (编辑总监审稿，使用轻量级模型 {})...", optimize_model)

    result = call_deepseek_with_retry(
        optimize_prompt,
        system_content="你是一位顶级科普编辑总监，负责确保多节长文的跨章节一致性。严格输出 JSON 数组。",
        timeout=90,
        max_tokens=8192,
        model=optimize_model
    )

    if not result:
        logger.warning("阶段2: 提示词自优化失败，将回退使用原始大纲")
        return None

    try:
        optimized_json = _extract_json_block(result)
        optimized = json.loads(optimized_json)
    except Exception as e:
        logger.warning("阶段2: 优化结果 JSON 解析失败: {}，将回退使用原始大纲", e)
        logger.debug("原始响应: {}", result[:300])
        return None

    if not isinstance(optimized, list) or len(optimized) == 0:
        logger.warning("阶段2: 优化结果格式错误，将回退使用原始大纲")
        return None

    logger.info("✅ 阶段2完毕: 已生成 {} 节定制化写作指令", len(optimized))
    for i, opt in enumerate(optimized):
        min_w = opt.get("min_words", "?")
        logger.info("   {}. {} (最低{}字)", i + 1, opt.get("title", "?"), min_w)
    return optimized


# ==========================================
#  阶段 2 回退: 大纲降级为基础写作指令
# ==========================================
def _fallback_to_basic_prompts(sections):
    """当阶段2失败时，将原始大纲转换为基础格式的写作指令"""
    fallback = []
    for sec in sections:
        fallback.append({
            "title": sec.get("title", ""),
            "optimized_prompt": sec.get("description", ""),
            "forbidden_overlaps": "",
            "min_words": 2000,
        })
    return fallback


# ==========================================
#  阶段 3: 串行生成 + 上文衔接
# ==========================================
def _generate_section(title, diff_label, opt_section, prev_tail, section_index, total_sections):
    """
    阶段3: 生成单节内容。
    注入上一节尾部文本和编辑总监的定制化写作指令。
    """
    sec_title = opt_section.get("title", f"第 {section_index + 1} 节")
    optimized_prompt = opt_section.get("optimized_prompt", "")
    forbidden = opt_section.get("forbidden_overlaps", "")
    min_words = opt_section.get("min_words", 2000)

    # 构建上文衔接片段
    context_block = ""
    if prev_tail and section_index > 0:
        context_block = f"""
## 上一节尾段（请自然衔接，不要重复上一节的内容）
---
{prev_tail}
---
"""

    # 构建禁止重复片段
    forbidden_block = ""
    if forbidden:
        forbidden_block = f"""
## 本节禁止出现的内容（防止与其他章节重复）
{forbidden}
"""

    section_prompt = f"""# 任务：撰写 AI 科普长文的第 {section_index + 1} 节（共 {total_sections} 节）

## 全文信息
全文标题：{title}
全文难度：{diff_label}
{context_block}
## 当前章节
你需要撰写的是：**{sec_title}**

## 编辑总监的定制化写作指令
{optimized_prompt}
{forbidden_block}
## 格式要求（严格遵守！）
0. **真实性要求**：必须保证数据、技术公式和概念的真实性，绝对不允许胡编乱造和无事实依据的臆测。
1. **本节字数要求 ≥ {min_words} 字。** 必须极其详实、生动、层层递进。内容复杂的部分要不惜篇幅讲透。
2. 必须以 `## {sec_title}` 作为本节的开头。
3. 如果编辑总监指令中要求图表，请包含图表占位符。{DIAGRAM_HINTS}
4. 必须包含至少 2 个 `> ` 引用段落（金句、要点、注意事项）。
5. 难度匹配 {diff_label}。如果是入门，大量使用类比；如果是进阶，深入技术细节。
6. (如果指令中要求写代码) 给出带详细注释的 Python 代码，单段控制在 25 行内。
7. 不要写任何"欢迎点赞关注"的废话，只输出纯 Markdown 正文。
8. **禁止 AI 生图**：绝对禁止在正文中使用 `【此处插入配图：...】` 等普通照片或 AI 生图占位符。配图必须且只能使用 `【此处绘制图表：描述】` 格式。
"""

    content = call_deepseek_with_retry(
        section_prompt, system_content=SYSTEM_PROMPT, timeout=180
    )
    return content


# ==========================================
#  主入口: 三阶段 Map-Reduce
# ==========================================
def generate_aikepu_article(topic_info):
    """
    三阶段 Map-Reduce 架构生成 15000+ 字长文：
    阶段1: 大纲生成
    阶段2: LLM 提示词自优化 (跨节一致性保障)
    阶段3: 串行生成 + 上文衔接
    """
    title = topic_info.get("title", "")
    tags = topic_info.get("tags", [])
    difficulty = topic_info.get("difficulty", 1)
    summary = topic_info.get("summary", "")

    difficulty_labels = {1: "入门", 2: "基础", 3: "进阶", 4: "前沿"}
    diff_label = difficulty_labels.get(difficulty, "基础")
    tags_str = " · ".join(tags)

    # ---- 阶段 1: 大纲生成 ----
    logger.info("🎓 [阶段1/3] 正在生成大纲: {}", title)
    sections = _generate_outline(title, summary, diff_label, tags_str)
    if not sections:
        return None

    # ---- 阶段 2: LLM 提示词自优化 ----
    logger.info("🧠 [阶段2/3] 正在进行提示词自优化...")
    optimized = _optimize_section_prompts(title, diff_label, sections)
    if not optimized:
        logger.warning("阶段2失败，回退使用原始大纲")
        optimized = _fallback_to_basic_prompts(sections)

    # ---- 阶段 3: 串行生成 + 上文衔接 ----
    logger.info("✍️  [阶段3/3] 正在逐节生成文章 ({} 节)...", len(optimized))
    full_article = []
    prev_tail = ""

    for i, opt_sec in enumerate(optimized):
        sec_title = opt_sec.get("title", f"第 {i + 1} 节")
        logger.info(
            "✍️  [阶段3] 正在生成第 {}/{} 节: {}",
            i + 1, len(optimized), sec_title
        )

        content = _generate_section(
            title, diff_label, opt_sec,
            prev_tail=prev_tail,
            section_index=i,
            total_sections=len(optimized),
        )

        if not content:
            logger.warning("第 {} 节生成失败，将导致文章不完整", i + 1)
            continue

        content = content.strip()
        full_article.append(content)

        # 传递本节尾部 500 字给下一节作为衔接上下文
        prev_tail = content[-500:] if len(content) > 500 else content

    if not full_article:
        return None

    final_article = "\n\n".join(full_article)

    # 强制清理可能误输出的普通照片配图占位符，落实“科普长文主要以图表为主，避免AI生图”的原则
    final_article = re.sub(r"【\s*此处插入配图\s*[：:]\s*.*?\s*】", "", final_article)

    # 追加知识地图和关注尾缀
    final_article += (
        f"\n\n## 知识地图导航\n\n"
        f"学习完这篇内容，你在 AI 技能树上又点亮了一个重要节点。"
        f"你可以继续探索与此相关的前置或后置知识，构建完整的知识体系。\n\n"
        f"**关注「{BRAND_NAME}」，系统学习 AI 知识体系。**"
    )

    # 统计
    word_count = len(final_article.replace(" ", "").replace("\n", ""))
    heading_count = final_article.count("## ")
    quote_count = final_article.count("> ")
    diagram_placeholders = final_article.count("【此处绘制图表：")

    print("\n📝 AI科普长文生成报告:")
    print(f"   标题: {title}")
    print(f"   字数: {word_count:,}")
    print(f"   二级标题: {heading_count} 个")
    print(f"   引用段落: {quote_count} 个")
    print(f"   图表占位符: {diagram_placeholders} 个")
    print("   生成架构: 三阶段 Map-Reduce (提示词自优化)")

    if word_count < 15000:
        logger.warning(
            "⚠️ 文章字数 ({:,}) 低于 15000 字目标", word_count
        )

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
