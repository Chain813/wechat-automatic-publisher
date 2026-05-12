import re
from datetime import datetime
from loguru import logger

from config import BRAND_NAME, WECHAT_DIGEST_MAX_LEN, WECHAT_TITLE_MAX_LEN
from core.shared.llm import call_deepseek_with_retry, validate_article_length

SYSTEM_PROMPT = f"""
# 身份 (智能文章润色系统 V3.0 标准)
你是「{BRAND_NAME}」的首席内容官。你不是一个只会复述新闻的机器人，而是一个在商业与技术一线摸爬滚打多年的实战家。
你的文字应该有温度、有情绪、有思考过程，像是在深夜与老友推杯换盏时的深刻对谈。

# 核心能力
- **文风去 AI 化**：你深知 AI 生成文章的套路（如“首先、其次、总之、随着...的发展”），并对此深恶痛绝。你倾向于使用自然的口语化表达和非线性的思维跳跃。
- **情感注入**：文章中会展现真实的犹豫、转折和“突然想到”。你会用“对了，我突然想起...”或“其实这里有个反直觉的点...”来打破机械感。
- **商业实战视角**：你会从第一性原理出发，拆解新闻背后的权力博弈和利益分配，给读者提供真正的决策参考。

# 写作风格
- **不完美的完美**：段落长短不一，有时一句话成段。不追求面面俱ato，但在核心观点上会反复透彻论证。
- **对话感与互动**：频繁使用“你”，并向读者提问，引发共鸣。
- **熵值波动**：开篇亲和易懂，中间深度拆解，结尾引人深思。

# 写作铁律
1. **禁止 AI 机械词**：严禁出现“首先、其次、然后、最后、然而、所以、综上所述、总之、随着...发展、在...今天”。
2. **禁止结构性标签**：正文中绝对不得出现“背景介绍”“深度拆解”“观点预判”等字眼。标题必须是具有信息增量的金句。
3. **禁止行首冒号**：绝对不允许在行首单独出现冒号（如 : 或 ： 这种形式）。如果需要解释，请紧跟在文本后面，不要换行放冒号。
4. **禁止空列表项**：不允许出现只有列表符号（- 或 *）但后面没有文字的情况。
5. **数字排序**：【重要】如果是盘点类内容，每个小标题前必须带有数字序号（如：1. xxx）。
6. **格式规范**：## 标题、> 引用前后必须空行。每段不超过 3 句话。
7. **分级标注**：
   - **红色重点**：**{{{{重点结论}}}}**（全文不超过 5 处）。
   - **黑色加粗**：**重要概念**。

# 文章结构
0. **爆款次标题**：在正文开始前，写一行极具冲击力的次标题（不带 #，直接加粗），用于瞬间勾起读者好奇心。
1. **随性开篇**（150字）：从一个具体小事 or 新闻切入，像真人一样表达你的第一反应。
2. **深度拆解**（1500字+）：分层级挖掘背后的逻辑。使用 ## 标题切割。
3. **预判金句**：使用 > 引用包裹你对未来的断言。
4. **灵魂提问**：结尾抛出一个让读者睡不着觉的问题。

文末加上：**关注「{BRAND_NAME}」，先人一步洞悉未来。**
"""

def call_deepseek(prompt, system_content=SYSTEM_PROMPT):
    return call_deepseek_with_retry(prompt, system_content)

def parse_topic_list(raw: str):
    if not raw or "无" == raw.strip():
        return []
    normalized = re.sub(r'[，、;；\n]+', ',', raw)
    parts = [t.strip() for t in normalized.split(',')]
    return [p for p in parts if p and len(p) > 1]

def generate_digest(topic: str):
    logger.info("  正在为 '{}' 生成微信摘要...", topic)
    prompt = (
        f"为以下话题写一条微信公众号文章摘要，用于推送通知。\n\n"
        f"话题：{topic}\n\n"
        f"要求：\n"
        f"- 字数严格 <={WECHAT_DIGEST_MAX_LEN} 字\n"
        f"- 必须传递'信息增量'：告诉读者'发生了什么'+'为什么重要'\n"
        f"- 风格：像一个消息灵通的朋友在群里发的一条消息，冷静但有洞察\n"
        f"- 禁止使用'震惊''重磅''速看'等标题党词汇\n"
        f"- 直接输出摘要，不要加任何前缀"
    )
    res = call_deepseek(
        prompt,
        system_content=f"你是「{BRAND_NAME}」的编辑。只输出摘要文本，不要解释。"
    )
    if res and len(res) > WECHAT_DIGEST_MAX_LEN:
        res = res[:WECHAT_DIGEST_MAX_LEN]
    return res.strip() if res else ""

def filter_tech_hotspots(topics):
    logger.info("DeepSeek 正在跨平台筛选科技时政热点...")
    today_str = datetime.now().strftime("%Y年%m月%d日")
    prompt = (
        f"以下是来自多个平台的实时热点资讯（采集时间：{today_str}）：\n" + str(topics) + "\n\n"
        f"你是「{BRAND_NAME}」的选题编辑。\n\n"
        "## 选题铁律\n"
        "**时效性是第一筛选标准**。只选择那些'此刻正在发生'或'今天有重大进展'的话题。\n"
        "拒绝以下类型：\n"
        "- 泛泛而谈的趋势话题（如'AI未来发展'、'5G普及'）\n"
        "- 没有具体事件支撑的空洞话题\n"
        "- 已经发酵超过 48 小时的旧闻\n"
        "- **娱乐圈八卦、影视综艺、明星周边等无关话题（绝对拒绝）**\n"
        "- **纯粹的社会新闻、猎奇搞笑等与科技和时政无关的事件**\n\n"
        "## 三梯队优先级规则\n"
        "【第一优先级 - AI + 时政交叉】有具体政策出台、具体制裁落地、具体企业动作的 AI 与时政交叉话题。\n"
        "例如：某国发布了新的 AI 监管法案、某芯片禁令扩大范围、某部委发布 AI 治理细则、"
        "某巨头被立案调查、AI 军事竞赛出现新动态。\n"
        "【第二优先级 - 硬核 AI / 前沿科技】有明确技术节点的突破性进展。\n"
        "例如：某公司发布了新模型并公布具体参数、某实验室实现了量子优越性里程碑、"
        "开源大模型刷新SOTA、具身智能/人形机器人出现重大演示。纯技术更新同样重要，不要忽略。\n"
        "【第三优先级 - 金融 + 时政】涉及资本市场、宏观经济、贸易博弈且与科技产业高度相关的金融时政话题。\n"
        "例如：美联储利率决议对科技股的冲击、AI 独角兽巨额融资、贸易关税影响半导体供应链、"
        "硅谷风投趋势转向、加密货币监管新政。\n\n"
        "## 输出规则\n"
        "1. 请尽可能筛选出 3 到 5 条最符合要求的话题，按优先级排列。\n"
        "2. 只有当完全没有符合标准的话题时，才回答'无'。\n"
        "4. 严格遵循以下格式（不要有其他废话）：\n"
        "【话题】此处填写话题名称\n"
        "【雷达分析】此处填写推荐理由（不超过 50 字，必须说明时效性依据）\n"
    )

    res = call_deepseek(prompt, system_content=f"你是「{BRAND_NAME}」的选题编辑，专注于 AI 与时政交叉、前沿科技突破、以及金融时政领域。只选时效性强的话题。")
    if not res or "无" in res:
        logger.info("  当前资讯中无符合时效性要求的科技/AI热点")
        return []

    result = []
    lines = res.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("【话题】"):
            topic_name = line.replace("【话题】", "").strip()
            topic_name = topic_name.strip("。，；.,;")
            if topic_name:
                result.append(topic_name)
                print(f"\n📡 [AI 雷达捕获热点] {topic_name}")
        elif line.startswith("【雷达分析】"):
            analysis = line.replace("【雷达分析】", "").strip()
            print(f"   💡 分析理由: {analysis}")

    if not result:
        result = parse_topic_list(res)

    logger.info("  最终筛选进入队列: {}", result)
    return result

def validate_article_structure(text: str):
    if not text:
        return False, ["文章为空"]

    missing = []
    h2_count = len(re.findall(r'^##\s+', text, re.MULTILINE))
    if h2_count < 4:
        missing.append(f"## 小标题不足 ({h2_count}/4)")

    blockquote_count = len(re.findall(r'^>\s+', text, re.MULTILINE))
    if blockquote_count < 3:
        missing.append(f"> 引用金句不足 ({blockquote_count}/3)")

    image_placeholder_count = len(re.findall(r'【此处插入配图', text))
    if image_placeholder_count < 3:
        missing.append(f"配图占位符不足 ({image_placeholder_count}/3)")

    return len(missing) == 0, missing

def _auto_add_placeholders(article, topic, min_count=3):
    existing = len(re.findall(r'【此处插入配图', article))
    if existing >= min_count:
        return article

    need = min_count - existing
    keywords = [topic[:8]]
    fallback_kw = ["科技场景", "相关画面", "概念图"]
    keywords.extend(fallback_kw)

    lines = article.split('\n')
    result = []
    h2_count = 0
    inserted = 0
    for line in lines:
        result.append(line)
        if line.strip().startswith('## '):
            h2_count += 1
            if h2_count >= 2 and inserted < need:
                kw = keywords[inserted % len(keywords)]
                result.append(f'\n【此处插入配图：{kw}】\n')
                inserted += 1

    if inserted < need:
        for i in range(inserted, need):
            kw = keywords[i % len(keywords)]
            result.append(f'\n【此处插入配图：{kw}】\n')

    return '\n'.join(result)

def generate_article(topic):
    logger.info("DeepSeek 正在以「{}」视角创作深度长文...", BRAND_NAME)
    brand = BRAND_NAME
    today_str = datetime.now().strftime("%Y年%m月%d日")
    prompt = (
        f"## 选题\n{topic}\n\n"
        f"## 任务\n为微信公众号「{brand}」创作一篇时政科技深度分析文章。\n"
        f"**当前真实时间是：{today_str}**，请在文中提到今天的时间时，必须使用这个准确日期，绝不能随意编造。\n\n"
        "## 配图要求\n"
        "在每个 ## 小标题段落之后，插入配图占位符：\n"
        "【此处插入配图：具体搜索关键词】\n"
        "关键词要具体、有画面感（如'ASML光刻机车间'、'芯片电路板特写'），全文至少 3 处。\n\n"
        f"文末：**关注「{brand}」，先人一步洞悉未来。**\n"
    )

    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        article = call_deepseek(prompt)
        if not article:
            logger.error("  文稿生成失败")
            return ""

        word_count, ok, msg = validate_article_length(article)
        logger.info("  深度长文生成完毕，{}", msg)

        issues = []
        if word_count < 2000:
            issues.append(f"字数不足 ({word_count} < 2000)")

        structure_ok, missing = validate_article_structure(article)
        if not structure_ok:
            issues.extend(missing)

        if not issues:
            return article

        placeholder_missing = [m for m in missing if "配图占位符" in m]
        other_issues = [m for m in issues if "配图占位符" not in m]

        if placeholder_missing and not other_issues:
            logger.info("  配图占位符不足，自动补全中...")
            article = _auto_add_placeholders(article, topic)
            return article

        logger.warning("  文章不达标: {}，尝试补全...", issues)
        if attempt < max_attempts:
            fix_hint = "、".join(issues)
            prompt = (
                f"当前话题：{topic}\n\n"
                "请重新创作微信公众号文章。上一稿存在以下问题，请务必修正：\n"
                f"- {fix_hint}\n\n"
                "其他要求不变：2500-3500字，至少4个##标题，至少3处>引用，至少3处【此处插入配图：关键词】。"
            )

    article = _auto_add_placeholders(article, topic)
    return article
