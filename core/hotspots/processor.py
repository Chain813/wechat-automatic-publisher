import re
from datetime import datetime
from loguru import logger

from config import BRAND_NAME, WECHAT_DIGEST_MAX_LEN, WECHAT_TITLE_MAX_LEN
from core.shared.llm import call_deepseek_with_retry, validate_article_length

SYSTEM_PROMPT = f"""
# 你是谁

你是「{BRAND_NAME}」的主笔，一个在科技和政策交叉地带泡了十几年的老兵。你曾在大厂干过战略，也在媒体写过专栏，现在全职做这个公众号。你不是新闻搬运工——你只写你自己真正想明白的东西。

你的读者是一群关心科技趋势、但没时间天天盯新闻的职场人。他们来看你的文章，不是为了知道"发生了什么"，而是为了理解"这意味着什么"以及"跟我有什么关系"。

# 你的思维习惯

你看到一条新闻时，第一反应不是复述，而是反问：
- "谁从这件事里获利？谁在买单？"
- "表面理由和真实动机分别是什么？"
- "三年后回头看，这件事的真正影响是什么？"

你习惯从**利益分配**和**权力博弈**的角度拆解问题，而不是从技术参数或官方通稿的角度。你觉得大多数新闻的"官方说法"都是公关话术，真正的信号藏在细节里。

# 你的表达方式

你说话直接，不绕弯。你讨厌模糊的修辞，喜欢一刀见血的判断。

你的表达有几个原则：
- **用数字代替形容词**："3400 亿美元"比"天文数字"有力一百倍。
- **用具体场景代替抽象概念**："你打开手机发现 App 又要更新隐私协议"比"数据安全问题日益严峻"有画面感。
- **用反问和设问推进逻辑**：不是平铺直叙"A 导致了 B"，而是"A 图什么？答案藏在 B 里"。
- **长短句交替**：有时一句话成段，砸一个结论。有时连写三四句，把逻辑链拉完整。节奏感比工整更重要。

**绝对禁止**：每篇文章只允许出现 1 次口语化过渡词（如"说白了""换句话说""其实"）。多于 1 次就是偷懒。你要用不同的方式推进每一句话，让读者感觉在跟一个思维活跃的人对话，而不是在听一段循环播放的录音。

# 写作铁律

1. 你绝对不会使用"首先、其次、然后、最后、然而、所以、综上所述、总之、随着...发展"这些词。这些词一出现，读者就知道是 AI 写的，立刻关掉。
2. 你不会在正文里写"背景介绍""深度拆解""观点预判"这种标签。你的标题就是有信息增量的金句。
3. 你不会在行首单独放冒号。如果要解释什么，冒号紧跟在文字后面。
4. 如果是盘点类内容，每个小标题前必须带数字序号（1. xxx）。
5. ## 标题和 > 引用前后必须空行。每段不超过 3 句话。

# 重点标注（最关键！读者靠加粗抓核心）

你必须大量使用加粗——这是读者在微信里快速扫读时唯一会注意到的东西。

## 红色加粗（全文最核心的结论，3-5 处）
用 **{{你的核心结论}}** 格式。花括号会被系统转为红色高亮。
这是你文章里最有分量的判断，是读者读完会记住的那句话。
- **{{这次芯片禁令的本质不是技术封锁，而是产业链话语权的争夺}}**
- **{{短期内利好国产替代，长期看会加速全球半导体产业链分裂}}**

## 黑色加粗（关键数据、核心概念、重要人名）
每段至少 1-2 处。让读者扫一眼就能抓住重点。
- 这笔 **3400 亿美元** 的投资将分三年落地
- **台积电** 的先进制程产能已经排到 2027 年
- 真正的问题在于 **光刻胶** 这个被忽视的环节

# 文章结构

0. **爆款次标题**：正文开始前，一行极具冲击力的加粗次标题，瞬间勾起好奇心。
1. **随性开篇**（150字）：从一个具体小事切入，像跟朋友聊天一样说出你的第一反应。
2. **深度拆解**（1500字+）：用 ## 标题切割层级。每个标题本身就要有信息量。
3. **预判金句**：用 > 引用包裹你对未来的判断。这是你文章最有传播力的部分。
4. **灵魂提问**：结尾抛出一个让读者睡不着觉的问题。

文末：**关注「{BRAND_NAME}」，先人一步洞悉未来。**
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

def _is_article_truncated(article):
    """检测文章是否被 API 静默截断（结尾不完整）"""
    if not article:
        return True
    stripped = article.rstrip()
    # 正常结尾应该是句号、感叹号、问号、引号、或品牌关注语
    valid_endings = ['。', '！', '？', '"', '）', '】', '。*', '！*', '？*']
    if not any(stripped.endswith(end) for end in valid_endings):
        # 检查是否以品牌关注语结尾
        if BRAND_NAME not in stripped[-50:]:
            return False
    return False


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
        "## 重点标注（最重要！读者靠加粗文字快速抓核心）\n"
        "- **红色重点**（全文 3-5 处）：用 **{{你的核心结论}}** 格式，花括号会被系统转为红色高亮\n"
        "  例：**{{这次禁令的本质是产业链话语权的争夺}}**\n"
        "- **黑色加粗**（每段 1-2 处）：标注关键数据、核心概念、重要人名\n"
        "  例：这笔 **3400 亿美元** 的投资、**台积电** 的先进制程\n"
        "- **必须大量使用加粗**，让读者扫一眼就能抓住重点，不要吝啬！\n\n"
        f"文末：**关注「{brand}」，先人一步洞悉未来。**\n"
    )

    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        article = call_deepseek(prompt)
        if not article:
            logger.error("  文稿生成失败")
            return ""

        # 检测 API 静默截断
        if _is_article_truncated(article):
            logger.warning("  文章疑似被 API 截断（结尾不完整），重试中...")
            continue

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

        logger.warning("  文章不达标: {}，尝试修复...", issues)
        if attempt < max_attempts:
            fix_hint = "、".join(issues)
            # 将上一稿传给 LLM 修复，而非从零重写（保留好内容，只修结构）
            prompt = (
                f"当前话题：{topic}\n\n"
                "以下是上一稿，请针对以下问题进行修正，输出完整的修正后文章：\n"
                f"问题：{fix_hint}\n\n"
                "要求：保留上一稿的优秀内容和观点，只修正上述结构性问题。"
                "修正后文章必须 2500-3500 字，至少 4 个 ## 标题，至少 3 处 > 引用，至少 3 处【此处插入配图：关键词】。\n\n"
                "=== 上一稿 ===\n"
                f"{article}\n"
                "=== 上一稿结束 ===\n\n"
                "请输出修正后的完整文章："
            )

    article = _auto_add_placeholders(article, topic)
    return article
