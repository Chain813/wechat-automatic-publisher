import os
import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from loguru import logger

from config import BRAND_NAME, WECHAT_DIGEST_MAX_LEN
from core.shared.llm import call_deepseek_with_retry, validate_article_length
from core.hotspots.narrative import (
    ARCHETYPES,
    select_narrative_archetype,
    select_dynamic_hook,
)

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

0. **真实性铁律**：绝对不允许胡编乱造。所有提及的技术指标、公司数据、政策条款、新闻事实都必须保证真实、客观、准确，杜绝 AI 幻觉和虚假内容。
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

# 动态叙事结构与推进
正文拒绝刻板八股大纲，根据母题法则与黄金切入点展开动态推进：
1. **黄金 Hook 切入**：以反常识冲突、隐秘代价、现场特写或认知逆转直击核心。
2. **逻辑递进**：深挖底层因果与博弈机理，小标题必须是具有信息增量和洞察的动态金句，严禁标签式小标题。
3. **视觉焦点**：关键预判用 > 引用块沉淀（50-100字），重要结论使用 **{{红色高亮}}**。
4. **文末结尾**：以具有启发性的深思收尾，文末落款：**关注「{BRAND_NAME}」，先人一步洞悉未来。**
"""

def load_hotspots_skill_prompt() -> str:
    """加载深度热点长文写作规范文件 prompts/hotspots_skill.md"""
    skill_path = os.path.join("prompts", "hotspots_skill.md")
    if os.path.exists(skill_path):
        try:
            with open(skill_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception as e:
            logger.warning("加载 hotspots_skill.md 失败: {}", e)
    return ""

def call_deepseek(prompt, system_content=None):
    if system_content is None:
        skill = load_hotspots_skill_prompt()
        system_content = skill if skill else SYSTEM_PROMPT
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

    item_map = {}
    if isinstance(topics, list):
        for t in topics:
            if hasattr(t, "title") and t.title:
                item_map[t.title.strip()] = t

    if item_map:
        formatted_topics = []
        for idx, t in enumerate(topics, 1):
            if hasattr(t, "title"):
                summary_part = f" (摘要: {t.summary[:90]})" if getattr(t, "summary", "") else ""
                source_part = f"[{t.source_id}] " if getattr(t, "source_id", "") else ""
                formatted_topics.append(f"{idx}. {source_part}{t.title}{summary_part}")
            else:
                formatted_topics.append(f"{idx}. {t}")
        topics_payload = "\n".join(formatted_topics)
    else:
        topics_payload = str(topics)

    prompt = (
        f"以下是来自多个平台的实时热点资讯（采集时间：{today_str}）：\n" + topics_payload + "\n\n"
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
    from core.plugins.base import HotspotItem
    from difflib import SequenceMatcher

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("【话题】"):
            topic_name = line.replace("【话题】", "").strip()
            topic_name = topic_name.strip("。，；.,;")
            if topic_name:
                matched_item = None
                for orig_title, item in item_map.items():
                    if topic_name == orig_title or topic_name in orig_title or orig_title in topic_name:
                        matched_item = item
                        break
                if not matched_item and item_map:
                    for orig_title, item in item_map.items():
                        if SequenceMatcher(None, topic_name, orig_title).ratio() > 0.45:
                            matched_item = item
                            break

                if matched_item:
                    final_item = HotspotItem(
                        title=topic_name,
                        url=matched_item.url,
                        source_id=matched_item.source_id,
                        summary=matched_item.summary,
                        publish_time=matched_item.publish_time,
                        raw_content=matched_item.raw_content,
                        tier=matched_item.tier
                    )
                    result.append(final_item)
                else:
                    result.append(HotspotItem(title=topic_name) if item_map else topic_name)
                print(f"\n📡 [AI 雷达捕获热点] {topic_name}")
        elif line.startswith("【雷达分析】"):
            analysis = line.replace("【雷达分析】", "").strip()
            print(f"   💡 分析理由: {analysis}")

    if not result:
        fallback_titles = parse_topic_list(res)
        if item_map:
            result = [HotspotItem(title=t) for t in fallback_titles]
        else:
            result = fallback_titles

    logger.info("  最终筛选进入队列: {}", [t.title if hasattr(t, "title") else t for t in result])
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
    base_topic = topic[:10].strip()
    distinct_keywords = [
        f"{base_topic} 核心背景",
        f"{base_topic} 关键技术架构",
        f"{base_topic} 产业应用场景",
        f"{base_topic} 发展趋势特写",
    ]

    lines = article.split('\n')
    result = []
    h2_count = 0
    inserted = 0
    for line in lines:
        result.append(line)
        if line.strip().startswith('## '):
            h2_count += 1
            if h2_count >= 2 and inserted < need:
                kw = distinct_keywords[inserted % len(distinct_keywords)]
                result.append(f'\n【此处插入配图：{kw}】\n')
                inserted += 1

    if inserted < need:
        for i in range(inserted, need):
            kw = distinct_keywords[i % len(distinct_keywords)]
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
            return True
    return False


def _auto_add_quotes(article, min_count=3):
    """自动规范并补充金句引用块（> 引用），仅将独立成行的结论句包裹为引用，严禁截断破坏正文"""
    if not article:
        return article

    quotes = re.findall(r'^>\s+', article, re.MULTILINE)
    if len(quotes) >= min_count:
        return article

    needed = min_count - len(quotes)
    lines = article.splitlines()
    new_lines = []
    added = 0

    for line in lines:
        stripped = line.strip()
        if added < needed and (stripped.startswith("**{{") or (stripped.startswith("**") and stripped.endswith("**") and len(stripped) > 8)):
            if not stripped.startswith(">"):
                new_lines.append(f"> {stripped}")
                added += 1
                continue
        new_lines.append(line)

    return "\n".join(new_lines)


def generate_article(topic, raw_content: str = "", search_results: Optional[List[Dict[str, str]]] = None):
    # 支持 HotspotItem 或常规字符串
    if hasattr(topic, "title"):
        topic_title = topic.title
        raw_content = getattr(topic, "raw_content", "") or raw_content
        topic_url = getattr(topic, "url", "")
    else:
        topic_title = str(topic)
        topic_url = ""

    logger.info("DeepSeek 正在以「{}」视角创作深度长文: {}", BRAND_NAME, topic_title)
    brand = BRAND_NAME
    today_str = datetime.now().strftime("%Y年%m月%d日")

    # 0. 若存在一手信源 URL 且尚未提取正文，立即调用 Scraper 抓取原文
    if topic_url and not raw_content:
        try:
            from core.hotspots.scraper import extract_article_content
            logger.info("  📄 正在从一手信源抓取正文: {}", topic_url)
            scraped = extract_article_content(topic_url)
            if scraped:
                raw_content = scraped
                logger.info("  ✅ 成功抓取一手报道正文 ({} 字)", len(raw_content))
                if hasattr(topic, "raw_content"):
                    topic.raw_content = raw_content
        except Exception as e:
            logger.warning("  抓取一手信源正文失败: {}", e)

    # 1. 动态加载叙事母题与黄金切入点 (Hook)
    archetype = select_narrative_archetype(topic_title)
    hook = select_dynamic_hook(archetype["id"])
    logger.info("  🎭 选中叙事母题: 「{}」, 黄金 Hook: 「{}」", archetype["name"], hook["name"])

    # 2. 真实性事实基座构建 (Grounding)
    fact_context = ""
    try:
        from core.hotspots.searcher import build_fact_context, search_topic_facts
        if search_results is None:
            search_results = search_topic_facts(topic_title)
        fact_context = build_fact_context(topic_title, raw_content=raw_content, search_results=search_results)
        if hasattr(topic, "fact_check_result") or hasattr(topic, "__dict__"):
            try:
                setattr(topic, "fact_check_result", fact_context[:800])
            except Exception:
                pass
    except Exception as e:
        logger.debug("构建事实基座降级: {}", e)

    # 3. 动态组装 Prompt
    guidelines_text = "\n".join(f"- {g}" for g in archetype.get("guidelines", []))

    initial_prompt = (
        f"## 选题\n{topic_title}\n\n"
        f"## 叙事母题与风格要求\n"
        f"**母题类型**：{archetype['name']}\n"
        f"**核心穿透视角**：{archetype['core_perspective']}\n"
        f"**叙事推进法则**：\n{guidelines_text}\n\n"
        f"## 黄金 Hook 开篇切入\n"
        f"**切入方式**：{hook['name']}\n"
        f"**写作指引**：{hook['instruction']}\n\n"
    )

    if fact_context:
        initial_prompt += f"## 真实事实基座（必须严格以此为事实依据，严禁虚构伪造事实）\n{fact_context}\n\n"

    initial_prompt += (
        f"## 任务\n为微信公众号「{brand}」创作一篇时政科技深度长文分析。\n"
        f"**当前真实时间是：{today_str}**，文内提及时间必须准确，绝不能随意编造。\n"
        f"**真实性铁律**：所有数据、参数、政策、条款必须真实可靠，杜绝 AI 幻觉和虚假内容。\n\n"
        "## 硬性排版与结构要求（必须完全满足！）：\n"
        "1. **小标题**：必须使用至少 4 个 `## ` 二级标题进行分段切割。小标题必须是具有信息增量和洞察的动态金句，严禁使用'背景介绍'、'深度拆解'等刻板标签！末尾严禁添加任何标点符号。\n"
        "2. **引用金句**：必须包含至少 3 处以 `> ` 开头的独立引用金句块（每处 50-100 字内）。\n"
        "3. **配图占位符**：必须包含至少 3 处 `【此处插入配图：具备画面感的具体关键词描述】`（紧跟在关键论述段落之后）。\n"
        "4. **正文字数**：总字数必须严格在 2500 - 3500 字，绝不能少于 2000 字！\n"
        "5. **重点标注**（读者靠加粗抓核心）：\n"
        "   - **红色重点**（全文 3-5 处）：用 **{{你的核心结论}}** 格式（系统会渲染为微光高亮卡片）\n"
        "   - **黑色加粗**（每段 1-2 处）：标注关键数据、核心概念、物理参数\n"
        "6. **微光卡片语法支持**：如涉及风险避坑、技术洞察或实操清单，可使用 `> ⚠️ **避坑指南**：`、`> 💡 **核心洞察**：`、`> 📌 **行动清单**：`。\n\n"
        f"文末结尾：**关注「{brand}」，先人一步洞悉未来。**\n"
    )

    max_attempts = 4
    current_prompt = initial_prompt

    for attempt in range(1, max_attempts + 1):
        logger.info("  正在发起第 {}/{} 次文章生成/重写请求...", attempt, max_attempts)
        article = call_deepseek(current_prompt)
        if not article:
            logger.warning("  第 {} 次生成请求未返回有效内容，自动重新尝试...", attempt)
            current_prompt = initial_prompt
            continue

        # 检测 API 静默截断
        if _is_article_truncated(article):
            logger.warning("  文章疑似被 API 截断（结尾不完整），退回重新生成...")
            current_prompt = (
                f"{initial_prompt}\n\n"
                "【紧急纠错】上一稿在结尾处被 API 截断了！请重新撰写完整的全篇文章，确保文末输出结尾标注："
                f"**关注「{brand}」，先人一步洞悉未来。**"
            )
            continue

        # 格式微调增强
        article = _auto_add_placeholders(article, topic_title)
        article = _auto_add_quotes(article)

        word_count, ok, msg = validate_article_length(article)
        structure_ok, missing = validate_article_structure(article)

        issues = []
        if word_count < 2000:
            issues.append(f"正文字数严重不足 ({word_count} < 2000 字)")
        if not structure_ok:
            issues.extend(missing)

        if not issues:
            logger.info("✅ 文稿成功通过硬性合规校验 (字数: {}, H2/引用/占位符全量达标)", word_count)
            return article

        logger.warning("  ⚠️ 第 {}/{} 次生成的文章未达硬性要求: {}，退回重新生成！", attempt, max_attempts, "；".join(issues))

        fix_hint = "；".join(issues)
        current_prompt = (
            f"## 重新生成指令（上一稿不满足硬性合规标准，必须重新撰写）\n"
            f"当前话题：{topic_title}\n"
            f"上一稿未达标硬性项目：{fix_hint}\n\n"
            f"## 叙事母题：{archetype['name']}，黄金 Hook：{hook['name']}\n\n"
            "## 强制重写要求\n"
            "请重新撰写一篇完整的深度长文，必须 100% 严格满足以下各项要求：\n"
            "1. 【字数】正文必须达 2500 - 3500 字，绝不能少于 2000 字！\n"
            "2. 【小标题】必须包含至少 4 个 `## ` 小标题（动态金句，严禁标签式小标题，末尾无标点）。\n"
            "3. 【金句引用】必须包含至少 3 处以 `> ` 开头的引用金句块。\n"
            "4. 【配图占位符】必须包含至少 3 处 `【此处插入配图：具体关键词】`。\n"
            "5. 【红黑加粗】必须包含 3-5 处 `**{{红色重点}}**` 及多处 `**黑色加粗**`。\n\n"
            "=== 上一稿（不达标版本，仅供参考，请重新写出更完整的正式版本） ===\n"
            f"{article}\n"
            "=== 上一稿结束 ===\n\n"
            "请输出重新生成的完整文章："
        )

    logger.error("❌ 文章在 {} 次重新生成后仍无法达到硬性合规要求", max_attempts)
    return ""
