# 🚀 AutoWeChat: 智界洞察社 AI 内容工厂

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.8+](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![DeepSeek: Powered](https://img.shields.io/badge/LLM-DeepSeek-green.svg)](https://api.deepseek.com)

**AutoWeChat** 是一款为微信公众号量身定制的、全自动化 AI 内容生产与发布系统。它集成了全网热点实时监控、AI 选题、深度长文创作、智能图像检索与排版等核心功能，旨在打造一个专业级、高效率的“数字编辑部”。

---

## ✨ 核心特性

- **🌍 全网热点聚合**：并行抓取微博、IT之家、36氪、百度等主流平台的实时热搜，确保选题永不落后。
- **🧠 AI 深度创作**：基于 DeepSeek 模型，模拟“智界洞察社”特有的科技科普人格，生成 2500-3500 字的深度叙事长文。
- **🎨 智能视觉引擎**：
    - 多源搜图：自动为文章段落匹配高清素材。
    - 智能评分：基于分辨率、色彩、文字密度等维度择优录取。
    - 尺寸适配：自动裁剪为微信封面 (2.35:1) 和正文插图规格。
    - 感知哈希：通过 pHash 去重，确保文章配图的独特性。
- **🛡️ 安全合规**：内置敏感词过滤、标题党校验、草稿箱内容审计（防重）。
- **🚀 一键发布/草稿**：直接对接微信公众号素材接口，一键同步至云端草稿箱。
- **📢 企业微信集成**：发布成功后自动推送通知至指定的企业微信群机器人。

---

## 🛠️ 技术栈

- **语言**: Python 3.8+
- **模型**: DeepSeek Chat (V3)
- **爬虫**: Requests, BeautifulSoup4, Selenium (Stealth Mode)
- **图像**: Pillow, icrawler, EasyOCR
- **API**: 微信公众号官方接口 (Draft API)

---

## 📥 快速开始

### 1. 克隆项目
```bash
git clone https://github.com/your-username/wechat_auto_publish.git
cd wechat_auto_publish
```

### 2. 配置环境
项目提供了全自动化的部署脚本，**只需双击 `run.bat`**：
- 自动检测并安装 Python 环境。
- 自动创建并激活 `venv` 虚拟环境。
- 自动使用国内镜像源安装所有依赖库。
- 自动生成 `.env` 配置文件。

### 3. 设置 API 密钥
打开项目根目录生成的 `.env` 文件，填入你的密钥：
```env
WECHAT_APP_ID="你的微信AppID"
WECHAT_APP_SECRET="你的微信AppSecret"
LLM_API_KEY="你的DeepSeek_API_Key"
QYWECHAT_WEBHOOK="（可选）企业微信机器人Webhook"
```

### 4. 运行
再次双击 `run.bat`，系统将启动全自动扫描与生成流程。

---

## 📂 项目结构

```text
wechat_auto_publish/
├── main.py             # 系统入口：协调各模块运行
├── config.py           # 核心配置中心
├── news_collector.py   # 全网热点聚合引擎
├── llm_processor.py    # AI 内容处理引擎 (DeepSeek)
├── image_handler.py    # 图像检索引擎
├── image_filter.py     # 智能图片评分与过滤系统
├── wechat_api.py       # 微信 API 封装
├── spider_engine.py    # 底层反检测爬虫引擎
├── requirements.txt    # 依赖清单
├── run.bat             # Windows 一键自动化部署脚本
├── .env.example        # 环境变量模板
└── assets/             # 自动下载的图像素材目录
```

---

## 📝 核心配置项

你可以在 `config.py` 中调整以下参数以适配你的品牌：
- `BRAND_NAME`: 品牌名称（默认：智界洞察社）
- `FILTER_CATEGORIES`: AI 优先筛选的话题关键词。
- `LLM_TEMPERATURE`: AI 创作的随机度。
- `NEWS_SOURCES`: 启用的采集源列表。

---

## ⚖️ 开源协议

本项目采用 [MIT License](LICENSE) 开源协议。

---

## ⚠️ 免责声明

本工具仅用于技术研究与内容创作辅助，请务必遵守微信公众号官方运营规范及相关法律法规。使用本系统生成的 AI 内容建议经过人工最终审核后发布。
