# AutoWeChat 二次开发与架构指南

本文档面向 **AutoWeChat** 的维护者与二次开发者，详细介绍系统的模块分层、核心流水线契约、Linear Modern Light 零构建前端工程以及测试排查规范。

---

## 1. 开发环境搭建

### 1.1 基础环境
- **Python**: 3.11+（推荐 3.11 或 3.12）
- **依赖安装**:
  ```bash
  python -m venv .venv
  # Windows
  .venv\Scripts\activate
  # macOS / Linux
  source .venv/bin/activate

  pip install -r requirements.txt
  cp .env.example .env
  ```

### 1.2 可选外部服务与浏览器依赖
- **Chrome / Chromium（Selenium & Playwright）**: 用于 `HTML+KaTeX`、本地 `Mermaid` 降级图表渲染、GitHub 无头抓取降级以及 [`tests/test_webui_e2e_interactions.py`](tests/test_webui_e2e_interactions.py) WebUI E2E 交互测试。
- **Graphviz (`dot`)**: 加入系统 `PATH` 后，[`utils/lite_render.py`](utils/lite_render.py) 可使用原生 Graphviz 渲染轻量结构图。
- **Local Stable Diffusion WebUI**: 可选启动 `http://127.0.0.1:7860`（需开启 `--api` 参数），作为通义万相 `Qwen-Image` 不可用时的二级 AI 生图备选。

---

## 2. 模块化架构总览

系统通过 [`core/engine.py`](core/engine.py) 对外暴露统一入口，支持 CLI（[`main.py`](main.py)）与 Web 控制台（[`webui.py`](webui.py)）双模式驱动：

```text
├── core/
│   ├── engine.py              # 统一任务分发中心: hotspots / github / aikepu / daily_knowledge
│   ├── db/
│   │   ├── models.py          # ArticleHistory ORM 模型 (status / quality_score / fact_check_result 等)
│   │   └── manager.py         # SQLite WAL 线程安全单例管理器 (data/auto_publish.sqlite)
│   ├── pipeline/
│   │   ├── nodes.py           # 流水线节点输入输出协议与上下文数据结构
│   │   ├── engine.py          # PipelineEngine 节点编排器
│   │   └── critic.py          # AI Critic 自动质检修复、评分与 REJECTED 门禁拦截
│   ├── plugins/
│   │   ├── base.py            # BaseSourcePlugin / HotspotItem 抽象基类
│   │   ├── manager.py         # PluginManager 动态源调度与健康度追踪
│   │   ├── hotspots_sources.py# 12 路热点源插件实现
│   │   └── github_source.py   # GitHub 开源项目数据插件
│   ├── hotspots/
│   │   ├── processor.py       # 热点主题聚类、大纲/正文生成与图谱过滤
│   │   ├── scraper.py         # Trafilatura 正文提取 + 浏览器伪装请求降级
│   │   ├── searcher.py        # DuckDuckGo (HTML/Lite) + Bing 实时联网事实搜索
│   │   ├── narrative.py       # 4 种叙事原型 × 4 种黄金开篇钩子动态策略器
│   │   └── workflow.py        # 热点端到端流水线
│   ├── github/
│   │   ├── collector.py       # Trending + Search 采集、截图抓取与 Demo 识别
│   │   ├── processor.py       # GitHub 技术深潜写作提示词与成文器
│   │   └── workflow.py        # GitHub 流水线与多图并行抓取
│   ├── aikepu/
│   │   ├── skill_tree.py      # 知识图谱 DAG 解析、前置依赖检查与状态同步
│   │   ├── processor.py       # Phase 1 Outline -> Phase 2 Flash Prompt 优化 -> Phase 3 并行 Sub-Agent
│   │   └── workflow.py        # 体系科普流水线
│   └── shared/
│       ├── llm.py             # DeepSeek/OpenAI 路由、可中断重试、Prompt Cache 统计
│       ├── publisher.py       # 微信 Token 锁、草稿上传、4 层标题防重、企微通知
│       ├── article_utils.py   # Linear Modern Light 微信内联排版 & 配图/图表并行替换
│       └── runtime.py         # Loguru 实时日志队列、cancel_event / pause_event 控制信号
├── daily_knowledge/           # 每日小知识独立工作流 (engine/workflow/deduplicator/database/llm_client)
├── tools/                     # 零访谈风格分析 (analyze_account.py) & 知识库构建 (build_knowledge_tree.py)
├── utils/                     # 生图链、5 模图表引擎、KeyPool、HTTP Session、反爬工具
└── templates/ & static/       # Linear Modern Light 零构建 ES Module 前端工程
```

---

## 3. 核心机制与扩展契约

### 3.1 统一控制信号与线程安全（必须遵守）
所有耗时操作、网络轮询与并发任务均必须兼容 [`core/shared/runtime.py`](core/shared/runtime.py) 的信号机制：
- **`cancel_event` (`threading.Event`)**：WebUI 点击「停止」时置位，循环与耗时步骤须调用 `check_cancelled()`。
- **`pause_event` (`threading.Event`)**：WebUI 点击「暂停」时清除，`check_cancelled()` 内部自动阻塞等待恢复。
- **`_interruptible_sleep()`**：禁止在工作流内部直接调用长时间 `time.sleep()`，防止任务卡死无法即时停止。
- **网络 Session 复用**：统一使用 [`utils/http_client.py`](utils/http_client.py) 提供的 `build_api_session()` 或 `build_cached_session()`，禁止裸用 `requests.get`。

### 3.2 新增热点信息源插件
1. 在 [`core/plugins/hotspots_sources.py`](core/plugins/hotspots_sources.py) 继承 `BaseSourcePlugin` 实现抓取方法，返回标准 `HotspotItem` 列表。
2. 在 [`core/plugins/manager.py`](core/plugins/manager.py) 的插件注册流程完成注册。
3. 在 [`config.py`](config.py) 的 `NEWS_SOURCES` 列表添加对应源标识。
4. 在 WebUI [`static/js/views/ops.js`](static/js/views/ops.js) 与 [`static/js/core/i18n.js`](static/js/core/i18n.js) 中补全展示标签，使「运维 → 信源健康矩阵」可探测与展示该信源。

### 3.3 事实核查（Fact Grounding）与动态叙事
- **事实检索链路**：当 `ENABLE_FACT_SEARCH=True` 时，[`core/hotspots/scraper.py`](core/hotspots/scraper.py) 先用 `trafilatura` 抓取原文详情；随后 [`core/hotspots/searcher.py`](core/hotspots/searcher.py) 通过 DuckDuckGo（HTML/Lite 双回退）与 Bing 网页检索补充事件时间线、数据实体（最多 `MAX_FACT_SNIPPETS` 条，默认 `4`）。
- **动态叙事策略**：[`core/hotspots/narrative.py`](core/hotspots/narrative.py) 根据主题匹配写作原型（`investigative_game` / `tech_deep_dive` / `business_war` / `narrative_human`）并分配开篇钩子（`counter_intuitive` / `cost_and_bill` / `critical_scene` / `cognitive_reversal`），防止多篇热文结构趋同。

### 3.4 AI Critic 质量门禁与 SQLite WAL 审计
- [`core/pipeline/critic.py`](core/pipeline/critic.py) 的 `evaluate_and_repair_article()` 在成文后执行：
  1. 标记高频套话，清除可独立删除的段首过渡词。
  2. 将文稿已有小标题提升为 H2，缺少标题时提示审校。
  3. 按文章类型检查汉字长度、标题字符上限与禁用结尾标点，计算综合 `quality_score`。
- **门禁拦截流程**：若评分或硬性规则不达标，文章状态记为 `REJECTED`，渲染预览保存至 `data/previews/fail_*.html`，并写入 [`data/auto_publish.sqlite`](core/db/manager.py)（启用 `PRAGMA journal_mode=WAL` 与 `busy_timeout=30000` 防并发锁死）。人工可在 WebUI `Audit` 审稿台预览并通过 `/api/review/approve` 核准补发草稿箱。

### 3.5 体系科普三阶段并发模型 (`core/aikepu/processor.py`)
1. **Phase 1 (`_generate_outline`)**：结合知识节点元数据与历史脉络生成结构化多节大纲。
2. **Phase 2 (`_optimize_section_prompts`)**：使用 Flash 模型为每节设计差异化论据、排他边界、类比与承接提示词。
3. **Phase 3 (`_run_subagent_worker`)**：使用 `ThreadPoolExecutor(max_workers=min(4, len(optimized)))` 并发生成多节正文并注入前序章节概要，再拼接全局校验。

### 3.6 照片配图与技术图表

- 热点和每日小知识的配图占位符由 `utils/source_photos.py` 检索 Openverse 照片。`core/shared/article_photos.py` 上传实图并渲染署名，对未命中的槽位调用 `download_image(..., allow_title_card=False)`。模型实际返回的图标明「AI 示意图」。封面优先使用实图，AI 封面嵌入同样的标识，实图和生成图均不可用时回退为标题卡。
- GitHub 原图和截图按采集时记录的地址注明出处。体系连载沿用固定封面及图表。Image Studio 支持单独调用通义万相重绘。
- **视觉评估模块 (`utils/image_filter.py`)**：收敛为 `Qwen-VL-Max` + 多维 CV 评分接口（已移除 Gemini Vision 与 Ollama）。
- **技术图表引擎 (`utils/diagram_gen.py`)**：
  - 高保真路线：Mermaid（`mermaid.ink` API → [`utils/html_render.py`](utils/html_render.py) Selenium 本地降级）、HTML + Tailwind + KaTeX 公式/数据面板。
  - 轻量路线：Graphviz DOT（[`utils/lite_render.py`](utils/lite_render.py)）与 Matplotlib 结构化卡片（公式、对比、总结卡）。
  - 微信兼容性：渲染结果统一转换为不透明纯白底图，防止微信黑暗模式/透明 PNG 发黑。

### 3.7 多 Key 轮换池 (`utils/key_pool.py`)
- `LLM_API_KEYS` 与 `DASHSCOPE_API_KEYS` 支持逗号分隔多个 Key。
- 线程安全 Round-Robin 调度；遇到 429 限流默认冷却 `120s`，遇到 401/403 认证异常冷却 `300s` 并自动切换下一可用 Key。

---

## 4. Linear Modern Light 前端工程开发指南

前端完全去除构建打包步骤（Zero-Build）及 Three.js WebGL 依赖，全部采用原生浏览器支持的 ES Module 与 CSS 变量设计体系：

### 4.1 样式与画布结构 (`static/css/`)
- [`tokens.css`](static/css/tokens.css)：全局色彩、字体排版（Inter / 思源黑体栈）、边框 (`--border`)、阴影与圆角设计令牌。
- [`components.css`](static/css/components.css)：胶囊切换器、按钮、状态徽章、卡片与模态弹窗标准件。
- [`views.css`](static/css/views.css)：4 层纯 CSS `.ambient-canvas`（柔光渐变球 `ambient-blob-1..3` + 精密工程网格 `ambient-grid` + 噪点微纹理 `ambient-noise`）以及 5 视图布局与移动端底部 Dock 响应式规则。

### 4.2 ES Module 结构 (`static/js/`)
- **入口**：[`static/js/main.js`](static/js/main.js) 初始化全局状态、SSE 日志流绑定、视图切换与双语切换。
- **核心层 (`static/js/core/`)**：
  - `api.js`：统一封装后端 `/api/*` 请求（含 `WEBUI_TOKEN` 登录重定向处理）。
  - `state.js` & `storage.js`：前端单向状态树与本地偏好持久化。
  - `i18n.js` & `icons.js`：全量中英文词条映射与零 Emoji 纯矢量 SVG 图标集。
  - `log-parser.js`：将后端 SSE 文本日志解析为 4 阶段 Pipeline Stepper 与 Timeline 手风琴结构。
- **视图层 (`static/js/views/`)**：
  - `console.js`（总控）、`graph.js`（知识图谱）、`audit.js`（审稿台）、`studio.js`（配图重绘工坊）、`ops.js`（信源探测 / APScheduler 调度 / 系统配置热更新）。
- **DOM 契约**：修改 [`templates/index.html`](templates/index.html) 时严禁随意删除 `id`、`data-view`、`data-task`、`data-i18n` 等 JS 绑定锚点；[`templates/login.html`](templates/login.html) 静态资源目录 `/static/` 在 [`webui.py`](webui.py) 中豁免鉴权拦截。

---

## 5. 测试与调试工作流

### 5.1 自动化测试套件 (`tests/`)
仓库共维护 **13 个 Pytest 测试文件**，涵盖核心模型、文章排版、数据库 WAL 迁移、Critic 质量门禁、GitHub 拦截门禁、热点抓取、事实搜索、叙事引擎、AI 生图降级、WebUI 鉴权及浏览器交互：

```bash
# 1. 运行全部核心单元测试与 API 集成测试（无浏览器依赖，日常开发必跑）
python -m pytest tests/ -v --ignore=tests/test_webui_e2e_interactions.py

# 2. 运行 WebUI Playwright 端到端交互测试（需本机安装 Playwright Chromium）
python -m pytest tests/test_webui_e2e_interactions.py -v
```

### 5.2 离线渲染与导入验证脚本 (`scratch/`)
根目录 `scratch/` 下保留有大量专题验证与视觉调优脚本，例如：
- `python scratch/verify_all_imports.py`：快速检查核心模块循环导入与缺失依赖。
- `python scratch/test_daily_knowledge.py` / `python scratch/test_diagram_and_code.py`：离线检验排版与图表样式渲染效果。

---

## 6. 常见故障排查

1. **微信公众号草稿箱推送失败 / `40001` / `40164`**
   - 核查微信公众号后台「基本配置 → IP 白名单」是否已录入当前机器或云端出口公网 IP。
   - 检查 `WECHAT_APP_ID` / `WECHAT_APP_SECRET` 前后是否误带空格；`publisher.py` 会在失效时自动刷新 Token，若云端部署多实例并发抢占 Token 需确保仅保留单活写节点或调整频率。
2. **DashScope 通义生图报 `429` 限流**
   - 检查 `QWEN_IMAGE_MIN_INTERVAL`（默认 `4` 秒）与 `QWEN_IMAGE_MAX_CONCURRENCY`（默认 `1`），或通过 `DASHSCOPE_API_KEYS` 填入多个账号 Key 叠加配额与自动冷却轮换。
3. **HTML+KaTeX 或本地 Mermaid 图表渲染失败**
   - 检查本机是否正确安装 Chrome/Chromium 及对应 Selenium 驱动；临时缺少无头浏览器时，`diagram_gen.py` 会自动降级至 `mermaid.ink`、`Graphviz DOT` 或 `Matplotlib` 兜底渲染。
4. **WebUI 无头服务器静态文件或登录后 401/403**
   - 检查 `.env` 中是否设置了 `WEBUI_TOKEN`，登录页为 `/login`，`/static/` 已放行免鉴权。
5. **SQLite `database is locked`**
   - 确认未多进程同时直接挂载非本地网络盘（如 NFS）下的 `.sqlite` 文件；[`core/db/manager.py`](core/db/manager.py) 已开启 WAL 模式并配置 `busy_timeout=30000`。
