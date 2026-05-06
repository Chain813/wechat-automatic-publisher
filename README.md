# AutoWeChat: AI 内容工厂

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.8+](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![DeepSeek: Powered](https://img.shields.io/badge/LLM-DeepSeek-green.svg)](https://api.deepseek.com)

微信公众号全自动化 AI 内容生产与发布系统。集成全网热点监控、AI 选题、深度长文创作、智能配图、一键发布等全流程能力。

---

## 核心特性

**全网热点聚合** — 并行抓取微博、IT之家、36氪、百度、知乎、CSDN、澎湃、虎嗅、抖音等 12 个平台的实时热搜，源级健康监控 + 自动降级。

**AI 深度创作** — 基于 DeepSeek 模型生成 2500-3500 字的深度分析文章，内置敏感词过滤、标题党校验、结构化质检。

**智能配图引擎** — 多源图片获取（Pollinations AI 生图 → Pexels 免费图库 → Bing/百度爬虫），分辨率/色彩/文字密度多维评分，感知哈希去重，微信尺寸自动适配。

**高效并行架构** — 图片下载+上传合并为并行 pipeline，文章资产生成与摘要生成并行执行，多源热点并发扫描。

**安全合规** — 4 策略标题查重（精确/模糊/关键词/AI 语义），topic 间内部去重，草稿箱审计防重。

**Web 管理界面** — Flask 驱动的暗色主题 Dashboard，支持一键启动任务、实时日志流、在线配置。

**企业微信集成** — 发布成功后自动推送通知至企业微信群机器人。

---

## 技术栈

- **语言**: Python 3.8+
- **LLM**: DeepSeek Chat
- **爬虫**: Requests, BeautifulSoup4, Selenium (Stealth Mode), icrawler
- **图像**: Pillow, numpy, Pollinations.ai API, Pexels API
- **缓存/匹配**: requests-cache, RapidFuzz
- **日志**: Loguru
- **Web**: Flask
- **API**: 微信公众号官方接口 (Draft API)

---

## 项目结构

```
wechat_auto_publish/
├── main.py                    # CLI 入口
├── webui.py                   # Flask Web 管理界面
├── config.py                  # 全局配置中心
├── requirements.txt           # 依赖清单
├── run.bat                    # CLI 启动脚本
├── run_gui.bat                # Web UI 启动脚本
├── core/
│   ├── engine.py              # 工作流调度器
│   ├── hotspots/
│   │   ├── collector.py       # 12 源热点采集引擎
│   │   ├── processor.py       # AI 文章生成引擎
│   │   └── workflow.py        # 热点发布流水线
│   ├── github/
│   │   ├── collector.py       # GitHub Trending 采集
│   │   ├── processor.py       # GitHub 文章生成
│   │   └── workflow.py        # GitHub 发布流水线
│   └── shared/
│       ├── llm.py             # DeepSeek API 封装
│       ├── publisher.py       # 微信 API + 标题查重
│       ├── article_utils.py   # Markdown→HTML + 配图嵌入
│       └── runtime.py         # 日志初始化
├── utils/
│   ├── image_handler.py       # 多源图片检索 + AI 生图
│   ├── image_filter.py        # 图片评分/OCR/pHash 去重
│   ├── http_client.py         # HTTP 会话 + 缓存 + 重试
│   └── spider.py              # Selenium 浏览器启动器
├── static/                    # Web UI 前端资源
├── templates/                 # Web UI 页面模板
└── assets/                    # 自动下载的图片素材
```

---

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/Chain813/wechat-automatic-publisher.git
cd wechat-automatic-publisher
```

### 2. 安装依赖

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

或直接双击 `run.bat` 自动完成环境搭建。

### 3. 配置密钥

复制 `.env.example` 为 `.env`，填入：

```env
WECHAT_APP_ID="你的微信AppID"
WECHAT_APP_SECRET="你的微信AppSecret"
LLM_API_KEY="你的DeepSeek_API_Key"
QYWECHAT_WEBHOOK="（可选）企业微信机器人Webhook"
```

### 4. 运行

- **CLI 模式**: `python main.py` 或双击 `run.bat`
- **Web 模式**: `python webui.py` 或双击 `run_gui.bat`，访问 http://127.0.0.1:5000

---

## 核心配置

在 `config.py` 中可调整：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `BRAND_NAME` | 品牌名称 | 智界洞察社 |
| `NEWS_SOURCES` | 启用的采集源 | 12 个平台 |
| `FILTER_CATEGORIES` | AI 优先筛选关键词 | 79 个时政科技词 |
| `LLM_MODEL` | LLM 模型 | deepseek-chat |
| `LLM_TEMPERATURE` | 创作随机度 | 0.75 |
| `MAX_TOPICS_PER_RUN` | 每次最大发布数 | 3 |
| `IMAGE_DEFAULT_CANDIDATES` | 图片候选数 | 5 |

---

## 配图策略

系统按优先级依次尝试：

1. **Pexels 免费图库** — 高质量免版权图片
2. **Pollinations.ai AI 生图** — 根据文章关键词生成匹配图片，免费无需 API Key
3. **Bing 图片搜索** — 大图+横版筛选
4. **百度图片搜索** — 国内源兜底
5. **本地默认图** — 最终兜底

每张图片经过分辨率、宽高比、清晰度、文字密度、色彩丰富度、文件大小 6 维评分，择优录取。

---

## 开源协议

本项目采用 [MIT License](LICENSE) 开源协议。

---

## 免责声明

本工具仅用于技术研究与内容创作辅助，请务必遵守微信公众号官方运营规范及相关法律法规。使用本系统生成的 AI 内容建议经过人工最终审核后发布。
