from core.shared.llm import call_deepseek_with_retry


class LLMClient:
    def generate(self, system_prompt, user_prompt, temperature=None):
        return call_deepseek_with_retry(user_prompt, system_content=system_prompt, temperature=temperature)
