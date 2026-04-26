# ==========================================
#  核心配置中心 (AutoWeChat v2.0)
# ==========================================

import os
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

# 1. 微信公众号配置
WECHAT_APP_ID = os.getenv("WECHAT_APP_ID", "")
WECHAT_APP_SECRET = os.getenv("WECHAT_APP_SECRET", "")

# 2. AI 配置 (DeepSeek)
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = "https://api.deepseek.com"

# 3. 企业微信机器人 (选填，留空则跳过通知)
QYWECHAT_WEBHOOK = os.getenv("QYWECHAT_WEBHOOK", "")

# 4. 品牌信息
BRAND_NAME = "智界洞察社"
BRAND_SLOGAN = "为你提供 AI 时代的生存与进化指南"
BRAND_DESC = "深度解析全球科技热点，将复杂的 AI 趋势转化为可感知的行业洞见，助你先人一步洞悉未来。"
ARTICLE_AUTHOR = "智界洞察社"

# 5. 超时设置 (秒)
LLM_TIMEOUT = 60
IMAGE_TIMEOUT = 15
WECHAT_API_TIMEOUT = 30
HOTSPOT_CACHE_TTL_SECONDS = int(os.getenv("HOTSPOT_CACHE_TTL_SECONDS", "600"))
HTTP_RETRY_TOTAL = int(os.getenv("HTTP_RETRY_TOTAL", "3"))
HTTP_RETRY_BACKOFF = float(os.getenv("HTTP_RETRY_BACKOFF", "0.8"))

# 6. LLM 模型参数 (可配置)
LLM_MODEL = "deepseek-chat"
LLM_TEMPERATURE = 0.75
LLM_MAX_TOKENS = 4096
LLM_MAX_RETRIES = 3          # API 调用最大重试次数

# 7. 微信发布规范限制
WECHAT_TITLE_MAX_LEN = 64    # 标题最大字数
WECHAT_DIGEST_MAX_LEN = 120  # 摘要最大字数 (微信限制 120 字)
WECHAT_DRAFT_SCAN_COUNT = int(os.getenv("WECHAT_DRAFT_SCAN_COUNT", "50"))
TITLE_DUPLICATE_RATIO = int(os.getenv("TITLE_DUPLICATE_RATIO", "88"))

# 8. 新闻采集源配置
NEWS_SOURCES = ["weibo", "ithome", "36kr", "baidu"]  # 启用的采集源
NEWS_FRESHNESS_HOURS = 24     # 仅保留 N 小时内的热点 (0 = 不限)
NEWS_MAX_PER_SOURCE = 15      # 每源最大条数

# 9. 热点优先过滤类别 (按顺序匹配)
FILTER_CATEGORIES = ["AI", "人工智能", "大模型", "GPT", "DeepSeek",
                     "科技", "半导体", "芯片", "机器人", "人形机器人",
                     "商业航天", "量子计算", "智能驾驶", "脑机接口"]

# 10. 图片采集参数
IMAGE_DEFAULT_CANDIDATES = 5  # 每次搜索下载候选图数量
IMAGE_RETRY_MAX = 3           # 单张下载最大重试次数

# 11. 微信敏感词列表 (部分示例，根据实际情况补充)
SENSITIVE_WORDS = []  # 留空则跳过敏感词过滤
