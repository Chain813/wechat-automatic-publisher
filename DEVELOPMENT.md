# 开发工作流

本文档面向开发者，说明项目的开发环境搭建、代码规范、测试方法和发布流程。

---

## 目录

- [开发环境搭建](#开发环境搭建)
- [项目架构](#项目架构)
- [代码规范](#代码规范)
- [测试方法](#测试方法)
- [发布流程](#发布流程)
- [常见开发任务](#常见开发任务)
- [调试技巧](#调试技巧)
- [故障排查](#故障排查)

---

## 开发环境搭建

### 必需环境

```bash
# 1. Python 3.8+
python --version

# 2. 克隆项目
git clone https://github.com/Chain813/wechat-automatic-publisher.git
cd wechat-automatic-publisher

# 3. 创建虚拟环境
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# 4. 安装依赖
pip install -r requirements.txt

# 5. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Key
```

### 可选环境

| 组件 | 用途 | 安装方式 |
|------|------|---------|
| [Stable Diffusion WebUI](https://github.com/AUTOMATIC1111/stable-diffusion-webui) | AI 生图 | 启动时加 `--api` 参数 |
| [Ollama](https://ollama.com) | 本地视觉 AI 评估 | `ollama pull gemma3:4b` |
| [Graphviz](https://graphviz.org/download/) | 架构图渲染 | 安装后添加到系统 PATH |
| Chrome 浏览器 | Selenium 截图 | 自动由 webdriver-manager 管理 |

### 快速验证

```bash
# 验证所有 Python 文件语法正确
python -c "import py_compile; import os; [py_compile.compile(os.path.join(r,f), doraise=True) for r,_,fs in os.walk('.') for f in fs if f.endswith('.py') and 'venv' not in r]"

# 验证配置完整性
python -c "from config import *; print('Config OK')"

# CLI 启动
python main.py --task hotspots
```

---

## 项目架构

### 分层设计

```
┌─────────────────────────────────────────────┐
│  入口层：main.py / webui.py                  │
├─────────────────────────────────────────────┤
│  调度层：core/engine.py                       │
├──────────────────────┬──────────────────────┤
│  热点模块             │  GitHub 模块          │
│  collector → processor│  collector → processor│
│  → workflow           │  → workflow           │
├──────────────────────┴──────────────────────┤
│  共享层：publisher / llm / article_utils      │
├─────────────────────────────────────────────┤
│  工具层：image_handler / image_filter / http  │
├─────────────────────────────────────────────┤
│  基础设施：config / runtime / .env            │
└─────────────────────────────────────────────┘
```

### 数据流

```
热点文章：
  12源采集 → LLM选题 → LLM创作 → 配图下载上传 → 微信草稿

GitHub文章：
  Search API → LLM评估 → 并行配图(6路) → LLM创作 → 微信草稿
```

### 关键设计决策

| 决策 | 理由 |
|------|------|
| ThreadPoolExecutor 而非 asyncio | requests 库同步 API，改动成本低 |
| cancel_event 全局检查点 | 用户可随时中断，无需等待长操作完成 |
| 配图并行 + 集满即停 | 6 种来源同时跑，最快 3 个胜出 |
| LLM 提示词在 processor.py | 集中管理，方便调优 |
| 微信 API 封装在 publisher.py | Token 自动刷新、线程安全、标题去重 |

---

## 代码规范

### 基本规则

- **编码**：所有文件 UTF-8
- **缩进**：4 空格，不用 Tab
- **行宽**：建议 120 字符以内
- **字符串**：内部用单引号，用户可见文本用双引号

### 日志规范

```python
from loguru import logger

# ✅ 正确：用 loguru
logger.info("正在处理 {}", item)
logger.warning("失败: {}", error)
logger.debug("调试信息")

# ❌ 错误：不用 print 做日志
print(f"Processing {item}")  # 只在 _print_banner 等用户可见输出中使用
```

### 线程安全规范

```python
# ✅ 共享资源加锁
_lock = threading.Lock()
with _lock:
    shared_resource.append(item)

# ✅ 检查中断信号
from core.shared.runtime import check_cancelled
check_cancelled()  # 在长时间操作前后调用

# ✅ 可中断等待
from core.shared.llm import _interruptible_sleep
_interruptible_sleep(5)  # 替代 time.sleep(5)
```

### 网络请求规范

```python
# ✅ 用封装的 Session（自动重试 + 缓存）
from utils.http_client import build_api_session
session = build_api_session()
res = session.get(url, timeout=15)

# ✅ 热点采集用缓存 Session
from utils.http_client import build_cached_session
session = build_cached_session("cache_name", ttl_seconds)

# ❌ 不用裸 requests
import requests  # 缺少重试和缓存
```

### LLM 调用规范

```python
# ✅ 统一用 call_deepseek_with_retry
from core.shared.llm import call_deepseek_with_retry
result = call_deepseek_with_retry(
    prompt,
    system_content="...",
    max_retries=2,
    timeout=180,
)

# ❌ 不直接调用 requests.post 到 LLM API
```

---

## 测试方法

### 语法检查

```bash
# 检查所有 Python 文件语法
python -c "
import py_compile, os
for root, _, files in os.walk('.'):
    if 'venv' in root or '__pycache__' in root: continue
    for f in files:
        if f.endswith('.py'):
            py_compile.compile(os.path.join(root, f), doraise=True)
print('All files compile OK')
"
```

### 单模块测试

```bash
# 测试热点采集
python -c "
from core.shared.runtime import configure_runtime
configure_runtime()
from core.hotspots.collector import fetch_all_hotspots
data = fetch_all_hotspots()
print(f'Got {len(data)} chars of hotspot data')
"

# 测试 LLM 调用
python -c "
from core.shared.runtime import configure_runtime
configure_runtime()
from core.shared.llm import call_deepseek_with_retry
result = call_deepseek_with_retry('你好，请回复OK', max_retries=1)
print(f'LLM response: {result}')
"

# 测试微信 Token
python -c "
from config import WECHAT_APP_ID, WECHAT_APP_SECRET
from core.shared.publisher import WeChatPublisher
p = WeChatPublisher(WECHAT_APP_ID, WECHAT_APP_SECRET)
print(f'Token: {p.access_token[:10]}...' if p.access_token else 'FAILED')
"
```

### 集成测试

```bash
# 完整工作流测试（会实际调用 API）
python main.py --task hotspots

# Web UI 测试
python webui.py
# 浏览器访问 http://127.0.0.1:5000
```

### 测试文件

项目在 `scratch/` 目录下有历史测试脚本：

| 文件 | 用途 |
|------|------|
| `test_scrapers.py` | 爬虫功能测试 |
| `test_similarity.py` | 标题相似度算法测试 |
| `test_github_trending.py` | GitHub Trending 采集测试 |
| `verify_all_imports.py` | 全模块导入验证 |

---

## 发布流程

### 版本号规范

项目使用语义化版本：`主版本.次版本.修订号`

- **主版本**：重大架构变更或不兼容改动
- **次版本**：新功能或显著优化
- **修订号**：Bug 修复和小改动

### 发布步骤

```bash
# 1. 确保所有改动已提交
git status

# 2. 运行语法检查
python -c "import py_compile; ..."

# 3. 更新 README.md 版本号和变更说明

# 4. 提交
git add -A
git commit -m "vX.Y.Z: description"

# 5. 推送
git push origin main
```

### 提交信息规范

```
<类型>: <简短描述>

类型：
- feat: 新功能
- fix: Bug 修复
- perf: 性能优化
- refactor: 代码重构
- docs: 文档更新
- style: 格式调整
- test: 测试相关
- chore: 构建/工具相关
```

---

## 常见开发任务

### 添加新的热点数据源

1. 在 `core/hotspots/collector.py` 添加 `fetch_xxx()` 函数
2. 注册到 `_SOURCE_FETCHERS` 字典
3. 在 `config.py` 的 `NEWS_SOURCES` 列表添加源名
4. 在 `source_labels` 字典添加中文标签
5. 测试：`python -c "from core.hotspots.collector import fetch_xxx; print(fetch_xxx())"`

### 修改文章生成提示词

- 热点文章：编辑 `core/hotspots/processor.py` 的 `SYSTEM_PROMPT`
- GitHub 文章：编辑 `core/github/processor.py` 的 `SYSTEM_PROMPT`
- 用户 prompt：编辑对应的 `generate_article()` / `generate_github_article()` 函数
- 测试：运行一次工作流，检查生成的文章质量

### 添加新的图片来源

1. 在 `utils/image_handler.py` 添加 `try_xxx()` 函数
2. 在 `download_image()` 中添加到调用链
3. 如果需要评分，参考 `image_filter.py` 的 `evaluate_image()`

### 修改配图管线

- 热点配图：`core/shared/article_utils.py` 的 `process_article_content()`
- GitHub 配图：`core/github/workflow.py` 的 `_ensure_deep_images()`
- 图片评分：`utils/image_filter.py` 的 `evaluate_image()`

---

## 调试技巧

### 查看实时日志

```bash
# CLI 模式直接看终端输出
python main.py --task hotspots

# Web 模式看浏览器控制台
python webui.py
# 浏览器 F12 → Console
```

### 调整日志级别

```python
# 在 configure_runtime() 中修改
logger.add(sys.stderr, level="DEBUG")  # 改为 DEBUG 看更多信息
```

### 测试单个函数

```python
# 直接导入测试
from core.shared.runtime import configure_runtime
configure_runtime()  # 初始化日志和配置

# 然后调用目标函数
from core.hotspots.processor import generate_article
article = generate_article("AI芯片禁令")
print(f"字数: {len(article)}")
```

### 检查微信 API

```bash
# 测试 Token 获取
python -c "
from config import WECHAT_APP_ID, WECHAT_APP_SECRET
from core.shared.publisher import WeChatPublisher
p = WeChatPublisher(WECHAT_APP_ID, WECHAT_APP_SECRET)
print('Token:', p.access_token[:20] if p.access_token else 'FAILED')
print('Drafts:', p.get_draft_titles()[:3])
"
```

---

## 故障排查

### 常见问题

| 症状 | 原因 | 解决 |
|------|------|------|
| `ModuleNotFoundError` | 依赖未安装 | `pip install -r requirements.txt` |
| `Token 授权失败` | AppID/Secret 错误 | 检查 `.env` 配置 |
| `AI 调用超时` | 网络或 API 问题 | 检查 `LLM_BASE_URL` 和网络 |
| `SD 服务未连接` | SD WebUI 未启动 | 启动 SD 并加 `--api` |
| `Selenium 报错` | Chrome 版本不匹配 | `pip install --upgrade webdriver-manager` |
| `文章被截断` | `LLM_MAX_TOKENS` 太低 | 检查 `config.py`（默认 8192） |
| `配图全部失败` | SD 服务挂了 | 检查 SD WebUI 状态 |

### 日志分析

```bash
# 保存日志到文件
python main.py --task hotspots 2>&1 | tee run.log

# 搜索错误
grep -i "error\|fail\|exception" run.log
```

### 重置状态

```bash
# 清理历史记录（重新开始）
rm hotspots_history.json github_history.json github_publish_records.json

# 清理图片缓存
rm -rf assets/

# 清理热点缓存
rm hotspot_cache.sqlite
```
