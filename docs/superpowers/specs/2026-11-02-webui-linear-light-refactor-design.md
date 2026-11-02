# AutoWeChat WebUI Linear Light 重构架构设计规范 (子项目 1)

- **版本**: 1.0.0 (生产就绪架构设计规范)
- **编制日期**: 2026-11-02
- **状态**: 批准 (Approved)
- **文档路径**: `docs/superpowers/specs/2026-11-02-webui-linear-light-refactor-design.md`
- **目标执行范围**: `webui.py`, `templates/index.html`, `templates/login.html`, `static/css/**`, `static/js/**`

---

## 1. 背景与子项目拆分 (Overview & Decomposition)

### 1.1 两阶段演进路线图

根据系统架构升级规划，AutoWeChat 的现代化重构划分为两个边界清晰、互不偶联的独立子项目：

1. **子项目 1：WebUI 管理控制台前端架构彻底重构（即本规范范围）**
   - **核心目标**: 依据 `408-helper/DESIGN.md` 与 `AGENTS.md` 规范，将现有 WebUI 全面升级为基于原生 ES Modules 的 Linear Modern Light 现代浅色桌面/移动全自适应架构。
   - **改造文件**: `templates/index.html`, `templates/login.html`, `static/css/**`, `static/js/**`，对 `webui.py` 仅保留已有 RESTful API 契约并提供 100% 向后兼容支持。
2. **子项目 2：微信公众号排版引擎与图表渲染卡片化重构（后续独立规范）**
   - **核心目标**: 针对推送至微信公众平台的正文图文 HTML，重构 CSS 内联排版引擎（`core/shared/article_utils.py`, `utils/html_render.py`），优化学术论文/科技资讯模板、LaTeX 公式内联渲染与 Mermaid 拓扑卡片图生成。
   - **执行顺序**: 必须在子项目 1 验收完成后单列规划与实施。

### 1.2 现有 WebUI 核心痛点与缺陷诊断

通过对当前工程代码（`templates/index.html` 共 1004 行、`static/js/app.js` 共 1495 行、`static/css/style.css` 共 1422 行）的静态分析与运行时审查，确认存在以下阻碍日常高频使用的系统级缺陷：

1. **视觉混杂与无意义渲染开销**:
   - `templates/index.html` 引入了体积达 608KB 的 `static/js/three.min.js` 以及 `static/js/three-bg.js`。其基于暗色背景叠加混合（Additive Blending）设计的粒子连线特效在浅色界面中完全不可见，却持续占用移动端 GPU 与电池电量。
   - 界面整体呈现半暗半浅的拼凑质感（例如深黑色 `#1e1e2e` 终端日志框突兀地嵌在浅色卡片中），缺乏统一设计语言。
2. **巨石单体代码与 DOM 语法破损**:
   - `templates/index.html` 存在 DOM 标签不匹配缺陷：配图工作台（Image Studio）区域内标签错位嵌套，导致其内部多个控制按钮失效。
   - 业务逻辑与全局变量散落在 `index.html` 内联 `<script>` 与 1495 行的 `app.js` 中；全局存在猴子补丁式的 `window.fetch` 拦截逻辑，直接破坏了历史记录批量删除复选框等标准事件委托机制。
3. **多端适配严重失调**:
   - 在 iPad 竖屏视口（宽度 820px）下，左侧常驻的 240px 侧边栏霸占了超过 29% 的横向屏幕空间，使主控制台卡片、DAG 图谱与审稿多列表格极度局促。
   - 在手机端（宽度小于 768px）下，底部导航栏强行横向排布了 7 个按钮，单项触控宽度不足 40px，严重违反移动端最小 44px 触控规范。
4. **日志呈现体验干瘪**:
   - 传统控制台仅能单行输出非结构化的终端纯文本，用户无法直观获取当前流水线处于何种生成阶段（信源扫描、图谱对齐、插图渲染、质量门禁），无法满足专业内容创作者的掌控感需求。

---

## 2. 设计哲学与 Token 体系 (Design Philosophy & Tokens)

设计规范严格遵循 Linear Modern Light 视觉体系，以纸质般的纯净感、精密的数据排布与微妙的顶斜角光影（Top Specular Bevel）为核心，彻底消除视觉杂讯与认知负荷。

### 2.1 CSS Custom Properties 设计令牌

所有设计变量均定义在 `static/css/tokens.css` 中，禁止在业务组件中硬编码十六进制颜色值。

```css
:root {
  /* 基础与表面背景色阶 */
  --bg-base: #F8F9FB;
  --bg-subtle: #F1F3F7;
  --bg-elevated: #FFFFFF;
  --surface-glass: rgba(255, 255, 255, 0.86);
  --surface-glass-hud: rgba(255, 255, 255, 0.94);

  /* 墨色文字阶梯 */
  --text-primary: #0C0D0E;
  --text-secondary: #5E6470;
  --text-muted: #8C919E;
  --text-inverse: #FFFFFF;

  /* 品牌与交互强调色 (Linear Indigo) */
  --accent: #4F5BD5;
  --accent-hover: #434EB8;
  --accent-active: #3842A6;
  --accent-subtle: rgba(79, 91, 213, 0.08);
  --accent-border: rgba(79, 91, 213, 0.25);

  /* 边框体系 */
  --border-color: rgba(0, 0, 0, 0.06);
  --border-subtle: rgba(0, 0, 0, 0.04);
  --border-strong: rgba(0, 0, 0, 0.12);

  /* 状态指示色阶 */
  --status-success: #10B981;
  --status-success-bg: rgba(16, 185, 129, 0.10);
  --status-warning: #F59E0B;
  --status-warning-bg: rgba(245, 158, 11, 0.12);
  --status-danger: #EF4444;
  --status-danger-bg: rgba(239, 68, 68, 0.10);

  /* 物理投影与顶部高光倒角 */
  --shadow-card: 0 1px 2px rgba(0, 0, 0, 0.03), 0 4px 16px rgba(15, 23, 42, 0.04), inset 0 1px 0 0 rgba(255, 255, 255, 1);
  --shadow-card-hover: 0 2px 4px rgba(0, 0, 0, 0.04), 0 8px 24px rgba(15, 23, 42, 0.08), inset 0 1px 0 0 rgba(255, 255, 255, 1);
  --shadow-btn-primary: 0 1px 2px rgba(0, 0, 0, 0.05), 0 4px 12px rgba(79, 91, 213, 0.30), inset 0 1px 0 0 rgba(255, 255, 255, 0.25);
  --shadow-dropdown: 0 10px 30px rgba(0, 0, 0, 0.08), 0 1px 3px rgba(0, 0, 0, 0.05);
  --shadow-modal: 0 20px 40px rgba(0, 0, 0, 0.12), 0 1px 3px rgba(0, 0, 0, 0.05);

  /* 圆角规范 */
  --radius-xs: 4px;
  --radius-sm: 6px;
  --radius-md: 9px;
  --radius-lg: 12px;
  --radius-pill: 9999px;

  /* 字体族定义 */
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  --font-mono: 'Cascadia Code', 'Fira Code', 'Menlo', 'Consolas', monospace;

  /* 动画曲线与时间 */
  --ease-expo: cubic-bezier(0.16, 1, 0.3, 1);
  --duration-fast: 160ms;
  --duration-normal: 220ms;
}
```

### 2.2 四层微光环境画布 (4-Layer Ambient Canvas)

全面废除无意义的 `three.min.js` 3D Canvas 渲染循环，通过极轻量的纯 CSS 多层叠加实现无 GPU 损耗的高级质感：

1. **第一层 (Base Gradient)**: 视口顶部径向高光 `radial-gradient(ellipse at 50% -10%, #FFFFFF 0%, #F8F9FB 55%, #EEF0F5 100%)`。
2. **第二层 (Ambient Blobs)**: 三处经过 80px 高斯模糊的淡色晕影，透明度严格控制在 8% 以下（Indigo `#4F5BD5`, Lavender `#A855F7`, Sky `#38BDF8`）。
3. **第三层 (Precision Hairline Grid)**: 64px 间距的高精度发丝几何网格，线条颜色为 `rgba(0, 0, 0, 0.025)`。
4. **第四层 (Subtle Noise Texture)**: 透明度仅为 0.012 的微细散斑纹理，赋予数字屏幕纸质触感，杜绝大面积色块断层。

### 2.3 零 Emoji 与线性矢量图标规范

- **绝对禁用 Emoji**: 无论是界面标签、状态标识、操作按钮还是提示信息，全量代码与数据严禁出现任何系统 Emoji 字符。
- **统一矢量规范**: 仅使用内联线性 `<svg>` 矢量图形，固定使用 `stroke="currentColor" stroke-width="1.75" fill="none" stroke-linecap="round" stroke-linejoin="round"`，图标尺寸统一遵循 14px（微型标签）、16px（标准正文/按钮）、20px（主要导航）三级规范。

### 2.4 文案极简原则 (Copywriting Minimalism)

- 界面操作与状态指示采用冷静、克制、精确的 2 至 4 字中文，禁止使用推销型或口语化冗余短语。
- 遵循严谨工程语义：例如使用「待审校」、「已核准」、「执行中」、「就绪」、「重置」，禁止使用冗余修饰词。

---

## 3. 零构建原生模块化工程架构 (Zero-Build Native ES Modules)

为了彻底杜绝前端构建工具链（如 Webpack、Vite、Node.js 依赖）引入的维护成本，项目坚持使用现代浏览器原生支持的原生 ES Modules 方案（Native `<script type="module">`）。每个独立模块的代码逻辑行数严格控制在 400 行以内。

### 3.1 目录组织树

```
static/
├── css/
│   ├── tokens.css             # 全局设计变量与 CSS 变量
│   ├── components.css         # 基础原子组件 (按钮、输入框、微标、开关、弹窗)
│   └── views.css              # 页面总壳层与五大业务视图布局样式
└── js/
    ├── core/
    │   ├── icons.js           # 集中式线性 SVG 图标字典库
    │   ├── storage.js         # 本地存储安全包装器 (含 Safari 无痕模式异常降级)
    │   ├── api.js             # RESTful 请求包装器 (防重发锁与 3s 幂等性守卫)
    │   ├── state.js           # 响应式状态总线与显式有限状态机 (FSM)
    │   ├── i18n.js            # 中英双语文本字典与切换引擎
    │   └── log-parser.js      # 流水线日志纯函数解析器 (生成四阶段数据模型)
    ├── views/
    │   ├── console.js         # 总控视图控制器 (流水线步进条、状态卡片、日志双模)
    │   ├── graph.js           # 图谱视图控制器 (点阵画布、DAG 拓扑连线、HUD 检查器)
    │   ├── audit.js           # 审稿视图控制器 (表格、卡片化自适应、批量操作、预览)
    │   ├── studio.js          # 配图视图控制器 (参考链接重绘、槽位提词、图片上传)
    │   └── ops.js             # 运维视图控制器 (信源健康矩阵、定时任务、系统配置)
    └── main.js                # 顶层入口模块 (路由切换、状态同步、无痕唤醒补偿)
```

### 3.2 模块职责与接口定义

#### 3.2.1 `static/js/core/api.js`
- **核心契约**: 彻底清除对全局 `window.fetch` 的暴力篡改，封装显式的 `request(url, options)` 接口。
- **并发与幂等控制**: 对具有数据修改副作用的方法（`POST`, `PUT`, `DELETE`）引入统一的 URL + Payload 哈希锁。在请求未响应前（或 3 秒内）拦截重复触发，自动展示禁用状态，杜绝网络抖动导致的数据重复推送。

#### 3.2.2 `static/js/core/storage.js`
- **容灾机制**: 针对 iOS Safari 隐私浏览模式或存储空间耗尽抛出的 `QuotaExceededError`，在捕获异常后自动无缝回退到内存 Map 结构，确保页面在任何受限环境下均不崩溃。

#### 3.2.3 `static/js/core/log-parser.js`
- **输入**: `GET /api/status` 返回字段 `logs` 中的增量单行字符串数组（自动剥离后端历史字符串中可能携带的任何 Emoji 字符）。
- **输出**: 结构化的四阶段流水线对象，字段包括：
  - `phase1`: 信源扫描数量、去重过滤统计、已锁定目标选题及评分。
  - `phase2`: 章节写作推进进度、Tokens 消耗与节省预估、排版内联状态。
  - `phase3`: 插图生成槽位数组（含槽位 ID、提示词、图表格式、质检评分与 CDN 状态）。
  - `phase4`: 质量门禁合规评分、事实校验项、生成的微信草稿 `media_id`。
  - `rawBuffer`: 供底层开发者随时核查的完整时间戳日志文本。

#### 3.2.4 `templates/index.html` 与 `templates/login.html`
- **纯粹语义骨架**: HTML 模板内 100% 移除内联 `<style>` 标签与业务逻辑 `<script>`。
- **引入协议**: 仅通过 `<link rel="stylesheet" href="/static/css/tokens.css?v=2026">`、`<link rel="stylesheet" href="/static/css/components.css?v=2026">`、`<link rel="stylesheet" href="/static/css/views.css?v=2026">` 引入样式，通过 `<script type="module" src="/static/js/main.js?v=2026"></script>` 启动主程序，全量资源添加版本查询字串杜绝浏览器强缓存。

---

## 4. 三端响应式与五大核心舞台设计规范

### 4.1 断点体系与导航壳层行为

界面依据屏幕物理特征划分为三类响应环境，视口高度基于现代 `100dvh` 标准设计，杜绝根节点产生任何横向水平滚动条：

| 视口形态 | 尺寸范围 (宽) | 典型设备 | 壳层结构 | 触控靶心规范 |
| :--- | :--- | :--- | :--- | :--- |
| **桌面工作台 (Desktop)** | `>= 1024px` | 1440x900, 1920x1080 | 56px 顶部毛玻璃分段条；右侧常驻 HUD 检查器 (320px) | 按钮高度 `>= 34px`，密集排布 |
| **平板优先 (Tablet/iPad)** | `768px ~ 1023px` | iPad 竖屏 (820x1180), 横屏 (1180x820), iPad Pro (1024x1366) | 56px 顶部毛玻璃分段条；100% 全幅主舞台；侧滑式 HUD 检查器 | 所有触控按钮与表单高度 `>= 44px` |
| **移动掌上端 (Mobile)** | `< 768px` | iPhone (375x812, 390x844), 安卓设备 | 48px 顶部粘性状态栏 + 底部 5 键式安全区 Dock (`56px + env(safe-area-inset-bottom)`) | 严格满足 `>= 44x44px`；输入框字号 `>= 16px` |

---

### 4.2 核心舞台 1：总控工作台 (Console Stage)

总控工作台彻底告别单行文字日志井，演进为现代化「可视化流水线执行舞台」：

#### 4.2.1 顶部紧凑触发与遥测栏
- **工作流选择器**: 扁平单行分段控制器（`今日热点` | `GitHub 趋势` | `体系连载` | `每日短文`），在移动端自适应折行排列。
- **主启动动作**: 右侧放置 `#4F5BD5` 主色「启动编排」按钮。执行过程中动态转变为「暂停」与「终止」组合控制键。
- **单行遥测数据带 (Telemetry Strip)**: 平铺展示核心指标：`Cache 命中率 94.2%`、`已省 Tokens 128.4k`、`节省资金 ¥1.82`、`体系连载 12/30 篇`，以及高亮交互入口「下一推荐节点：Transformer 自注意力机制」与「预热图谱缓存」按钮。

#### 4.2.2 四阶段实时步进条 (4-Step Live Pipeline Stepper)
横向贯穿的步进进度组件，直观展示文章从无到有的流水线加工状态：
1. **阶段 01（信源采集与去重）**: 状态包含「已完成 · 1.8s」，展示微标「12 源扫描 / 36 候选」，带有绿色对勾图标。
2. **阶段 02（深度创作与润色）**: 状态包含「已完成 · 6.4s」，展示微标「Cache 命中 94% / 2,840 字」，带有绿色对勾图标。
3. **阶段 03（多模配图与渲染）**: 运行中状态具有高亮脉冲光环，展示微标「Qwen-VL 评分 2/3 槽位」，带有动态旋转进度环。
4. **阶段 04（事实核查与草稿推送）**: 门禁等待态，展示微标「质量门禁 >= 80」，带有浅灰色锁闭图标。

#### 4.2.3 结构化阶段手风琴与实时产出微卡片 (Timeline Accordion Cards)
支持用户在「可视时间轴 (Timeline)」与「原始流 (Raw)」之间一键切换：
- **阶段 01 折叠卡片**: 内置「信源雷达扫描条」（展示 Hacker News、GitHub、ArXiv 及微信历史库 0 冲突微标）与「锁定目标选题卡片」（展示相关度分值 96.4）。
- **阶段 02 折叠卡片**: 内置 Map-Reduce 章节并行写作进度行（3 节生成进度、字数及排版内联确认），附带局部图谱切片节省统计。
- **阶段 03 折叠卡片**: 内置三槽位并行多模态视觉网格：
  - 槽位 1：SVG/Mermaid 架构拓扑图，显示 850px 渲染就绪缩略图。
  - 槽位 2：微距芯片与算力集群 2.35:1 封面题图，显示 Qwen-VL 视觉质检分 91.5（PASS）。
  - 槽位 3：专家负载动态热力插图，显示 CDN 上传进度条（实时 78%）。
- **阶段 04 折叠卡片**: 点击启动或流式完成后动态点亮展开，呈现「质量门禁结果卡片」：标注综合质量分 94.0、3/3 项核验无误、微信草稿 `media_id: WxDraft_89a4f2c`，并直接提供「预览排版草稿」快捷弹窗。

---

### 4.3 核心舞台 2：知识图谱 (Graph · Connected Papers Pattern)

#### 4.3.1 工具栏与筛选体系
- 顶部集成体系选择器下拉框（支持切换《AI 核心科普体系》、《全栈工程师进阶图谱》）。
- 提供阶梯过滤胶囊（`全部` | `入门` | `基础` | `进阶` | `前沿`）。
- 操作区集成「微信同步」与「撰写推荐节点」主 CTA 按钮。

#### 4.3.2 24px 点阵无界画布与拓扑连线
- 画布采用 `radial-gradient(#cbd5e1 1.2px, transparent 1.2px)` 形成的 24px 精准点阵，支持全向平移与拖拽探索。
- 4 阶拓扑列（入门、基础、进阶、前沿）节点由底层动态 SVG 的三次贝塞尔曲线（Cubic-bezier curves）平滑相连：已发布节点使用绿色实线连接，今日解锁的推荐推进路径使用 Indigo 虚线连接，未解锁节点使用静音灰线连接。
- 每一个节点卡片清晰标识节点编号（如 N-12）、发文状态（已发布、草稿、今日推荐、待解锁）及阅读赞同数据。

#### 4.3.3 毛玻璃 HUD 节点检查器 (HUD Inspector)
- **桌面与平板端**: 侧边停靠的 320px 毛玻璃面板（`background: rgba(255,255,255,0.94)`, `backdrop-filter: blur(16px)`），支持独立折叠与展开。
- **移动端**: 自动转变为最大高度为 `75dvh` 的触控底部抽屉（Bottom Sheet Drawer）。
- **检查内容**: 节点 ID、完整标题、知识点结构大纲、前置依赖解锁标签、直接状态覆盖操作（标记已发 / 设为草稿 / 重置），以及底端全宽的「撰写此节点 (一键下发管线)」按钮。

---

### 4.4 核心舞台 3：审稿工作台 (Audit Workbench)

#### 4.4.1 数据与动作闭环
- 数据统一源自 `/api/history` 接口，提供全局分类筛选胶囊：`全部`、`待审`、`已通过`、`需复核`。
- 支持全选复选框、批量删除（`/api/history/delete`）及批量核准推送（`/api/review/approve`）。

#### 4.4.2 响应式形态自适应转换
- **桌面与平板端 (`>= 768px`)**: 呈现高对比度 Linear 数据表格，列项包含复选框、文章标题与信源归属、质量评分徽章、事实核验通过率、CSS 内联校验状态、流程状态胶囊及快捷操作按钮。
- **移动端 (`< 768px`)**: 数据表格自动解构为独立的垂直文章卡片流，彻底消灭横向滚动条。标题、评分、核验状态以块状紧凑排布，底端平铺提供满足 44px 高度的「预览」与「核准推送」按键。

#### 4.4.3 微信图文排版弹窗预览 (WeChat Preview Modal)
- 点击任意文章的「预览」按钮呼出全屏毛玻璃弹窗。
- 完整模拟微信移动端排版样式，直观呈现富文本内联样式、引用块、代码语法高亮与封面题图，核验通过后可直接在弹窗内点击「确认群发排期」。

---

### 4.5 核心舞台 4：配图工作台 (Image Studio)

- **DOM 结构修复**: 彻底校正旧版代码中的标签嵌套错位，恢复输入与交互稳定性。
- **顶部参考重绘工具栏**: 提供参考微信公众号链接输入框与「抓图重绘」触发器，调用 `/api/image-studio/redraw`。
- **左右分栏布局**:
  - **左栏**: 文章标题与正文 Markdown 编辑区，预置 `【此处插入配图：题图或插图描述】` 占位标记，提供「提取插图提示词」按钮（调用 `/api/image-studio/prompts`）。
  - **右栏**: 垂直排布的插图槽位卡片。槽位 1 展示已生成的 2.35:1 晶圆题图微缩图、英文生成 Prompt、Qwen-VL 视觉质量评分及「设为封面题图」按钮；槽位 2 提供 16:9 插图提示词与虚线拖拽/点选上传区域（支持移动端调起系统相册）。

---

### 4.6 核心舞台 5：运维工作台 (Ops Stage)

采用二级分段控制器切换三大运维主域：

1. **信源健康 (Sources Matrix)**:
   - 调用 `GET /api/sources` 与 `POST /api/sources/test`，以扁平卡片网格呈现 12 大信源（机器之心、GitHub Trending、ArXiv AI、少数派、Hacker News、36氪等）。
   - 标注协议类型（RSS / Webhook / API）、网络延迟毫秒数（如 28ms）、最近同步时效及健康绿点。
2. **定时任务 (Cron Scheduler)**:
   - 调用 `GET /api/schedule/jobs`、`POST /api/schedule/add`、`POST /api/schedule/remove`、`POST /api/schedule/pause` 与 `POST /api/schedule/resume`，顶端设置紧凑添加栏（管线类型选择 `task_type`、Cron 表达式标准输入框 `cron_expr`）。
   - 列表呈现已有活跃定时任务，支持一键暂停、恢复与删除。
3. **系统设置 (System Config)**:
   - 调用 `GET / POST /api/config` 与 `GET /api/system/sd_status`，提供双列规整表单：微信公众号凭据（`WECHAT_APP_ID` / `WECHAT_APP_SECRET` 密码框脱敏）、`LLM_API_KEY`、`DASHSCOPE_API_KEY`、`QWEN_IMAGE_MODEL`、`QWEN_VL_MODEL`、`LLM_MODEL`、`QYWECHAT_WEBHOOK`、`IMAGE_GEN_MODEL`、`DIAGRAM_PARALLEL_WORKERS` 及生图服务在线状态检测，底部提供「保存全部设置」操作。

---

## 5. 显式状态机、API 契约与容错机制

### 5.1 工作流有限状态机 (Workflow FSM)

控制台全局管线调度遵循严格的单向有限状态机模型，杜绝非受控并发：

```
                ┌───────────────────────────────────────┐
                │                                       │
                ▼                                       │
            ┌───────┐      用户点击启动       ┌──────────┐      接口返回成功       ┌─────────┐
            │ IDLE  │ ─────────────────────> │ STARTING │ ─────────────────────> │ RUNNING │
            └───────┘                        └──────────┘                        └─────────┘
                ▲                                                                     │
                │                           用户点击终止 / 异常中断                    │
                │                 ┌───────────────────────────────────────────────────┤
                │                 │                                                   │
                │                 ▼                                                   ▼
                │           ┌──────────┐                                        ┌────────┐
                └────────── │ STOPPING │ <───────────────────────────────────── │ PAUSED │
                │           └──────────┘            用户点击暂停                └────────┘
                │                 ▲
                │                 │ 门禁质检通过
                │                 │
                │           ┌───────────┐
                └────────── │ COMPLETED │
                            └───────────┘
```

- `IDLE`: 系统就绪，等待下发任务。
- `STARTING`: 调用 `POST /api/start`，按钮处于加载态，网络锁生效。
- `RUNNING`: 周期轮询 `GET /api/status`（同时获取 `is_running`、`is_paused` 与增量 `logs` 队列），更新四阶段步进条与手风琴卡片。
- `PAUSED`: 调用 `POST /api/pause` 进入挂起态，调用 `POST /api/resume` 恢复运行。
- `STOPPING`: 调用 `POST /api/stop`，安全回收工作流线程。
- `COMPLETED`: 终态质检完成，微信草稿已入库，支持一键呼出预览。
- `ERROR`: 异常捕获，展示错误警示条，保留现场日志。

### 5.2 移动与平板端唤醒同步机制 (Visibility Resync)

由于 iPad 及手机锁屏或切换应用时后台定时器会被系统挂起，前端必须监听浏览器的可见性变更事件：

```javascript
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') {
    // 立即发起一次全量轻量状态核验，修复可能断连的轮询时序
    State.resyncRunningStatus();
  }
});
```

### 5.3 现有 RESTful API 契约向后兼容清单

所有重构前端模块严格对接 `webui.py` 现有已实现路由，保持 100% 协议一致，无需重构 Python 后端接口：

| 方法 | 路由端点 | 载荷参数 / 查询参数 | 返回结构契约 | 归属视图 |
| :--- | :--- | :--- | :--- | :--- |
| `GET` | `/api/status` | 无 | `{"is_running": false, "is_paused": false, "logs": ["SYSTEM \| ..."]}` | 全局 / 总控 |
| `POST`| `/api/start` | `{"task_type": "hotspots"\|"github"\|"aikepu"\|"daily_knowledge"}` | `{"status": "success", "message": "Workflow started"}` | 总控 |
| `POST`| `/api/pause` | 无 | `{"status": "success", "message": "Paused"}` | 总控 |
| `POST`| `/api/resume` | 无 | `{"status": "success", "message": "Resumed"}` | 总控 |
| `POST`| `/api/stop` | 无 | `{"status": "success", "message": "Stop signal sent"}` | 总控 |
| `GET` | `/api/system/llm_cache_stats` | 无 | `{"hit_rate": 0.94, "saved_tokens": 128400, "saved_cny": 1.82, "last_latency_ms": 420}` | 总控 |
| `POST`| `/api/system/warmup_cache` | 无 | `{"status": "success"}` | 总控 |
| `GET` | `/api/kepu/trees` | 无 | `{"status": "success", "active": "default", "trees": [...]}` | 图谱 |
| `GET/POST`| `/api/kepu/active` | `{"name": "law"}` (POST) | `{"status": "success", "active": "law", "title": "...", "node_count": 12}` | 图谱 |
| `POST`| `/api/kepu/import` | `multipart/form-data (file, name)` | `{"status": "success", "name": "custom", "node_count": 30}` | 图谱 |
| `GET` | `/api/aikepu/tree_stats` | `?force=0\|1` | `{"status": "success", "stats": {...}}` | 总控 / 图谱 |
| `GET` | `/api/aikepu/full_tree` | `?force=0\|1` | `{"status": "success", "meta": {...}, "nodes": [...], "published_ids": [...], "draft_ids": [...], "available_ids": [...], "stats": {...}}` | 图谱 |
| `POST`| `/api/aikepu/sync_wechat` | 无 | `{"status": "success", "message": "...", "result": {...}}` | 图谱 |
| `POST`| `/api/aikepu/set_node_status` | `{"node_id": "math-basics", "status": "published"\|"draft"\|"reset"}` | `{"status": "success", "published_ids": [...], "stats": {...}}` | 图谱 |
| `POST`| `/api/aikepu/generate_node` | `{"node_id": "math-basics"}` | `{"status": "success", "message": "..."}` | 图谱 |
| `GET` | `/api/history`| 无 | `{"history": {...}, "unsent": [...], "sent": [...]}` | 审稿 |
| `POST`| `/api/history/delete` | `{"ids": [1, 2]}` 或 `{"id": 1}` | `{"status": "success", "deleted": 2}` | 审稿 |
| `POST`| `/api/history/mark_published` | `{"id": 1}` | `{"status": "success"}` | 审稿 |
| `POST`| `/api/review/approve` | `{"id": 1}` | `{"status": "success", "draft_id": "..."}` | 审稿 |
| `GET` | `/api/preview/<preview_id>` | 路径参数 `preview_id` | 完整渲染后的文章 HTML 文档（直接挂载于 `iframe.src`） | 审稿 (弹窗) |
| `POST`| `/api/image-studio/redraw` | `{"article_url": "https://mp.weixin.qq.com/s/...", "count": 4}` | `{"status": "success", "count": 4, "images": [{"index": 1, "url": "/static_assets/..."}]}` | 配图 |
| `POST`| `/api/image-studio/prompts`| `{"article_title": "...", "article_text": "..."}` | `{"status": "success", "prompts": [{"index": 1, "keyword": "...", "prompt": "..."}]}` | 配图 |
| `POST`| `/api/image-studio/upload` | `multipart/form-data (image, index)` | `{"status": "success", "index": 1, "url": "/static_assets/..."}` | 配图 |
| `POST`| `/api/image-studio/preview` | `{"article_title": "...", "article_text": "...", "images": {"1": "/static_assets/..."}}` | `{"status": "success", "html": "..."}` | 配图 |
| `GET` | `/api/sources` | 无 | `{"sources": {...}}` | 运维 |
| `POST`| `/api/sources/test` | 无 | `{"status": "success", "sources": {...}}` | 运维 |
| `GET` | `/api/schedule/jobs`| 无 | `{"status": "success", "jobs": [{"id": "...", "name": "...", "task_type": "...", "next_run_time": "...", "status": "active"}]}` | 运维 |
| `POST`| `/api/schedule/add`| `{"task_type": "hotspots", "cron_expr": "0 8 * * *"}` | `{"status": "success", "job_id": "..."}` | 运维 |
| `POST`| `/api/schedule/remove`| `{"job_id": "..."}` | `{"status": "success"}` | 运维 |
| `POST`| `/api/schedule/pause`| `{"job_id": "..."}` | `{"status": "success"}` | 运维 |
| `POST`| `/api/schedule/resume`| `{"job_id": "..."}` | `{"status": "success"}` | 运维 |
| `GET/POST` | `/api/config` | 环境变量键值 JSON (POST) | 配置键值 JSON 或 `{"status": "success"}` | 运维 |
| `GET` | `/api/system/sd_status`| 无 | `{"connected": true, "url": "...", "mode": "...", "message": "..."}` | 运维 |

---

## 6. 验收标准与质量门禁 (Verification & Quality Gates)

重构代码合入前必须逐项核对并完全通过以下 6 项硬性质量门禁：

1. **零 Emoji 纯净性门禁**:
   - 运行自动化扫描脚本，对全部提交文件（HTML, CSS, JS, MD）进行 Unicode 字符区段检查：
   - 匹配正则 `[\uD800-\uDBFF][\uDC00-\uDFFF]|[\u2600-\u27BF]|[\u2300-\u23FF]|[\u2B50-\u2B55]|[\u203C-\u2049]`，匹配项必须严格为 0。
2. **模块代码行数门禁**:
   - `static/js/` 下的每一个独立 ES Module（包括 `core/*.js` 与 `views/*.js`）单文件逻辑代码行数（不含文件头注释）不得超过 400 行。超过即强制进一步拆分子模块。
3. **占位符零容忍门禁**:
   - 整个提交树中严禁出现任何未决占位标记（包括未完成事项标记或省略号字符）。所有常量、路径、DOM 映射及状态枚举必须 100% 显式闭环。
4. **多端触控尺寸与无滚动条门禁**:
   - 在 `390x844` (iPhone)、`820x1180` (iPad 竖屏)、`1180x820` (iPad 横屏)、`1024x1366` (iPad Pro) 与 `1440x900` (桌面屏) 5 组基准视口下测试：
   - 页面根节点（`html`, `body`）在任何时刻 `document.documentElement.scrollWidth <= window.innerWidth`，严禁出现根水平滚动条。
   - 移动端所有交互式按钮、Tab、复选框靶心尺寸实测 `getBoundingClientRect()` 宽高均 `>= 44px`。
5. **资产纯净度与静态加载门禁**:
   - 审查网络请求面板，确认 `static/js/three.min.js` 与 `static/js/three-bg.js` 不再被引入或加载。页面加载性能提升明显，无废弃暗色样式污染。
6. **现有测试套件回归门禁**:
   - 在项目根目录下执行 `pytest tests/`，所有关于工作流、搜索器及抓取器的既有后端测试用例必须 100% 保持通过状态，无破坏性改动。
