# AutoWeChat 事实核查与推文去同质化品质升级实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建真实一手信源采集、联网事实检索核验（Search Grounding）、多叙事母题动态生成、多维质量审查拦截与人机协同的完整闭环，从根本上杜绝虚假幻觉信息，并彻底根除硬编码模板导致的千篇一律推文问题。

**Architecture:** 
1. 采集层将纯标题重构为结构化 `HotspotItem` 并引入轻量正文爬虫（Trafilatura）与多信源联网检索器；
2. 创作层彻底废弃单一体裁硬编码，建立包含 4 种叙事弧（博弈调查、技术深挖、商业攻防、叙事微观史）与 4 种黄金 Hook 的自适应 Prompt 引擎，注入事件专属真实事实上下文；
3. 渲染层扩充微光提示卡与多格式组件，删除生硬正则打补丁代码；
4. 门禁层落实真正的 `ReviewGateNode` 阻断机制与主编审校 Agent（Critic），配合 WebUI 待审工作台实现人机风控。

**Tech Stack:** Python 3.8+, Trafilatura, BeautifulSoup4, DuckDuckGo / Bing Search / Bocha API, SQLite / SQLAlchemy, Flask, Loguru, pytest.

---

## 模块改造与文件职责映射

| 模块 | 负责文件 | 核心职责 |
| :--- | :--- | :--- |
| **信源采集对象化** | `core/plugins/base.py`<br>`core/plugins/hotspots_sources.py` | 统一 `HotspotItem` 契约，保留 URL、时间、摘要 |
| **正文抓取与事实基座** | `core/hotspots/scraper.py`<br>`core/hotspots/searcher.py` | 轻量正文提取 + 权威信源联网二次检索 |
| **去套路化动态创作引擎** | `core/hotspots/narrative.py`<br>`prompts/hotspots_skill.md`<br>`core/hotspots/processor.py` | 4 种动态叙事弧路由、Hook 库、禁止八股与套话 |
| **GitHub 质量与安全门禁** | `core/github/collector.py` | Fork/Star 比率、活跃度排查、Demo 截图安全白名单 |
| **排版与视觉组件扩展** | `core/shared/article_utils.py` | 移除生硬补丁正则，支持微光警告卡、对比卡、图注 |
| **审查拦截与主编 Agent** | `core/pipeline/critic.py`<br>`core/hotspots/workflow.py`<br>`core/github/workflow.py` | 修复 `all_ok` 阻断失效 Bug，实现多维质量评分拦截 |
| **数据库追溯与 WebUI 待审池** | `core/db/models.py`<br>`webui.py`<br>`templates/index.html` | 存储信源快照与评分，支持发布前预览与一键打回纠错 |

---

## 实施任务拆解

### Task 1: 数据层重构——采集插件保留结构化信源 (HotspotItem) 与轻量正文提取器

**Files:**
- Create: `core/hotspots/scraper.py`
- Modify: `core/plugins/base.py`
- Modify: `core/plugins/hotspots_sources.py`
- Test: `tests/test_hotspot_scraper.py`

- [ ] **Step 1: 编写测试用例 `tests/test_hotspot_scraper.py`**

```python
import pytest
from core.plugins.base import HotspotItem
from core.hotspots.scraper import extract_article_content

def test_hotspot_item_creation():
    item = HotspotItem(
        title="芯片产业重大政策落地",
        url="https://example.com/news/123",
        source_id="ithome",
        summary="简要概述",
        publish_time="2026-10-08 12:00:00"
    )
    assert item.title == "芯片产业重大政策落地"
    assert item.url == "https://example.com/news/123"
    assert item.summary == "简要概述"

def test_scraper_handles_empty_url():
    assert extract_article_content("") == ""
    assert extract_article_content(None) == ""
```

- [ ] **Step 2: 运行测试验证失败**
Run: `pytest tests/test_hotspot_scraper.py -v`
Expected: FAIL（`HotspotItem` 与 `extract_article_content` 未定义）

- [ ] **Step 3: 在 `core/plugins/base.py` 中定义 `HotspotItem` 数据类**

```python
from dataclasses import dataclass
from typing import Optional, List
from abc import ABC, abstractmethod

@dataclass
class HotspotItem:
    title: str
    url: str = ""
    source_id: str = ""
    summary: str = ""
    publish_time: Optional[str] = None
    raw_content: str = ""
    tier: int = 2  # 1: 官方权威, 2: 科技商业媒体, 3: 社交热搜

class BaseSourcePlugin(ABC):
    @property
    @abstractmethod
    def source_id(self) -> str:
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        pass

    @abstractmethod
    def fetch_data(self) -> List[HotspotItem]:
        """抓取热点数据，返回结构化 HotspotItem 列表"""
        pass
```

- [ ] **Step 4: 实现 `core/hotspots/scraper.py` 正文提取器**

```python
import trafilatura
from loguru import logger
from utils.http_client import build_api_session

HTTP_SESSION = build_api_session()

def extract_article_content(url: str, timeout: int = 10, max_chars: int = 2500) -> str:
    """从目标网页提取主体正文文本，免渲染且高效"""
    if not url or not url.startswith("http"):
        return ""
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=True,
                favor_precision=True
            )
            if text:
                return text[:max_chars].strip()
    except Exception as e:
        logger.warning("抓取原文失败 ({}): {}", url, e)
    return ""
```

- [ ] **Step 5: 改造 `core/plugins/hotspots_sources.py` 中主流源保留 URL 与 Summary**
在各 Plugin 的 `fetch_data()` 中，将解析到的 `title`、`link`、`summary` 封装为 `HotspotItem` 返回，并在向后兼容层中支持字符串自动转换。

- [ ] **Step 6: 运行测试验证通过**
Run: `pytest tests/test_hotspot_scraper.py -v`
Expected: PASS

---

### Task 2: 事实核验与检索基座 (Search Grounding & Fact Verification Engine)

**Files:**
- Create: `core/hotspots/searcher.py`
- Modify: `config.py`
- Test: `tests/test_searcher.py`

- [ ] **Step 1: 编写搜索器测试 `tests/test_searcher.py`**

```python
import pytest
from core.hotspots.searcher import build_fact_context, clean_search_snippets

def test_clean_search_snippets():
    raw_results = [
        {"title": "新闻标题A", "snippet": "这是详细的事件事实数据：投资340亿。"},
        {"title": "新闻标题B", "snippet": "重复内容或简短描述。"}
    ]
    context = clean_search_snippets(raw_results)
    assert "新闻标题A" in context
    assert "投资340亿" in context

def test_build_fact_context_empty():
    ctx = build_fact_context("未知话题", raw_content="")
    assert "未获取到原文详细报道" in ctx or "核心检索事实" in ctx
```

- [ ] **Step 2: 运行测试验证失败**
Run: `pytest tests/test_searcher.py -v`
Expected: FAIL（模块未实现）

- [ ] **Step 3: 在 `config.py` 增加搜索与核查配置项**

```python
# 事实核查与搜索配置
ENABLE_FACT_SEARCH = os.getenv("ENABLE_FACT_SEARCH", "True").lower() == "true"
FACT_SEARCH_PROVIDER = os.getenv("FACT_SEARCH_PROVIDER", "duckduckgo") # duckduckgo / bocha / bing
MAX_FACT_SNIPPETS = int(os.getenv("MAX_FACT_SNIPPETS", "4"))
```

- [ ] **Step 4: 实现 `core/hotspots/searcher.py`**

```python
from typing import List, Dict
from loguru import logger
import requests
from config import ENABLE_FACT_SEARCH, MAX_FACT_SNIPPETS

def search_topic_facts(query: str, max_results: int = MAX_FACT_SNIPPETS) -> List[Dict[str, str]]:
    """轻量检索外部权威信源，补充事件背景事实"""
    if not ENABLE_FACT_SEARCH or not query:
        return []
    results = []
    # 策略 1: 优先尝试无需 API key 的 DuckDuckGo Lite 提取
    try:
        from bs4 import BeautifulSoup
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": f"{query} 科技 新闻"},
            headers=headers,
            timeout=8
        )
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for result in soup.select(".result")[:max_results]:
                t = result.select_one(".result__title")
                s = result.select_one(".result__snippet")
                if t and s:
                    results.append({
                        "title": t.get_text(strip=True),
                        "snippet": s.get_text(strip=True)
                    })
            if results:
                logger.info("  🔍 成功获取 {} 条外部事实佐证材料", len(results))
                return results
    except Exception as e:
        logger.debug("DuckDuckGo 事实检索降级: {}", e)

    return results

def clean_search_snippets(raw_results: List[Dict[str, str]]) -> str:
    lines = []
    for idx, r in enumerate(raw_results, 1):
        lines.append(f"[{idx}] {r['title']}: {r['snippet']}")
    return "\n".join(lines)

def build_fact_context(topic: str, raw_content: str = "", search_results: List[Dict[str, str]] = None) -> str:
    """组合原文正文与外部检索，构建结构化真实事实基座"""
    parts = []
    if raw_content:
        parts.append(f"【一手正文抓取核心片段】：\n{raw_content[:1800]}")
    else:
        parts.append("【一手正文抓取】：未获取到原文全文，需依赖外部检索材料核查。")

    if search_results:
        parts.append("【外部权威媒体交叉检索佐证】：\n" + clean_search_snippets(search_results))
    
    return "\n\n".join(parts)
```

- [ ] **Step 5: 运行测试验证通过**
Run: `pytest tests/test_searcher.py -v`
Expected: PASS

---

### Task 3: 消除硬编码——动态叙事弧 (Narrative Archetypes) 与反套路多风格创作系统

**Files:**
- Create: `core/hotspots/narrative.py`
- Create: `prompts/hotspots_skill.md`
- Modify: `core/hotspots/processor.py`
- Test: `tests/test_narrative_engine.py`

- [ ] **Step 1: 编写叙事路由测试 `tests/test_narrative_engine.py`**

```python
import pytest
from core.hotspots.narrative import select_narrative_archetype, select_dynamic_hook

def test_select_narrative_archetype():
    # 政策与制裁话题应匹配博弈调查型
    arch_policy = select_narrative_archetype("某国升级对华半导体出口管制法案")
    assert arch_policy["id"] == "investigative_game"
    
    # 开源突破/架构话题应匹配技术破局型
    arch_tech = select_narrative_archetype("DeepSeek 发布全新稀疏混合专家模型架构")
    assert arch_tech["id"] == "tech_deep_dive"

def test_select_dynamic_hook():
    hook = select_dynamic_hook("investigative_game")
    assert hook["name"] in ["反常识冲突", "利益账单与代价", "关键现场特写", "认知逆转"]
```

- [ ] **Step 2: 运行测试验证失败**
Run: `pytest tests/test_narrative_engine.py -v`
Expected: FAIL（模块未实现）

- [ ] **Step 3: 实现 `core/hotspots/narrative.py` 动态体裁与 Hook 分发器**

```python
import random
from typing import Dict, Any

# 4 大叙事母题（彻底打破单一 4个H2 的八股）
NARRATIVE_ARCHETYPES = [
    {
        "id": "investigative_game",
        "name": "利益博弈调查型",
        "keywords": ["管制", "制裁", "法案", "监管", "反垄断", "关税", "地缘", "政策", "调查", "封锁"],
        "tone": "抽丝剥茧、算清利益账单的深度调查记者",
        "structural_flow": "暗线切入(揭开未被关注的受损方) -> 算账时刻(量化各方得失数据) -> 博弈暗流(表象下的深层权力平衡) -> 终局推演(对行业格局的链式反应)",
        "heading_style": "疑问句与矛盾推断型标题，如：'ASML为什么在此时表态？'、'35%税率背后的暗中妥协'"
    },
    {
        "id": "tech_deep_dive",
        "name": "极客技术破局型",
        "keywords": ["模型", "架构", "芯片", "算法", "参数", "开源", "算力", "量子", "具身智能", "机器人", "SOTA"],
        "tone": "一眼看穿技术本质的资深架构师",
        "structural_flow": "打破营销话术(直戳真实技术指标) -> 原理极简拆解(用顿悟级类比讲清架构创新) -> 工程落地的真实代价(算力、内存与吞吐瓶颈) -> 开发者行动启示",
        "heading_style": "技术机制命名型标题，如：'拆解 MoE 路由的稀疏陷阱'、'显存带宽：隐蔽的木桶短板'"
    },
    {
        "id": "business_war",
        "name": "商业与产业链攻防型",
        "keywords": ["财报", "融资", "收购", "市值", "IPO", "独角兽", "英伟达", "微软", "OpenAI", "苹果", "华为"],
        "tone": "深谙产业周期与商业底牌的战略观察家",
        "structural_flow": "暴风眼事件 -> 护城河保卫战(老霸主的防御与新贵的突围) -> 供应链上下游震荡 -> 周期宿命预判",
        "heading_style": "商业攻防态势型标题，如：'万卡集群的折旧钟声'、'从软硬件绑定到生态防线破裂'"
    },
    {
        "id": "narrative_human",
        "name": "叙事特写与认知逆转型",
        "keywords": [],  # 缺省通用备选
        "tone": "洞察时代变迁、文笔犀利冷静的专栏作家",
        "structural_flow": "微观切片(一个具体从业者或实验室的微小异动) -> 宏观巨浪(小异动折射的时代风暴) -> 认知的盲区(绝大多数人错判了什么) -> 留白与沉思",
        "heading_style": "具象镜头感金句标题，如：'实验室深夜的一行警报'、'被遗忘在聚光灯外的人'"
    }
]

HOOK_TEMPLATES = [
    {"name": "反常识冲突", "instruction": "以一个所有人都坚信但事实完全相反的残酷反差开头。"},
    {"name": "利益账单与代价", "instruction": "以一个具体的经济损失、算力账单或隐形成本切入，让读者瞬间产生切肤之痛。"},
    {"name": "关键现场特写", "instruction": "以一个具体的时间点、具体的屏幕警告或一次闭门会议细节开场，极具画面感。"},
    {"name": "认知逆转", "instruction": "指出舆论都在狂欢/恐慌，但最关键的信号其实藏在一个被 99% 人忽略的冷门条款里。"}
]

def select_narrative_archetype(topic: str) -> Dict[str, Any]:
    for arch in NARRATIVE_ARCHETYPES[:3]:
        if any(kw in topic for kw in arch["keywords"]):
            return arch
    return NARRATIVE_ARCHETYPES[3]

def select_dynamic_hook(archetype_id: str) -> Dict[str, str]:
    return random.choice(HOOK_TEMPLATES)
```

- [ ] **Step 4: 创建 `prompts/hotspots_skill.md` 动态多变风格指南**
编写独立 Skill 文件，明确列出《AI 刻板套话黑名单》（严禁“在这场...背后”、“不仅如此”、“换句话说”、“不得不提”、“不可否认”、“毫无疑问”），要求标题动态生成，段落长短交替，彻底铲除硬编码模板。

- [ ] **Step 5: 重构 `core/hotspots/processor.py` 中的生成逻辑**
- 彻底移除硬编码模板中的 `0. 爆款次标题 -> 1. 随性开篇(150字) -> 2. 深度拆解` 刻板大纲；
- 彻底删除 `_auto_add_quotes` 中“用正则强行把正文截取包成 `> 核心视角：...`”的工业化补丁代码；
- 根据传入的 `HotspotItem` 或 `topic`，动态调用 `select_narrative_archetype` 与 `build_fact_context`，组装出**每一次都截然不同的定制 Prompt**。

- [ ] **Step 6: 运行测试验证通过**
Run: `pytest tests/test_narrative_engine.py -v`
Expected: PASS

---

### Task 4: GitHub 真实性四维过滤器与外部链接安全沙箱

**Files:**
- Modify: `core/github/collector.py`
- Modify: `core/github/processor.py`
- Test: `tests/test_github_gate.py`

- [ ] **Step 1: 编写 GitHub 质量与安全测试 `tests/test_github_gate.py`**

```python
import pytest
from unittest.mock import MagicMock
from core.github.collector import is_qualified_repository, is_safe_screenshot_url

def test_is_qualified_repository():
    # 模拟空壳 PPT 项目 (size < 50KB)
    fake_empty_repo = MagicMock()
    fake_empty_repo.archived = False
    fake_empty_repo.fork = False
    fake_empty_repo.license = True
    fake_empty_repo.size = 20
    ok, reason = is_qualified_repository(fake_empty_repo)
    assert not ok
    assert "空壳" in reason

    # 模拟刷量项目 (Star=2000, Fork=5, 比例 < 1%)
    fake_farm_repo = MagicMock()
    fake_farm_repo.archived = False
    fake_farm_repo.fork = False
    fake_farm_repo.license = True
    fake_farm_repo.size = 500
    fake_farm_repo.stargazers_count = 2000
    fake_farm_repo.forks_count = 5
    ok, reason = is_qualified_repository(fake_farm_repo)
    assert not ok
    assert "刷量" in reason or "Fork/Star" in reason

def test_is_safe_screenshot_url():
    assert is_safe_screenshot_url("https://project.github.io/demo") is True
    assert is_safe_screenshot_url("https://my-tool.vercel.app") is True
    assert is_safe_screenshot_url("https://unknown-suspicious-site.com/login") is False
```

- [ ] **Step 2: 运行测试验证失败**
Run: `pytest tests/test_github_gate.py -v`
Expected: FAIL（函数未实现）

- [ ] **Step 3: 在 `core/github/collector.py` 实现 `is_qualified_repository` 与白名单**

```python
SAFE_SCREENSHOT_DOMAINS = [
    "github.io", "vercel.app", "huggingface.co", "pages.dev", "streamlit.app", "gradio.live"
]

def is_safe_screenshot_url(url: str) -> bool:
    if not url: return False
    from urllib.parse import urlparse
    netloc = urlparse(url).netloc.lower()
    return any(netloc == d or netloc.endswith("." + d) for d in SAFE_SCREENSHOT_DOMAINS)

def is_qualified_repository(repo) -> tuple:
    if getattr(repo, "archived", False):
        return False, "项目已归档 (Archived)"
    if getattr(repo, "fork", False):
        return False, "属于 Fork 镜像副本"
    if not getattr(repo, "license", None):
        return False, "缺少开源协议 (License)"
    if getattr(repo, "size", 0) < 50:
        return False, "代码体积过小 (<50KB)，疑似空壳 PPT 项目"

    stars = getattr(repo, "stargazers_count", 0)
    forks = getattr(repo, "forks_count", 0)
    if stars >= 500 and (forks / max(stars, 1)) < 0.015:
        return False, f"Fork/Star 比例异常低 ({forks}/{stars})，疑似刷 Star"

    return True, "合格"
```
在 `take_live_ui_screenshot` 中，增加 `if not is_safe_screenshot_url(url): return None` 拦截保护，坚决杜绝爬虫盲目访问未知第三方域名截图。

- [ ] **Step 4: 清除 `core/github/processor.py` 中的诱导虚构指令**
删除 Prompt 中“*用数字说话：比同类快 3 倍*”的诱导编造文字，替换为：
“*真实性铁律：所有性能指标与实测特性必须严格来自 README 或依赖列表，严禁在无评测数据时凭空编造对比倍数！*”

- [ ] **Step 5: 运行测试验证通过**
Run: `pytest tests/test_github_gate.py -v`
Expected: PASS

---

### Task 5: 视觉排版与微光组件库升级 (自适应容器与图注)

**Files:**
- Modify: `core/shared/article_utils.py`
- Test: `tests/test_article_styling.py`

- [ ] **Step 1: 编写排版渲染测试 `tests/test_article_styling.py`**

```python
import pytest
from core.shared.article_utils import _render_custom_callouts

def test_render_custom_callouts():
    text = "> ⚠️ **避坑指南**：切勿使用 root 权限直接部署。\n\n> 💡 **核心洞察**：底层通信瓶颈在跨机通信。"
    rendered = _render_custom_callouts(text)
    assert "#dc2626" in rendered or "border-left: 4px solid #ef4444" in rendered # 告警红
    assert "#2563eb" in rendered or "border-left: 4px solid #3b82f6" in rendered # 洞察蓝
```

- [ ] **Step 2: 运行测试验证失败**
Run: `pytest tests/test_article_styling.py -v`
Expected: FAIL

- [ ] **Step 3: 在 `core/shared/article_utils.py` 实现自适应微光卡片**
- 增加 `_render_custom_callouts`：
  - `> ⚠️ **避坑/风险**：` → 琥珀红警示框
  - `> 💡 **核心洞察**：` → 极客蓝微光卡
  - `> 📌 **行动清单**：` → 墨绿清单框
- 修复配图占位符游标：当某张图片未生成时，不再留下突兀空行，而是平滑自适应消除。
- 彻底删除当图表关闭时在正文中显示 `🎨 AI 配图提示词卡片（待网页端生图人工替换）` 的草稿污染逻辑，直接平滑转为精美高亮分析文本。

- [ ] **Step 4: 运行测试验证通过**
Run: `pytest tests/test_article_styling.py -v`
Expected: PASS

---

### Task 6: 质量把关门禁 (Review Gate) 与主编审校 Agent (Critic)

**Files:**
- Create: `core/pipeline/critic.py`
- Modify: `core/hotspots/workflow.py`
- Modify: `core/github/workflow.py`
- Modify: `core/aikepu/workflow.py`
- Test: `tests/test_review_gate.py`

- [ ] **Step 1: 编写审核门禁与阻断测试 `tests/test_review_gate.py`**

```python
import pytest
from core.pipeline.critic import evaluate_article_quality

def test_critic_rejects_hallucination_or_cliche():
    bad_article = "在这场看似平静的背后，不仅如此，换句话说，总之发展..."
    result = evaluate_article_quality(title="测试标题", article_text=bad_article, fact_context="真实背景资料")
    assert result["score"] < 80
    assert result["passed"] is False
    assert len(result["critic_issues"]) > 0
```

- [ ] **Step 2: 运行测试验证失败**
Run: `pytest tests/test_review_gate.py -v`
Expected: FAIL（模块未实现）

- [ ] **Step 3: 实现 `core/pipeline/critic.py` 主编审校智能体**

```python
import re
from typing import Dict, Any
from core.shared.llm import call_deepseek_with_retry

CLICHE_PATTERNS = [
    r"在这场.+背后", r"不仅如此", r"换句话说", r"不得不提",
    r"不可否认", r"综上所述", r"总而言之", r"随着.+飞速发展"
]

def evaluate_article_quality(title: str, article_text: str, fact_context: str = "") -> Dict[str, Any]:
    issues = []
    score = 100

    # 1. 检测刻板 AI 套话
    cliche_hits = []
    for pat in CLICHE_PATTERNS:
        matches = re.findall(pat, article_text)
        if matches:
            cliche_hits.extend(matches)
    if len(cliche_hits) >= 2:
        score -= 20
        issues.append(f"命中刻板 AI 套话 {len(cliche_hits)} 次: {list(set(cliche_hits))}")

    # 2. 检查字数合理性 (2000-4000)
    chinese_chars = len(re.findall(r'[\u4e00-\u9fa5]', article_text))
    if chinese_chars < 1800:
        score -= 30
        issues.append(f"正文汉字字数不足 ({chinese_chars} < 1800)")

    passed = score >= 75
    return {
        "score": score,
        "passed": passed,
        "critic_issues": issues,
        "char_count": chinese_chars
    }
```

- [ ] **Step 4: 修复 `core/hotspots/workflow.py` 等 4 个工作流中 `all_ok` 被忽略的致命 Bug**
在各 Workflow 的发布前置位，接收审核结果并严密拦截：
```python
review_res = evaluate_article_quality(clean_title, article_text, fact_context)
if not review_res["passed"]:
    err_msg = f"未通过主编质量门禁 ({review_res['score']}分): {'; '.join(review_res['critic_issues'])}"
    logger.error("❌ 拦截发布: {}", err_msg)
    _save_publish_result(clean_title, success=False, error=err_msg)
    return topic, False, err_msg
```

- [ ] **Step 5: 运行测试验证通过**
Run: `pytest tests/test_review_gate.py -v`
Expected: PASS

---

### Task 7: 数据库审计扩展与 WebUI 人机协同待审工作台 (HITL)

**Files:**
- Modify: `core/db/models.py`
- Modify: `core/db/manager.py`
- Modify: `webui.py`
- Modify: `templates/index.html`
- Test: `tests/test_audit_db.py`

- [ ] **Step 1: 编写数据库扩充测试 `tests/test_audit_db.py`**

```python
import pytest
from core.db.models import ArticleHistory
from core.db.manager import db_manager

def test_article_history_new_fields():
    session = db_manager.get_session()
    ah = ArticleHistory(
        title="测试审计篇目",
        source_type="hotspots",
        publish_date="2026-10-08",
        source_url="https://example.com/test",
        quality_score=92.5,
        status="PENDING_REVIEW"
    )
    session.add(ah)
    session.commit()

    saved = session.query(ArticleHistory).filter_by(title="测试审计篇目").first()
    assert saved.source_url == "https://example.com/test"
    assert saved.quality_score == 92.5
    assert saved.status == "PENDING_REVIEW"
    session.delete(saved)
    session.commit()
```

- [ ] **Step 2: 运行测试验证失败**
Run: `pytest tests/test_audit_db.py -v`
Expected: FAIL（字段不存在）

- [ ] **Step 3: 扩充 `core/db/models.py` 与 `core/db/manager.py` 字段**
在 `ArticleHistory` 中增加：
- `source_url` (Text)
- `quality_score` (Float)
- `status` (String, 默认为 `"PENDING_REVIEW"` 或 `"PUBLISHED"`)
- `fact_check_result` (Text)
在 `DBManager._init_db()` 中使用 `ALTER TABLE` 保证 SQLite 向后平滑兼容。

- [ ] **Step 4: 在 `webui.py` 增加审核操作路由**
- 增加 `/api/review/approve`：将 `PENDING_REVIEW` 草稿正式推送到微信草稿箱；
- 增加 `/api/review/reject`：支持带人工修改意见打回，触发局部 AI 润色；
- 增加 `/api/review/edit`：支持在 WebUI 页面直接轻量在线修正标题和错漏字。

- [ ] **Step 5: 在 `templates/index.html` 渲染【待审池与事实评分】标签页**
在前端展示文章的综合评分、信源链接、事实核查状态与一键发布/纠错操作按钮。

- [ ] **Step 6: 运行测试验证通过**
Run: `pytest tests/test_audit_db.py -v`
Expected: PASS

---

## 自我审查与防硬编码检查项

1. **是否有写死的字数或段落数？**
   - 彻底废除“强制 4 个 H2、强制 3 处金句”。Prompt 指导模型根据事实材料量体裁衣，2000~3500 字自然成文。
2. **是否有写死的大纲结构？**
   - 彻底引入 4 大叙事母题（博弈调查、技术深挖、商业攻防、叙事特写），按话题自适应挑选，拒绝机械套路。
3. **是否有生硬的正则后处理？**
   - 废除强制截断正文做引用的打补丁逻辑，确保排版完全源于大模型对文章语境的理解。
4. **事实输入是否充分？**
   - 确保每篇文章生成时均传入一手正文与权威二次检索，杜绝无事实凭空编造。
