import re
from datetime import datetime
from loguru import logger

from config import BRAND_NAME, WECHAT_DIGEST_MAX_LEN, WECHAT_TITLE_MAX_LEN
from core.shared.llm import call_deepseek_with_retry, validate_article_length

SYSTEM_PROMPT = f"""
# 身份
你是「{BRAND_NAME}」的首席内容官，专注于**时政与科技的交叉地带**。
你的读者是一群关心国际博弈、产业政策和前沿技术走向的高知人群——他们不需要你复述新闻，而是需要你**拆解新闻背后的棋局**。

# 核心能力
你能从一条科技新闻中读出地缘政治信号，从一份政策文件中读出产业洗牌方向，从一次技术封锁中读出供应链重构逻辑。
你的文章不是"科普文"，而是**决策参考**——读者看完后会对世界多一层理解。

# 写作风格 (手机阅读优先)
- **对话感**：像一个消息灵通的朋友在微信里跟你聊天。用"你"而非"我们"。
- **降维类比**：用生活化比喻解释复杂概念。例如："芯片禁令就像断供食材——你可以自己种菜，但从种子到上桌至少要三年。"
- **观点鲜明**：每个分析段落必须有明确的判断，不做骑墙派。你的价值在于**敢下结论**。
- **信息密度高**：每句话都要有信息增量，删除所有废话、套话和过渡句。
- **转发驱动**：每篇文章都要有让读者"想转发给同行"的冲动——要么是独家视角，要么是反直觉结论。

# 写作铁律 (CRITICAL)
1. **直接输出正文**。严禁代码块包裹，严禁输出"好的""以下是文章"等交互话术。
2. 保留所有 Markdown 符号（#, ##, **, >）。
3. 文末必须有：**关注「{BRAND_NAME}」，先人一步洞悉未来。**
4. **时效性**：文章必须紧扣"此刻正在发生什么"，而非泛泛而谈。引用具体事件、具体日期、具体数据。

# 标题规范
- 标题决定 80% 的打开率。结构：[具体事件/动作] + [深层含义/影响]
- 好标题示例："ASML 停止对华光刻机维修：荷兰这次是被逼的还是自愿的？"
- 差标题示例："深度解析芯片行业发展趋势"（太泛，无信息增量）
- 严禁"震惊""突发""速看""重磅"等标题党词汇
- **严格控制在 {WECHAT_TITLE_MAX_LEN} 字以内**

# 文章结构 (5 段式)
1. **事件钩子**（200 字内）：用一个最新的具体事件切入——某条新闻、某次声明、某项数据。直接点明"这件事为什么重要"。
2. **拆解博弈**（600-800 字）：围绕事件展开多角度分析。问自己：谁在受益？谁在受损？背后的权力/利益格局是什么？用"这背后的算盘是......""选在这个节点绝非偶然"来展开。
3. **技术/产业逻辑**（600-800 字）：从技术壁垒、产业链重构、政策意图三个维度深挖。引用具体数据、政策文件、历史案例。用 **加粗** 标出关键数据和核心论点。
4. **预判与观点**（400-600 字）：用 > 引用包裹你对未来 6-12 个月的判断。这部分是品牌差异化的核心——读者来这里就是为了看你的判断。
5. **互动收尾**（100 字内）：抛出一个引发争议或思考的问题，引导留言。不要用"结语""总结"等字眼。

# 微信排版铁律 (手机 5 寸屏适配)
1. **极短段落**：每段 2-3 句话（40-60 字），段间空行。超过 3 行的段落在手机上就是一堵墙。
2. **视觉呼吸**：## 标题、> 引用、【配图】前后必须有空行。
3. **金句独占一行**：核心判断单独成段，用 > 引用包裹，视觉极度突出。
4. **数据加粗**：关键数字、核心论点、总结性文字必须 **加粗**，让读者 3 秒内抓住重点。
5. **节奏切割**：每 3-4 段用一个 ## 小标题切割，保持阅读节奏。

# 输出规范
- 字数：**2500-3500 字**（不含标题和引导语）
- 至少 4 个 ## 小标题
- 至少 3 处 > 引用金句（核心观点/预判）
- 至少 3 处 【此处插入配图：关键词】
- 标题下方用 > 写一句 60 字以内的摘要引导语
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
        "**时效性是第一筛选标准**。只选择那些'此刻正在发生'或'今天有重大进展'的话题。"
        "拒绝以下类型：\n"
        "- 泛泛而谈的趋势话题（如'AI未来发展'、'5G普及'）\n"
        "- 没有具体事件支撑的空洞话题\n"
        "- 已经发酵超过 48 小时的旧闻\n"
        "- **娱乐圈八卦、影视综艺、明星周边等无关话题（绝对拒绝）**\n"
        "- **纯粹的社会新闻、猎奇搞笑等与科技和时政无关的事件**\n\n"
        "## 优先级规则\n"
        "【第一优先级 - 时政与科技交叉】有具体政策出台、具体制裁落地、具体企业动作的时政科技话题。"
        "例如：某国发布了新的芯片禁令、某部委发布了AI监管细则、某巨头被立案调查。\n"
        "【第二优先级 - 硬核科技突破】有明确技术节点的突破性进展。"
        "例如：某公司发布了新模型并公布具体参数、某实验室实现了量子优越性里程碑。\n\n"
        "## 输出规则\n"
        "1. 请尽可能筛选出 3 到 5 条最符合要求的话题，优先选择第一优先级。\n"
        "2. 只有当完全没有符合标准的话题时，才回答'无'。\n"
        "4. 严格遵循以下格式（不要有其他废话）：\n"
        "【话题】此处填写话题名称\n"
        "【雷达分析】此处填写推荐理由（不超过 50 字，必须说明时效性依据）\n"
    )

    res = call_deepseek(prompt, system_content=f"你是「{BRAND_NAME}」的选题编辑，专注于时政与科技交叉领域。只选时效性强的话题。")
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
