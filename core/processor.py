"""
============================================================
  AI 内容处理引擎 (DeepSeek)
  定制品牌：智界洞察社
  职责：热点筛选、深度长文创作、关键词简化
  新增：指数退避重试、敏感词过滤、微信规范校验、多分隔符解析
============================================================
"""
import re
import time
import requests

from config import (
    LLM_API_KEY, LLM_BASE_URL, LLM_TIMEOUT,
    BRAND_NAME, BRAND_SLOGAN, BRAND_DESC,
    LLM_MODEL, LLM_TEMPERATURE, LLM_MAX_TOKENS, LLM_MAX_RETRIES,
    WECHAT_TITLE_MAX_LEN, WECHAT_DIGEST_MAX_LEN, SENSITIVE_WORDS
)

from loguru import logger
from utils.http_client import build_api_session

API_SESSION = build_api_session()

# ==========================================
#  角色设定 (智界洞察社 · 时政科技深度分析)
# ==========================================
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



# ==========================================
#  通用 API 调用 (带指数退避重试)
# ==========================================
def call_deepseek(prompt, system_content=SYSTEM_PROMPT):
    """调用 DeepSeek API，带指数退避重试"""
    return call_deepseek_with_retry(prompt, system_content)


def call_deepseek_with_retry(prompt, system_content=SYSTEM_PROMPT,
                              max_retries=None, backoff_base=1.0):
    """带指数退避的 API 调用"""
    if max_retries is None:
        max_retries = LLM_MAX_RETRIES

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}"
    }

    for attempt in range(1, max_retries + 1):
        try:
            data = {
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt}
                ],
                "temperature": LLM_TEMPERATURE,
                "max_tokens": LLM_MAX_TOKENS
            }
            response = API_SESSION.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers=headers,
                json=data,
                timeout=LLM_TIMEOUT
            )
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content']

        except Exception as e:
            if isinstance(e, requests.exceptions.Timeout):
                logger.warning("AI 调用超时 (第 {}/{} 次)", attempt, max_retries)
                if attempt < max_retries:
                    time.sleep(backoff_base * (2 ** (attempt - 1)))
                continue
            if isinstance(e, requests.exceptions.HTTPError):
                status = getattr(e.response, 'status_code', 500)
                # 429 限流：退避重试
                if status == 429:
                    logger.warning("AI 限流 429 (第 {}/{} 次)，退避重试", attempt, max_retries)
                    if attempt < max_retries:
                        time.sleep(backoff_base * (2 ** attempt))
                    continue
                # 5xx 服务端错误：退避重试
                if status >= 500:
                    logger.error("AI 服务端错误 {} (第 {}/{} 次)", status, attempt, max_retries)
                    if attempt < max_retries:
                        time.sleep(backoff_base * (2 ** (attempt - 1)))
                    continue
                # 4xx 客户端错误 (非429)：不重试，直接退出
                logger.error("AI 客户端错误 {}，不重试: {}", status, e)
                return ""
            if isinstance(e, (KeyError, IndexError)):
                logger.error("AI 响应格式异常: {}", e)
                return ""
            logger.error("AI 调用失败: {} (第 {}/{} 次)", e, attempt, max_retries)
            if attempt < max_retries:
                time.sleep(backoff_base * (2 ** (attempt - 1)))

    return ""


# ==========================================
#  话题列表解析 (多分隔符兼容)
# ==========================================
def parse_topic_list(raw: str):
    """
    多分隔符兼容解析话题列表。
    支持：中文逗号、英文逗号、顿号、分号、换行
    """
    if not raw or "无" == raw.strip():
        return []
    # 统一分隔符
    normalized = re.sub(r'[，、;；\n]+', ',', raw)
    parts = [t.strip() for t in normalized.split(',')]
    return [p for p in parts if p and len(p) > 1]


# ==========================================
#  微信规范校验
# ==========================================
def validate_title(title: str):
    """
    校验标题是否符合微信规范。
    返回 (处理后的标题, 警告信息列表)
    """
    warnings = []
    clean_title = title.strip()

    # 移除标题党词汇
    clickbait = ["震惊", "突发", "速看", "重磅", "紧急", "刚刚",
                 "不看后悔", "深度好文", "干货", "收藏"]
    for word in clickbait:
        if word in clean_title:
            clean_title = clean_title.replace(word, "")
            warnings.append(f"已移除标题党词汇: '{word}'")

    # 标题号限制
    if len(clean_title) > WECHAT_TITLE_MAX_LEN:
        warnings.append(f"标题超长 ({len(clean_title)} > {WECHAT_TITLE_MAX_LEN})，已截断")
        clean_title = clean_title[:WECHAT_TITLE_MAX_LEN]

    return clean_title, warnings


def validate_article_length(text: str):
    """
    校验文章字数。
    返回 (实际字数, 是否达标, 消息)
    """
    word_count = len(text.replace('\n', '').replace(' ', ''))
    if word_count < 2000:
        return word_count, False, f"字数不足 ({word_count} < 2000)"
    elif word_count < 2500:
        return word_count, True, f"字数略低 ({word_count})"
    elif word_count > 4000:
        return word_count, True, f"字数偏多 ({word_count} > 4000，微信阅读体验可能不佳)"
    else:
        return word_count, True, f"字数达标 ({word_count})"


# ==========================================
#  敏感词过滤 (正则词边界匹配)
# ==========================================
def filter_sensitive(text: str):
    """
    敏感词检测与过滤（使用正则词边界，避免误匹配子串）。
    返回 (过滤后文本, 命中敏感词列表)
    """
    if not SENSITIVE_WORDS:
        return text, []

    hit_words = []
    filtered = text
    for word in SENSITIVE_WORDS:
        if not word:
            continue
        # 对中文用前瞻/后顾断言模拟词边界，英文用 \b
        if re.search(r'[一-鿿]', word):
            # 中文敏感词：允许前后是标点或字符串边界
            pattern = re.compile(
                r'(?<![一-鿿])' + re.escape(word) + r'(?![一-鿿])'
            )
        else:
            pattern = re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE)

        if pattern.search(filtered):
            hit_words.append(word)
            filtered = pattern.sub('*' * len(word), filtered)

    return filtered, hit_words


# ==========================================
#  摘要生成
# ==========================================
def generate_digest(topic: str):
    """
    AI 生成微信规范的摘要 (≤120 字)，强调时效性和信息增量。
    """
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


# ==========================================
#  热点筛选（AI 优先级排序）
# ==========================================
def filter_tech_hotspots(topics):
    """从多源热搜中筛选时效性强的科技与时政交叉热点"""
    logger.info("DeepSeek 正在跨平台筛选科技时政热点...")
    prompt = (
        "以下是来自多个平台的实时热点资讯（采集时间：今天）：\n" + str(topics) + "\n\n"
        f"你是「{BRAND_NAME}」的选题编辑。\n\n"
        "## 选题铁律\n"
        "**时效性是第一筛选标准**。只选择那些'此刻正在发生'或'今天有重大进展'的话题。"
        "拒绝以下类型：\n"
        "- 泛泛而谈的趋势话题（如'AI未来发展'、'5G普及'）\n"
        "- 没有具体事件支撑的空洞话题\n"
        "- 已经发酵超过 48 小时的旧闻\n\n"
        "## 优先级规则\n"
        "【第一优先级 - 时政与科技交叉】有具体政策出台、具体制裁落地、具体企业动作的时政科技话题。"
        "例如：某国发布了新的芯片禁令、某部委发布了AI监管细则、某巨头被立案调查。\n"
        "【第二优先级 - 硬核科技突破】有明确技术节点的突破性进展。"
        "例如：某公司发布了新模型并公布具体参数、某实验室实现了量子优越性里程碑。\n\n"
        "## 输出规则\n"
        "1. 如果存在第一优先级话题，必须优先选择，最多选 2 条。\n"
        "2. 仅当完全没有第一优先级话题时，才从第二优先级中选择。\n"
        "3. 如果两个优先级都没有（全是泛泛而谈的话题），请直接回答'无'。\n"
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


# ==========================================
#  文章结构校验
# ==========================================
def validate_article_structure(text: str):
    """
    校验文章是否包含要求的结构元素。
    返回 (是否达标, 缺失项列表)
    """
    if not text:
        return False, ["文章为空"]

    missing = []

    # 1. 至少 4 个 ## 小标题
    h2_count = len(re.findall(r'^##\s+', text, re.MULTILINE))
    if h2_count < 4:
        missing.append(f"## 小标题不足 ({h2_count}/4)")

    # 2. 至少 3 处 > 引用金句
    blockquote_count = len(re.findall(r'^>\s+', text, re.MULTILINE))
    if blockquote_count < 3:
        missing.append(f"> 引用金句不足 ({blockquote_count}/3)")

    # 3. 至少 3 处 【此处插入配图：xxx】
    image_placeholder_count = len(re.findall(r'【此处插入配图', text))
    if image_placeholder_count < 3:
        missing.append(f"配图占位符不足 ({image_placeholder_count}/3)")

    return len(missing) == 0, missing


# ==========================================
#  文稿创作（深度科普长文）
# ==========================================
def _auto_add_placeholders(article, topic, min_count=3):
    """
    后处理兜底：如果 AI 漏掉了配图占位符，自动在 ## 小标题后补充。
    """
    existing = len(re.findall(r'【此处插入配图', article))
    if existing >= min_count:
        return article

    need = min_count - existing
    # 根据话题生成通用关键词
    keywords = [topic[:8]]
    fallback_kw = ["科技场景", "相关画面", "概念图"]
    keywords.extend(fallback_kw)

    # 在 ## 小标题后面插入占位符（跳过第一个标题，从第二个开始）
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
        # 还不够，在文末追加
        for i in range(inserted, need):
            kw = keywords[i % len(keywords)]
            result.append(f'\n【此处插入配图：{kw}】\n')

    return '\n'.join(result)


def generate_article(topic):
    """针对话题创作符合品牌调性的深度分析长文，带结构校验重试"""
    logger.info("DeepSeek 正在以「{}」视角创作深度长文...", BRAND_NAME)
    brand = BRAND_NAME
    prompt = (
        f"## 选题\n{topic}\n\n"
        f"## 任务\n为微信公众号「{brand}」创作一篇时政科技深度分析文章。\n\n"
        "## 核心原则\n"
        "这篇文章的价值 = **时效性 x 深度 x 观点**。\n"
        "- 时效性：紧扣'此刻正在发生什么'，引用具体事件、日期、数据，让读者感觉'这篇就是为今天写的'。\n"
        "- 深度：不止于复述新闻，而是拆解新闻背后的权力格局、利益链条和技术逻辑。\n"
        "- 观点：每个分析段落必须有明确判断。读者来这里不是为了看'客观分析'，而是为了看**你怎么看**。\n\n"
        "## 写作要求\n"
        "1. **开篇**（200 字内）：用一个最新具体事件切入——某条新闻、某次声明、某项数据。直接点明'这件事为什么重要'，不要用'钩子''事件钩子'等术语。\n"
        "2. **拆解博弈**：问自己——谁在受益？谁在受损？背后的权力/利益格局是什么？用'这背后的算盘是......''选在这个节点绝非偶然'来展开分析。\n"
        "3. **技术/产业逻辑**：从技术壁垒、产业链重构、政策意图三个维度深挖。引用具体政策文件名称、具体数据、历史案例。**加粗** 标出关键数字和核心论点。\n"
        "4. **预判与观点**：用 > 引用包裹你对未来 6-12 个月的判断。这是品牌差异化的核心——读者来这里就是为了看你的判断。\n"
        "5. **互动收尾**：抛出一个引发争议或思考的问题，引导留言。不要用'结语''总结'等字眼。\n\n"
        "## 排版规则（手机 5 寸屏适配）\n"
        "- 每段 2-3 句话（40-60 字），段间空行\n"
        "- 每 3-4 段用 ## 小标题切割节奏\n"
        "- 关键数据、核心论点必须 **加粗**\n"
        "- 至少 3 处 > 引用金句（核心观点/预判）\n\n"
        "## 配图要求（极其重要，必须遵守）\n"
        "在每个 ## 小标题段落之后，**必须**插入一行配图占位符，格式如下：\n"
        "【此处插入配图：具体搜索关键词】\n"
        "关键词示例：'ASML光刻机车间'、'黄仁勋发布会现场'、'芯片电路板特写'、'会议室谈判场景'\n"
        "全文至少插入 3 处，关键词要具体、有画面感，不要用抽象描述。\n\n"
        "## 输出\n"
        "- 直接输出正文，不要加任何前缀或代码块\n"
        "- 全文 2500-3500 字\n"
        f"- 文末：**关注「{brand}」，先人一步洞悉未来。**\n"
    )

    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        article = call_deepseek(prompt)
        if not article:
            logger.error("  文稿生成失败")
            return ""

        word_count, ok, msg = validate_article_length(article)
        logger.info("  深度长文生成完毕，{}", msg)

        # 收集所有不达标项
        issues = []
        if word_count < 2000:
            issues.append(f"字数不足 ({word_count} < 2000)")

        structure_ok, missing = validate_article_structure(article)
        if not structure_ok:
            issues.extend(missing)

        if not issues:
            return article

        # 配图占位符不足：自动补全，不需要重新生成
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

    # 最终兜底：如果还是不够，自动补上
    article = _auto_add_placeholders(article, topic)
    return article


# ==========================================
#  关键词简化（配图降级搜索用）
# ==========================================
def simplify_keyword(complex_kw):
    """将复杂短语转化为具备场景感的视觉关键词"""
    logger.info("  正在根据内容深度提炼视觉方向 '{}'...", complex_kw)
    prompt = (
        "你是一个顶尖的摄影指导。请根据以下内容，提炼一个最适合配图的视觉关键词。\n"
        "逻辑规则：\n"
        "1. 如果是人物话题：直接返回【人物姓名】，例如：'黄仁勋'。\n"
        "2. 如果是产品/技术话题：返回【产品细节特写】，例如：'H200芯片特写'、'机械狗关节'。\n"
        "3. 如果是趋势/宏观话题：返回【意境场景】，例如：'赛博朋克城市夜景'、'巨大的服务器机房'。\n"
        "4. 如果是科普原理：返回【具象物体】，例如：'显微镜下的电路'、'发光的神经元'。\n"
        "注意：严禁任何描述性长句，只需要返回 1 个具体的搜索词。"
        f"输入：{complex_kw}"
    )
    result = call_deepseek(prompt, system_content="你是一个视觉审美极高的图片策划。").strip()
    result = re.sub(r'["\'""]', '', result)
    logger.info("  视觉导向：'{}'", result)
    return result
