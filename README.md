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
- [开发工作流](DEVELOPMENT.md)
- [Claude Code 指南](CLAUDE.md)
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

- **人格化主笔 (v4.1)**：热点主笔和 GitHub 推荐官均有完整的人格画像——背景经历、思维习惯、表达原则、世界观，彻底告别”AI 味”。
- **分级重点标注**：红色加粗（`**{{核心结论}}`**，3-5 处）+ 黑色加粗（关键数据/概念，每段 1-2 处），读者扫一眼就能抓住核心。LLM 未输出足够粗体时自动兜底补全。
- **API 截断检测**：自动检测文章是否被 LLM API 静默截断（结尾不完整），截断时自动重试，杜绝残缺文章发布。
- **智能重试**：首稿不合格时将原文传给 LLM 定向修复（而非从零重写），保留好内容，只修结构问题。
- **双端活跃标题去重 (v4.0)**：4 种策略（精确/模糊/关键词/AI语义匹配）查重，彻底杜绝重复。
- **云端状态自动同步 (v4.0)**：运行前自动拉取微信草稿和已发布列表，云端已删除的内容自动释放本地历史。
- **排版健壮性**：自动修复行首冒号、清理空列表项、修复红字重点花括号溢出、统一字体栈。时间戳（如 `10:30`）不会被误改。
- **三梯队选题体系**：AI+时政（最高优先级）→ 硬核 AI → 金融时政，确保内容契合品牌定位。

### 智能配图

多源图片检索 + AI 生成，自动为文章匹配最佳配图：

- **6 维评分体系**：从分辨率、宽高比、清晰度、文字密度、色彩丰富度、文件大小 6 个维度对候选图片打分
- **感知哈希去重**：使用 pHash（感知哈希）算法检测相似图片，避免重复配图
- **微信尺寸适配**：自动裁剪为微信推荐尺寸（封面 900×383，正文 900×500）
- **视觉 AI 二次评估**：候选图片经 Gemini Vision（云端）或 Ollama（本地）AI 模型二次评估，选出最佳
- **本地 Stable Diffusion 集成**：支持调用本地 SD WebUI API 生成极客艺术感插图。
- **LLM 图像关键词优化**：当常规搜索无果时，由 LLM 将抽象术语转化为视觉化搜索词（如“监管政策”→“科技感天平”），大幅提升匹配率。
- **固定专题封面**：GitHub 专题统一采用 2.35:1 黄金比例的固定品牌封面，增强辨识度。

### 高效并行架构

- **GitHub 配图全并行**：6 种图片来源同时启动，集满 3 张自动停止，速度提升 3-5 倍
- **封面与文章并行**：封面 SD 生图与文章创作同时进行，每篇节省 5-20 秒
- **GitHub 正文配图并行**：多张配图同时下载上传
- **热点多篇并行**：多篇文章同时生成和发布
- **12 源热点并发扫描**：所有数据源同时抓取
- **可中断**：所有长时间操作均支持用户中断（Stop 按钮 0.5 秒内响应）

### 安全合规

- **4 策略标题去重**：精确匹配 → 模糊匹配（RapidFuzz）→ 关键词匹配 → AI 语义匹配
- **跨话题内部去重**：同一批次内的相似话题自动去重
- **草稿箱审计**：发布前与微信草稿箱已有文章比对，防止重复

### Web 管理界面

Flask 暗色主题仪表盘：

| 页面 | 功能说明 |
|------|---------|
| **控制台** | 一键启停任务、实时日志流、任务类型选择（热点/GitHub）。支持暂停/恢复/停止 |
| **历史记录** | 按日期分组，显示发布状态（✓/✗）、时间、草稿 ID、错误信息 |
| **数据源** | 12 个数据源的健康状态卡片（绿=正常/黄=告警/红=故障） |
| **设置** | API Key 在线配置，密钥脱敏显示，防注入校验 |

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

# LLM 模型（默认: deepseek-v4-pro）
LLM_MODEL="deepseek-v4-pro"

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
- **一键启停**：Start / Pause / Resume / Stop 完整控制流
- **实时日志**：轮询推送的实时运行日志，滚动显示
- **状态指示**：Running / Paused / Idle 状态标识

### 历史记录页面

- 按日期分组展示发布结果
- 每条记录显示：✓/✗ 状态、话题名、发布时间、草稿 ID
- 失败记录显示错误原因

### 数据源页面

- 12 个数据源的健康状态卡片
- 绿色 = 正常 / 黄色 = 降级 / 红色 = 故障
- 连续失败 3 次自动降级，下次运行自动恢复

### 设置页面

- API Key 在线编辑，密钥脱敏显示
- 输入校验（防换行注入、长度限制）
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

### GitHub 文章配图与深度剖析 (v4.1)

GitHub 专题升级为 **单项目深度拆解模式**。配图管线 **全部并行执行**，集满 3 张自动停止，速度提升 3-5 倍。智能 Demo URL 检测支持 Vercel/Netlify/GitHub Pages 等主流平台。

| 优先级 | 来源 | 说明 |
|--------|------|------|
| 1 | **Social Preview 封面** | **(新)** 提取仓库所有者设置的社交预览图（`open_graph_image_url`），通常是项目最精美的封面 |
| 2 | **GIF 动画** | **(新)** 优先提取 README 中的 GIF 动画——项目实际运行效果，比任何截图都有说服力 |
| 3 | **在线 Demo 截图** | 多策略检测 Demo URL（关键词→Badge 链接→平台 URL→GitHub Pages），截取真实界面 |
| 4 | **README 截图** | 无头浏览器截取 README 渲染页面，自动裁剪为 2.35:1 微信比例 |
| 5 | **SD 艺术插图** | DeepSeek 生成专属 Prompt → 本地 Stable Diffusion 创作极客风格配图 |
| 6 | **代码截图** | carbon API 渲染代码片段为带语法高亮的精美截图 |

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
| `LLM_MODEL` | DeepSeek 模型名称 | `deepseek-v4-pro` |
| `LLM_TIMEOUT` | LLM API 超时设置 (秒) | 180 |
| `LLM_TEMPERATURE` | 生成文本的随机性（0-1，越高越随机） | 0.75 |
| `LLM_BASE_URL` | LLM API 地址 | https://api.deepseek.com |
| `IMAGE_DEFAULT_CANDIDATES` | 每次图片搜索的候选数量 | 5 |
| `OLLAMA_VISION_MODEL` | Ollama 本地视觉模型名称 | gemma3:4b |
| `GITHUB_TOKEN` | GitHub API Token（可选） | 个人/机构 Token |
| `PEXELS_API_KEY` | Pexels 图库 API Key（可选） | 未配置 |
| `SD_ENABLED` | 是否启用本地 Stable Diffusion 生图 | `True` |
| `SD_API_URL` | Stable Diffusion WebUI API 地址 | `http://127.0.0.1:7860` |
| `WECHAT_TITLE_MAX_LEN` | 微信标题最大字数限制 | 64 |
| `WECHAT_DIGEST_MAX_LEN` | 微信摘要最大字数限制 | 120 |

---

## 名词解释

项目涉及的技术术语、工具名称和专业概念的详细解释，请参阅 **[GLOSSARY.md](GLOSSARY.md)**。

涵盖：技术术语 | 图片相关 | GitHub 相关 | 微信相关

---

## 开发文档

| 文档 | 说明 |
|------|------|
| **[DEVELOPMENT.md](DEVELOPMENT.md)** | 开发工作流：环境搭建、代码规范、测试方法、发布流程、调试技巧、故障排查 |
| **[CLAUDE.md](CLAUDE.md)** | Claude Code 项目指南：架构概览、核心模块、编码规范、常见开发任务 |

---

## 环境要求

| 依赖 | 说明 | 是否必须 |
|------|------|---------|
| Python 3.8+ | 运行环境 | 必须 |
| [Graphviz](https://graphviz.org/download/) | 架构图渲染引擎，安装后需添加到系统 PATH | 必须（GitHub 模块） |
| Chrome 浏览器 | Selenium 备用爬取需要 | 可选 |
| [Ollama](https://ollama.com) | 本地运行视觉 AI 模型 | 可选 |
| [Stable Diffusion](https://github.com/AUTOMATIC1111/stable-diffusion-webui) | 本地生图引擎（需开启 `--api`） | 可选 |
| EasyOCR | 图片文字检测（需 PyTorch ~2GB） | 可选 |

---

## 许可证

[MIT License](LICENSE)

---

## 免责声明

本工具仅供技术研究和内容创作辅助使用。请遵守微信公众号运营规范及相关法律法规。AI 生成内容需人工审核后发布。使用者应自行承担因使用本工具产生的一切法律责任。
