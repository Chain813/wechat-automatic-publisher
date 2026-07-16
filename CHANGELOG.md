# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

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
