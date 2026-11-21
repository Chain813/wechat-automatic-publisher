import os
import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from loguru import logger

from config import BRAND_NAME, HOTSPOT_TIERS, WECHAT_DIGEST_MAX_LEN
from core.shared.llm import call_deepseek_with_retry, validate_article_length
from core.hotspots.narrative import (
    ARCHETYPES,
    select_narrative_archetype,
    select_dynamic_hook,
)

SYSTEM_PROMPT = f"""
你负责为「{BRAND_NAME}」解读科技和政策新闻。开头直接说谁做了什么、改变了哪一步。
每个小节回答一个读者问题。用原文条款、产品行为或有出处的数字说明变化。
把机构的说法归给机构。写推断时交代依据和成立条件。材料缺失时说明仍待确认之处。
不要代写当事人的想法，不要杜撰采访、现场、数据或行业共识。删去换个话题也能用的句子。

使用有实义的 ## 小标题和 > 摘要块，前后留空行，每段不超过三句话。
全文 3–5 处核心判断用 **{{{{核心结论}}}}**，关键名词与数字用普通 **黑色加粗**。
使用【此处插入配图：可检索的具体主体】单行配图标记。遵循本次任务的数量和长度要求。
落款为 **关注「{BRAND_NAME}」。**
"""


def load_hotspots_skill_prompt() -> str:
    """加载深度热点长文写作规范文件 prompts/hotspots_skill.md"""
    skill_path = os.path.join("prompts", "hotspots_skill.md")
    if os.path.exists(skill_path):
        try:
            with open(skill_path, "r", encoding="utf-8") as f:
                return f.read().strip().replace("{BRAND_NAME}", BRAND_NAME)
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
        f"- 概括话题原文里的主体和动作，只写题目已说明的影响，保留“拟”“试点”等限定词\n"
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

def _format_hotspot_tiers(tiers: List[Dict[str, Any]]) -> str:
    """将 config.HOTSPOT_TIERS 渲染为可供选题 Prompt 直接消费的优先级规则块。"""
    blocks = []
    for tier in tiers:
        name = tier.get("name", "").strip()
        desc = tier.get("description", "").strip()
        keywords = "、".join(tier.get("keywords", []))
        block = f"【{name}】{desc}"
        if keywords:
            block += f"\n重点参考方向与关键词：{keywords}"
        blocks.append(block)
    return "\n".join(blocks)


def filter_tech_hotspots(topics):
    logger.info("DeepSeek 正在跨平台筛选科技、政策与研学热点...")
    today_str = datetime.now().strftime("%Y年%m月%d日")

    item_map = {}
    if isinstance(topics, list):
        for t in topics:
            if hasattr(t, "title") and isinstance(getattr(t, "title"), str) and t.title:
                item_map[t.title.strip()] = t

    if item_map:
        formatted_topics = []
        for idx, t in enumerate(topics, 1):
            if hasattr(t, "title") and isinstance(getattr(t, "title"), str):
                summary_part = f" (摘要: {t.summary[:90]})" if getattr(t, "summary", "") else ""
                source_part = f"[{t.source_id}] " if getattr(t, "source_id", "") else ""
                formatted_topics.append(f"{idx}. {source_part}{t.title}{summary_part}")
            else:
                formatted_topics.append(f"{idx}. {t}")
        topics_payload = "\n".join(formatted_topics)
    else:
        topics_payload = str(topics)

    tiers_block = _format_hotspot_tiers(HOTSPOT_TIERS)

    prompt = (
        f"以下是来自多个平台的实时热点资讯（采集时间：{today_str}）：\n" + topics_payload + "\n\n"
        f"你是「{BRAND_NAME}」的选题编辑。\n\n"
        "## 选题铁律\n"
        "**时效性是第一筛选标准**。只选择那些'此刻正在发生'或'今天有重大进展'的话题。\n"
        "拒绝以下类型：\n"
        "- 泛泛而谈的趋势话题（如'AI未来发展'、'科技改变生活'）\n"
        "- 没有具体事件支撑的空洞话题\n"
        "- 已经发酵超过 48 小时的旧闻\n"
        "- **娱乐圈八卦、影视综艺、明星周边等无关话题（绝对拒绝）**\n"
        "- **纯粹的社会新闻、猎奇搞笑等与科技、政策、高校科研及技术人才无关的事件**\n\n"
        "## 三梯队优先级规则\n"
        f"{tiers_block}\n\n"
        "## 输出规则\n"
        "1. 请尽可能筛选出 3 到 5 条最符合要求的话题，按优先级排列。\n"
        "2. 只有当完全没有符合标准的话题时，才回答'无'。\n"
        "4. 严格遵循以下格式（不要有其他废话）：\n"
        "【话题】此处填写话题名称\n"
        "【雷达分析】此处填写推荐理由（不超过 50 字，必须说明时效性依据）\n"
    )

    res = call_deepseek(
        prompt,
        system_content=(
            f"你是「{BRAND_NAME}」的选题编辑，专注于 AI 与科技政策交叉、硬核 AI 与开源工程突破、"
            "以及高校科研/考研升学/技术人才与科技财经领域。只选时效性强的话题。"
        ),
    )
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

    logger.info("  最终筛选进入队列: {}", [t.title if hasattr(t, "title") and isinstance(getattr(t, "title"), str) else str(t) for t in result])
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

    from core.shared.article_utils import count_black_bold
    black_bold_count = count_black_bold(text)
    if black_bold_count < 6:
        missing.append(f"黑色重点加粗不足 ({black_bold_count}/6)")

    return len(missing) == 0, missing

def _auto_add_placeholders(article, topic, min_count=3):
    need = min_count - len(re.findall(r'【此处插入配图', article))
    if need <= 0:
        return article

    sections = re.split(r'(?=^##[ \t]+)', article, flags=re.MULTILINE)
    name_pattern = re.compile(r'[A-Z][A-Za-z0-9-]+(?: [A-Z0-9][A-Za-z0-9-]*){0,3}')
    keyword_pattern = re.compile(r'\*\*([^*{}【】\n。，：；！？]{2,24})\*\*')
    section_ids = [i for i, section in enumerate(sections) if section.startswith("## ")]
    # 优先在导语以后的未配图小节补图。
    ordered = section_ids[1:] + section_ids[:1] if section_ids else [0]
    slots = [i for i in ordered if "【此处插入配图" not in sections[i]] or ordered
    title_name = name_pattern.search(topic)
    title_query = title_name.group() if title_name else re.split(r'[，。！？：、\n【】]', topic.strip())[0][:40]

    for slot in range(need):
        index = slots[slot % len(slots)]
        section = sections[index]
        # 排除品牌落款、链接和已有的配图标记。
        content = re.sub(r'关注「.*|https?://\S+|【[^】]*】', '', section)
        name = name_pattern.search(content)
        keyword = keyword_pattern.search(content)
        query = title_query
        if name:
            query = name.group()
        elif keyword:
            query = keyword.group(1).strip()
        marker = f"【此处插入配图：{query}】"
        signature = re.search(r'(?m)^(?:\*\*)?关注「', section)
        position = signature.start() if signature else len(section)
        sections[index] = f"{section[:position].rstrip()}\n\n{marker}\n\n{section[position:]}"
    return "".join(sections)


def _is_article_truncated(article):
    """检测文章是否被 API 静默截断（结尾不完整）"""
    if not article or len(article.strip()) < 500:
        return True
    stripped = article.rstrip()
    # 剥除尾部 Markdown 格式符号与空白，准确定位最后有效字符
    clean_tail = re.sub(r'[\s\*_#>`~\-—]+$', '', stripped)
    valid_endings = ('。', '！', '？', '…', '"', '”', '’', '）', '】', '》', '.', '!', '?')
    if clean_tail and clean_tail.endswith(valid_endings):
        return False
    # 检查末尾是否包含品牌关注语或结语标记
    if BRAND_NAME in stripped[-100:] or "关注" in stripped[-60:] or "洞见" in stripped[-60:]:
        return False
    return True


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
    if hasattr(topic, "title") and isinstance(getattr(topic, "title"), str):
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
    fact_context = raw_content
    try:
        from core.hotspots.searcher import build_fact_context, search_topic_facts
        if search_results is None:
            search_results = search_topic_facts(topic_title)
        fact_context = build_fact_context(topic_title, raw_content=raw_content, search_results=search_results)
    except Exception as e:
        logger.debug("构建事实基座降级: {}", e)

    references = []
    if topic_url:
        references.append(f"采集条目链接：{topic_url}")
    if getattr(topic, "summary", ""):
        references.append(f"采集条目摘要：{topic.summary}")
    if fact_context:
        references.append(fact_context)
    fact_context = "\n\n".join(references)
    if hasattr(topic, "fact_check_result") or hasattr(topic, "__dict__"):
        try:
            topic.fact_check_result = fact_context[:800]
        except (AttributeError, TypeError):
            pass

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

    initial_prompt += (
        f"## 本篇参考材料\n{fact_context or '目前只有选题标题。'}\n\n"
        f"## 任务\n为微信公众号「{brand}」解读这个事件。今天是{today_str}，采集时间不能当作事件日期。\n"
        "先交代主体、动作和对象。每节选一项材料中的变化，解释它会改变谁的哪一步，或如何核对。"
        "报道、公司宣称和作者推断分开表达，重要引述就近注明材料中给出的出处。"
        "数字保留单位、比较基准和时间范围。资料只支持一部分时，写清适用条件或尚缺的信息。\n"
        "上述母题和开场只在材料能支撑时采用。不得补写采访、现场、人物动机、趋势或预测。"
        "资料有限时，可解释文中术语、核对路径与待证问题，勿用套话、改述同一结论或新增事实凑字数。\n\n"
        "## 硬性排版与结构要求（必须完全满足！）：\n"
        "1. **小标题**：必须使用至少 4 个 `## ` 二级标题进行分段切割。小标题说清该节解释的具体变化或读者问题，严禁使用'背景介绍'、'深度拆解'等刻板标签！末尾严禁添加任何标点符号。\n"
        "2. **引用金句**：必须包含至少 3 处以 `> ` 开头的独立要点块（每处 50-100 字），提炼已有论据或条件；只有逐字引述原文才加引号。\n"
        "3. **配图占位符**：必须包含至少 3 处 `【此处插入配图：具体主体】`（紧跟在关键论述段落之后）。每处只填简短可搜的名称，优先用相关产品、设备、地点的英文专名，不填画风或运镜。\n"
        "4. **正文字数**：总字数必须严格在 2500 - 3500 字，绝不能少于 2000 字！\n"
        "5. **重点标注**（最关键！读者靠加粗扫读抓核心，绝不能吝啬！）：\n"
        "   - **红色重点**（全文 3-5 处）：用 **{{你的核心结论}}** 格式（系统会渲染为醒目红底微光高亮卡片）\n"
        "   - **黑色加粗**（强制每段 1-2 处，全文不少于 12 处！）：用 `**关键词或核心判断**`（不含花括号）标注关键数字（如 `**3400 亿美元**`、`**48%**`）、核心技术概念（如 `**光刻胶**`）、关键公司/人物（如 `**台积电**`）及转折金句。绝不能只写红字而不写普通黑色加粗！\n"
        "6. **微光卡片语法支持**：如涉及风险避坑、技术洞察或实操清单，可使用 `> ⚠️ **避坑指南**：`、`> 💡 **核心洞察**：`、`> 📌 **行动清单**：`。\n\n"
        f"文末结尾：**关注「{brand}」。**\n"
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
                f"**关注「{brand}」。**"
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
            f"{initial_prompt}\n\n"
            f"## 修订上一稿\n上一稿未达标项目：{fix_hint}。保留参考材料及其限定条件，按原排版要求重写完整正文。"
            "上一稿只供定位问题，不能用作事实来源。删除其中找不到依据的断言，补充材料能回答的问题。\n\n"
            f"=== 上一稿 ===\n{article}\n=== 上一稿结束 ===\n"
        )

    logger.error("❌ 文章在 {} 次重新生成后仍无法达到硬性合规要求", max_attempts)
    return ""
