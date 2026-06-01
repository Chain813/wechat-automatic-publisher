# CLAUDE.md — AutoWeChat 项目指南

## 项目概述

AutoWeChat 是微信公众号全自动内容生产与发布系统。集成 12 源热点监控、AI 选题、深度文章创作、智能配图、一键发布。

## 技术栈

- Python 3.8+ / Flask / Loguru
- DeepSeek LLM（文章生成、选题、摘要）
- Gemini Vision + Ollama（图片 AI 评估）
- Selenium（浏览器截图）
- Stable Diffusion（AI 生图）
- PyGithub（GitHub API）
- 微信公众号 API（草稿发布）

## 项目结构

```
├── main.py                    # CLI 入口 (--task hotspots/github)
├── webui.py                   # Flask Web 管理界面
├── config.py                  # 全局配置中心
├── core/
│   ├── engine.py              # 工作流调度器
│   ├── hotspots/              # 热点文章模块
│   │   ├── collector.py       # 12 源热点采集
│   │   ├── processor.py       # AI 文章生成 + SYSTEM_PROMPT
│   │   └── workflow.py        # 热点发布流水线
│   ├── github/                # GitHub Trending 模块
│   │   ├── collector.py       # GitHub 采集 + 截图 + Demo 检测
│   │   ├── processor.py       # GitHub 文章生成 + SYSTEM_PROMPT
│   │   └── workflow.py        # GitHub 发布流水线（并行配图）
│   └── shared/
│       ├── llm.py             # DeepSeek API 封装（可中断重试）
│       ├── publisher.py       # 微信 API 封装（线程安全 Token）
│       ├── article_utils.py   # Markdown→HTML + 样式注入 + 配图
│       └── runtime.py         # 日志 + 控制信号 (cancel_event/pause_event)
├── utils/
│   ├── image_handler.py       # 图片检索 + SD 生图
│   ├── image_filter.py        # 图片评分（6 维 CV + 视觉 AI）
│   ├── http_client.py         # HTTP Session（缓存 + 重试）
│   └── spider.py              # Selenium 隐身浏览器
├── static/                    # 前端 CSS/JS
└── templates/                 # Flask HTML 模板
```

## 核心架构

### 工作流

1. `run_main()` → `sync_local_history_with_wechat()` → `run_hotspots_workflow()` 或 `run_github_workflow()`
2. 热点：`fetch_all_hotspots()` → `filter_tech_hotspots()` → `generate_article()` → `process_article_content()` → `add_draft()`
3. GitHub：`fetch_one_worthy_project()` → `_ensure_deep_images()`（并行）→ `generate_github_article()` → `process_article_content()` → `add_draft()`

### 控制信号

- `cancel_event`（threading.Event）：用户点 Stop 时置位，所有关键节点检查
- `pause_event`（threading.Event）：用户点 Pause 时清除，`check_cancelled()` 中 `wait()`
- `WorkflowCancelled`：cancel 时抛出的异常，被 `run_workflow_thread` 捕获

### 并发模型

- 热点发布：外层 `ThreadPoolExecutor` 并行多篇，内层并行（资产 + 摘要）
- GitHub 配图：`_ensure_deep_images` 用 `ThreadPoolExecutor` 并行 6 种图片来源，集满 3 张即停
- 封面生成：与文章创作并行（不依赖文章内容）
- 所有网络调用支持中断（`_interruptible_sleep` + `cancel_event` 检查）

### 文章格式

- 红色重点：`**{{核心结论}}**` → 后处理转为 `<strong style="color: #d73a49">`
- 黑色粗体：`**重要概念**` → 后处理转为 `<strong style="color: #1a1a1a">`
- 配图占位符：`【此处插入配图：关键词】` → 并行下载上传后替换为 `<img>`
- GitHub 配图：`【GITHUB配图：URL】` → 下载后上传到微信 CDN

## 编码规范

- 所有文件使用 UTF-8 编码
- 日志使用 `loguru`（`from loguru import logger`），不用 `print` 做日志
- 线程安全：共享资源用 `threading.Lock`，检查 `cancel_event`
- 网络请求用 `build_api_session()` 或 `build_cached_session()`，不用裸 `requests`
- 配置项集中在 `config.py`，通过 `.env` 覆盖
- LLM 调用统一用 `call_deepseek_with_retry()`

## 常见任务

### 添加新的热点数据源

1. 在 `core/hotspots/collector.py` 添加 `fetch_xxx()` 函数
2. 注册到 `_SOURCE_FETCHERS` 字典
3. 在 `config.py` 的 `NEWS_SOURCES` 列表添加源名
4. 在 `get_source_health_report()` 的 `source_labels` 添加标签

### 修改文章生成提示词

- 热点：编辑 `core/hotspots/processor.py` 的 `SYSTEM_PROMPT`
- GitHub：编辑 `core/github/processor.py` 的 `SYSTEM_PROMPT`
- 用户 prompt 在 `generate_article()` / `generate_github_article()` 函数中

### 修改配图策略

- 配图评分：`utils/image_filter.py` 的 `evaluate_image()`
- 图片下载：`utils/image_handler.py` 的 `download_image()` 系列
- GitHub 配图管线：`core/github/workflow.py` 的 `_ensure_deep_images()`
- 文章内配图：`core/shared/article_utils.py` 的 `process_article_content()`

## 本地服务依赖

- **Stable Diffusion**：`http://127.0.0.1:7860`（需启动 `--api` 模式）
- **Ollama**：`http://localhost:11434`（需拉取 `gemma3:4b` 视觉模型）
- **Graphviz**：系统 PATH 中（diagrams 架构图需要）
