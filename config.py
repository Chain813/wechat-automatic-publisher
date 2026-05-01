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
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")

# 3. 企业微信机器人 (选填，留空则跳过通知)
QYWECHAT_WEBHOOK = os.getenv("QYWECHAT_WEBHOOK", "")

# 4. 品牌信息
BRAND_NAME = "智界洞察社"
BRAND_SLOGAN = "在政策与技术的交叉点，洞见未来格局"
BRAND_DESC = "聚焦时政与科技的深度交汇——从大国博弈到技术封锁，从产业政策到 AI 监管，将复杂的科技政治局势转化为可感知的趋势洞见。"
ARTICLE_AUTHOR = "智界洞察社"

# 5. 超时设置 (秒)
LLM_TIMEOUT = 60
IMAGE_TIMEOUT = 15
WECHAT_API_TIMEOUT = 30
HOTSPOT_CACHE_TTL_SECONDS = int(os.getenv("HOTSPOT_CACHE_TTL_SECONDS", "600"))
HTTP_RETRY_TOTAL = int(os.getenv("HTTP_RETRY_TOTAL", "3"))
HTTP_RETRY_BACKOFF = float(os.getenv("HTTP_RETRY_BACKOFF", "0.8"))

# 6. LLM 模型参数 (可配置)
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.75"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))
LLM_MAX_RETRIES = 3          # API 调用最大重试次数

# 7. 微信发布规范限制
WECHAT_TITLE_MAX_LEN = 64    # 标题最大字数
WECHAT_DIGEST_MAX_LEN = 120  # 摘要最大字数 (微信限制 120 字)
WECHAT_DRAFT_SCAN_COUNT = int(os.getenv("WECHAT_DRAFT_SCAN_COUNT", "50"))
TITLE_DUPLICATE_RATIO = int(float(os.getenv("TITLE_DUPLICATE_RATIO", "88")))

# 8. 新闻采集源配置
NEWS_SOURCES = ["weibo", "ithome", "36kr", "baidu", "zhihu", "csdn", "rss", "politics", "toutiao", "thepaper", "huxiu", "douyin"]
NEWS_FRESHNESS_HOURS = 24     # 仅保留 N 小时内的热点 (0 = 不限)
NEWS_MAX_PER_SOURCE = 15      # 每源最大条数

# 60s API 配置（用于微博/知乎/抖音/头条，比直接爬更稳定）
API_60S_BASE = "https://60s.viki.moe/v2"

# 自定义 RSS 订阅源 (直接源，不依赖 rsshub)
RSS_FEEDS = [
    "https://www.ithome.com/rss/",                      # IT之家 RSS (直接)
    "https://sspai.com/feed",                           # 少数派
    "https://36kr.com/feed",                            # 36氪 RSS (直接)
]

# 9. 热点优先过滤类别 (按顺序匹配)
#    第一梯队：时政+科技交叉话题
#    第二梯队：纯科技/纯时政高价值话题
FILTER_CATEGORIES = [
    # 时政科技交叉 (核心)
    "AI监管", "科技制裁", "芯片封锁", "技术封锁", "出口管制",
    "数字主权", "数据安全", "网络安全", "数字经济", "数字治理",
    "科技政策", "新质生产力", "产业政策", "科技自主", "国产替代",
    "中美科技", "科技战", "贸易战", "关税", "实体清单",
    # AI 与前沿技术
    "AI", "人工智能", "大模型", "GPT", "DeepSeek", "Gemini", "Claude",
    "科技", "半导体", "芯片", "机器人", "人形机器人",
    "商业航天", "量子计算", "智能驾驶", "脑机接口",
    # 大国博弈与地缘科技
    "华为", "台积电", "ASML", "英伟达", "NVIDIA",
    "SpaceX", "星链", "北斗", "嫦娥",
]

# 10. 图片采集参数
IMAGE_DEFAULT_CANDIDATES = 5  # 每次搜索下载候选图数量
IMAGE_RETRY_MAX = 3           # 单张下载最大重试次数

# 11. 微信敏感词列表 (部分示例，根据实际情况补充)
SENSITIVE_WORDS = []  # 留空则跳过敏感词过滤
