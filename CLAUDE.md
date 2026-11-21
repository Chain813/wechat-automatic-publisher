# CLAUDE.md — AutoWeChat 项目指南

## 智能体研发自律准则：八荣八耻

在 AutoWeChat 的全自动采集、文章生成、配图排版、发布流水线与 WebUI 开发中，智能体必须恪守以下八条行为底线：

1. **以瞎猜接口为耻，以认真查询为荣**：
   严禁凭直觉瞎猜微信 Official Account API 字段、12源热点采集器结构、DashScope/Qwen 生图接口或 Token 刷新参数，调用前必查代码与文档。
2. **以模糊执行为耻，以寻求确认为荣**：
   面对选题偏好、发文频次、知识库节点更新、敏感词风控等不明确要求，严禁暗自盲目推进，必须主动向用户确认。
3. **以臆想业务为耻，以人类确认为荣**：
   严禁替人类脑补文章事实、数据引用、科技史实或法税专业条文；文章质量与专业知识库规则由人类确认把关，坚守严格事实核查。
4. **以创造接口为耻，以复用现有为荣**：
   优先复用 `call_deepseek_with_retry()`、`build_cached_session()`、`image_handler.py` 等成熟公共设施，严禁使用裸 requests 或随手造重复轮子。
5. **以跳过验证为耻，以主动测试为荣**：
   文章生成、标签注入或样式重构后，必须进行离线渲染测试与格式断言；代码修改必须执行单元测试，确认 Exit Code 为 0 后方可交付。
6. **以破坏架构为耻，以遵循规范为荣**：
   严格遵守线程安全（`threading.Lock`）、控制信号（`cancel_event` / `pause_event`）检查、UTF-8 编码与 `loguru` 统一日志规范，严禁破坏既有异步并发模型。
7. **以假装理解为耻，以诚实无知为荣**：
   遇到微信 40001 Token 失效、Selenium 隐身检测反爬拦截或 SD WebUI 连接拒绝，诚实上报真实错误日志，绝不伪造抓取或发布成功。
8. **以盲目断言为耻，以闭环交付为荣**：
   严禁留存半成品；交付前必须验证 SQLite 标题去重生效、发布历史正常落库、`.env` 敏感凭据脱敏以及 CHANGELOG 文档同步更新。若本地存在 `.gitignore` 忽略的私有云端部署脚本 `deploy_to_server.py`，代码修改并通过单元测试（`pytest` 退出码为 0）后，必须执行 `python deploy_to_server.py` 增量同步云端并确认远端导入冒烟与服务健康检查通过，严禁遗留本地与线上代码漂移。

## 项目概述

AutoWeChat 是企业级微信公众号 AI 全流程创作与合规发布工作台，采用 Human-in-the-Loop（人机协同审核）架构。集成 12 路热点采集、网页深抓与联网事实核查、动态叙事写作、Critic 质量门禁、可追溯来源的资料照片与技术图表，最终安全推送至微信草稿箱并经 Audit 审稿台终审。

## 技术栈

- **后端与调度**：Python 3.11+ / Flask / APScheduler / SQLAlchemy (SQLite WAL) / Loguru / Pytest
- **LLM 与路由**：DeepSeek / OpenAI 兼容接口（Flash/Pro 分层路由 + Prompt Cache 统计 + `utils/key_pool.py` 多 Key 轮换）
- **视觉生图**：通义万相 `Qwen-Image-3.0` / `Qwen-Image-3.0-Pro`（DashScope）+ 本地 Stable Diffusion（备选）+ Pillow Linear Light 矢量卡片兜底；`Qwen-VL-Max` 视觉辅助模块
- **抓取与事实核查**：`trafilatura` 正文深抓 + DuckDuckGo/Bing 实时事实搜索 + Selenium / Chrome 无头截图（GitHub 页面 & HTML+KaTeX/Mermaid 降级渲染）+ Graphviz / Matplotlib 轻量图表
- **前端控制台**：Linear Modern Light 零构建原生 ES Module（`static/js/core/` + `static/js/views/` + `tokens.css`/`components.css`/`views.css` + 4 层 CSS `.ambient-canvas`）
- **发布集成**：微信公众号 API（草稿箱推送 + 4 层标题查重）与企业微信 Webhook 通知

## 项目结构

```text
├── main.py                        # CLI 无头入口 (--task hotspots|github|aikepu|daily_knowledge)
├── webui.py                       # Flask + SSE 五维 Web 控制台与 REST API
├── config.py                      # 全局配置中心（.env 覆盖默认值）
├── data/                          # 运行时数据库、知识图谱与预览落地
│   ├── auto_publish.sqlite        # SQLite WAL 主库：标题去重、审稿状态、质量分与事实摘要
│   ├── daily_knowledge.sqlite     # 每日百科独立 SQLite 库
│   ├── hotspot_cache.sqlite       # 网络请求缓存库
│   ├── knowledge_trees/           # 5 套内置知识图谱 (*.json) 与 _active.txt 当前激活指针
│   ├── cache/aikepu/aikepu_history.json  # 体系科普节点发布进度记录
│   └── previews/                  # 审稿预览与 Critic 拦截落地的 fail_*.html
├── core/
│   ├── engine.py                  # 统一任务调度总线 (4 类工作流)
│   ├── db/                        # ORM 模型 (`models.py`) 与连接池 (`manager.py`)
│   ├── pipeline/                  # PipelineEngine (`engine.py`)、节点协议 (`nodes.py`) 与 Critic 门禁 (`critic.py`)
│   ├── plugins/                   # 12 路热点数据源与 GitHub 插件注册 (`hotspots_sources.py`, `manager.py`)
│   ├── hotspots/                  # `processor.py` / `workflow.py` / `scraper.py` / `searcher.py` / `narrative.py`
│   ├── github/                    # GitHub 采集、截图与深潜成文 (`collector.py`, `processor.py`, `workflow.py`)
│   ├── aikepu/                    # 知识图谱解析 (`skill_tree.py`)、并发 Sub-Agent 写作 (`processor.py`, `workflow.py`)
│   └── shared/                    # `llm.py` / `publisher.py` / `article_utils.py` / `runtime.py`
├── daily_knowledge/               # 每日小知识独立引擎、去重器、数据库与工作流
├── tools/                         # 零访谈账号分析 (`analyze_account.py`) 与图谱生成 (`build_knowledge_tree.py`)
├── prompts/                       # 分工作流与分领域 Writing Skill（`hotspots`/`aikepu`/`daily_knowledge`/`law`/`tax`）
├── utils/
│   ├── image_handler.py           # Qwen-Image-3.0 -> Local SD -> Pillow 兜底生图链路（热点禁用 Bing 爬虫）
│   ├── diagram_gen.py             # Mermaid / HTML+KaTeX / Graphviz / Matplotlib 并行图表引擎
│   ├── lite_render.py / html_render.py  # 轻量卡片渲染器 & 无头浏览器渲染器
│   ├── image_prompt_gen.py / image_filter.py  # Image Studio 提示词提取与视觉筛选辅助模块
│   └── key_pool.py / http_client.py / spider.py  # 多 Key 轮换、缓存 HTTP Session 与爬虫件
├── static/
│   ├── css/                       # `tokens.css` / `components.css` / `views.css`
│   └── js/                        # `main.js` + `core/{api,i18n,icons,log-parser,state,storage}.js` + `views/{console,graph,audit,studio,ops}.js`
├── templates/                     # `index.html` (5 维控制台) 与 `login.html` (WEBUI_TOKEN 鉴权页)
└── tests/                         # 13 个 Pytest 单元、集成与 WebUI 交互测试套件
```

## 核心架构

### 工作流

1. `run_main()` → `sync_local_history_with_wechat()` → 分发至 `hotspots` / `github` / `aikepu` / `daily_knowledge`
2. 热点 (`core/hotspots/`)：`fetch_all_hotspots()` → `filter_tech_hotspots()` → `scraper.py` 正文提取 + `searcher.py` 联网事实核查 → `narrative.py` 叙事策略与 `generate_article()` → `critic.py` 质量门禁修复/评分 → `process_article_content()` → `add_draft()` / `REJECTED` 入库审稿
3. GitHub (`core/github/`)：`fetch_one_worthy_project()` → `_ensure_deep_images()` → `generate_github_article()` → `critic.py` 质检 → `process_article_content()` → `add_draft()`
4. 体系科普 (`core/aikepu/`)：`select_next_node()` → Phase 1 `_generate_outline()` → Phase 2 `_optimize_section_prompts()` (Flash 优化排他/类比/钩子) → Phase 3 `ThreadPoolExecutor` (最多 4 并发 `_run_subagent_worker`) → `critic.py` 质检 → `process_article_content()` → `add_draft()`
5. 每日百科 (`daily_knowledge/`)：`engine.py` + `workflow.py` + `deduplicator.py` 规划主题并生成轻科普草稿。

### 控制信号

- `cancel_event`（threading.Event）：用户点 Stop 时置位，所有关键节点检查
- `pause_event`（threading.Event）：用户点 Pause 时清除，`check_cancelled()` 中 `wait()`
- `WorkflowCancelled`：cancel 时抛出的异常，被 `run_workflow_thread` 捕获

### 并发模型

- 热点发布：外层 `ThreadPoolExecutor` 并行多篇，内层并行资产提取与正文撰写
- 体系科普 Phase 3：`ThreadPoolExecutor(max_workers=min(4, len(optimized)))` 并行生成各章节
- GitHub 配图：`_ensure_deep_images` 并行多种仓库截图与视觉来源
- 技术图表渲染：`DIAGRAM_PARALLEL_WORKERS`（默认 `5`）控制图表并行渲染线程数
- 通义生图限流：`QWEN_IMAGE_MAX_CONCURRENCY` 与 `QWEN_IMAGE_MIN_INTERVAL` 保护百炼 QPM 配额
- 所有网络调用支持中断（`_interruptible_sleep` + `cancel_event` 检查）

### 文章格式与排版

- Linear Modern Light 微信内联排版（`core/shared/article_utils.py`）：沉降式代码块卡片、对比表格、Callout 提示框
- 红色重点：`**{{核心结论}}**` → `<strong style="color: #d73a49">`
- 黑色粗体：`**重要概念**` → `<strong style="color: #1a1a1a">`
- 配图占位符：`【此处插入配图：关键词】` → 并发生成并上传微信 CDN 后替换为 `<img>`
- GitHub 配图：`【GITHUB配图：URL】` → 下载并转存微信 CDN

## 编码规范

- 所有文件使用 UTF-8 编码
- 日志使用 `loguru`（`from loguru import logger`），不用 `print` 做日志
- 线程安全：共享资源用 `threading.Lock`，长耗时循环/网络调用检查 `cancel_event`
- 网络请求用 `build_api_session()` 或 `build_cached_session()`，不用裸 `requests`
- 配置项集中在 `config.py`，通过 `.env` 覆盖
- LLM 调用统一用 `call_deepseek_with_retry()`

## 常见任务

### 添加新的热点数据源

1. 在 `core/plugins/hotspots_sources.py` 新增继承 `BaseSourcePlugin` 的采集类并在 `PluginManager` (`core/plugins/manager.py`) 中注册
2. 在 `config.py` 的 `NEWS_SOURCES` 列表添加源名
3. 在对应健康检查标签与前端 `ops.js` 信源矩阵中补充展示名

### 修改文章生成提示词与质量门禁

- 热点：`core/hotspots/processor.py`、`prompts/hotspots_skill.md` 及 `core/hotspots/narrative.py`
- GitHub：`core/github/processor.py`
- 体系科普与垂直赛道：`prompts/{主题包}_skill.md`（优先加载，缺省回退 `prompts/aikepu_writing_skill.md`）
- 每日百科：`prompts/daily_knowledge_skill.md`
- 质检红线与套话清洗规则：`core/pipeline/critic.py`

### 修改配图与图表策略

- 热点和每日小知识自动配图：`utils/source_photos.py` 检索开放许可照片，`core/shared/article_photos.py` 完成上传、署名和封面。
- AI 配图工具：`utils/image_handler.py` 中的 `download_image()` / `download_cover_image()`（`Qwen-Image-3.0` → 本地 SD → Pillow 矢量卡片）
- 视觉辅助评估模块：`utils/image_filter.py` 的 `evaluate_image()` / `evaluate_image_with_qwen_vl()`
- 技术图表渲染：`utils/diagram_gen.py`（Mermaid / HTML+KaTeX / Graphviz / Matplotlib）与 `utils/lite_render.py`
- GitHub 配图管线：`core/github/workflow.py` 的 `_ensure_deep_images()`
- 文章内配图：`core/shared/article_utils.py` 的 `process_article_content()`

### 新增知识体系主题包（含零访谈定制）

1. 零访谈定制：`python tools/build_knowledge_tree.py "主题名" --slug law --nodes 12 --samples "客户文章链接1,链接2" --activate`（自动扒取客户历史文章 → `tools/analyze_account.py` 提炼画像 → 按画像生成知识库与风格文件）
2. 半自动生成：`python tools/build_knowledge_tree.py "主题名" --slug law --nodes 12 --audience "目标读者" --tone "风格关键词" --activate`
3. 手动创建：`data/knowledge_trees/{name}.json`（结构：`meta.name/column_name` + `nodes[{id,title,tags,prerequisites,difficulty,summary,custom_prompt}]`）
4. 写作风格：`prompts/{name}_skill.md`（引擎自动按激活主题加载，缺省回退 `aikepu_writing_skill.md`）
5. 激活：WebUI `图谱 (Graph)` 页下拉切换，或写入 `data/knowledge_trees/_active.txt` / 设置 `KNOWLEDGE_TREE={name}`

### 调整 Linear Modern Light WebUI 与样式

- 设计 Token 与画布：`static/css/tokens.css`（色彩/圆角/阴影/字体 Token）、`components.css`、`views.css`（含 4 层 CSS `.ambient-canvas`，无 Three.js 依赖）
- 零构建 ES Module：`static/js/main.js`、`static/js/core/{api,i18n,icons,log-parser,state,storage}.js` 及 5 视图模块 `static/js/views/{console,graph,audit,studio,ops}.js`
- 主页面模板：`templates/index.html`（核心 DOM `id` / `data-i18n` / `data-view` / `data-task` 属性不可随意删改）
- 登录页模板：`templates/login.html`（`WEBUI_TOKEN` 鉴权模式；`/static/` 已在 `webui.py` 豁免认证）

## 本地服务依赖

- **Stable Diffusion**：`http://127.0.0.1:7860`（可选，需启动 `--api` 模式作为 `Qwen-Image` 备选源）
- **Chrome / Chromium**：可选，用于 `HTML+KaTeX`、`Mermaid` 本地无头降级渲染与 GitHub 抓取降级
- **Graphviz**：系统 PATH 中的 `dot` 命令（可选，轻量 DOT 结构图需要）
