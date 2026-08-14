import requests
import json
import logging
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TEMPERATURE, LLM_MAX_TOKENS, LLM_MAX_RETRIES

logger = logging.getLogger(__name__)

class LLMClient:
    """
    独立于核心项目的 LLM 调用客户端，专注于“每日小知识”模块的文本生成。
    """
    def __init__(self):
        self.api_key = LLM_API_KEY
        self.base_url = LLM_BASE_URL
        self.model = LLM_MODEL
        
    def generate(self, system_prompt: str, user_prompt: str, temperature: float = None) -> str:
        """
        调用 LLM 接口生成文本内容
        """
        if temperature is None:
            temperature = LLM_TEMPERATURE
            
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        # 兼容 DeepSeek / OpenAI 格式的 endpoint
        endpoint = f"{self.base_url.rstrip('/')}/chat/completions"
        if "api.deepseek.com" not in self.base_url and "api.openai.com" not in self.base_url:
            # 根据实际基建情况，可在这里做特定适配
            pass
            
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temperature,
            "max_tokens": LLM_MAX_TOKENS
        }
        
        for attempt in range(LLM_MAX_RETRIES):
            try:
                response = requests.post(endpoint, headers=headers, json=payload, timeout=120)
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
            except Exception as e:
                logger.warning(f"LLM 每日小知识生成失败 (尝试 {attempt+1}/{LLM_MAX_RETRIES}): {e}")
                if attempt == LLM_MAX_RETRIES - 1:
                    raise Exception(f"每日小知识模块 LLM 生成最终失败: {e}")
        return ""
