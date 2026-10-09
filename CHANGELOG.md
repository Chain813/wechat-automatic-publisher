# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### 🧬 零访谈内容定制 (Zero-Interview Customization)
- 新增 `tools/analyze_account.py` 客户账号画像分析器：粘贴客户公众号历史文章链接 → 自动扒取正文（`js_content` 解析）→ DeepSeek 提炼 9 维画像（领域/读者/语气/开头钩子/结构/高频主题/雷区/金句风格/配图风格）。
- `build_knowledge_tree.py` 新增 `--samples`（文章链接直接定制）与 `--profile`（画像文件）两种注入方式，知识 DAG 与写作风格文件自动对齐客户账号风格。
- 内置示范：law（法商避坑 10 节点）、tax（财税第一课 6 节点）两套付费级样张。

### 🎁 内容定制工具链 (Content Customization)
- 新增 `tools/build_knowledge_tree.py` 定制知识库生成器：输入主题简报（行业/读者/风格/节点数）→ DeepSeek 自动产出知识 DAG（含每节点专属写作策略）+ 行业写作风格文件，含占位 id 自动修复与结构校验。
- 写作 Skill 文件按主题加载：`prompts/{主题包}_skill.md` 优先，回退默认文件。
- 内置第 4 套示范知识库：「法商避坑」10 节点（小微企业主法律科普），可直接作为付费定制样张。

### 🔑 API Key 轮询制度 (Key Rotation)
- 新增 `utils/key_pool.py` 通用多 Key 轮询池：DeepSeek（`LLM_API_KEYS`）与千问（`DASHSCOPE_API_KEYS`）支持逗号分隔多 Key，429 限流 / 401 欠费 / 403 被禁自动切换下一 Key 并进入冷却（429=120s，认证类=300s）。
- 生图新增 `QWEN_IMAGE_SIZE=1280*720` 分辨率锁定，单张成本锁定在约 ¥0.35。

### 🇨🇳 全栈国产化与配置精简 (Domestic-Only Stack)
- **移除全部境外依赖**: 删除 Gemini（识图）、Pixabay/Pexels/Unsplash/Pollinations（图库）、GitHub Token（限流）等境外服务代码与配置；视觉评估收敛为 Qwen-VL-Max 唯一模型，图源链收敛为「Qwen-Image 生图 → Bing 搜图 → 本地文字卡兜底」。
- **3 个 Key 即可运行**: 必填项精简为 微信公众号 AppID/Secret + DeepSeek + DashScope 千问（一个 Key 覆盖生图+识图）；Settings 页同步改造（千问 Key + 生图/识图模型下拉）。
- **GitHub Actions 免费定时发布**: 恢复每日 8:00 cron，工作流升级为国内栈（DashScope 密钥），历史记录跨运行持久化（SQLite + 历史文件回写仓库），公开仓库零服务器成本。

### 🚀 产品普适化改造 (Product Generalization)
- **体系连载引擎**: AI 科普技能树泛化为多主题知识库连载引擎（`data/knowledge_trees` 内置 AI 科普/职场成长/健康科普三套模板包），WebUI 支持主题包一键切换与自定义知识库 JSON 导入，提示词按主题动态注入。
- **国内生图接入**: 新增通义万相 Qwen-Image-3.0（DashScope 国内直连）：文本生图 + 参考图重绘（图生图），注册为配图首选源；新增 Pixabay 正版图库源。
- **国内识图接入**: 视觉评分默认改用 Qwen-VL-Max（`QWEN_VL_MODEL` 可配，Gemini 备用），国内直连且单张评估成本不足 1 分钱。
- **文章参考图重绘**: 图片工作台新增一键「抓图并重绘」：粘贴公众号文章链接 → 自动抓取参考图 → Qwen-Image-3.0-Pro 重绘为全新原创配图（合规二次创作，替代去水印）。
- **信息源国内化**: GitHub 图片下载自动降级 jsdelivr CDN 镜像；RSS 补充爱范儿/极客公园/量子位等国内 feed。

### 🛠️ 修复与可维护性 (Fixes & Maintainability)
- **修复并收敛视觉评估链路**: 代码硬编码的 `gemini-2.0-flash` 已被 Google 下线导致视觉评分静默失效；模型改为可配置 `GEMINI_VISION_MODEL`（默认 `gemini-3.6-flash`），实测恢复图片 AI 评估。
- **移除 Ollama 本地视觉依赖**: 弃用 gemma3 本地视觉链路（删除 `ollama_startup` / `evaluate_image_with_ollama` 及相关配置与文档），部署不再需要安装 Ollama；视觉评估统一为 Gemini（云端）+ 6 维 CV 双通道。

### 🎨 UI 重写 (UI Rewrite)
- **白色主题全新重构**: 管理后台从暗色玻璃拟态升级为浅色主题，统一设计 token（`--accent` 靛蓝 / `--accent-2` 紫），并加入 Three.js 3D 粒子网络背景。
- **登录页同步换肤**: 云端 Token 登录页从深紫渐变更新为浅色主题 + 3D 背景，云端模式对 `/static/` 静态资源放开认证。
- **图片工作台 token 化**: Image Studio 样式全部改用新版 CSS 变量，面板级圆角统一为 `var(--radius)`。

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
