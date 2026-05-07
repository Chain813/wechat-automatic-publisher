[English](README_EN.md) | 中文

# AutoWeChat: 全自动 AI 内容工厂

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.8+](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![DeepSeek: Powered](https://img.shields.io/badge/LLM-DeepSeek-green.svg)](https://api.deepseek.com)
[![Gemini Vision](https://img.shields.io/badge/Vision-Gemini%20Flash-orange.svg)](https://ai.google.dev/)

微信公众号全自动内容生产与发布系统。集成实时热点监控、AI 选题、深度文章创作、智能配图、一键发布。

---

## 功能特性

**多源热点聚合** — 12 平台并行采集（微博、IT之家、36氪、百度、知乎、CSDN、RSS、时政、头条、澎湃、虎嗅、抖音）。源级健康监控，自动降级。

**AI 深度创作** — DeepSeek 驱动 2500-3500 字深度分析文章。内置敏感词过滤、标题去重（4 策略）、结构质量检查。

**智能配图** — 多源图片检索（Pollinations AI 生图 → Pexels 免费图库 → Bing/百度爬取）。6 维评分（分辨率、宽高比、清晰度、文字密度、色彩丰富度、文件大小）。感知哈希去重。微信封面/正文双模式评分。**Gemini Vision + Ollama 本地视觉模型** AI 图片评估，自动降级。

**高效并行架构** — 图片下载+上传合并为并行流水线。文章资产生成与摘要生成并行。多源热点并发扫描。

**安全合规** — 4 策略标题去重（精确/模糊/关键词/AI 语义）。跨话题内部去重。草稿箱审计防重。

**Web 管理界面** — Flask 暗色主题仪表盘，一键启停任务、实时日志流、文章历史、源健康监控、在线配置。

**企业微信集成** — 发布后自动推送通知到企微群机器人。

---

## 技术栈

- **语言**: Python 3.8+
- **LLM**: DeepSeek Chat / Reasoner
- **视觉 AI**: Gemini Flash 2.0（云端）+ Gemma 3 4B via Ollama（本地）
- **GitHub 工具链**: PyGithub（API）、rich（目录树渲染）、diagrams（架构图生成）、carbon（代码截图）
- **爬虫**: Requests, BeautifulSoup4, Selenium（隐身模式）, icrawler
- **图片**: Pillow, numpy, Pollinations.ai API, Pexels API
- **缓存/匹配**: requests-cache, RapidFuzz
- **日志**: Loguru
- **Web**: Flask
- **API**: 微信公众号草稿箱 API

---

## 项目结构

```
wechat_auto_publish/
├── main.py                    # CLI 入口（支持 --task hotspots/github）
├── webui.py                   # Flask Web 管理界面 (v3.0)
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
│   │   ├── collector.py       # GitHub Trending（PyGithub + rich 目录树 + diagrams 架构图 + carbon 代码截图）
│   │   ├── processor.py       # GitHub 文章生成（微信排版优化）
│   │   └── workflow.py        # GitHub 发布流水线
│   └── shared/
│       ├── llm.py             # DeepSeek API 封装
│       ├── publisher.py       # 微信 API + 标题去重
│       ├── article_utils.py   # Markdown→HTML + 配图嵌入
│       └── runtime.py         # 日志初始化
├── utils/
│   ├── image_handler.py       # 多源图片检索 + AI 生图
│   ├── image_filter.py        # 图片评分 / OCR / pHash 去重 / 视觉 AI
│   ├── http_client.py         # HTTP 会话 + 缓存 + 重试
│   └── spider.py              # Selenium 浏览器启动器
├── static/                    # Web UI 前端资源
├── templates/                 # Web UI 模板
└── assets/                    # 自动下载的图片资源
```

---

## 快速开始

### 1. 克隆

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

或双击 `run.bat` 自动安装。

### 3. 配置

复制 `.env.example` 为 `.env`，填入：

```env
# 必填
WECHAT_APP_ID="你的微信AppID"
WECHAT_APP_SECRET="你的微信AppSecret"
LLM_API_KEY="你的DeepSeek API Key"

# 可选：GitHub API（获取 Trending 项目，提高速率限制）
GITHUB_TOKEN="你的GitHub Personal Access Token"

# 可选：Gemini Vision（云端图片评估）
GEMINI_API_KEY="你的Gemini API Key"

# 可选：企微群机器人通知
QYWECHAT_WEBHOOK=""

# 可选：Ollama 本地视觉模型
OLLAMA_DEFAULT_MODEL="gemma4:e2b-it-q4_K_M"
OLLAMA_VISION_MODEL="gemma3:4b"

# 可选：Pexels 免费图库
PEXELS_API_KEY=""
```

### 4. 运行

**CLI 模式：**
```bash
python main.py                    # 热点发布（默认）
python main.py --task github      # GitHub Trending 发布
```

**Web 模式：**
```bash
python webui.py
```
访问 http://127.0.0.1:5000

---

## Web UI (v3.0)

暗色主题仪表盘：

| 页面 | 功能 |
|------|------|
| **控制台** | 一键启停、实时日志流、任务类型选择 |
| **历史记录** | 按日期分组的已发布文章 |
| **数据源** | 12 源健康状态（绿/黄/红卡片） |
| **设置** | API Key 配置，密钥脱敏显示 |

---

## 配图策略

### 热点文章（AI 生图优先）

1. **Pollinations.ai AI 生图** — 时政事件概念图（新闻照片无法匹配具体事件）
2. **Pexels 免费图库** — 高质量版权免费图片
3. **Bing 图片搜索** — 大尺寸横版图过滤
4. **百度图片搜索** — 国内兜底
5. **本地默认图** — 最终兜底

### GitHub 文章（多层兜底）

1. **README 图片** — 架构图、演示截图（按相关性评分）
2. **目录树截图** — rich 库渲染为样式化 PNG
3. **架构图** — diagrams 库根据技术栈自动生成
4. **代码截图** — carbon API 从项目入口文件生成
5. **关键词搜索** — 网页图片搜索最终兜底

每张图片经过 6 维评分，可选视觉 AI 二次评估：

```
CV 6 维评分 → Top 3 候选 → 视觉 AI 二次评估
                     |
               Gemini 可用？ → Gemini Flash 2.0（60% 权重）
                     | 否
               Ollama 可用？ → Gemma 3 4B 本地（60% 权重）
                     | 否
               纯 CV 评分兜底
```

---

## 核心配置

在 `config.py` 或 `.env` 中调整：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `BRAND_NAME` | 品牌名称 | AutoWeChat |
| `NEWS_SOURCES` | 启用的源 | 12 平台 |
| `FILTER_CATEGORIES` | 优先过滤关键词 | 79 个 |
| `LLM_MODEL` | LLM 模型 | deepseek-chat |
| `LLM_TEMPERATURE` | 生成随机性 | 0.75 |
| `IMAGE_DEFAULT_CANDIDATES` | 每次搜索候选图片数 | 5 |
| `OLLAMA_VISION_MODEL` | 本地视觉模型 | gemma3:4b |
| `GITHUB_TOKEN` | GitHub API Token（可选，提高速率限制） | 匿名 (60次/小时) |

---

## 环境要求

- Python 3.8+
- [Graphviz](https://graphviz.org/download/)（架构图生成，需添加到 PATH）
- Chrome 浏览器（Selenium 备用爬取）
- 可选：[Ollama](https://ollama.com) 本地视觉 AI
- 可选：EasyOCR 文字检测（需 PyTorch ~2GB）

---

## 许可证

[MIT License](LICENSE)

---

## 免责声明

本工具仅供技术研究和内容创作辅助。请遵守微信公众号运营规范及相关法律法规。AI 生成内容需人工审核后发布。
