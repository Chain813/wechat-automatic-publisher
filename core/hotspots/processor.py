import os
import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from loguru import logger

from config import (
    ARTICLE_SIGNATURE,
    BRAND_NAME,
    HOTSPOT_TIERS,
    LLM_ENABLE_WEB_SEARCH,
    LLM_FORMATTER_MODEL,
    LLM_MODEL,
    LLM_RESEARCH_MODEL,
    LLM_WRITER_MODEL,
    LLM_WRITER_REASONING_EFFORT,
    WECHAT_DIGEST_MAX_LEN,
)
from core.shared.llm import call_deepseek_with_retry, validate_article_length
from core.hotspots.narrative import (
    ARCHETYPES,
    select_narrative_archetype,
    select_dynamic_hook,
)

SYSTEM_PROMPT = f"""
你是公众号「{BRAND_NAME}」的主笔，秉持「终极钻研」底色，长期写 AI、硬核科技与产业政策的深度评论。
开头前 3 句话直接抛出一处具体画面或尖锐反差，不写新闻通稿起手式。
新闻事件中的人名、日期、数字、引述严格忠于调研简报，绝不杜撰；同时结合可靠的计算机、硬件、产业与工程实践常识讲透门道。
严禁在正文中出现「材料未说明」「材料在此处截断」「下面按材料拆开」等 AI 审稿元话语，严禁空洞套话。
全篇设 3–4 个有信息增量的 ## 小标题（末尾不加标点），每段 2–4 句，讲透就收。
落款为 {ARTICLE_SIGNATURE}
"""


def load_hotspots_skill_prompt() -> str:
    """加载深度热点长文写作规范文件 prompts/hotspots_skill.md"""
    skill_path = os.path.join("prompts", "hotspots_skill.md")
    if os.path.exists(skill_path):
        try:
            with open(skill_path, "r", encoding="utf-8") as f:
                return (
                    f.read()
                    .strip()
                    .replace("{BRAND_NAME}", BRAND_NAME)
                    .replace("{ARTICLE_SIGNATURE}", ARTICLE_SIGNATURE)
                )
        except Exception as e:
            logger.warning("加载 hotspots_skill.md 失败: {}", e)
    return ""


def call_deepseek(prompt, system_content=None, model=None, reasoning_effort=None, tools=None, max_tokens=None):
    if system_content is None:
        skill = load_hotspots_skill_prompt()
        system_content = skill if skill else SYSTEM_PROMPT
    return call_deepseek_with_retry(
        prompt,
        system_content,
        model=model,
        reasoning_effort=reasoning_effort,
        tools=tools,
        max_tokens=max_tokens,
    )

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
    if h2_count < 3:
        missing.append(f"## 小标题不足 ({h2_count}/3)")

    blockquote_count = len(re.findall(r'^>\s+', text, re.MULTILINE))
    if blockquote_count < 3:
        missing.append(f"> 引用金句不足 ({blockquote_count}/3)")

    image_placeholder_count = len(re.findall(r'【此处插入配图', text))
    card_placeholder_count = len(re.findall(r'【此处绘制(?:图表|架构图|流程图|示意图|逻辑图)?', text))
    total_visual_count = image_placeholder_count + card_placeholder_count
    if image_placeholder_count < 1 or total_visual_count < 3:
        missing.append(f"配图/分析卡片标记不足 (配图={image_placeholder_count}, 卡片={card_placeholder_count})")

    from core.shared.article_utils import count_black_bold
    black_bold_count = count_black_bold(text)
    if black_bold_count < 6:
        missing.append(f"黑色重点加粗不足 ({black_bold_count}/6)")

    return len(missing) == 0, missing

def _auto_add_placeholders(article, topic, min_count=3):
    photo_count = len(re.findall(r'【此处插入配图', article))
    card_count = len(re.findall(r'【此处绘制(?:图表|架构图|流程图|示意图|逻辑图)?', article))
    need = min_count - (photo_count + card_count)
    if photo_count == 0 and need <= 0:
        need = 1
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


def research_topic_dossier(
    topic_title: str,
    topic_url: str = "",
    raw_content: str = "",
    summary: str = "",
    today_str: str = "",
) -> str:
    """
    Stage 1: 使用 DeepSeek 原生联网搜索 (deepseek_web_search + deepseek_read_url)
    交叉核验多信源，生成高密度结构化调研简报。
    """
    today_label = today_str or datetime.now().strftime("%Y年%m月%d日")
    seed_parts = []
    if topic_url:
        seed_parts.append(f"初始报道链接：{topic_url}")
    if summary:
        seed_parts.append(f"初始摘要：{summary[:800]}")
    if raw_content:
        seed_parts.append(f"已抓取正文节选：{raw_content[:1500]}")
    seed_block = "\n".join(seed_parts) if seed_parts else "无初始链接，请直接联网检索最新权威报道。"

    research_prompt = (
        f"请对以下新闻热点进行多信源深度联网调研（今天是 {today_label}）：\n"
        f"话题：{topic_title}\n"
        f"{seed_block}\n\n"
        "请调用联网搜索和网页阅读工具，核实并汇总以下信息（只写可查证的事实与出处，不编造、不自行估算未出现的价格或数字）：\n"
        "1. 完整事件脉络与准确时间线（核对年份与前后关联事件，避免把旧闻或不同年份混为一谈）。\n"
        "2. 核心硬数据、技术细节与机制拆解（具体规格、指标口径、技术实现或执行方式）。\n"
        "3. 各方真实反应与争议焦点（官方/机构声明、当事群体、专家或行业媒体有署名的真实观点）。\n"
        "4. 1 个最尖锐、最有穿透力的文章核心切口（点明这件事真正触及的底层矛盾或对读者/行业的现实意义）。\n\n"
        "输出为精炼、高密度的中文结构化调研简报。"
    )
    logger.info("  [Stage 1/3] 正在启动原生联网多信源深调研 ({}): {}", LLM_RESEARCH_MODEL, topic_title)
    try:
        dossier = call_deepseek_with_retry(
            research_prompt,
            system_content="你是一名严谨的科技与政策调查记者，擅长使用联网搜索核查一手信源并整理高密度调研简报。",
            model=LLM_RESEARCH_MODEL,
            reasoning_effort="low",
            tools=[{"type": "deepseek_web_search"}, {"type": "deepseek_read_url"}],
            max_tokens=8192,
        )
        cleaned = (dossier or "").strip()
        if cleaned:
            logger.info("  [Stage 1/3] 深度调研简报就绪 ({} 字)", len(cleaned))
        return cleaned
    except Exception as e:
        logger.warning("  [Stage 1/3] 原生联网深调研降级: {}", e)
        return ""


def _strip_leading_h1(article: str) -> str:
    """移除正文首行多余的一级标题（微信草稿箱标题由独立字段展示）。"""
    lines = article.lstrip().splitlines()
    if lines and re.match(r"^#\s+\S+", lines[0]):
        return "\n".join(lines[1:]).lstrip()
    return article.strip()


def format_article_for_wechat(article: str, topic_title: str, brand: str = BRAND_NAME, signature: str = ARTICLE_SIGNATURE) -> str:
    """
    Stage 3: 轻量微信排版与视觉标注 Pass（默认使用快速 Flash 关思考模型）。
    严禁改写叙事腔调或新增事实，仅在保留原文的基础上完成红字高亮、黑色加粗、金句摘录与配图标记。
    """
    formatter_model = LLM_FORMATTER_MODEL or LLM_MODEL
    logger.info("  [Stage 3/3] 正在执行轻量微信排版与视觉标注 ({})...", formatter_model)
    fmt_system = (
        f"你是公众号「{brand}」的排版编辑。你只负责在不破坏作者行文和事实的前提下，"
        "为已定稿的 Markdown 长文添加微信扫读所需的视觉标注与配图标记。"
    )
    fmt_prompt = (
        f"选题：{topic_title}\n\n"
        "请对下面这篇已完成的正文做轻量微信排版标注，严格遵守以下规则：\n"
        "1. **严禁改写作者的观点、叙事节奏或删减实质内容**，严禁编造新事实，严禁加入「材料未说明」类审稿元话语。\n"
        "2. 保留原有的 `## ` 二级小标题（确保末尾无标点），必要时保证全文有 3–4 个 `## ` 小标题。\n"
        "3. **红色高亮（3–4 处）**：从作者原有最有穿透力的判断句中挑选 3–4 句，用 `**{{核心判断}}**` 包裹（保留原有条件限定）。\n"
        "4. **黑色加粗（不少于 12 处）**：用 `**关键词**`（不含花括号）自然标出关键数字、专有名词、机构/产品名与核心技术概念。\n"
        "5. **独立金句引用块（3 处）**：在关键小节后插入独立的 `> ` 引用块（每处 35–85 字），用凝练视角点出本节核心反差或结论，**严禁把上一段正文原样复制一遍**。\n"
        "6. **1 张纯视觉核心主图 + 2 张结构化分析卡片（严禁用 AI 画流程图或字表）**：\n"
        "   - 在第 1 个关键小节后放 **1 处**概念插画标记：`【此处插入配图：用一句具象物理隐喻概括本文核心冲突】`（例如「一扇紧闭的玻璃门前亮起的红灯」，仅用于生成 1 张《经济学人》风格纯视觉无字主图，严禁写流程图或文字标签）。\n"
        "   - 在后两个关键小节后各放 **1 处**结构化分析卡片标记：`【此处绘制图表：6-12字标题｜要点1 → 要点2 → 要点3】` 或 `【此处绘制图表：6-12字对比标题｜A方事实 vs B方事实】`（由本地零成本排版为高清卡片；数字一律使用精确阿拉伯数字如 `-14%`、`2.7万亿`、`8.4x`，严禁写成汉字数字，所有数据必须源自正文）。\n"
        f"7. 文末保持唯一落款：`{signature}`\n\n"
        "直接输出排版后的完整 Markdown 正文（不要输出 `# 一级标题`，不要加任何解释）：\n\n"
        f"=== 待排版正文 ===\n{article}\n=== 结束 ==="
    )
    try:
        formatted = call_deepseek_with_retry(
            fmt_prompt,
            system_content=fmt_system,
            model=formatter_model,
            reasoning_effort="none",
            max_tokens=8192,
        )
        cleaned = _strip_leading_h1(formatted or "")
        # 安全护栏：仅在排版稿未发生大幅缩水时采纳
        if cleaned and len(cleaned) >= int(len(article) * 0.78):
            if f"关注「{brand}」" not in cleaned[-120:]:
                cleaned = cleaned.rstrip() + f"\n\n{signature}"
            return cleaned
        logger.warning("  [Stage 3/3] 排版输出长度异常 ({} vs 原稿 {})，回退保留原稿并走本地补强", len(cleaned), len(article))
    except Exception as e:
        logger.warning("  [Stage 3/3] 轻量排版阶段异常，回退本地补强: {}", e)
    return article


def generate_article(topic, raw_content: str = "", search_results: Optional[List[Dict[str, str]]] = None):
    # 支持 HotspotItem 或常规字符串
    if hasattr(topic, "title") and isinstance(getattr(topic, "title"), str):
        topic_title = topic.title
        raw_content = getattr(topic, "raw_content", "") or raw_content
        topic_url = getattr(topic, "url", "")
        topic_summary = getattr(topic, "summary", "")
    else:
        topic_title = str(topic)
        topic_url = ""
        topic_summary = ""

    logger.info("三段式热点引擎启动（「{}」视角）: {}", BRAND_NAME, topic_title)
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

    # 1. Stage 1：多信源事实调研（优先原生联网深调研；单测显式传入 search_results 或关闭开关时沿用本地检索基座）
    research_dossier = ""
    if search_results is None and LLM_ENABLE_WEB_SEARCH:
        research_dossier = research_topic_dossier(
            topic_title=topic_title,
            topic_url=topic_url,
            raw_content=raw_content,
            summary=topic_summary,
            today_str=today_str,
        )

    fact_context = raw_content
    if not research_dossier:
        try:
            from core.hotspots.searcher import build_fact_context, search_topic_facts
            if search_results is None:
                search_results = search_topic_facts(topic_title)
            fact_context = build_fact_context(topic_title, raw_content=raw_content, search_results=search_results)
        except Exception as e:
            logger.debug("构建事实基座降级: {}", e)

    references = []
    if research_dossier:
        references.append(f"### 多信源深度调研简报\n{research_dossier}")
    if topic_url:
        references.append(f"采集条目链接：{topic_url}")
    if topic_summary:
        references.append(f"采集条目摘要：{topic_summary}")
    if fact_context and (not research_dossier or raw_content):
        references.append(fact_context)
    fact_context = "\n\n".join(references)
    if hasattr(topic, "fact_check_result") or hasattr(topic, "__dict__"):
        try:
            topic.fact_check_result = fact_context[:800]
        except (AttributeError, TypeError):
            pass

    # 2. Stage 2：无紧箍咒纯写作（默认由 LLM_WRITER_MODEL=deepseek-v4-pro + low 思考档位执笔）
    initial_prompt = (
        f"今天是 {today_str}（请准确锚定当前年份，切勿将当年新闻错写成去年）。\n"
        f"请为微信公众号「{brand}」写一篇深度解读文章，话题：{topic_title}\n\n"
        f"=== 调研素材与信源 ===\n{fact_context or '目前只有选题标题。'}\n=== 素材结束 ===\n\n"
        "## 写作要求（专注内容质量与可读性，不要做机械格式打卡）\n"
        "1. **抓人开篇**：前 3 句话直接抛出一处具体画面、真实细节或尖锐反差，严禁「据某某报道，X 月 X 日某人宣布……」的通稿开头。\n"
        "2. **事实克制 + 深度讲透**：新闻事件里的人名、时间、数字、价格与引述严格以素材为准，绝不编造采访、心理描写或未出现的价格数字；但要充分结合可靠的计算机/AI 硬件/产业规律与工程实践常识，把底层逻辑与现实影响讲深讲透。\n"
        "3. **零审稿腔、零套话**：严禁在正文中写「材料未说明」「材料没有说明」「材料在此处截断」「报道未列出」「下面按材料拆开」「判断这条消息时可核对」等内部审稿词；缺细节自然略过。严禁「值得注意的是」「不可否认」「赋能」「重塑格局」「双刃剑」「让我们拭目以待」。\n"
        "4. **篇幅与结构**：目标 **1,600–2,400 字**（信息密度决定篇幅，绝不车轱辘复述凑字数，但核心内容不少于 1,500 字）。全篇设 **3–4 个**短小锋利、有信息增量的 `## ` 二级小标题（末尾不加标点），每段 2–4 句，留足呼吸感。\n"
        f"5. **自然收束**：结尾落回事件折射的底层命题或读者启发，最后一行统一落款：`{ARTICLE_SIGNATURE}`\n\n"
        "直接输出 Markdown 正文（无需输出 `# 一级标题`）。"
    )

    max_attempts = 4
    current_prompt = initial_prompt
    writer_model = LLM_WRITER_MODEL or LLM_MODEL
    writer_effort = LLM_WRITER_REASONING_EFFORT or None

    for attempt in range(1, max_attempts + 1):
        logger.info(
            "  [Stage 2/3] 正在发起第 {}/{} 次纯写作请求 (model={}, effort={})...",
            attempt, max_attempts, writer_model, writer_effort or "default",
        )
        article = call_deepseek(
            current_prompt,
            model=writer_model,
            reasoning_effort=writer_effort,
        )
        if not article:
            logger.warning("  第 {} 次生成请求未返回有效内容，自动重新尝试...", attempt)
            current_prompt = initial_prompt
            continue

        article = _strip_leading_h1(article)

        # 检测 API 静默截断
        if _is_article_truncated(article):
            logger.warning("  文章疑似被 API 截断（结尾不完整），退回重新生成...")
            current_prompt = (
                f"{initial_prompt}\n\n"
                "【紧急纠错】上一稿在结尾处被截断了！请重新输出完整的全篇文章，确保文末落款为："
                f"{ARTICLE_SIGNATURE}"
            )
            continue

        # 先检查 Stage 2 主体深度（字数与小标题），避免把半成品送入 Stage 3
        draft_word_count, _, _ = validate_article_length(article)
        draft_h2_count = len(re.findall(r'^##\s+', article, re.MULTILINE))
        draft_issues = []
        if draft_word_count < 1500:
            draft_issues.append(f"正文字数严重不足 ({draft_word_count} < 1500 字)")
        if draft_h2_count < 3:
            draft_issues.append(f"## 小标题不足 ({draft_h2_count}/3)")

        if draft_issues:
            fix_hint = "；".join(draft_issues)
            logger.warning("  ⚠️ 第 {}/{} 次纯写作未达基础要求: {}，退回重写！", attempt, max_attempts, fix_hint)
            current_prompt = (
                f"{initial_prompt}\n\n"
                f"## 修订上一稿\n上一稿未达标项目：{fix_hint}。保留参考素材与事实边界，补充实质技术与背景拆解后重写完整正文。\n\n"
                f"=== 上一稿 ===\n{article}\n=== 上一稿结束 ===\n"
            )
            continue

        # Stage 3：独立轻量微信排版与视觉标注 Pass
        article = format_article_for_wechat(article, topic_title, brand=brand)

        # 确定性本地兜底补齐（占位符 / 引用 / 黑色加粗）
        article = _auto_add_placeholders(article, topic_title)
        article = _auto_add_quotes(article)
        from core.shared.article_utils import _apply_bold_fallback, count_black_bold
        if count_black_bold(article) < 6:
            article = _apply_bold_fallback(article, as_html=False)

        word_count, _, _ = validate_article_length(article)
        structure_ok, missing = validate_article_structure(article)

        issues = []
        if word_count < 1500:
            issues.append(f"正文字数严重不足 ({word_count} < 1500 字)")
        if not structure_ok:
            issues.extend(missing)

        if not issues:
            logger.info("✅ 三段式成稿成功通过硬性合规校验 (字数: {}, H2/引用/加粗/占位符全量达标)", word_count)
            return article

        logger.warning("  ⚠️ 第 {}/{} 次成稿结构未达标: {}，退回重新生成！", attempt, max_attempts, "；".join(issues))
        fix_hint = "；".join(issues)
        current_prompt = (
            f"{initial_prompt}\n\n"
            f"## 修订上一稿\n上一稿未达标项目：{fix_hint}。保留参考素材及其事实边界，按要求重写完整正文。\n\n"
            f"=== 上一稿 ===\n{article}\n=== 上一稿结束 ===\n"
        )

    logger.error("❌ 文章在 {} 次重新生成后仍无法达到硬性合规要求", max_attempts)
    return ""
