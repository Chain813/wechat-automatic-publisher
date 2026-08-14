import json
from daily_knowledge.llm_client import LLMClient
from daily_knowledge.database import get_recent_concepts

def check_duplicate_with_llm(new_concept: str, historical_concepts: list[str]) -> bool:
    """
    使用大语言模型进行高精度的语义查重。
    判断新生成的概念是否在历史记录中出现过（即使字面不同，但核心语义一致也算重复）。
    返回 True 表示重复，False 表示没有重复。
    """
    if not historical_concepts:
        return False
        
    client = LLMClient()
    
    system_prompt = """
    你是一个严谨的技术概念查重系统。
    你的任务是判断给定的【新概念】是否与【历史概念列表】中的任何一个概念在技术语义上高度重合或完全等价。
    例如：“自注意力机制”和“Self-Attention”属于重合；“RNN”和“循环神经网络”属于重合。
    
    你必须以 JSON 格式输出你的判断结果。
    格式要求：
    {
        "is_duplicate": true或false,
        "reason": "简短的解释原因，如果不重复则留空"
    }
    绝不要输出 JSON 以外的任何文本内容。
    """
    
    user_prompt = f"""
    历史概念列表：
    {json.dumps(historical_concepts, ensure_ascii=False)}
    
    新概念：
    {new_concept}
    
    请判断该新概念是否与历史概念重复。
    """
    
    try:
        # 查重属于简单分类任务，可以将温度调低以确保结果稳定
        response = client.generate(system_prompt, user_prompt, temperature=0.1)
        
        # 提取 JSON（处理模型可能返回的 ```json 包裹）
        response_clean = response.strip()
        if response_clean.startswith("```json"):
            response_clean = response_clean[7:]
        if response_clean.endswith("```"):
            response_clean = response_clean[:-3]
            
        result = json.loads(response_clean.strip())
        return result.get("is_duplicate", False)
        
    except Exception as e:
        # 如果 LLM 调用或解析失败，降级为字面量匹配
        print(f"语义查重解析失败，降级为字面量查重: {e}")
        return new_concept in historical_concepts
