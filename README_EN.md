English | [中文](README.md)

# AutoWeChat: AI Content Factory

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.8+](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![DeepSeek: Powered](https://img.shields.io/badge/LLM-DeepSeek-green.svg)](https://api.deepseek.com)
[![Gemini Vision](https://img.shields.io/badge/Vision-Gemini%20Flash-orange.svg)](https://ai.google.dev/)

Fully automated WeChat public account content production and publishing system. Integrates real-time hotspot monitoring, AI topic selection, deep article creation, intelligent image selection, and one-click publishing.

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
- [Web UI](#web-ui-v30)
- [Image Selection Strategy](#image-selection-strategy)
- [Core Configuration](#core-configuration)
- [Glossary](GLOSSARY_EN.md)
- [Requirements](#requirements)
- [License](#license)
- [Disclaimer](#disclaimer)

---

## Features

**Multi-Source Hotspot Aggregation** — Parallel scraping from 12 platforms (Weibo, IT Home, 36Kr, Baidu, Zhihu, CSDN, RSS, Politics, Toutiao, The Paper, Huxiu, Douyin). Source-level health monitoring with automatic degradation.

**AI Deep Creation** — DeepSeek-powered 2500-3500 word analysis articles. Built-in sensitive word filtering, title dedup (4 strategies), structural quality checks.

**Intelligent Image Selection** — Multi-source image retrieval (Pollinations AI generation -> Pexels free stock -> Bing/Baidu crawling). 6-dimension scoring (resolution, aspect ratio, sharpness, text density, color richness, file size). Perceptual hash dedup. WeChat cover/body dual-mode scoring. **Gemini Vision + Ollama local vision model** for AI-powered image evaluation with automatic fallback.

**Efficient Parallel Architecture** — Image download+upload merged into parallel pipeline. Article asset generation parallelized with digest generation. Multi-source hotspot concurrent scanning.

**Safety & Compliance** — 4-strategy title dedup (exact/fuzzy/keyword/AI semantic). Cross-topic internal dedup. Draft box audit to prevent duplicates.

**Web Management UI** — Flask dark-theme dashboard with one-click task start/stop, real-time log streaming, article history, source health monitoring, online configuration.

**WeChat Integration** — Auto-push notifications to WeChat group bots after publishing.

---

## Tech Stack

- **Language**: Python 3.8+
- **LLM**: DeepSeek Chat / Reasoner
- **Vision AI**: Gemini Flash 2.0 (cloud) + Gemma 3 4B via Ollama (local)
- **GitHub**: PyGithub (API), rich (directory tree rendering), diagrams (architecture diagrams), carbon (code screenshots)
- **Crawling**: Requests, BeautifulSoup4, Selenium (Stealth Mode), icrawler
- **Image**: Pillow, numpy, Pollinations.ai API, Pexels API
- **Cache/Match**: requests-cache, RapidFuzz
- **Logging**: Loguru
- **Web**: Flask
- **API**: WeChat Official Account Draft API

---

## Project Structure

```
wechat_auto_publish/
├── main.py                    # CLI entry (supports --task hotspots/github)
├── webui.py                   # Flask Web management UI (v3.0)
├── config.py                  # Global configuration center
├── requirements.txt           # Dependencies
├── run.bat                    # CLI launch script
├── run_gui.bat                # Web UI launch script
├── core/
│   ├── engine.py              # Workflow dispatcher
│   ├── hotspots/
│   │   ├── collector.py       # 12-source hotspot engine
│   │   ├── processor.py       # AI article generation engine
│   │   └── workflow.py        # Hotspot publishing pipeline
│   ├── github/
│   │   ├── collector.py       # GitHub Trending (PyGithub + rich tree + diagrams + carbon)
│   │   ├── processor.py       # GitHub article generation (WeChat formatting)
│   │   └── workflow.py        # GitHub publishing pipeline
│   └── shared/
│       ├── llm.py             # DeepSeek API wrapper
│       ├── publisher.py       # WeChat API + title dedup
│       ├── article_utils.py   # Markdown->HTML + image embedding
│       └── runtime.py         # Log initialization
├── utils/
│   ├── image_handler.py       # Multi-source image retrieval + AI generation
│   ├── image_filter.py        # Image scoring / OCR / pHash dedup / Vision AI
│   ├── http_client.py         # HTTP session + cache + retry
│   └── spider.py              # Selenium browser launcher
├── static/                    # Web UI frontend assets
├── templates/                 # Web UI templates
└── assets/                    # Auto-downloaded image assets
```

---

## Quick Start

### 1. Clone

```bash
git clone https://github.com/Chain813/wechat-automatic-publisher.git
cd wechat-automatic-publisher
```

### 2. Install Dependencies

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Or double-click `run.bat` for automatic setup.

### 3. Configure

Copy `.env.example` to `.env` and fill in:

```env
# Required
WECHAT_APP_ID="your-wechat-appid"
WECHAT_APP_SECRET="your-wechat-appsecret"
LLM_API_KEY="your-deepseek-api-key"

# Optional: GitHub API (for GitHub Trending articles, higher rate limit)
GITHUB_TOKEN="your-github-personal-access-token"

# Optional: Gemini Vision (cloud image evaluation)
GEMINI_API_KEY="your-gemini-api-key"

# Optional: WeChat group bot notification
QYWECHAT_WEBHOOK=""

# Optional: Ollama local vision model
OLLAMA_DEFAULT_MODEL="gemma4:e2b-it-q4_K_M"
OLLAMA_VISION_MODEL="gemma3:4b"

# Optional: Pexels free stock images
PEXELS_API_KEY=""
```

### 4. Run

**CLI mode:**
```bash
python main.py                    # Hotspot publishing (default)
python main.py --task github      # GitHub Trending publishing
```

**Web mode:**
```bash
python webui.py
```
Visit http://127.0.0.1:5000

---

## Web UI (v3.0)

The dark-themed dashboard provides:

| Page | Features |
|------|----------|
| **Console** | One-click start/stop, real-time log streaming, task type selection |
| **History** | Published articles grouped by date |
| **Sources** | 12-source health status (green/yellow/red cards) |
| **Settings** | API key configuration with secret masking |

---

## Image Selection Strategy

### Hotspot Articles (AI-first)

1. **Pollinations.ai AI Generation** — Conceptual illustrations for current affairs (no stock photo matches specific events)
2. **Pexels Free Stock** — High-quality copyright-free images
3. **Bing Image Search** — Large landscape images filtered
4. **Baidu Image Search** — Domestic fallback
5. **Local Default** — Final fallback

### GitHub Articles (multi-layer fallback)

1. **README Images** — Architecture diagrams, screenshots (scored by relevance)
2. **Directory Tree** — Rendered via rich library as styled PNG
3. **Architecture Diagram** — Auto-generated via diagrams library based on tech stack
4. **Code Screenshot** — Generated via carbon API from repo's main entry file
5. **Keyword Search** — Web image search as final fallback

Each image is evaluated on 6 dimensions, then optionally re-evaluated by vision AI:

```
CV 6-dim scoring -> Top 3 candidates -> Vision AI re-evaluation
                         |
                   Gemini available? -> Gemini Flash 2.0 (60% weight)
                         | No
                   Ollama available? -> Gemma 3 4B local (60% weight)
                         | No
                   Pure CV scoring fallback
```

---

## Core Configuration

Adjustable in `config.py` or `.env`:

| Config | Description | Default |
|--------|-------------|---------|
| `BRAND_NAME` | Brand name | AutoWeChat |
| `NEWS_SOURCES` | Enabled sources | 12 platforms |
| `FILTER_CATEGORIES` | Priority filter keywords | 79 terms |
| `LLM_MODEL` | LLM model | deepseek-chat |
| `LLM_TEMPERATURE` | Generation randomness | 0.75 |
| `IMAGE_DEFAULT_CANDIDATES` | Image candidates per search | 5 |
| `OLLAMA_VISION_MODEL` | Local vision model | gemma3:4b |
| `GITHUB_TOKEN` | GitHub API token (optional, higher rate limit) | anonymous (60/hr) |

---

## Glossary

Detailed explanations of technical terms, tool names, and concepts used in this project: **[GLOSSARY_EN.md](GLOSSARY_EN.md)**

Covers: Technical Terms | Image Terms | GitHub Terms | WeChat Terms

---

## Requirements

- Python 3.8+
- [Graphviz](https://graphviz.org/download/) (for architecture diagram generation, add to PATH)
- Chrome browser (for Selenium fallback scraping)
- Optional: [Ollama](https://ollama.com) for local vision AI
- Optional: EasyOCR for text detection (requires PyTorch ~2GB)

---

## License

[MIT License](LICENSE)

---

## Disclaimer

This tool is for technical research and content creation assistance only. Please comply with WeChat official account operating guidelines and relevant laws. AI-generated content should be reviewed by a human before publishing.
