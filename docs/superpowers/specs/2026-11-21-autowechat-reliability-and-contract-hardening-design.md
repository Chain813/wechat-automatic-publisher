# AutoWeChat 稳定性、前后端契约与安全加固设计文档

- **日期**: 2026-11-21
- **范围**: 方案 A — 5 模块定点加固 + 全量回归测试闭环
- **非目标 (Non-Goals)**: 不拆分 `webui.py` 为多 Blueprint，不更换云端 systemd/WSGI 启动形态，不改动文章写作风格与前端 Linear Modern Light 视觉设计体系。

---

## 1. 目标与总体架构

本次加固围绕 AutoWeChat 现有的 4 条内容流水线（`hotspots` / `github` / `aikepu` / `daily_knowledge`）、公共设施层（`publisher` / `llm` / `runtime` / `http_client` / `image_handler`）以及 Flask + ES Module 五维 WebUI，在不破坏既有 156 条测试契约的前提下，消除已核实的 **P0 崩溃/数据损坏/功能失效**、**前后端字段错配** 与 **云端安全/CI 隐患**。

改动划分为 5 个边界清晰、可独立单测的模块：

1. **模块 1 · 知识体系与工作流核心修复**（`core/aikepu/`、`core/hotspots/`、`core/engine.py`、`utils/image_handler.py`）
2. **模块 2 · 发布器、HTTP、配置热更新与每日百科收口**（`core/shared/`、`utils/http_client.py`、`utils/key_pool.py`、`daily_knowledge/`、`core/hotspots/searcher.py`）
3. **模块 3 · WebUI 前后端契约全对齐**（`webui.py`、`templates/index.html`、`static/js/`）
4. **模块 4 · 安全、游标日志缓冲与自动化基线**（`core/shared/runtime.py`、`webui.py`、`.github/workflows/trigger.yml`、`pytest.ini`）
5. **模块 5 · 回归测试与文档闭环**（`tests/`、`CHANGELOG.md`）

---

## 2. 模块详细设计

### 2.1 模块 1：知识体系与工作流核心修复

1. **修复知识树缓存重置崩溃 (`core/aikepu/skill_tree.py`)**
   - `_tree_cache` 始终保持 `dict` 类型。
   - `reconcile_history_file()`（原第 331 行）与 `reset_tree_cache()`（原第 781 行）改为在 `_tree_lock` 保护下执行 `_tree_cache.clear()`，禁止赋值为 `None`。
2. **修复主题包激活优先级 (`core/aikepu/skill_tree.py`)**
   - `get_active_tree_name()` 改为优先读取持久化的 `_active.txt`（用户在 WebUI 切换写入的指针），仅在 `_active.txt` 不存在或为空时回退读取 `os.getenv("KNOWLEDGE_TREE")` 与默认值 `"aikepu"`；`set_active_tree()` 切换后同时刷新缓存。
   - 保持环境变量覆盖在无 `_active.txt` 的无头容器/CI 环境照常生效。
3. **修复 `set_node_status` SQLite `NOT NULL` 失败 (`core/aikepu/skill_tree.py`)**
   - 手动插入 `ArticleHistory` 记录时显式写入 `publish_date=datetime.now().strftime("%Y-%m-%d")`、`status="APPROVED" if is_pub else "DRAFT"`。
4. **补齐 `get_skill_tree_stats()` 契约字段 (`core/aikepu/skill_tree.py`)**
   - 保留原有全部字段（`total`/`published`/`draft_count`/`total_count`/`published_count`/`available`/`progress_pct`/`difficulty_distribution`），新增前端所需别名与派生字段：
     - `total_nodes`: `total`
     - `available_count`: `available`
     - `locked_count`: `max(0, total - published - draft_count - available)`
     - `next_recommended_topic`: `available_nodes[0]["title"]`（无可用节点时为空字符串）
5. **打通指定节点撰写链路 (`webui.py` + `core/engine.py` + `core/aikepu/workflow.py`)**
   - `run_workflow_thread(task_type="hotspots", override_node_id=None)` 与 `run_main(task_type="hotspots", override_node_id=None)` 及 `run_aikepu_workflow(publisher, override_node_id=None)` 透传可选 `override_node_id`。
   - `/api/aikepu/generate_node` 先校验目标 `node_id` 存在于当前知识树（不存在返回 400），再将该 `node_id` 传入 `run_workflow_thread("aikepu", override_node_id=node_id)`；`run_aikepu_workflow` 在 `reset_tree_cache()` 之后，若存在 `override_node_id`，直接调用 `select_next_topic(override_node_id=override_node_id)`，不再被 `reset_tree_cache()` 清空。
6. **禁止原地损坏静态 `.png` 资产 (`utils/image_handler.py` + `core/aikepu/workflow.py`)**
   - `resize_for_wechat(img_path, purpose="body")` 写入 JPEG 时：若原路径本身已是 `.jpg`/`.jpeg` 且不属于受保护静态资产（非 `static/` 且文件名非 `default_*`），仍就地保存；否则写入派生路径 `assets/_resized/<stem>_wechat.jpg`（自动建目录）并返回新路径，确保静态素材 `assets/default_aikepu_cover.png`、`static/images/github_fixed_cover.png` 永不被原地改写，且文件扩展名与实际 JPEG 内容/MIME 类型完全一致。
   - `core/aikepu/workflow.py` 封面压缩重试改为写入临时 `.jpg` 文件后再上传，并在 `finally` 中清理临时文件，不再覆写 `default_aikepu_cover.png`。
   - `download_cover_image()` 调用本地 SD 前补齐 `if config.SD_ENABLED` 判断。
7. **消除工作流并发竞态与吞取消异常 (`core/hotspots/workflow.py` + `core/aikepu/workflow.py` + `core/engine.py`)**
   - 将 `hotspots/workflow.py` 的 `reset_image_cache()` 从并行单篇 worker `_generate_article_assets()` 移至 `ParallelPublishNode.execute()` 启动线程池之前执行一次，避免并行线程互清感知哈希去重缓存。
   - `hotspots/workflow.py` `_publish_single_topic()` 与 `aikepu/workflow.py` `_publish_single_topic()` 在 `except WorkflowCancelled:` 分支显式释放预留节点并直接 `raise`，不再落入 `except Exception` 被吞掉或误记为 `FAILED` 文章。
   - `hotspots/workflow.py` `_get_past_topics()` 的布尔过滤改为 `ArticleHistory.success_status.is_(False)`。
   - `core/engine.py` `sync_local_history_with_wechat()` 用 `try/finally` 确保 `db_manager.remove_session()` 始终执行，避免异常时连接泄漏。

---

### 2.2 模块 2：发布器、HTTP、配置热更新与每日百科收口

1. **微信分页拉取、按凭据隔离 Token 与可中断重试 (`core/shared/publisher.py`)**
   - `get_draft_titles(count=WECHAT_DRAFT_SCAN_COUNT)` 与 `get_published_titles(count=WECHAT_DRAFT_SCAN_COUNT)` 遵循微信官方每页最多 20 条的限制：循环按 `page_size = min(20, remaining)` + `offset += page_size` 分页拉取，遇到 `40001`/`42001` 自动刷新一次 Token 重试，且当返回条数 `< page_size` 或已达 `total_count` 时停止。
   - 全局 Token 缓存改为按 `(app_id, app_secret)` 键存储的字典 `_global_tokens[(app_id, app_secret)] = (token, expires_at)`，并提供 `clear_token_cache()` 类方法供配置热更新调用，杜绝换号复用旧 Token。
   - `add_draft()` 内部重试退避改用可中断等待（检查 `cancel_event`）；`_ai_semantic_check` 降级轻量模型仅替换尾部 `-pro`（或包含 `-pro` 片段），并动态读取 `config.LLM_MODEL`、`config.ARTICLE_AUTHOR`、`config.WECHAT_API_TIMEOUT`。
2. **HTTP 传输层仅对幂等方法自动重试 (`utils/http_client.py`)**
   - `_mount_retry()` 将 `allowed_methods` 收紧为 `frozenset({"GET", "HEAD", "OPTIONS"})`，不再在 urllib3 层对非幂等 `POST`（微信新建草稿、LLM 推理、通义生图）做静默重放，避免与上层多 Key 切换和业务重试叠乘。
3. **运行时信号与配置启动门禁 (`core/shared/runtime.py` + `utils/key_pool.py`)**
   - `check_cancelled()` 在 `pause_event.wait()` 唤醒后立即二次检查 `cancel_event.is_set()`，确保「暂停后点停止」立刻抛出 `WorkflowCancelled`。
   - `_validate_config(strict=True)` 同时认可 `LLM_API_KEY` 与 `LLM_API_KEYS`（任意非空即通过）。`configure_runtime(validate=True)` 保留 CLI（`main.py`）严格校验行为；`webui.py` 启动时传 `validate=False`（仅告警缺失项，允许用户进入 WebUI 设置页填写 `.env`，并在实际执行工作流时校验）。
   - `utils/key_pool.py` 的 `RateLimiter.wait()` 改用 `cancel_event.wait(delta)`，中断时立即抛出 `WorkflowCancelled`。
4. **配置热更新闭环与线程安全 (`core/shared/llm.py` + `core/engine.py` + `utils/image_handler.py` + `core/hotspots/searcher.py` + `core/hotspots/scraper.py` + `webui.py`)**
   - `core/shared/llm.py`：
     - `LLMCacheMetrics` 增加 `threading.Lock`，并同时在 `get_stats()` 中返回 `hit_tokens`、`saved_tokens`（与 `hit_tokens` 一致）、`last_latency_ms` 与 `avg_latency_ms`（累计平均延迟）。
     - `call_deepseek_with_retry()` 动态读取 `config.LLM_BASE_URL` / `config.LLM_MODEL` / `config.LLM_TEMPERATURE` / `config.LLM_MAX_TOKENS` / `config.LLM_TIMEOUT` / `config.LLM_MAX_RETRIES`。
     - 提供 `reset_llm_key_pool()` 供配置变更后重建多 Key 池。
   - `utils/image_handler.py`：提供 `reset_qwen_key_pool()`，`_qwen_post_with_rotation()` 内 429 退避改用可中断等待（`cancel_event.wait`），`generate_article_images_batch()` 检查 `_get_qwen_key_pool().size == 0`，`generate_default_cover()` 动态读取 `config.BRAND_NAME`。
   - `core/engine.py`：`run_main()` 动态读取 `config.WECHAT_APP_ID` / `config.WECHAT_APP_SECRET`。
   - `core/hotspots/searcher.py`：保留 `requests.get`/`requests.post` 调用形态以兼容现有 `tests/test_searcher.py` 的 `@patch("core.hotspots.searcher.requests.*")` 测试契约；同时支持模块级 `ENABLE_FACT_SEARCH` 与 `config.ENABLE_FACT_SEARCH` 联动，并在 `webui.py` `POST /api/config` 保存时同步更新 `searcher.ENABLE_FACT_SEARCH`。
   - `webui.py` `POST /api/config`：
     - 同步更新 `config.QWEN_IMAGE_API_KEY`、`config.LLM_API_KEYS`、`config.DASHSCOPE_API_KEYS`、`config.DIAGRAM_PARALLEL_WORKERS`、`config.BRAND_NAME`、`config.ARTICLE_AUTHOR`。
     - 不再粗暴用 `"*" not in str(val)` 过滤全部字段，仅对脱敏密钥字段（`WECHAT_APP_SECRET`、`LLM_API_KEY`、`DASHSCOPE_API_KEY`、`GITHUB_TOKEN`）判断掩码跳过更新。
     - 调用 `reset_llm_key_pool()`、`reset_qwen_key_pool()`、`WeChatPublisher.clear_token_cache()`。
5. **每日百科复用公共基础设施 (`daily_knowledge/llm_client.py` + `daily_knowledge/workflow.py`)**
   - `daily_knowledge/llm_client.py` 委托给 `core.shared.llm.call_deepseek_with_retry()`（保留 `LLMClient` 类签名以兼容外部调用与单测），统一接入多 Key 轮换、Prompt Cache 统计、`loguru` 日志与 `cancel_event` 中断。
   - `daily_knowledge/workflow.py` 接入 `_print_review_report()` 返回值 `all_ok` 到发布门禁判定，并兼容 `result` 非字典时的错误提取。

---

### 2.3 模块 3：WebUI 前后端契约全对齐

严格遵守 `tests/test_webui_refactor.py` 与 `tests/test_webui_auth_and_mobile.py` 的全部硬约束（零 Emoji、每个 JS 模块非空非注释行数 `< 400`、无内联 `<style>`、静态资源版本 `?v=2026`、所有 `getElementById` 在模板中存在）：

1. **知识图谱视图 (`static/js/views/graph.js`)**
   - 分列逻辑：`const tier = Math.min(4, Math.max(1, Number(node.tier ?? node.difficulty) || 1));`；HUD 徽章同步读取 `node.tier ?? node.difficulty ?? 1`。
   - 主题包下拉框：`const packId = tree.name || tree.id;`、`const packLabel = tree.title || tree.name || tree.id;`，正确选中 `packId === res.active`。
   - 未解锁计数：`stats.locked_count ?? Math.max(0, nodes.length - published_ids.length - draft_ids.length - available_ids.length)`（使用 `??` 避免 `0` 被 `||` 覆盖）。
2. **总控遥测栏 (`static/js/views/console.js`)**
   - Cache 遥测兼容读取 `c.saved_tokens ?? c.hit_tokens ?? 0` 与 `c.avg_latency_ms ?? c.last_latency_ms ?? 0`。
   - 图谱进度正确解包 `const stats = t.stats || t;`，读取 `stats.published_count ?? stats.published ?? 0`、`stats.total_nodes ?? stats.total ?? 0` 以及 `stats.next_recommended_topic || stats.available_nodes?.[0]?.title`。
   - 轮询 `/api/status` 改为携带增量游标 `?since=${logCursor}`，避免多标签页互相抢空日志，清空日志时仅推进前端游标。
3. **审稿工作台 (`static/js/views/audit.js`)**
   - 筛选逻辑与后端 `/api/history` 的 `sent`/`unsent` 分桶严格一致：`const isSuccess = Boolean(a.success ?? a.success_status);`，`sent` 筛选 `isSuccess && Boolean(a.is_published)`（已群发），`unsent` 筛选 `!(isSuccess && Boolean(a.is_published))`（含草稿箱未群发、待审与拦截稿）。
   - 移动端卡片 `renderMobileCardHtml` 对齐桌面端使用 `const previewId = a.preview_id || a.draft_id || a.media_id || a.id;`，并补齐删除按钮。
4. **运维视图与设置表单 (`static/js/views/ops.js` + `templates/index.html` + `webui.py`)**
   - `webui.py` `get_scheduled_jobs()` 从 `job.trigger` 或 `job.name` 提取并返回 `cron_expr` 字段；`ops.js` 正确显示 Cron 表达式，并在信源卡片展示失败次数（`info.failures`）。
   - `templates/index.html` 更新模型下拉选项：
     - `#llm-model`：`deepseek-v4-flash`、`deepseek-v4-pro`、`deepseek-chat`、`deepseek-reasoner`、`deepseek-ai/DeepSeek-V3`、`deepseek-ai/DeepSeek-R1`、`qwen-plus`、`qwen-max`。
     - `#qwen-image-model`：`qwen-image-3.0`、`qwen-image-3.0-pro`、`wanx2.1-t2i-turbo`。
     - `#image-gen-model`：`qwen-image-3.0`、`qwen-image-3.0-pro`、`sd-local`（移除已废弃 `imagen-3`）。
   - `ops.js` `setSelect(id, val)` 若后端返回的自定义模型不在预设 `<option>` 中，动态追加一个临时 `<option>` 并选中，彻底杜绝保存时反向覆盖用户自定义的 `.env` 模型名。
5. **连续上传防误锁 (`static/js/core/api.js`)**
   - `computeBodyHash()` 对 `FormData` 按键值摘要（如 `index` + 文件名/大小），不再把所有上传固定为 `'formdata'`，支持 3 秒内向不同槽位连续上传图片。

---

### 2.4 模块 4：安全、游标日志缓冲与自动化基线

1. **线程安全游标日志缓冲 + `/api/status` 免鉴权脱敏 (`core/shared/runtime.py` + `webui.py`)**
   - 在 `runtime.py` 中新增线程安全环形缓冲 `LogBuffer(maxlen=5000)`，每条日志分配单调递增序号 `seq`，提供 `append(msg)`、`get_since(cursor)`、`drain()`（保持旧 `log_queue` 导出向后兼容）。
   - `webui.py` `/api/status` 在 `CLOUD_MODE` 且配置了 `WEBUI_TOKEN` 但请求未携带有效凭证时：**仍返回 HTTP 200**（兼容 Render/健康检查及 `test_webui_auth_and_mobile.py`），但仅返回 `{"is_running": ..., "is_paused": ..., "logs": []}`，**既不泄露日志也不消费缓冲**。
   - 鉴权通过（或本地模式）时：若带 `?since=<int>` 参数，按游标非破坏性读取新增日志并返回 `next_cursor`；若不带 `since`，兼容返回最新日志并支持现有单测断言 `assert "logs" in status_json`。
2. **上传路径穿越、SSRF、XSS 与输入校验 (`webui.py` + `static/js/views/studio.js` + `static/js/views/ops.js`)**
   - `/api/image-studio/upload`：先严格校验 `index` 必须为非负整数（`int(index)` 且 `0 <= idx <= 999`，失败直接返回 400），再用校验后的整型 `idx` 构造文件名，禁止先存盘后转换。
   - `/api/image-studio/redraw`：新增 `_is_safe_public_url(url)` 校验（仅 `http`/`https`、拒绝 `localhost`/回环/内网/链路本地/保留 IP，DNS 解析校验所有目标 IP），拦截 SSRF 返回 400；同样对 `scrape_article_images()` 提取的图片 URL 做安全校验。
   - `/api/preview/<preview_id>`：统一使用清洗后的 `safe_preview_id` 发起后续逻辑，对微信拉回的 `title` 做 `html.escape(title)` 转义。
   - `/api/schedule/add`：校验 `task_type in ("hotspots", "github", "aikepu", "daily_knowledge")`，非法值返回 400。
   - `/api/review/approve`：保留无预览 HTML 时直接人工核准通过的行为（兼容 `test_api_review_approve`）；当检测到本地预览 HTML 且已配置微信凭证但 `publish_and_notify` 失败时，在响应中显式返回 `push_error` 并提示前端告警，不默默吞掉推送失败。
   - `/api/history/delete`：修复 Markdown 关联文件匹配，使用 `os.path.splitext(fname)[0]` 替代误删子串的 `.replace("md", "")`。
   - `studio.js` 与 `ops.js`：所有写入 `innerHTML` 的后端错误文本与动态消息统一经 `escapeHtml()` 转义。
3. **GitHub Actions 定时任务与 Pytest 配置修复**
   - `.github/workflows/trigger.yml`：为 4 个工作流步骤补充 `schedule` 事件默认行为（`github.event_name == 'schedule'` 默认执行 `hotspots`，手动 `workflow_dispatch` 按 `inputs.task_type` 执行），并补齐 `permissions: contents: write`。
   - `pytest.ini`：补充 `pythonpath = .`，使直接运行 `pytest -q` 与 `python -m pytest -q` 一致通过。

---

### 2.5 模块 5：回归测试与文档闭环

- 新增针对性测试文件（如 `tests/test_hardening_fixes.py`）覆盖全部 P0/P1 修复点：
  - `reset_tree_cache()` / `reconcile_history_file()` 后立即 `load_skill_tree()` 不崩；
  - `set_node_status()` 写入 SQLite 包含 `publish_date` 且落库成功；
  - `get_active_tree_name()` 在设置 `KNOWLEDGE_TREE` 环境变量时仍尊重 WebUI 切换的 `_active.txt`；
  - `generate_specific_node` 透传 `override_node_id`；
  - `resize_for_wechat` 不覆盖 `.png` 源文件；
  - `WeChatPublisher.get_draft_titles(count=50)` 正确分 3 页（20+20+10）请求微信接口，且不同凭据不共享全局 Token；
  - `http_client` 不重试 `POST`；
  - `runtime` 支持仅配 `LLM_API_KEYS`、支持 `validate=False`、暂停后停止立即抛 `WorkflowCancelled`；
  - `LLMCacheMetrics` 字段对齐与并发安全；
  - WebUI 安全回归：`/api/status` 云端未鉴权不返回也不消费日志、带 `since` 多消费者互不抢空、upload 非法 `index` 返回 400 且不落盘、redraw 拦截内网 SSRF、`/api/schedule/add` 校验 `task_type`、`/api/schedule/jobs` 返回 `cron_expr`、`/api/config` 热更新 `QWEN_IMAGE_API_KEY` 与 Key 池；
  - 前端静态契约回归：`graph.js` 使用 `difficulty` 和 `tree.name`、`console.js` 读取 `t.stats` 与 `hit_tokens`/`saved_tokens`、`audit.js` 移动端使用 `preview_id`、`index.html` 包含 `deepseek-v4-flash` 与 `qwen-image-3.0`。
- 运行全量 `pytest -q` 确认 100% 通过。
- 同步更新 `CHANGELOG.md`。
- （可选闭环，实施完成后向用户确认）执行 `python deploy_to_server.py` 同步云端并验证健康检查。
