# CLAUDE.md — AutoWeChat 项目指南

## 项目概述

AutoWeChat 是微信公众号全自动内容生产与发布系统。集成 12 源热点监控、AI 选题、深度文章创作、智能配图、一键发布。

## 技术栈

- Python 3.8+ / Flask / Loguru
- DeepSeek LLM（文章生成、选题、摘要）
- 通义千问 Qwen-VL（识图评估）+ Qwen-Image（生图），DashScope 一个 Key 国内直连
- Selenium（浏览器截图）
- Stable Diffusion（AI 生图）
- PyGithub（GitHub API）
- 微信公众号 API（草稿发布）

## 项目结构

```
├── main.py                    # CLI 入口 (--task hotspots/github)
├── webui.py                   # Flask Web 管理界面
├── config.py                  # 全局配置中心
├── data/                      # 数据库与运行时配置目录
│   ├── auto_publish.sqlite    # 标题去重与发布历史 SQLite 数据库
│   ├── knowledge_trees/       # 知识体系主题包（AI科普/职场/健康/自定义）
│   ├── aikepu_skill_tree.json # 旧版 AI 科普技能树结构（向后兼容）
│   ├── aikepu_history.json    # 已发布节点历史（自动生成）
│   └── hotspot_cache.sqlite   # 网络请求缓存数据库（自动生成）
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
│   ├── image_prompt_gen.py    # 提示词提取与移动端渲染引擎 (Image Studio)
│   ├── image_filter.py        # 图片评分（6 维 CV + 视觉 AI）
│   ├── http_client.py         # HTTP Session（缓存 + 重试）
│   └── spider.py              # Selenium 隐身浏览器
├── static/                    # 前端 CSS/JS
└── templates/                 # Flask HTML 模板
```

## 核心架构

### 工作流

1. `run_main()` → `sync_local_history_with_wechat()` → `run_hotspots_workflow()`、`run_github_workflow()` 或 `run_aikepu_workflow()`
2. 热点：`fetch_all_hotspots()` → `filter_tech_hotspots()` → `generate_article()` → `process_article_content()` → `add_draft()`
3. GitHub：`fetch_one_worthy_project()` → `_ensure_deep_images()`（并行）→ `generate_github_article()` → `process_article_content()` → `add_draft()`
4. AI科普（三阶段 Map-Reduce 提示词自优化）：`select_next_node()` → Phase 1: `generate_outline()` (生成大纲) → Phase 2: `optimize_prompts()` (LLM 针对大纲每一节做排他、类比和钩子自优化) → Phase 3: `generate_sections_serial()` (串行生成，每节引入前一节末尾 500 字上文) → `process_article_content()` → `add_draft()`

### 控制信号

- `cancel_event`（threading.Event）：用户点 Stop 时置位，所有关键节点检查
- `pause_event`（threading.Event）：用户点 Pause 时清除，`check_cancelled()` 中 `wait()`
- `WorkflowCancelled`：cancel 时抛出的异常，被 `run_workflow_thread` 捕获

### 并发模型

- 热点发布：外层 `ThreadPoolExecutor` 并行多篇，内层并行（资产 + 摘要）
- GitHub 配图：`_ensure_deep_images` 用 `ThreadPoolExecutor` 并行 6 种图片来源，集满 3 张即停
- 封面生成：与文章创作并行（不依赖文章内容）
- 架构图绘制：`DIAGRAM_PARALLEL_WORKERS` 控制多线程 Chrome/Graphviz 实例的绘图并发度
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

### 新增知识体系主题包（含零访谈定制）

1. 零访谈定制：`python tools/build_knowledge_tree.py "主题名" --slug law --nodes 12 --samples "客户文章链接1,链接2" --activate`（自动扒取客户历史文章 → `tools/analyze_account.py` 提炼画像 → 按画像生成知识库与风格文件）
2. 半自动生成：`python tools/build_knowledge_tree.py "主题名" --slug law --nodes 12 --audience "目标读者" --tone "风格关键词" --activate`
3. 手动创建：`data/knowledge_trees/{name}.json`（结构：meta.name/column_name + nodes[{id,title,tags,prerequisites,difficulty,summary,custom_prompt}]）
4. 写作风格：`prompts/{name}_skill.md`（引擎自动按激活主题加载，缺省回退 `aikepu_writing_skill.md`）
5. 激活：WebUI 技能树页下拉切换，或设环境变量 `KNOWLEDGE_TREE={name}`

### 调整 WebUI 主题与样式

- 设计 token：`static/css/style.css` 的 `:root`（`--accent`、`--bg`、`--radius` 等；旧变量名在 `:root` 末尾保留别名）
- 3D 粒子背景：`static/js/three-bg.js`（粒子数量、连线距离、颜色数组、鼠标跟随参数）
- 主页面模板：`templates/index.html`（`id` / `data-i18n` / `data-target` / `data-task` 属性不可删，JS 逻辑依赖）
- 登录页模板：`templates/login.html`（云端 Token 模式；`/static/` 已在 `webui.py` 豁免认证）

## 本地服务依赖

- **Stable Diffusion**：`http://127.0.0.1:7860`（需启动 `--api` 模式）
- **Graphviz**：系统 PATH 中（diagrams 架构图需要）
