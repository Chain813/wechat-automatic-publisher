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
import logging
import requests

from config import (
    LLM_API_KEY, LLM_BASE_URL, LLM_TIMEOUT,
    BRAND_NAME, BRAND_SLOGAN, BRAND_DESC,
    LLM_MODEL, LLM_TEMPERATURE, LLM_MAX_TOKENS, LLM_MAX_RETRIES,
    WECHAT_TITLE_MAX_LEN, WECHAT_DIGEST_MAX_LEN, SENSITIVE_WORDS
)

logger = logging.getLogger(__name__)

# ==========================================
#  角色设定 (智界洞察社 · 深度科普定制)
# ==========================================
SYSTEM_PROMPT = f"""
# Role
你是「{BRAND_NAME}」的首席内容官兼科技科普作家。
你的使命是：{BRAND_SLOGAN}。
你的定位是：{BRAND_DESC}

# 写作人格画像
你不是一个新闻复读机，你是一个有观点、有温度、有远见的科技思想者。
- 你像一个坐在读者对面的聪明朋友，用咖啡聊天的口吻，把最前沿的 AI 和科技趋势讲透。
- 你擅长"降维类比"：用生活中的例子解释复杂技术。比如用"自助餐 vs 点菜"来解释"通用大模型 vs 垂直模型"。
- 你有自己的观点立场，不做骑墙派。在分析完事实后，你会亮出自己的判断。
- 你的文章有一种"读完之后想转发给同事"的驱动力。

# 写作铁律 (CRITICAL_RULES)
1. 直接输出正文内容。严禁使用代码块（```）包裹。严禁输出任何非正文的交互话术（如"好的""以下是文章"等）。
2. 保留所有 Markdown 结构符号（#，##，**，>）。
3. 文章末尾必须附带引导关注语：**关注「{BRAND_NAME}」，先人一步洞悉未来。**

# 标题 (Title)
- 标题是文章的"第一生产力"。好标题决定了 80% 的打开率。
- 标题必须传递"信息增量"：让读者觉得"这篇文章能告诉我别人不知道的事"。
- 推荐结构：[核心事件]＋[深层解读/反常识角度]，中间用冒号或竖线分割。
- 严禁使用"震惊""突发""速看""重磅"等低质标题党词汇。
- **标题严格控制在 {WECHAT_TITLE_MAX_LEN} 字以内**。

# 文章结构 (Architecture) — 深度叙事逻辑
你的文章应遵循以下逻辑层次，但**严禁在正文中输出"第一幕"、"钩子"、"科普底座"、"纵深"等创作术语**：

1. **引人入胜的开篇**：用反常识事实或场景直接入题，不要加标题，直接用加粗文字或引用开头。
2. **通俗易懂的原理科普**：使用如"技术背后的真相"或"这到底意味着什么"之类的小标题。
3. **多维度的深度拆解**：使用具有洞察力的小标题，如"行业的推倒与重来"、"普通人的生存法则"。
4. **独家观点与预判**：用 > 引用符号包裹核心洞察，体现品牌态度。
5. **互动结语**：引导讨论，不要加"结语"二字。


# 阅读体验 (Reading Experience)
1. **短段落与留白**：每段不超过 3 行（约 60 字）。**段与段之间必须保持至少一个物理空行**。
2. **视觉呼吸感 (Double Spacing)**：在##小标题、>金句引用、以及【此处插入配图】的前后，**必须使用双倍空行**，通过空白建立视觉隔离，让读者有"呼吸"的空间。
3. **金句孤行**：核心洞察或反常识结论，请尽量单独成段（单行成段），并在上下各留一个空行，使其在视觉上极度突出。
4. **视觉节奏**：每 3-5 段必须通过小标题或加粗金句进行视觉切割。
5. **重点加粗**：对核心论点、关键数据、结论进行 **加粗** 处理。


# 输出规范
- 字数：**2500 - 3500 字**。
- 必须包含至少 3 个 ## 级别的小标题。
- 必须包含至少 2 处 > 引用金句。
- 必须包含至少 3 处 【此处插入配图：关键词】。
- 摘要：标题下方提供 60 字左右的摘要，用 > 引用符号包裹。
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
            response = requests.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers=headers,
                json=data,
                timeout=LLM_TIMEOUT
            )
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content']

        except requests.exceptions.Timeout:
            logger.warning("AI 调用超时 (第 %d/%d 次)", attempt, max_retries)
            if attempt < max_retries:
                time.sleep(backoff_base * (2 ** (attempt - 1)))
        except requests.exceptions.HTTPError as e:
            logger.error("AI 返回 HTTP 错误: %s (第 %d/%d 次)", e, attempt, max_retries)
            if attempt < max_retries and getattr(e.response, 'status_code', 500) >= 500:
                time.sleep(backoff_base * (2 ** (attempt - 1)))
        except (KeyError, IndexError) as e:
            logger.error("AI 响应格式异常: %s", e)
            return ""
        except Exception as e:
            logger.error("AI 调用失败: %s (第 %d/%d 次)", e, attempt, max_retries)
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
#  敏感词过滤
# ==========================================
def filter_sensitive(text: str):
    """
    敏感词检测与过滤。
    返回 (过滤后文本, 命中敏感词列表)
    """
    if not SENSITIVE_WORDS:
        return text, []

    hit_words = []
    filtered = text
    for word in SENSITIVE_WORDS:
        if word and word in filtered:
            hit_words.append(word)
            filtered = filtered.replace(word, '*' * len(word))

    return filtered, hit_words


# ==========================================
#  摘要生成
# ==========================================
def generate_digest(topic: str):
    """
    AI 生成微信规范的摘要 (≤120 字)。
    """
    logger.info("  正在为 '%s' 生成微信摘要...", topic)
    prompt = (
        f"请为以下科技话题生成一段微信文章摘要（预告式风格），"
        f"字数严格控制在 {WECHAT_DIGEST_MAX_LEN} 字以内，"
        f"能吸引读者点击阅读，不使用标题党词汇。\n\n话题：{topic}"
    )
    res = call_deepseek(
        prompt,
        system_content=f"你是「{BRAND_NAME}」的编辑。只输出摘要文本，不要加任何前缀。"
    )
    if res and len(res) > WECHAT_DIGEST_MAX_LEN:
        res = res[:WECHAT_DIGEST_MAX_LEN]
    return res.strip() if res else ""


# ==========================================
#  热点筛选（AI 优先级排序）
# ==========================================
def filter_tech_hotspots(topics):
    """从多源热搜中筛选科技热点（人工智能优先）"""
    logger.info("DeepSeek 正在跨平台筛选科技热点（AI 优先）...")
    prompt = (
        "以下是来自多个平台的实时热点资讯：\n" + str(topics) + "\n\n"
        f"你是「{BRAND_NAME}」的选题编辑，你的读者关注 AI 与前沿科技。\n"
        "请按照以下优先级规则，从中筛选出 1-2 条最有深度报道价值的话题：\n\n"
        "【第一优先级 - 必选】人工智能、AI大模型、GPT、DeepSeek、Gemini、Claude、"
        "机器学习、AI芯片、智能体Agent、AIGC、Sora 等 AI 相关话题。\n"
        "【第二优先级 - 备选】半导体、芯片、商业航天、人形机器人、脑机接口、"
        "量子计算、新能源汽车智能驾驶等前沿科技话题。\n\n"
        "规则：\n"
        "1. 如果存在第一优先级话题，必须优先选择，最多选2条。\n"
        "2. 仅当完全没有第一优先级话题时，才从第二优先级中选择。\n"
        "3. 如果两个优先级都没有，请返回'无'。\n"
        "4. 只返回话题名称，用中文逗号隔开。"
    )

    res = call_deepseek(prompt, system_content=f"你是「{BRAND_NAME}」的选题编辑，专注于人工智能与前沿科技领域。")
    if not res or "无" in res:
        logger.info("  当前资讯中无科技/AI相关爆点")
        return []

    result = parse_topic_list(res)
    logger.info("  筛选结果: %s", result)
    return result


# ==========================================
#  文稿创作（深度科普长文）
# ==========================================
def generate_article(topic):
    """针对话题创作符合品牌调性的深度科普长文"""
    logger.info("DeepSeek 正在以「%s」视角创作深度长文...", BRAND_NAME)
    prompt = (
        f"当前话题：{topic}\n\n"
        "请严格按照系统设定的'五幕深度叙事'结构创作全文。\n"
        "特别注意：\n"
        "1. 第二幕'科普底座'是本文核心，必须用通俗类比让零基础读者也能看懂这项技术。\n"
        "2. 第三幕'深度拆解'必须从技术、产业、社会三个维度展开，引用具体数据或案例。\n"
        "3. 第四幕'纵深判断'必须亮出你的独家观点，给出对未来 6-12 个月的预判。\n"
        "4. 全文字数必须在 2500-3500 字之间，不要偷工减料。\n"
        "5. 至少插入 3 个【此处插入配图：关键词】占位符。\n"
        "6. 现在开始创作。"
    )
    article = call_deepseek(prompt)
    if article:
        # 校验字数
        word_count, ok, msg = validate_article_length(article)
        logger.info("  深度长文生成完毕，%s", msg)
    else:
        logger.error("  文稿生成失败")
    return article


# ==========================================
#  关键词简化（配图降级搜索用）
# ==========================================
def simplify_keyword(complex_kw):
    """将复杂短语转化为具备场景感的视觉关键词"""
    logger.info("  正在根据内容深度提炼视觉方向 '%s'...", complex_kw)
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
    logger.info("  视觉导向：'%s'", result)
    return result
