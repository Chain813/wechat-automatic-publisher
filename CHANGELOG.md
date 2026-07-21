# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

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
