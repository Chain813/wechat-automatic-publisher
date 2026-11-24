# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### 发布可靠性与审稿台

- 微信建稿前持久化投递尝试。断连后可核对本次发送标识；已收到微信回执时可直接补记本地历史。审稿台展示对应状态，并阻止重复点击再次建稿。
- 微信列表分页对账，按公众号隔离凭据与历史。知识树节点分树记录，Web 与 CLI 并行写历史时使用跨进程锁。
- 四个栏目、总控台和 CLI 共用执行结果。部分成功退出码为 2，取消为 130。日志支持多标签页独立读取。
- Actions 定时运行热点栏目，通过独立账号分支保全加密的恢复记录。若 runner 在保存回执前中断，后续自动运行会停在账号预留步骤；管理员应先核对该次运行及微信草稿，恢复可信状态后再清理对应的 inflight 分支。
- 重绘下载逐跳核验公网地址、限制响应大小；默认封面随仓库提供。存量 SQLite 库升级时校验投递标识和账号字段。

### 公众号名称、写作与配图

- 默认公众号名为 **极研JiYan**。文章作者默认沿用公众号名，两者可以通过 `BRAND_NAME` 和 `ARTICLE_AUTHOR` 单独配置。写作模板与标题卡使用同一配置。
- 热点稿修订时保留原始材料。热点与项目解读要求把事实、推断和未披露的信息写清楚，质检仅自动删除可独立移除的段首套话。
- 热点和每日小知识优先使用带署名的 Openverse 资料照片。缺图时尝试 AI 生图，正文图下注明「AI 示意图」，AI 封面直接嵌入标识。生图失败且封面仍缺失时使用公众号标题卡。GitHub 项目原图与截图标记来源。
- 热点选题梯队重构为 `config.py` 中的 `HOTSPOT_TIERS` 唯一配置源（同步更新 AI/科技政策、硬核 AI/开源工程与高校科研/考研升学/科技财经三梯队关键词）并接入 `filter_tech_hotspots()` 动态生效；补齐私有云端增量部署闭环规范。
- 修复 `deepseek-v4-flash` 默认思考模式占用全部 `max_tokens=8192` 导致长文正文为空或被截断的问题：新增 `LLM_ENABLE_THINKING`（默认 `False`）并将默认 `LLM_MAX_TOKENS` 提升至 `16384`，补充 `finish_reason`/`reasoning_tokens` 诊断日志与思考耗尽自动降级重试。
- 热点内容引擎重构为三段式解耦架构：Stage 1 使用 `deepseek-flash` 原生 `deepseek_web_search` + `deepseek_read_url` 进行多信源深调研；Stage 2 使用 `deepseek-v4-pro`（`reasoning_effort="low"`）执行无格式紧箍咒纯写作（去审稿笔录腔、自然字数下限 1500 字）；Stage 3 由快速模型独立完成红字/加粗/金句/配图排版标注；`Critic` 新增 AI 内部审稿元话语拦截。
- 统一各工作流文末落款为可配置项 `ARTICLE_SIGNATURE`（默认 `**关注「极研JiYan」，只讲有出处的科技门道与深度拆解。**`），并对齐「终极钻研」品牌定位。
- 热点信源扩容至 14 路中国大陆直连采集并加固长效连通性：新增带三层容灾兜底（Algolia → 官方 RSS → Firebase）的 `HackerNewsPlugin` 与双通道兜底的 `WallStreetCNPlugin`；升级 `ThirtySixKrPlugin`（官方 Gateway 快讯 JSON API 优先 + WAF 校验过滤）与 `HuxiuPlugin`（官方 RSS 优先 + `articleList` API 兜底）绕过网页端 WAF 拦截；`RSS_FEEDS` 清理失效/重复源并扩充至 10 路国内直连高质量科技 RSS（InfoQ / Solidot / 开源中国 / 量子位 / 爱范儿 / 极客公园 / 钛媒体 / 雷峰网 / 少数派 / GitHub Blog）；重构 `RssPlugin` 为并发抓取 + 单源故障隔离 + 轮询公平交错合并；升级信源熔断器支持冷却到期（默认 `SOURCE_CIRCUIT_COOLDOWN_SECONDS=1800`）自动半开恢复；扩容 HTTP 连接池至 32 并优化 `/api/sources/test` 实测延迟与展示名上报。
- 深化 AI 示意图生图提示词与视觉管线：将 `Qwen-Image-3.0` 提示词从「禁文字的泛科技概念插画」全面升级为「16:9 宽屏横版浅色科技商业杂志编辑信息图（Editorial Infographic）」体系；强制左中右横向并排 / 左右双栏对比 / 左图右卡三大宽屏原型，严禁竖版与纵向堆叠，并将每卡文字限制为「1 短标题 + 1 行简短标注」杜绝小字乱码；新增线程局部生图上下文透传与轻量 LLM 视觉导演（差异化顶部标签并智能关闭 `prompt_extend` 防改字）；Stage 3 同步升级为结构化 `标题｜要点` 配图标记并直连信息图生成，跳过无效境外图库超时。

### 🔍 事实核查、动态叙事与 AI Critic 质量门禁 (Fact Grounding & Quality Gate)
- **联网事实核查与正文深抓**：新增 `core/hotspots/scraper.py`（基于 `trafilatura` 与浏览器伪装请求提取原始网页正文）及 `core/hotspots/searcher.py`（DuckDuckGo HTML/Lite 与 Bing 网页事实检索，由 `ENABLE_FACT_SEARCH` / `MAX_FACT_SNIPPETS` 控制），为深度创作提供可核查事实现场。
- **动态叙事防套话引擎**：新增 `core/hotspots/narrative.py`，支持 4 种写作原型（`investigative_game` / `tech_deep_dive` / `business_war` / `narrative_human`）× 4 种黄金开篇钩子动态调度。
- **Critic 自动质检门禁与 HITL 审稿台**：新增 `core/pipeline/`（`PipelineEngine`、`nodes.py`、`critic.py`），自动清洗常见 AI 套话、补齐缺失 H2 小节并执行多维评分；拦截稿件标记为 `REJECTED`、预览落地至 `data/previews/fail_*.html` 并同步 `data/auto_publish.sqlite`（WAL 模式），通过 WebUI `审稿 (Audit)` 视图支持人工复核与 `/api/review/approve` 直推微信草稿箱。

### 🎨 Linear Modern Light 全新前端与微信正文排版重构
- **WebUI 五维零构建控制台**：全面重构前端为 **Linear Modern Light** 浅色设计体系（`tokens.css` / `components.css` / `views.css` + 4 层纯 CSS `.ambient-canvas` + 零构建原生 ES Module `static/js/core/` 与 `static/js/views/`），支持桌面端分段导航与移动端底部 Dock 双端适配，整合为 `总控 (console)`、`图谱 (graph)`、`审稿 (audit)`、`配图 (image)`、`运维 (ops)` 五大核心视图及 ZH/EN 实时切换。
- **微信正文 Linear Light 排版**：升级 `core/shared/article_utils.py`，支持沉降式代码块卡片、对比数据表格与 Highlight Callout 提示框，并优化 H2/H3 标题层级与可阅读性。
- **前端工程清理**：正式移除旧版单文件样式 `static/css/style.css` 与 Three.js 3D 粒子网络背景（`three-bg.js` / `three.min.js`），显著降低首屏负载。

### 📚 每日小知识工作流与并发图表引擎 (`daily_knowledge` & `diagram_gen`)
- **每日百科工作流**：新增 `daily_knowledge/` 独立模块（专属 `engine.py`、`workflow.py`、`deduplicator.py` 与 `data/daily_knowledge.sqlite`），支持 `--task daily_knowledge` 独立或定时运行。
- **体系科普 Phase 3 并行生成**：重构 `core/aikepu/processor.py` Phase 3，由串行改为 `ThreadPoolExecutor`（最多 4 并发 Sub-Agent Worker）协同撰写。
- **5 模多模态技术图表引擎**：升级 `utils/diagram_gen.py` 与 `utils/lite_render.py` / `utils/html_render.py`，统一 Mermaid、`HTML+Tailwind+KaTeX`、Graphviz DOT 与 Matplotlib 卡片（公式/对比/总结）的 Linear Modern Light 浅色配色，支持 `DIAGRAM_PARALLEL_WORKERS=5` 并行渲染与微信透明 PNG 白底兼容转换。

### 🖼️ 100% AI 生图收敛与境内基础设施优化
- **纯 AI 生图容错链**：`utils/image_handler.py` 主配图与封面生成已禁用热点 Bing 爬虫抓取，收敛为「`Qwen-Image-3.0`（含并发与间隔限流，`QWEN_IMAGE_SIZE=1280*720`）→ 本地 `Stable Diffusion` → 本地 Pillow Linear Modern Light 矢量封面卡片」三级链路；Image Studio 参考图合规重绘模型升级为 `qwen-image-3.0-pro`。
- **移除境外与重型本地依赖**：彻底移除 Gemini Vision、Ollama 本地视觉、Pixabay/Pexels/Unsplash/Pollinations 图库代码与配置（保留可选 `GITHUB_TOKEN` 提升 GitHub API 限额），视觉评估模块收敛为 `Qwen-VL-Max` (`utils/image_filter.py`)；清理遗留 `_try_icrawler_bing()` 死代码与 `requirements.txt` 中的 `icrawler` 依赖，并同步更新 `Dockerfile`、`docker-compose*.yml`、`render.yaml` 与 `.github/workflows/trigger.yml`。
- **多 Key 线程安全轮换池**：新增 `utils/key_pool.py`，支持 `LLM_API_KEYS` 与 `DASHSCOPE_API_KEYS` 逗号分隔多 Key 轮询与 429/认证异常冷却（120s / 300s）。

### 🧬 零访谈账号定制与多领域知识包 (Customization & Knowledge Packs)
- **零访谈风格克隆**：新增 `tools/analyze_account.py` 账号画像分析器与 `tools/build_knowledge_tree.py` 定制知识库生成器（支持 `--samples` / `--profile`），自动生成 DAG 知识图谱与 `prompts/{slug}_skill.md`。
- **内置 5 套领域图谱**：`data/knowledge_trees/` 内置 `aikepu`（30 节点）、`career`（10 节点）、`health`（8 节点）、`law`（10 节点）与 `tax`（6 节点），配合 `law_skill.md`、`tax_skill.md` 等领域写法规范与 `_active.txt` 热切换。
- **运维与自动化加固**：升级 [`.github/workflows/trigger.yml`](.github/workflows/trigger.yml) 与容器清单，支持持久化数据库与多工作流定时调度；新增 13 个 Pytest 单元、集成及 WebUI 交互测试套件（`tests/`）。

## [4.3.0] - 2026-07-21

### ✨ 新特性 (New Features)
- **图片工作台 (Image Studio)**: 推出全新的前端可视化配图工作台。支持从 Markdown 文章一键提取 `【此处插入配图：xxx】` 占位标签，调用 LLM 批量转化为 Imagen 3 / Midjourney 专业英文提示词。
- **拖拽式直观配图**: 前端支持 HTML5 原生拖拽上传图片至对应卡片，支持实时进度条、缩略图展示、一键复制 Prompt 及替换/删除。
- **高保真移动端预览**: 后端根据拖拽上传的图片映射动态替换文章占位符，渲染符合微信公众号排版标准的移动端预览弹窗。

### ♻️ 架构重构与优化 (Refactoring & Optimization)
- **解耦与清理自动化生图**: 彻底移除不稳定的 Gemini Selenium 网页自动化生图模块及会话缓存，降级策略调整为高清免费图源搜索，大幅提升系统稳定性与纯净度。
- **代码库级规范审计**: 修复了 SQLAlchemy 规范布尔过滤、PIL `ImageDraw`/`ImageFont` 引用及冗余 f-string，全项目通过 `ruff check` 零警告标准。
- **完善全量自动化测试**: 适配历史数据同步引擎与单元测试 mock 机制，18 个自动化测试全部通过 (18 passed)。

## [3.0.0] - 2026-07-16

### ✨ 新特性 (New Features)
- **AI 科普工作流 (AI Kepu)**: 基于预设技能树 DAG（有向无环图）的全新内容管线，系统化输出从入门到前沿的教育科普文章。
- **Web UI 控制台**: 全新的 Flask 暗色主题仪表盘，支持一键启停任务、实时日志查看和数据源健康状态监控。
- **标题去重增强**: 引入双端活跃标题查重机制（本地数据库 + 微信云端草稿箱同步），配合 4 种查重策略彻底杜绝重复发布。

### ♻️ 架构重构与优化 (Refactoring & Optimization)
- **数据库替换**: 将原有的基于 `json` 存储的历史发布记录平滑迁移至 `SQLite`，彻底解决并发写入冲突问题，提高查询效率。
- **插件化数据源**: 采用 `PluginManager` 动态加载数据源，12 个热点采集平台全部实现插件化重构，支持独立健康度监控与自动降级。
- **代码库级 Clean Code**: 清理了历史版本遗留的僵尸代码和无用引用，实现了全项目严格的 Flake8 零错误/零警告标准。

### 🐛 Bug 修复 (Bug Fixes)
- 修复了 `reset_source_health` 未导出导致每次工作流启动时直接引发 `ImportError` 崩溃的致命错误。
- 修复了 AI 科普发布失败时 `logger.warning` 因参数不匹配导致的二次字符串格式化异常。
- 修复了 `webui.py` 中重复声明 `_start_lock` 带来的潜在线程安全隐患。
