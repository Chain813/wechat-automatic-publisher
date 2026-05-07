[English](README_EN.md) | 中文

# AutoWeChat: 全自动 AI 内容工厂

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.8+](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![DeepSeek: Powered](https://img.shields.io/badge/LLM-DeepSeek-green.svg)](https://api.deepseek.com)
[![Gemini Vision](https://img.shields.io/badge/Vision-Gemini%20Flash-orange.svg)](https://ai.google.dev/)

微信公众号全自动内容生产与发布系统。集成实时热点监控、AI 选题、深度文章创作、智能配图、一键发布。

---

## 目录

- [功能特性](#功能特性)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
- [Web 管理界面](#web-管理界面)
- [配图策略](#配图策略)
- [核心配置](#核心配置)
- [名词解释](GLOSSARY.md)
- [环境要求](#环境要求)
- [许可证](#许可证)
- [免责声明](#免责声明)

---

## 功能特性

### 多源热点聚合

12 个平台并行采集实时热点资讯：

| 平台 | 类型 | 说明 |
|------|------|------|
| 微博热搜 | 社交媒体 | 实时热搜榜，覆盖全网热点 |
| IT之家 | 科技资讯 | 国内头部科技媒体 |
| 36氪 | 创投科技 | 创业投资与科技前沿 |
| 百度热搜 | 搜索引擎 | 基于搜索量的热点排行 |
| 知乎热榜 | 问答社区 | 深度讨论型热点 |
| CSDN | 开发者社区 | 技术开发者聚集地 |
| RSS 订阅 | 信息聚合 | 支持自定义 RSS 源 |
| 时政新闻 | 新闻媒体 | 时政要闻聚合 |
| 今日头条 | 资讯平台 | 算法推荐热点 |
| 澎湃新闻 | 新闻媒体 | 深度新闻报道 |
| 虎嗅 | 商业媒体 | 商业科技深度分析 |
| 抖音热点 | 短视频 | 短视频平台热点趋势 |

每个数据源独立健康监控（绿/黄/红状态），故障时自动降级，不影响其他源。

### AI 深度创作

基于 DeepSeek 大语言模型生成 2500-3500 字深度分析文章：

- **5 段式结构**：开篇切入 → 多角度分析 → 技术与产业深挖 → 预判与观点 → 互动收尾
- **敏感词过滤**：自动检测并过滤敏感词汇
- **标题去重**：4 种策略防止重复发布（精确匹配/模糊匹配/关键词匹配/AI 语义匹配）
- **结构质量检查**：验证标题数、引用数、配图数是否达标
- **自动补全**：配图不足时自动插入占位符

### 智能配图

多源图片检索 + AI 生成，自动为文章匹配最佳配图：

- **6 维评分体系**：从分辨率、宽高比、清晰度、文字密度、色彩丰富度、文件大小 6 个维度对候选图片打分
- **感知哈希去重**：使用 pHash（感知哈希）算法检测相似图片，避免重复配图
- **微信尺寸适配**：自动裁剪为微信推荐尺寸（封面 900×383，正文 900×500）
- **视觉 AI 二次评估**：候选图片经 Gemini Vision（云端）或 Ollama（本地）AI 模型二次评估，选出最佳

### 高效并行架构

- 图片下载与上传合并为并行流水线（ThreadPoolExecutor）
- 文章资产生成与摘要生成并行执行
- 多源热点并发扫描
- 多篇文章并行发布

### 安全合规

- **4 策略标题去重**：精确匹配 → 模糊匹配（RapidFuzz）→ 关键词匹配 → AI 语义匹配
- **跨话题内部去重**：同一批次内的相似话题自动去重
- **草稿箱审计**：发布前与微信草稿箱已有文章比对，防止重复

### Web 管理界面

Flask 暗色主题仪表盘（v3.0）：

| 页面 | 功能说明 |
|------|---------|
| **控制台** | 一键启停任务、实时日志流、任务类型选择（热点/GitHub） |
| **历史记录** | 按日期分组的已发布文章列表 |
| **数据源** | 12 个数据源的健康状态卡片（绿=正常/黄=告警/红=故障） |
| **设置** | API Key 在线配置，密钥脱敏显示 |

### 企业微信集成

发布成功后自动推送通知到企业微信群机器人，内容包含品牌名和文章标题。

---

## 技术栈

| 类别 | 技术 | 用途 |
|------|------|------|
| **语言** | Python 3.8+ | 主开发语言 |
| **LLM** | DeepSeek Chat / Reasoner | 文章生成、选题筛选、摘要生成 |
| **视觉 AI** | Gemini Flash 2.0 + Gemma 3 4B | 图片质量 AI 评估（云端/本地双通道） |
| **GitHub 工具链** | PyGithub | GitHub API 封装，获取 Trending 项目、仓库元数据 |
| | rich | Python 富文本库，渲染项目目录树为高质量 PNG 图片 |
| | diagrams | Python 架构图生成库，根据技术栈自动生成项目架构图 |
| | carbon | 代码截图服务，将代码片段渲染为精美截图 |
| **爬虫** | Requests | HTTP 请求库 |
| | BeautifulSoup4 | HTML 解析库 |
| | Selenium（隐身模式） | 浏览器自动化，用于反爬严格的网站 |
| | icrawler | 图片爬虫框架（Bing/百度图片搜索） |
| **图片处理** | Pillow | Python 图片处理库，裁剪/缩放/格式转换 |
| | numpy | 数值计算，用于图片评分算法 |
| | Pollinations.ai | 免费 AI 生图 API，无需 API Key |
| | Pexels | 免费高质量图库 API |
| **缓存/匹配** | requests-cache | HTTP 请求缓存，减少重复请求 |
| | RapidFuzz | 高性能模糊字符串匹配库 |
| **日志** | Loguru | Python 日志库 |
| **Web** | Flask | 轻量级 Web 框架 |
| **API** | 微信公众号草稿箱 API | 文章发布接口 |

---

## 项目结构

```
wechat_auto_publish/
├── main.py                    # CLI 入口，支持 --task hotspots/github 参数
├── webui.py                   # Flask Web 管理界面，提供暗色主题仪表盘
├── config.py                  # 全局配置中心，集中管理所有可调参数
├── .env.example               # 环境变量模板
├── requirements.txt           # Python 依赖清单
├── run.bat                    # Windows CLI 一键启动脚本
├── run_gui.bat                # Windows Web UI 一键启动脚本
│
├── core/                      # 核心业务逻辑
│   ├── engine.py              # 工作流调度器，根据任务类型分发到对应工作流
│   │
│   ├── hotspots/              # 热点文章模块
│   │   ├── collector.py       # 12 源热点采集引擎，并行抓取各平台热点
│   │   ├── processor.py       # AI 文章生成引擎，包含 SYSTEM_PROMPT 定义
│   │   └── workflow.py        # 热点发布完整流水线（采集→筛选→创作→配图→发布）
│   │
│   ├── github/                # GitHub Trending 模块
│   │   ├── collector.py       # GitHub 采集引擎（PyGithub API + 目录树 + 架构图 + 代码截图）
│   │   ├── processor.py       # GitHub 文章生成（微信公众号排版优化）
│   │   └── workflow.py        # GitHub 发布完整流水线
│   │
│   └── shared/                # 共享模块
│       ├── llm.py             # DeepSeek API 封装，含重试机制和敏感词过滤
│       ├── publisher.py       # 微信公众号 API 封装（token管理/草稿发布/标题去重）
│       ├── article_utils.py   # Markdown→HTML 转换 + 样式注入 + 配图嵌入
│       └── runtime.py         # 日志初始化和全局配置
│
├── utils/                     # 工具模块
│   ├── image_handler.py       # 智能图片检索引擎（多源搜索 + AI 生图 + 评分筛选 + 尺寸适配）
│   ├── image_filter.py        # 图片质量评估（6维评分 + OCR文字检测 + pHash去重 + 视觉AI）
│   ├── http_client.py         # HTTP 会话管理（缓存 + 重试 + 超时控制）
│   └── spider.py              # Selenium 浏览器启动器（隐身模式配置）
│
├── static/                    # Web UI 前端资源（CSS/JS/图标）
├── templates/                 # Web UI HTML 模板
└── assets/                    # 运行时自动下载的图片资源目录
```

---

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/Chain813/wechat-automatic-publisher.git
cd wechat-automatic-publisher
```

### 2. 安装依赖

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境（Windows）
venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

或直接双击 `run.bat` 自动完成以上步骤。

**额外依赖**：[Graphviz](https://graphviz.org/download/)（架构图生成需要，安装后需添加到系统 PATH）

### 3. 配置环境变量

复制 `.env.example` 为 `.env`，填入你的 API 密钥：

```env
# ===== 必填 =====
WECHAT_APP_ID="你的微信公众号AppID"
WECHAT_APP_SECRET="你的微信公众号AppSecret"
LLM_API_KEY="你的DeepSeek API Key"

# ===== 可选 =====

# GitHub API Token（可选，提高 API 速率限制，匿名60次/小时 → 认证5000次/小时）
# 获取方式：GitHub Settings → Developer settings → Personal access tokens → Generate new token
# 权限：只需勾选 public_repo
GITHUB_TOKEN="ghp_xxxxxxxxxxxx"

# Gemini Vision API Key（可选，用于 AI 图片质量评估）
GEMINI_API_KEY="AIzaSyxxxxxxxxxxx"

# 企业微信群机器人 Webhook（可选，发布后自动推送通知）
QYWECHAT_WEBHOOK=""

# Ollama 本地视觉模型（可选，本地 AI 图片评估，需先安装 Ollama）
OLLAMA_DEFAULT_MODEL="gemma4:e2b-it-q4_K_M"
OLLAMA_VISION_MODEL="gemma3:4b"

# Pexels 免费图库 API Key（可选，高质量版权免费图片）
# 获取方式：https://www.pexels.com/api/ 免费注册
PEXELS_API_KEY=""
```

### 4. 运行

**CLI 模式：**
```bash
python main.py                    # 热点文章发布（默认）
python main.py --task github      # GitHub Trending 文章发布
```

**Web 模式：**
```bash
python webui.py
```
浏览器访问 http://127.0.0.1:5000

---

## Web 管理界面

### 控制台页面

- **任务类型选择**：热点发布 / GitHub Trending 发布
- **一键启停**：点击按钮即可启动或停止任务
- **实时日志**：WebSocket 推送的实时运行日志，滚动显示
- **状态指示**：运行中/已停止/已完成 状态标识

### 历史记录页面

- 按日期分组展示已发布的文章
- 显示标题、发布时间、状态
- 支持按日期筛选

### 数据源页面

- 12 个数据源的健康状态卡片
- 绿色 = 正常响应
- 黄色 = 响应缓慢或部分失败
- 红色 = 完全不可用
- 显示最近一次采集时间和结果数

### 设置页面

- API Key 在线编辑
- 密钥脱敏显示（仅显示前4位和后4位）
- 保存后立即生效

---

## 配图策略

### 热点文章配图（AI 生图优先）

时政科技热点事件往往没有现成的新闻照片（如"ASML停止对华光刻机维修"），因此优先使用 AI 生成概念性插图：

| 优先级 | 来源 | 说明 |
|--------|------|------|
| 1 | **Pollinations.ai AI 生图** | 根据关键词生成概念图，免费无需 API Key |
| 2 | **Pexels 免费图库** | 高质量版权免费图片，适合通用场景 |
| 3 | **Bing 图片搜索** | 大尺寸横版图过滤，覆盖面广 |
| 4 | **百度图片搜索** | 国内图片源，作为兜底 |
| 5 | **本地默认图** | 最终兜底方案 |

### GitHub 文章配图（多层兜底）

为每个 GitHub 项目生成配图，优先使用项目自身的资源：

| 优先级 | 来源 | 说明 |
|--------|------|------|
| 1 | **README 图片** | 从项目 README 中提取图片，按架构图/流程图优先级评分 |
| 2 | **目录树截图** | 使用 rich 库获取项目目录结构，渲染为深色主题 PNG 图片 |
| 3 | **架构图** | 使用 diagrams 库根据项目语言和技术栈自动生成架构图 |
| 4 | **代码截图** | 使用 carbon API 将项目入口文件代码渲染为精美截图 |
| 5 | **关键词搜索** | 以项目名+语言为关键词进行网页图片搜索 |

### 图片评估流程

每张候选图片经过以下评估流程：

```
第一步：6 维 CV 评分
├── 分辨率（像素数量）
├── 宽高比（是否适合微信展示）
├── 清晰度（拉普拉斯方差）
├── 文字密度（OCR 检测文字占比）
├── 色彩丰富度（颜色直方图熵）
└── 文件大小（是否在微信限制内）

第二步：Top 3 候选进入视觉 AI 二次评估
├── Gemini Flash 2.0 可用？ → 使用 Gemini 评估（权重 60%）
├── Ollama 本地模型可用？ → 使用 Gemma 3 4B 评估（权重 60%）
└── 都不可用？ → 纯 CV 评分结果

第三步：择优录取 + 微信尺寸适配
├── 选择综合得分最高的图片
├── 裁剪为微信推荐尺寸（封面 900×383 / 正文 900×500）
├── 压缩至微信文件大小限制内（正文 2MB）
└── 感知哈希去重（避免与已选图片重复）
```

---

## 核心配置

在 `config.py` 或 `.env` 中调整：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `BRAND_NAME` | 品牌名称，显示在文章末尾和通知中 | AutoWeChat |
| `NEWS_SOURCES` | 启用的热点数据源列表 | 12 个平台 |
| `FILTER_CATEGORIES` | 优先筛选的关键词类别 | 79 个关键词 |
| `LLM_MODEL` | DeepSeek 模型名称 | deepseek-chat |
| `LLM_TEMPERATURE` | 生成文本的随机性（0-1，越高越随机） | 0.75 |
| `LLM_BASE_URL` | LLM API 地址 | https://api.deepseek.com |
| `IMAGE_DEFAULT_CANDIDATES` | 每次图片搜索的候选数量 | 5 |
| `OLLAMA_VISION_MODEL` | Ollama 本地视觉模型名称 | gemma3:4b |
| `GITHUB_TOKEN` | GitHub API Token（可选） | 匿名（60次/小时） |
| `PEXELS_API_KEY` | Pexels 图库 API Key（可选） | 未配置 |
| `WECHAT_TITLE_MAX_LEN` | 微信标题最大字数限制 | 64 |
| `WECHAT_DIGEST_MAX_LEN` | 微信摘要最大字数限制 | 120 |

---

## 名词解释

项目涉及的技术术语、工具名称和专业概念的详细解释，请参阅 **[GLOSSARY.md](GLOSSARY.md)**。

涵盖：技术术语 | 图片相关 | GitHub 相关 | 微信相关

---

## 环境要求

| 依赖 | 说明 | 是否必须 |
|------|------|---------|
| Python 3.8+ | 运行环境 | 必须 |
| [Graphviz](https://graphviz.org/download/) | 架构图渲染引擎，安装后需添加到系统 PATH | 必须（GitHub 模块） |
| Chrome 浏览器 | Selenium 备用爬取需要 | 可选 |
| [Ollama](https://ollama.com) | 本地运行视觉 AI 模型 | 可选 |
| EasyOCR | 图片文字检测（需 PyTorch ~2GB） | 可选 |

---

## 许可证

[MIT License](LICENSE)

---

## 免责声明

本工具仅供技术研究和内容创作辅助使用。请遵守微信公众号运营规范及相关法律法规。AI 生成内容需人工审核后发布。使用者应自行承担因使用本工具产生的一切法律责任。
