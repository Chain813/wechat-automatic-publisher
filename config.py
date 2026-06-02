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

# 3. Gemini Vision (图片智能评分，选填)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# 4. 企业微信机器人 (选填，留空则跳过通知)
QYWECHAT_WEBHOOK = os.getenv("QYWECHAT_WEBHOOK", "")

# 5. 品牌信息
BRAND_NAME = "智界洞察社"
BRAND_SLOGAN = "在政策与技术的交叉点，洞见未来格局"
BRAND_DESC = "聚焦时政与科技的深度交汇——从大国博弈到技术封锁，从产业政策到 AI 监管，将复杂的科技政治局势转化为可感知的趋势洞见。"
ARTICLE_AUTHOR = "智界洞察社"

# 6. 超时设置 (秒)
LLM_TIMEOUT = 180
IMAGE_TIMEOUT = 15
WECHAT_API_TIMEOUT = 30
HOTSPOT_CACHE_TTL_SECONDS = int(os.getenv("HOTSPOT_CACHE_TTL_SECONDS", "60"))
HTTP_RETRY_TOTAL = int(os.getenv("HTTP_RETRY_TOTAL", "3"))
HTTP_RETRY_BACKOFF = float(os.getenv("HTTP_RETRY_BACKOFF", "0.8"))

# 7. LLM 模型参数 (可配置)
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-pro")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.75"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "8192"))
LLM_MAX_RETRIES = 3          # API 调用最大重试次数

# 8. 微信发布规范限制
WECHAT_TITLE_MAX_LEN = 64    # 标题最大字数
WECHAT_DIGEST_MAX_LEN = 120  # 摘要最大字数 (微信限制 120 字)
WECHAT_DRAFT_SCAN_COUNT = int(os.getenv("WECHAT_DRAFT_SCAN_COUNT", "50"))
TITLE_DUPLICATE_RATIO = int(float(os.getenv("TITLE_DUPLICATE_RATIO", "88")))

# 9. 新闻采集源配置
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

# 10. 热点优先过滤类别 (按顺序匹配，三梯队优先级)
#    第一梯队：AI + 时政交叉（最高优先）
#    第二梯队：硬核 AI / 前沿科技突破
#    第三梯队：金融 + 时政
FILTER_CATEGORIES = [
    # ===== 第一梯队：AI + 时政交叉 (核心命脉) =====
    "AI监管", "AI治理", "AI安全", "AI军事", "AI武器",
    "科技制裁", "芯片封锁", "技术封锁", "出口管制", "实体清单",
    "数字主权", "数据安全", "网络安全", "数字治理",
    "科技政策", "新质生产力", "产业政策", "科技自主", "国产替代",
    "中美科技", "科技战", "中美博弈", "技术脱钩",
    # 大国博弈与地缘科技
    "华为", "台积电", "ASML", "英伟达", "NVIDIA",
    "SpaceX", "星链", "北斗", "嫦娥",

    # ===== 第二梯队：硬核 AI / 前沿科技突破 =====
    "AI", "人工智能", "大模型", "GPT", "DeepSeek", "Gemini", "Claude",
    "开源模型", "AGI", "多模态", "AI Agent", "具身智能",
    "科技", "半导体", "芯片", "机器人", "人形机器人",
    "商业航天", "量子计算", "智能驾驶", "脑机接口",
    "算力", "数据中心", "AI芯片", "GPU",

    # ===== 第三梯队：金融 + 时政 =====
    "贸易战", "关税", "数字经济",
    "美联储", "加息", "降息", "汇率", "人民币",
    "数字货币", "央行数字货币", "CBDC", "加密货币",
    "金融监管", "资本市场", "IPO", "风投", "融资",
    "硅谷", "创投", "独角兽",
]

# 11. 微信图片规格
WECHAT_COVER_WIDTH = 900
WECHAT_COVER_HEIGHT = 383
WECHAT_BODY_WIDTH = 900
WECHAT_BODY_HEIGHT = 500
WECHAT_BODY_MAX_MB = 2

# 12. 本地 Stable Diffusion 配置
SD_ENABLED = os.getenv("SD_ENABLED", "True").lower() == "true"
SD_API_URL = os.getenv("SD_API_URL", "http://127.0.0.1:7860")
SD_TIMEOUT = int(os.getenv("SD_TIMEOUT", "120"))        # 单次生图超时秒数
SD_STEPS = int(os.getenv("SD_STEPS", "15"))              # 采样步数（15 兼顾速度与质量）
SD_MAX_RETRIES = int(os.getenv("SD_MAX_RETRIES", "2"))   # 最大重试次数（不含首次）

# 13. Ollama 本地视觉模型配置
OLLAMA_DEFAULT_MODEL = os.getenv("OLLAMA_DEFAULT_MODEL", "gemma4:e2b-it-q4_K_M")
OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "gemma3:4b")

# 14. 微信敏感词列表 (部分示例，根据实际情况补充)
SENSITIVE_WORDS = []  # 留空则跳过敏感词过滤

# 15. 工作流参数
MAX_TOPICS_PER_RUN = int(os.getenv("MAX_TOPICS_PER_RUN", "3"))      # 每次运行最多发布文章数
MAX_TOPIC_CANDIDATES = int(os.getenv("MAX_TOPIC_CANDIDATES", "5"))  # 候选话题上限
HOTSPOTS_HISTORY_FILE = os.getenv("HOTSPOTS_HISTORY_FILE", "hotspots_history.json")
GITHUB_HISTORY_FILE = os.getenv("GITHUB_HISTORY_FILE", "github_history.json")
ASSET_RETENTION_DAYS = int(os.getenv("ASSET_RETENTION_DAYS", "5"))  # 素材保留天数
HISTORY_MAX_ENTRIES = int(os.getenv("HISTORY_MAX_ENTRIES", "2000")) # 历史记录最大条数

# 16. GitHub 搜索配置
GITHUB_SEARCH_STARS_THRESHOLDS = [200, 500, 1000, 5000, 10000]  # 星数阈值梯度
GITHUB_SEARCH_LANGUAGES = ["Python", "JavaScript", "TypeScript", "Go", "Rust", "Java", "C++"]

# 17. 专题固定封面
GITHUB_FIXED_COVER = os.path.join("static", "images", "github_fixed_cover.png")
