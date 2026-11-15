# AutoWeChat 核心概念与术语表 (Glossary)

本文档用于统一开发团队、运营人员及 AI 协作伙伴在 **AutoWeChat** 项目中的专业术语口径。

---

## 一、四大创作工作流

| 术语 | 英文 / 代码标识 | 定义与职责 |
| :--- | :--- | :--- |
| **综合热点追踪** | `hotspots` | 从 12 路科技/财经/资讯信源采集热点，经关键词初筛、全文深抓、联网事实核查与动态叙事策略后生成深度解读文章。 |
| **GitHub 开源深潜** | `github` | 自动发现 GitHub Trending 或高星开源项目，抓取 README、截图与架构信息，生成工程级开源拆解长文。 |
| **体系科普长文** | `aikepu` / Knowledge Graph Series | 基于多阶梯知识图谱 DAG（内置 5 套垂直主题包），按前置依赖解锁节点，通过大纲、Prompt 优化与并行 Sub-Agent 协同产出系统化长文。 |
| **每日小知识 / 每日百科** | `daily_knowledge` | 位于 `daily_knowledge/` 的独立轻量科普工作流，负责日更级轻量百科选题规划、历史去重、独立 SQLite 记录与快速发布。 |

---

## 二、质量保障与安全发布术语

| 术语 | 英文 / 代码标识 | 定义与职责 |
| :--- | :--- | :--- |
| **人机协同发布** | `Human-in-the-Loop (HITL)` | 系统核心合规原则：所有 AI 生成内容只推送至微信**草稿箱**，配合审稿工作台由人类终审后手动群发，拒绝无监督全自动群发。 |
| **联网事实核查** | `Fact Grounding` (`scraper.py` / `searcher.py`) | 先通过 `trafilatura` 抓取信源原始正文，再经 DuckDuckGo / Bing 实时搜索关键事实片段注入写作上下文，减少大模型幻觉。 |
| **动态叙事引擎** | `Dynamic Narrative Engine` (`narrative.py`) | 将文章拆分为 4 种叙事原型与 4 种开篇钩子的动态组合，打破传统固定提示词造成的“八股文”同质化。 |
| **AI Critic 质量门禁** | `Critic Gate` (`core/pipeline/critic.py`) | 发文前的自动质检关卡：自动清洗 AI 套话、补全 H2 结构、校验字数与标题规范；不达标稿件状态置为 `REJECTED` 并落地 `data/previews/fail_*.html`。 |
| **HITL 审稿工作台** | `Audit Workbench` (`audit` 视图) | WebUI 第三核心视图，支持预览通过或被拦截的文章全文，核准后通过 `/api/review/approve` 直推微信草稿箱。 |
| **四层标题防重** | `4-Layer Title Dedup` (`publisher.py`) | 合并微信云端草稿箱、公众号已发布列表与本地数据库，依次执行精确匹配、字符模糊匹配、关键词重叠度校验与 AI 语义兜底查重。 |

---

## 三、视觉引擎与前端控制台

| 术语 | 英文 / 代码标识 | 定义与职责 |
| :--- | :--- | :--- |
| **Linear Modern Light** | Design System | 项目统一采用的浅色工程级极简美学体系（`#FFFFFF` / `#F8F9FB` 高对比表面 + `#4F5BD5` 靛蓝点缀），同时贯穿于 WebUI 控制台、微信正文排版与技术图表卡片。 |
| **4 层微光网格画布** | `.ambient-canvas` (`views.css`) | 纯 CSS 实现的轻量动态背景（3 组渐变光斑 + 工程网格 + 噪点微纹），已彻底替代旧版重型 Three.js 3D 粒子网络。 |
| **零构建 ES Module** | Zero-Build Frontend (`static/js/`) | 不依赖 Webpack/Vite 打包，由浏览器直接加载 `main.js`、`core/` 与 `views/` 原生模块，包含 `console` / `graph` / `audit` / `image` / `ops` 五大视图。 |
| **100% AI 生图容错链** | `image_handler.py` | 已禁用热点场景下的 Bing 爬虫抓图，统一采用「`Qwen-Image-3.0` → 本地 `Stable Diffusion` → Pillow 矢量卡片」三级纯生成链路。 |
| **5 模并行图表引擎** | `diagram_gen.py` | 按需调度 `Mermaid`、`HTML+Tailwind+KaTeX`、`Graphviz DOT` 与 `Matplotlib` 结构体卡片（公式/对比/总结）的并行绘制引擎，自动修复微信端透明背景发黑问题。 |
| **配图合规重绘工作台** | `Image Studio` (`image` 视图) | 支持解析任意公众号文章链接参考图并用 `Qwen-Image-3.0-Pro` 原创重绘，同时支持 Markdown 占位符提取、拖拽上传与 1:1 手机预览。 |

---

## 四、知识定制与运维基础设施

| 术语 | 英文 / 代码标识 | 定义与职责 |
| :--- | :--- | :--- |
| **零访谈账号定制** | Zero-Interview Customization (`tools/`) | 通过 `analyze_account.py` 自动从历史文章萃取 9 维账号画像，再由 `build_knowledge_tree.py` 全自动生成知识图谱 DAG 与行业写作 Skill Prompt。 |
| **多领域知识包** | Knowledge Packs (`data/knowledge_trees/`) | 内置 `aikepu`、`career`、`health`、`law`、`tax` 5 套领域图谱 JSON，并通过 `_active.txt` 与 `prompts/{slug}_skill.md` 热切换生效领域。 |
| **多 Key 轮换池** | `KeyPool` (`utils/key_pool.py`) | 支持 `LLM_API_KEYS` 与 `DASHSCOPE_API_KEYS` 逗号分隔多组 Key 线程安全轮询与 429/401/403 自动冷却。 |
| **Prompt Cache 遥测** | Cache Telemetry (`llm.py`) | 在控制台顶部实时追踪 LLM 上下文缓存命中率、节省 Token 数量与节省人民币成本。 |
| **控制信号机制** | `cancel_event` / `pause_event` | 基于 `threading.Event` 的实时中断与暂停信号，确保一键 Stop/Pause 可快速安全响应。 |
| **云端无状态模式** | `CLOUD_MODE=1` | 针对 GitHub Actions 或 Render 等无状态云环境的保护开关，强制优先同步微信云端记录并保护本地仓库历史不被误覆写。 |
| **GitHub Token** | `GITHUB_TOKEN` | 可选的 GitHub API 个人访问令牌（PAT），用于提升 `github` 开源项目发现与仓库检索的 API 速率限制。 |
