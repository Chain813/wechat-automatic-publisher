# AutoWeChat WebUI Linear Light Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the AutoWeChat WebUI (`templates/index.html`, `templates/login.html`, `static/css/**`, `static/js/**`) into a zero-build, modular ES Modules + Linear Modern Light interface supporting Desktop, iPad/Tablet, and Mobile viewports with a Visual Pipeline Execution Stage and Connected Papers style Knowledge Graph HUD.

**Architecture:** Decompose the legacy monolithic `index.html` (1004 lines) and `app.js` (1495 lines) into 3 modular CSS files (`tokens.css`, `components.css`, `views.css`) and 12 focused ES Modules (`< 400` LOC each) under `static/js/core/` and `static/js/views/`, removing the 608KB `three.min.js` bundle while keeping 100% backward compatibility with all 27 Flask RESTful routes in `webui.py`.

**Tech Stack:** Python 3.11 / Flask (`webui.py`), Semantic HTML5, Vanilla CSS Custom Properties (Linear Modern Light tokens), Native Browser ES Modules (`<script type="module">`), Inline Linear SVG Icons (`stroke-width="1.75"`), Pytest.

---

## File Structure Map

| Operation | File Path | Logical LOC | Responsibility |
| :--- | :--- | :--- | :--- |
| **Modify** | `.gitignore` | 1-2 lines added | Ignore `.superpowers/` brainstorm and plan scratch files |
| **Create** | `tests/test_webui_refactor.py` | ~120 lines | Frontend regression and contract test suite (zero emojis, template contracts, LOC guard, route smoke tests) |
| **Create** | `static/css/tokens.css` | ~110 lines | Linear Modern Light CSS custom properties, 4-Layer Ambient Canvas background, reset, typography scale |
| **Create** | `static/css/components.css` | ~210 lines | 56px top floating segmented bar, mobile 5-tab bottom dock (`>= 44px`), linear cards, buttons, inputs, pills, modal |
| **Create** | `static/css/views.css` | ~260 lines | Responsive view layouts (Console Stepper + Accordions, Graph Dot-grid + HUD, Audit Table + Card Feed, Studio, Ops) |
| **Create** | `static/js/core/icons.js` | ~160 lines | Centralized inline linear SVG dictionary (24 icons, `stroke-width="1.75"`, zero emojis) |
| **Create** | `static/js/core/storage.js` | ~50 lines | Safe LocalStorage wrapper with in-memory fallback for Safari Private Browsing quota errors |
| **Create** | `static/js/core/api.js` | ~90 lines | RESTful fetch wrapper with 3s mutation lock/debounce, JSON parse, error toast dispatch |
| **Create** | `static/js/core/state.js` | ~95 lines | Finite State Machine (`IDLE`, `STARTING`, `RUNNING`, `PAUSED`, `STOPPING`, `COMPLETED`, `ERROR`) and global store |
| **Create** | `static/js/core/i18n.js` | ~80 lines | Chinese/English dictionary dictionary and language toggle engine |
| **Create** | `static/js/core/log-parser.js` | ~110 lines | Pure reducer parsing `GET /api/status` (`logs` array) into structured 4-phase pipeline status and raw buffer |
| **Create** | `static/js/views/console.js` | ~220 lines | Console stage controller: 4-step stepper, workflow selector, phase accordion widgets, timeline/raw toggle |
| **Create** | `static/js/views/graph.js` | ~240 lines | Graph stage controller: 24px dot-grid canvas, 4-tier DAG layout, SVG bezier curves, right HUD / bottom sheet |
| **Create** | `static/js/views/audit.js` | ~190 lines | Audit stage controller: history list, filter pills, batch checkbox selection, approve/delete, preview modal |
| **Create** | `static/js/views/studio.js` | ~180 lines | Studio stage controller: reference redraw, Markdown placeholder prompt extraction, slot cards, image upload |
| **Create** | `static/js/views/ops.js` | ~170 lines | Ops stage controller: secondary segmented tabs (12-source health matrix, Cron scheduler list, settings form) |
| **Create** | `static/js/main.js` | ~110 lines | App entry point: stage switching, mobile dock sync, topbar status updates, visibilitychange wake-up resync |
| **Rewrite**| `templates/login.html` | ~90 lines | Clean Linear Modern Light login card, pure semantic HTML5, zero inline script/style, `?v=2026` |
| **Rewrite**| `templates/index.html` | ~210 lines | Clean semantic HTML5 skeleton for all 5 stages, mobile dock, preview modal, ES Module script tag |
| **Modify** | `webui.py` | 3 lines edited | Strip 3 legacy emojis at line 74 (lock), line 279 (pause), line 293 (play) |
| **Delete** | `static/js/three.min.js` | -608 KB | Obsolete 3D Canvas bundle |
| **Delete** | `static/js/three-bg.js` | -180 lines | Obsolete dark particle script |
| **Delete** | `static/js/app.js` | -1495 lines | Obsolete monolithic JavaScript file |
| **Delete** | `static/js/image-studio.js` | -220 lines | Obsolete separate studio script |
| **Delete** | `static/css/style.css` | -1422 lines | Obsolete monolithic CSS file |
| **Delete** | `static/css/image-studio.css`| -310 lines | Obsolete separate studio stylesheet |

---

## Implementation Tasks

### Task 1: 前端重构契约测试套件与 `.gitignore` 配置

**Files:**
- Modify: `.gitignore`
- Create: `tests/test_webui_refactor.py`

- [ ] **Step 1: 更新 `.gitignore` 忽略临时工件**

打开 `.gitignore`，在文件末尾追加：
```gitignore
# Superpowers brainstorm & plan scratch directories
.superpowers/
```

- [ ] **Step 2: 编写契约与回归测试套件 `tests/test_webui_refactor.py`**

创建 `tests/test_webui_refactor.py`，完整写入自动化验证契约代码：

```python
import os
import re
import pytest
from webui import app


class TestWebUIRefactorContracts:
    """前端重构契约与质量门禁测试套件"""

    EMOJI_PATTERN = re.compile(
        r"[\uD800-\uDBFF][\uDC00-\uDFFF]|[\u2600-\u27BF]|[\u2300-\u23FF]|[\u2B50-\u2B55]|[\u203C-\u2049]"
    )

    EXPECTED_CORE_MODULES = [
        "icons.js",
        "storage.js",
        "api.js",
        "state.js",
        "i18n.js",
        "log-parser.js",
    ]

    EXPECTED_VIEW_MODULES = [
        "console.js",
        "graph.js",
        "audit.js",
        "studio.js",
        "ops.js",
    ]

    def test_templates_have_no_inline_styles_and_link_modular_assets(self):
        """测试 index.html 和 login.html 不含内联 style，且引入版本化模块静态文件"""
        for template_name in ["templates/index.html", "templates/login.html"]:
            assert os.path.exists(template_name), f"缺少必要模板: {template_name}"
            with open(template_name, "r", encoding="utf-8") as f:
                content = f.read()

            # 禁止内联 <style> 块
            assert "<style>" not in content, f"{template_name} 包含内联 <style>，违反模块化规范"
            # 禁止引用已废弃的 three.js 资产
            assert "three.min.js" not in content, f"{template_name} 仍包含废弃 three.min.js"
            assert "three-bg.js" not in content, f"{template_name} 仍包含废弃 three-bg.js"

        # 检查 index.html 专属引入
        with open("templates/index.html", "r", encoding="utf-8") as f:
            index_content = f.read()
        assert "/static/css/tokens.css?v=2026" in index_content
        assert "/static/css/components.css?v=2026" in index_content
        assert "/static/css/views.css?v=2026" in index_content
        assert 'type="module"' in index_content
        assert "/static/js/main.js?v=2026" in index_content

    def test_zero_emojis_in_frontend_code(self):
        """测试 templates/, static/css/, static/js/ 中不存在任何系统 Emoji"""
        target_dirs = ["templates", "static/css", "static/js"]
        violating_files = []

        for target_dir in target_dirs:
            if not os.path.exists(target_dir):
                continue
            for root, _, files in os.walk(target_dir):
                for file_name in files:
                    if file_name.endswith((".html", ".css", ".js")):
                        file_path = os.path.join(root, file_name)
                        # 跳过即将删除的废弃资产
                        if any(legacy in file_name for legacy in ["three", "app.js", "style.css", "image-studio"]):
                            continue
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            text = f.read()
                        matches = self.EMOJI_PATTERN.findall(text)
                        if matches:
                            violating_files.append((file_path, matches))

        assert len(violating_files) == 0, f"发现文件中存在 Emoji 字符: {violating_files}"

    def test_modules_exist_and_under_400_loc(self):
        """测试全部 12 个 ES 模块均存在且非空/非注释代码行数严格小于 400 行"""
        base_dir = "static/js"

        for mod in self.EXPECTED_CORE_MODULES:
            path = os.path.join(base_dir, "core", mod)
            assert os.path.exists(path), f"缺少核心模块: {path}"
            self._verify_loc(path)

        for mod in self.EXPECTED_VIEW_MODULES:
            path = os.path.join(base_dir, "views", mod)
            assert os.path.exists(path), f"缺少视图模块: {path}"
            self._verify_loc(path)

        entry_path = os.path.join(base_dir, "main.js")
        assert os.path.exists(entry_path), f"缺少入口模块: {entry_path}"
        self._verify_loc(entry_path)

    def _verify_loc(self, path):
        with open(path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip() and not line.strip().startswith("//")]
        assert len(lines) < 400, f"模块代码行数超标 (>400 行): {path} ({len(lines)} 行)"

    def test_flask_webui_routes_smoke(self):
        """测试 Flask WebUI 核心路由连通性"""
        app.config["TESTING"] = True
        client = app.test_client()

        # 访问根路径
        res_root = client.get("/")
        assert res_root.status_code in [200, 401]

        res_status = client.get("/api/status")
        assert res_status.status_code == 200
        status_json = res_status.get_json()
        assert "is_running" in status_json
        assert "logs" in status_json
```

- [ ] **Step 3: 运行测试验证预期失败 (TDD 失败断言)**

运行测试命令：
```bash
pytest tests/test_webui_refactor.py -v
```
预期输出：测试执行失败（报错指出 `templates/index.html` 仍含 `three.min.js` 或模块文件尚未建立），符合 TDD 规范。

- [ ] **Step 4: 提交 Task 1 代码**

```bash
git add .gitignore tests/test_webui_refactor.py
git commit -m "test(webui): add frontend modular refactor contract test suite"
```

---

### Task 2: Linear Modern Light CSS 样式体系

**Files:**
- Create: `static/css/tokens.css`
- Create: `static/css/components.css`
- Create: `static/css/views.css`

- [ ] **Step 1: 编写设计变量与环境画布 `static/css/tokens.css`**

写入全套 CSS Custom Properties、4 层微光环境背景及排版基准，代码行数约 110 行：
- 定义 `--bg-base`, `--bg-subtle`, `--bg-elevated`, `--surface-glass`, `--text-primary`, `--text-secondary`, `--text-muted`, `--accent`, `--border-color`, `--shadow-card`, `--shadow-btn-primary`, `--radius-sm` 等完整变量。
- 实现 `.ambient-canvas`, `.ambient-blob-1/2/3`, `.ambient-grid`, `.ambient-noise` 四层环境微光。
- 配置 `-webkit-font-smoothing: antialiased`、标准盒模型与 `user-select: none` 壳层保护。

- [ ] **Step 2: 编写基础组件库 `static/css/components.css`**

写入全套通用原子组件，代码行数约 210 行：
- 顶部 56px 悬浮毛玻璃导航条 (`.topbar`) 与移动端底部安全区 5 键 Dock (`.mobile-bottom-dock`，支持 `>= 44x44px` 触控靶心)。
- 纸质微倒角卡片 (`.linear-card`，具备 `inset 0 1px 0 0 rgba(255, 255, 255, 1)` 顶斜角白光微光倒角)。
- 按钮体系 (`.btn-primary`, `.btn-secondary`, `.btn-ghost`, `.btn-danger-ghost`, `.btn-sm`)。
- 高对比表单输入框 (`.linear-input`, `.linear-select`, `.linear-textarea`，移动端字体强制 `>= 16px` 防止 iOS 自动聚焦缩放)。
- 分段控制器 (`.segmented-nav`, `.filter-pills`)、状态药丸 (`.status-pill`) 与排版预览弹窗 (`.modal-overlay`, `.modal-card`)。

- [ ] **Step 3: 编写五大业务舞台布局与多端断点 `static/css/views.css`**

写入业务舞台样式，代码行数约 260 行：
- **总控舞台 (`.console-stage`)**: 4-Step 实时流水线步进条 (`.stepper-track`, `.step-item.completed/.active/.pending`)；结构化手风琴时间轴 (`.phase-accordion.highlight`)；信源雷达条 (`.radar-strip`)；Map-Reduce 进度行 (`.section-progress-row`)；三槽位视觉资产网格 (`.asset-slots-grid`, `.asset-slot-card`)；质量门禁结果卡片 (`.gate-result-card`)；浅色凹陷 Monospace 日志井 (`.pipeline-raw-view`)。
- **图谱舞台 (`.graph-stage`)**: 24px 点阵背景画布 (`.dotgrid-canvas`)；4 阶拓扑列 (`.tier-column`)；SVG 连线层 (`.graph-svg-layer`)；停靠式 320px 毛玻璃 HUD 检查器 (`.hud-inspector`, 支持 `.collapsed`)；在 `< 768px` 媒体查询下自适应为 `max-height: 75dvh` 的触控底部抽屉。
- **审稿舞台 (`.audit-stage`)**: 桌面端高对比 Linear 表格 (`.linear-table`)；移动端自动解构为卡片流布局；评分微标 (`.score-badge.high/.mid/.warn`)。
- **配图舞台 (`.image-stage`)**: 参考链接重绘工具栏；桌面左右分栏 / 移动垂直单列响应式切换。
- **运维舞台 (`.ops-stage`)**: 12 信源健康网格 (`.source-matrix`, `.source-card`)；定时任务 Cron 管理列表；双列规整设置表单 (`.settings-grid`)。

- [ ] **Step 4: 验证 CSS 文件语法与零 Emoji**

运行验证命令：
```bash
powershell -Command "$c = Get-Content 'static/css/*.css' -Raw; if ($c -match '[\uD800-\uDBFF][\uDC00-\uDFFF]|[\u2600-\u27BF]|[\u2300-\u23FF]|[\u2B50-\u2B55]|[\u203C-\u2049]') { Write-Error 'Emoji found!' } else { Write-Host 'CSS files verified clean: 0 emojis.' }"
```
预期输出：`CSS files verified clean: 0 emojis.`

- [ ] **Step 5: 提交 Task 2 代码**

```bash
git add static/css/tokens.css static/css/components.css static/css/views.css
git commit -m "feat(css): implement Linear Modern Light CSS design system"
```

---

### Task 3: 核心基础模块 (`static/js/core/**`)

**Files:**
- Create: `static/js/core/icons.js`
- Create: `static/js/core/storage.js`
- Create: `static/js/core/api.js`
- Create: `static/js/core/state.js`
- Create: `static/js/core/i18n.js`
- Create: `static/js/core/log-parser.js`

- [ ] **Step 1: 编写集中式矢量图标字典 `static/js/core/icons.js`**

创建 `static/js/core/icons.js`，导出函数 `getIcon(name, size = 14, strokeWidth = 1.75)`。
覆盖 24 组线性矢量图标：`console`, `graph`, `audit`, `image`, `ops`, `play`, `pause`, `stop`, `refresh`, `check`, `lock`, `clock`, `chevronDown`, `close`, `trash`, `external`, `sparkle`, `upload`, `search`, `settings`, `radar`, `layers`, `alert`, `view`。
所有图标均使用 `stroke="currentColor" stroke-width="1.75" fill="none" stroke-linecap="round" stroke-linejoin="round"`。严禁包含任何 Emoji。

- [ ] **Step 2: 编写安全本地存储包装器 `static/js/core/storage.js`**

创建 `static/js/core/storage.js`，封装 `Storage` 单例类：
- 提供 `get(key, defaultValue)`, `set(key, value)`, `remove(key)`。
- 对每次读写操作包裹 `try/catch` 逻辑。当捕获到 `QuotaExceededError`（常见于 iOS Safari 隐私浏览模式）时，自动降级至内部 `Map` 内存存储，并在控制台记录一条静默告警，保证程序在受限环境下平稳运行。

- [ ] **Step 3: 编写 RESTful API 客户端与防重复提交守卫 `static/js/core/api.js`**

创建 `static/js/core/api.js`，导出 `request(endpoint, options)` 及常用的快捷方法：
- 对所有的变更请求（`POST`, `PUT`, `DELETE`）引入统一的 URL + Payload 字符串哈希防抖锁。如果在 3 秒内收到相同请求，自动拦截并抛出防抖异常。
- 严禁任何猴子补丁式的 `window.fetch` 篡改，确保全局原生事件委托机制安全运行。
- 集中处理 HTTP 401 认证过期（自动跳转 `/login`）、网络断线重试提示及返回 JSON 解析。

- [ ] **Step 4: 编写全局响应式状态总线与有限状态机 `static/js/core/state.js`**

创建 `static/js/core/state.js`，导出单例 `State`：
- 严格实现状态机状态集合：`IDLE`, `STARTING`, `RUNNING`, `PAUSED`, `STOPPING`, `COMPLETED`, `ERROR`。
- 管理全局响应式字段：`currentStage`（默认 `'console'`）、`engineState`、`activeWorkflow`、`selectedNode`、`auditList`、`activeLanguage`（`'zh'` 或 `'en'`）。
- 提供基于轻量发布-订阅（Pub/Sub）模式的 `on(event, handler)`、`off(event, handler)` 与 `emit(event, payload)` 方法。

- [ ] **Step 5: 编写双语文本切换引擎 `static/js/core/i18n.js`**

创建 `static/js/core/i18n.js`，导出 `t(key)` 与 `toggleLanguage()`：
- 包含中文/英文对齐字典，涵盖五大导航标签、步进条阶段名、常用按钮、状态标签（例如：`{ "console": { zh: "总控", en: "Console" }, "approve": { zh: "准发", en: "Approve" } }`）。
- 语言偏好持久化写入 `Storage`，在页面加载时自动恢复。

- [ ] **Step 6: 编写结构化流水线日志解析器 `static/js/core/log-parser.js`**

创建 `static/js/core/log-parser.js`，导出纯函数 `parseLogs(logLines, prevState)`：
- 接收从 `GET /api/status` 返回的 `logs` 增量字符串数组。
- 纯函数归约为四阶段模型：
  - 检索信源采集/抓取/去重/同步关键词，填充 `phase1`（信源扫描计数与锁定目标选题）。
  - 检索大纲/章节/Map-Reduce/DeepSeek 关键词，填充 `phase2`（章节生成进度与 Token 节省）。
  - 检索配图/生图/Qwen-VL/评分/渲染/上传关键词，填充 `phase3`（三槽位生成与 CDN 进度）。
  - 检索核查/质量/评分/草稿/`media_id` 关键词，填充 `phase4`（门禁分值与微信草稿 ID）。
- 自动剔除日志行内可能由后端遗留的控制字符或 Emoji 表情符，返回纯净结构对象与 `rawBuffer`。

- [ ] **Step 7: 检查核心模块 LOC 与零 Emoji**

运行验证命令：
```bash
powershell -Command "Get-ChildItem 'static/js/core/*.js' | ForEach-Object { $lines = (Get-Content $_.FullName | Where-Object { $_.Trim() -and -not $_.Trim().StartsWith('//') }).Count; Write-Host $_.Name : $lines lines; if ($lines -ge 400) { Write-Error 'LOC exceeded!' } }"
```
预期输出：每个模块行数均小于 400 行。

- [ ] **Step 8: 提交 Task 3 代码**

```bash
git add static/js/core/
git commit -m "feat(core): implement core modules (icons, storage, api, state, i18n, log-parser)"
```

---

### Task 4: 五大业务舞台视图控制器与主入口

**Files:**
- Create: `static/js/views/console.js`
- Create: `static/js/views/graph.js`
- Create: `static/js/views/audit.js`
- Create: `static/js/views/studio.js`
- Create: `static/js/views/ops.js`
- Create: `static/js/main.js`

- [ ] **Step 1: 编写总控视图控制器 `static/js/views/console.js`**

创建 `static/js/views/console.js`，导出 `initConsoleView()`：
- 绑定 4 选项工作流选择器事件（`hotspots`、`github`、`aikepu`、`daily_knowledge`），更新 `State.activeWorkflow`。
- 绑定「启动编排」/「暂停」/「恢复」/「终止」按钮，调用 `POST /api/start`（传入 `{"task_type": ...}`）、`POST /api/pause`、`POST /api/resume`、`POST /api/stop` 接口。
- 绑定 Prompt Cache 统计与预热（`GET /api/system/llm_cache_stats`、`POST /api/system/warmup_cache`）以及连载摘要（`GET /api/aikepu/tree_stats`）。
- 启动周期性轮询（每 1500ms），拉取 `GET /api/status`（包含 `is_running`、`is_paused`、`logs`）。调用 `parseLogs` 将增量日志同步刷新至：
  - 顶部 4-Step 实时步进条高亮状态。
  - 四大 Phase 折叠卡片内的雷达指标、章节进度、3 槽位生成网格与质检门禁徽章。
- 提供「可视时间轴」与「原始流 (Raw)」双模视图切换函数 `toggleLogViewMode(mode)`。
- 逻辑代码行数严格控制在 300 行以内。

- [ ] **Step 2: 编写知识图谱视图控制器 `static/js/views/graph.js`**

创建 `static/js/views/graph.js`，导出 `initGraphView()`：
- 对接 `GET /api/kepu/trees`、`POST /api/kepu/active`、`POST /api/kepu/import`、`GET /api/aikepu/full_tree` 与 `POST /api/aikepu/sync_wechat`。
- 基于 DOM 节点渲染 4 阶拓扑列（入门、基础、进阶、前沿）。
- 动态计算并更新 SVG 层的三次贝塞尔曲线坐标路径，连接各阶段依赖节点。
- 节点点击交互：设置 `.selected` 样式，在桌面与平板端联动右侧 320px 毛玻璃 HUD 检查器展开；在移动端（`< 768px`）呼出 `75dvh` 底部抽屉。
- HUD 内部对接 `POST /api/aikepu/set_node_status`（`published` / `draft` / `reset`）与 `POST /api/aikepu/generate_node` 直接触发该节点撰写并切回总控舞台。
- 逻辑代码行数严格控制在 300 行以内。

- [ ] **Step 3: 编写审稿视图控制器 `static/js/views/audit.js`**

创建 `static/js/views/audit.js`，导出 `initAuditView()`：
- 调用 `GET /api/history` 获取历史生成记录（统一解析 `unsent`、`sent` 与 `history`），提供 `全部`、`待审`、`已通过`、`草稿`、`已发` 分类过滤。
- 桌面端渲染 `.linear-table`，移动端（`< 768px`）自动渲染为垂直无横向滚动卡片流。
- 绑定表格行复选框与全选复选框；实现「批量删除」调用 `POST /api/history/delete`；实现「核准推送」调用 `POST /api/review/approve`。
- 绑定「预览」按键，将 `iframe.src` 指向 `/api/preview/<preview_id>` 呼出微信排版全屏毛玻璃弹窗。
- 逻辑代码行数严格控制在 250 行以内。

- [ ] **Step 4: 编写配图视图控制器 `static/js/views/studio.js`**

创建 `static/js/views/studio.js`，导出 `initStudioView()`：
- 修复旧版标签破损问题，保证正文 Markdown 编辑区与提示词槽位卡片双向绑定。
- 绑定顶部参考文章重绘，调用 `POST /api/image-studio/redraw`（`{"article_url": ..., "count": 4}`）。
- 绑定「提取插图提示词」，调用 `POST /api/image-studio/prompts`（`{"article_title": ..., "article_text": ...}`）。
- 槽位卡片绑定本地文件拖拽与点选上传，调用 `POST /api/image-studio/upload`（表单字段 `image`, `index`），支持移动端点击调起系统相册选择，以及调用 `POST /api/image-studio/preview` 预览合成图文。
- 逻辑代码行数严格控制在 250 行以内。

- [ ] **Step 5: 编写运维视图控制器 `static/js/views/ops.js`**

创建 `static/js/views/ops.js`，导出 `initOpsView()`：
- 绑定二级分段导航，切换展示 `信源健康`、`定时任务`、`系统设置`。
- 信源健康：调用 `GET /api/sources` 与 `POST /api/sources/test` 渲染 12 信源延迟矩阵与健康状态。
- 定时任务：调用 `GET /api/schedule/jobs`、`POST /api/schedule/add`（`task_type`, `cron_expr`）、`POST /api/schedule/remove`、`POST /api/schedule/pause`、`POST /api/schedule/resume`。
- 系统设置：调用 `GET / POST /api/config` 与 `GET /api/system/sd_status`，实现表单回填、生图服务状态检测与「保存设置」。
- 逻辑代码行数严格控制在 250 行以内。

- [ ] **Step 6: 编写应用主入口 `static/js/main.js`**

创建 `static/js/main.js`：
- 作为 `<script type="module">` 的唯一顶级启动器：若当前页面存在 `#login-form`（登录页），则绑定 Cookie `aw_token` 写入与 `/api/config` 校验跳转逻辑；若存在主控台壳层，则调用五大视图初始化函数。
- 实现顶栏与移动端底栏 5 键 Dock 的双向激活同步：`switchStage(stageName)`。
- 注册 `document.addEventListener('visibilitychange', handleVisibilityChange)` 监听器：当屏幕解锁或由后台切回前台时，自动调用 `State.resyncRunningStatus()` 补齐丢失的轮询时钟。
- 绑定语言切换按键与全局状态灯更新逻辑。
- 逻辑代码行数控制在 150 行以内。

- [ ] **Step 7: 检查视图模块 LOC 与零 Emoji**

运行验证命令：
```bash
powershell -Command "Get-ChildItem 'static/js/views/*.js', 'static/js/main.js' | ForEach-Object { $lines = (Get-Content $_.FullName | Where-Object { $_.Trim() -and -not $_.Trim().StartsWith('//') }).Count; Write-Host $_.Name : $lines lines; if ($lines -ge 400) { Write-Error 'LOC exceeded!' } }"
```
预期输出：每个视图模块与主入口均小于 400 行。

- [ ] **Step 8: 提交 Task 4 代码**

```bash
git add static/js/views/ static/js/main.js
git commit -m "feat(views): implement stage view controllers and main entrypoint"
```

---

### Task 5: 模板重写、旧资产清理与全量验收

**Files:**
- Modify: `webui.py:74,279,293`
- Rewrite: `templates/login.html`
- Rewrite: `templates/index.html`
- Delete: `static/js/three.min.js`
- Delete: `static/js/three-bg.js`
- Delete: `static/js/app.js`
- Delete: `static/js/image-studio.js`
- Delete: `static/css/style.css`
- Delete: `static/css/image-studio.css`

- [ ] **Step 1: 清除 `webui.py` 中的 3 处遗留 Emoji**

打开 `webui.py`，修改以下 3 处包含 Emoji 的字符串：
1. **第 74 行**: 将包含锁闭图标的口令认证提示替换为纯文本 `AutoWeChat Cloud — 需要 token 认证`。
2. **第 279 行**: 将包含暂停图标的日志消息替换为纯文本 `SYSTEM | [PAUSE] User requested pause\n`。
3. **第 293 行**: 将包含播放图标的日志消息替换为纯文本 `SYSTEM | [RESUME] User requested resume\n`。

- [ ] **Step 2: 重写登录模板 `templates/login.html`**

重写 `templates/login.html` 为纯语义 HTML5 结构（约 90 行）：
- 引入 `/static/css/tokens.css?v=2026` 与 `/static/css/components.css?v=2026`。
- 渲染居中 Linear Modern Light 卡片，包含 AutoWeChat 矢量品牌标志、口令输入框与「登入工作台」主要按钮。
- 彻底移除所有内联 `<style>` 标签与 Emoji 字符。

- [ ] **Step 3: 重写主控模板 `templates/index.html`**

重写 `templates/index.html` 为纯语义 HTML5 骨架（约 210 行）：
- 引入三套样式表（`tokens.css?v=2026`, `components.css?v=2026`, `views.css?v=2026`）。
- 声明四层微光背景骨架（`.ambient-canvas`）。
- 搭建 56px 顶部悬浮毛玻璃壳层（品牌微标、5 键分段导航、状态胶囊、EN 切换键）。
- 声明五大舞台容器骨架（`#view-console`, `#view-graph`, `#view-audit`, `#view-image`, `#view-ops`）。
- 声明移动端底部 5 键 Dock（`.mobile-bottom-dock`）与微信排版预览弹窗（`#preview-modal`）。
- 在文档底端引入唯一入口：`<script type="module" src="/static/js/main.js?v=2026"></script>`。
- 彻底消除所有旧版内联脚本、未匹配闭合的破损标签与 Emoji。

- [ ] **Step 4: 删除旧版巨石与无效 3D 资产**

删除 6 个已完全解构并废弃的旧资产文件：
```bash
git rm static/js/three.min.js static/js/three-bg.js static/js/app.js static/js/image-studio.js static/css/style.css static/css/image-studio.css
```

- [ ] **Step 5: 运行全量测试套件执行回归验收**

运行回归与契约测试命令：
```bash
pytest tests/test_webui_refactor.py -v
pytest tests/ -v
```
预期输出：所有新增的契约测试与已有的 93 项核心逻辑测试全部以 100% 通过（PASS）。

- [ ] **Step 6: 提交 Task 5 代码**

```bash
git add webui.py templates/login.html templates/index.html
git commit -m "feat(templates): clean legacy assets, rewrite index & login with Linear Modern Light"
```

---

## 质量核验清单 (Quality Checklist)

在宣布实施完毕前，必须逐一验证以下指标：
- [ ] 零 Emoji 扫描：运行正则匹配 `[\uD800-\uDBFF][\uDC00-\uDFFF]|[\u2600-\u27BF]|[\u2300-\u23FF]|[\u2B50-\u2B55]|[\u203C-\u2049]`，全工程前端与模板文件匹配计数为 0。
- [ ] 模块体积守卫：`static/js/core/*.js` 与 `static/js/views/*.js` 下所有模块单文件非空非注释代码均严格 `< 400` LOC。
- [ ] 无废弃网络开销：检查浏览器网络瀑布流，确认 `three.min.js` (608KB) 与 `three-bg.js` 已被永久除名。
- [ ] 多端视口适配：在 `390x844`, `820x1180`, `1180x820`, `1024x1366`, `1440x900` 视口下无任何根横向滚动条，移动端触控靶心尺寸实测均 `>= 44px`。
- [ ] 自动化测试全绿：执行 `pytest tests/`，所有测试用例 100% 通过。
