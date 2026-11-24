from core.shared.runtime import WorkflowCancelled
import os
import re
import logging
from config import BRAND_NAME
from daily_knowledge.llm_client import LLMClient
from daily_knowledge.database import get_recent_concepts, record_concept
from daily_knowledge.deduplicator import check_duplicate_with_llm

logger = logging.getLogger(__name__)

def generate_daily_knowledge(domain: str = "人工智能与深度学习", max_retries: int = 3) -> tuple[str, str]:
    """
    生成一篇解耦的“每日小知识”文章。
    内置查重机制与多次重试。
    返回 (文章内容, 提取的概念名称) 以便在发布成功后再入库。
    """
    client = LLMClient()
    
    # 1. 读取系统 Prompt
    prompt_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "prompts",
        "daily_knowledge_skill.md"
    )
    try:
        with open(prompt_path, 'r', encoding='utf-8') as f:
            system_prompt = f.read().replace("{BRAND_NAME}", BRAND_NAME)
    except WorkflowCancelled:
        raise
    except Exception as e:
        logger.error(f"无法读取系统 Prompt: {e}")
        return "", ""
        
    for attempt in range(max_retries):
        logger.info(f"正在生成每日小知识 (尝试 {attempt+1}/{max_retries})，领域: {domain}")
        
        # 2. 获取历史概念（防重复黑名单）
        historical_concepts = get_recent_concepts(limit=50)
        
        user_prompt = f"请为领域【{domain}】生成今天的每日小知识寓言。\n"
        user_prompt += "【排版铁律】：严禁使用任何 LaTeX 数学公式与 $...$ 美元符号！所有变量与表达式必须直接写成纯文本（如写 K 而非 $K$，写 x_i 而非 $x_i$，写 ≥ 而非 \\ge）。\n"
        user_prompt += (
            "【配图要求】在寓言故事与概念解析中分布 2-3 个真实照片占位符。"
            "选取文中可拍摄的实体，填写 2-5 个英文检索词或国际通用专名，例如【此处插入配图：library shelves】。"
            "省略光效、构图和作画指令。\n"
        )
        if historical_concepts:
            user_prompt += "注意，请绝对不要使用以下已经在历史中讲述过的概念：\n"
            user_prompt += ", ".join(historical_concepts) + "\n"
        
        # 3. 调用 LLM 生成文章
        try:
            article = client.generate(system_prompt, user_prompt)
        except WorkflowCancelled:
            raise
        except Exception as e:
            logger.error(f"LLM 生成文章失败: {e}")
            continue
            
        # 4. 解析输出的 [CONCEPT_TAG: xxx]
        match = re.search(r"\[CONCEPT_TAG:\s*(.+?)\]", article)
        if not match:
            logger.warning("大模型未能在文章末尾输出 [CONCEPT_TAG: xxx]，触发重试。")
            continue
            
        concept_name = match.group(1).strip()
        logger.info(f"成功提取生成概念：{concept_name}")
        
        # 5. 调用大模型进行严格的语义查重
        is_duplicate = check_duplicate_with_llm(concept_name, historical_concepts)
        if is_duplicate:
            logger.warning(f"概念 '{concept_name}' 与历史概念存在语义重复，已丢弃并准备重试。")
            continue
            
        # 6. 验证通过，清理末尾的机器标签但不马上入库（交由外部在发布成功后入库）
        clean_article = re.sub(r"\[CONCEPT_TAG:\s*(.+?)\]", "", article).strip()
        logger.info(f"概念 '{concept_name}' 查重通过，等待发布成功后入库。")
        
        return clean_article, concept_name
        
    logger.error("每日小知识生成失败：超过最大重试次数，无法生成独特概念。")
    return "", ""
