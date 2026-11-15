---
name: auto-wechat-lifecycle-delivery
description: >-
  Use when developing, refactoring, fixing bugs, writing articles, or optimizing
  the AutoWeChat pipeline to enforce code safety, factual accuracy, anti-scraping resilience,
  and closed-loop delivery.
---

# AutoWeChat Lifecycle & Engineering Skill (微信全自动发布系统研发规范)

## 0. 智能体工程自律准则（八荣八耻）

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
   严禁留存半成品；交付前必须验证 SQLite 标题去重生效、发布历史正常落库、`.env` 敏感凭据脱敏以及 CHANGELOG 文档同步更新。

---

## 1. 核心流水线与开发约束

- **网络请求统一封装**：严禁裸写 `requests.get/post`，必须使用 `build_api_session()` 或 `build_cached_session()`。
- **大模型重试防击穿**：LLM 调用统一通过 `core/shared/llm.py` 的 `call_deepseek_with_retry()` 调度，确保支持可中断与自动指数退避。
- **微信 API 与多线程安全**：微信 Token 刷新使用单例并加线程锁保护；所有后台批处理循环必须实时响应 `cancel_event` 与 `pause_event` 控制信号。
- **样式注入与格式后处理**：
  - 红色重点：`**{{核心结论}}**` 自动转换为 `<strong style="color: #d73a49">`；
  - 黑色粗体：`**重要概念**` 自动转换为 `<strong style="color: #1a1a1a">`；
  - 配图占位符：`【此处插入配图：关键词】` 自动触发多源配图下载与微信 CDN 上传替换。
