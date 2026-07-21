"""
============================================================
  图表生成引擎 v2.0 (双引擎架构)
  优先使用轻量级本地渲染 (Graphviz + Matplotlib)
  降级使用 Selenium Headless 浏览器渲染
============================================================
"""
import os
import re
import json
import time
from loguru import logger
from core.shared.llm import call_deepseek_with_retry

# 图表占位符正则
DIAGRAM_PLACEHOLDER_PATTERN = re.compile(r"【\s*此处绘制图表\s*[：:]\s*(.*?)\s*】")

# ==========================================
#  LLM 图表代码生成 Prompt
# ==========================================
LITE_DIAGRAM_SYSTEM_PROMPT = """你是一位精通数据可视化的技术图表专家。你的任务是将用户的中文描述转化为结构化的图表渲染指令。

## 图表类型判定
根据描述内容，选择以下最合适的格式：

### 1. GRAPHVIZ (适合流程图、架构图、依赖关系图、步骤说明、神经网络结构)
如果描述涉及"流程"、"步骤"、"架构"、"结构"、"关系"、"网络层"，选择此格式。
输出严格的 DOT 语言代码，用 ```dot 包裹。
- 必须使用中文标签
- 使用 rankdir=TB 或 rankdir=LR
- 节点使用 shape=box, style=filled, fillcolor 等美化
- 示例：
```dot
digraph G {
    rankdir=TB;
    node [shape=box, style="filled,rounded", fontname="Microsoft YaHei"];
    A [label="输入数据", fillcolor="#1e3a5f", fontcolor="white"];
    B [label="特征提取", fillcolor="#2563eb", fontcolor="white"];
    A -> B [color="#3b82f6"];
}
```

### 2. FORMULA (适合数学公式、方程、核心定理)
如果描述涉及"公式"、"方程"、"求导"、"矩阵"、"损失函数"、"更新规则"，选择此格式。
输出 JSON 格式，用 ```json 包裹：
```json
{
    "type": "formula",
    "title": "公式标题",
    "formulas": ["LaTeX公式1", "LaTeX公式2"],
    "notes": ["变量说明1", "变量说明2"]
}
```
注意：LaTeX 公式中反斜杠需要正常书写（如 \\frac, \\sum），不要双重转义。

### 3. COMPARISON (适合对比表格、PK、特性比较)
如果描述涉及"对比"、"比较"、"区别"、"特征"、"优缺点"，选择此格式。
输出 JSON 格式：
```json
{
    "type": "comparison",
    "title": "对比标题",
    "columns": ["特性", "方案A", "方案B"],
    "rows": [
        ["数据需求", "大量", "少量"],
        ["训练速度", "慢", "快"]
    ]
}
```

### 4. SUMMARY (适合要点清单、核心概念总结)
如果描述涉及"要点"、"总结"、"清单"、"概念"，选择此格式。
输出 JSON 格式：
```json
{
    "type": "summary",
    "title": "卡片标题",
    "points": ["要点1", "要点2", "要点3"]
}
```

## 输出规则
- 直接输出代码块，不要有任何多余解释
- 图表内容必须与描述**高度匹配**，不要遗漏核心信息
- 所有文本使用中文
"""

# Selenium 渲染的旧版 Prompt（回退用）
SELENIUM_DIAGRAM_SYSTEM_PROMPT = """你是一位精通可视化设计的排版与图表专家。你的任务是将用户的中文描述转化为一张美观、直观且高颜值的技术图表、数学公式卡片或核心概念总结卡片。

## 图表类型判定
根据用户的描述，选择以下三种最合适的格式之一：

1. **MERMAID** (适合流程图、思维脑图、架构图、时序图、步骤说明)
   - 语法必须用 ```mermaid 和 ``` 包裹。
   - 请使用规范的 Mermaid 语法（例如：graph TD; A-->B）。
   - 尽量包含清晰的中文标签。

2. **LATEX** (适合展示复杂的数学公式、定理、神经网络公式等)
   - 必须用 ```html 和 ``` 包裹。整个内容作为一个居中的高档学术卡片，外面加上标题。公式部分用 $$ ... $$ 包裹。

3. **HTML** (适合展示对比表格、要点清单、带渐变色的核心概念总结卡、代码高亮)
   - 必须用 ```html 和 ``` 包裹。
   - 可以自由使用 Tailwind CSS 样式类。
   - 确保使用现代科技感配色。

## 设计要求
1. 宽窗口布局在 700px 左右，请使用圆角和阴影增加立体感。
2. 配色以深色高档科技风为主：背景色为深色，主色调青蓝色 #3b82f6 / #06b6d4，强调色橙色/红色 #f97316 / #ef4444。
3. 文本行高、内边距必须适中，提供极佳的阅读体验。

## 输出格式
直接输出完整的代码块，不要有任何多余的解释字句。
"""


def _extract_code_block(text):
    """提取响应中的代码块并返回 (类型, 代码内容)"""
    # dot / graphviz
    m = re.search(r'```(?:dot|graphviz)\s*\n(.*?)\n```', text, re.DOTALL | re.IGNORECASE)
    if m:
        return "graphviz", m.group(1).strip()

    # json
    m = re.search(r'```json\s*\n(.*?)\n```', text, re.DOTALL | re.IGNORECASE)
    if m:
        return "json", m.group(1).strip()

    # mermaid
    m = re.search(r'```mermaid\s*\n(.*?)\n```', text, re.DOTALL | re.IGNORECASE)
    if m:
        return "mermaid", m.group(1).strip()

    # html
    m = re.search(r'```html\s*\n(.*?)\n```', text, re.DOTALL | re.IGNORECASE)
    if m:
        return "html", m.group(1).strip()

    # 通用代码块
    m = re.search(r'```\s*\n(.*?)\n```', text, re.DOTALL)
    if m:
        content = m.group(1).strip()
        if content.lstrip().startswith(("digraph", "graph", "strict")):
            return "graphviz", content
        if content.lstrip().startswith("{"):
            return "json", content
        if "graph" in content and ("-->" in content or "---" in content):
            return "mermaid", content
        return "html", content

    # 裸文本判定
    text_s = text.strip()
    if text_s.startswith(("digraph", "graph ")):
        return "graphviz", text_s
    if text_s.startswith("{"):
        return "json", text_s
    return "text", text_s


# ==========================================
#  轻量级渲染管线 (Graphviz + Matplotlib)
# ==========================================
def _try_lite_render(description, save_dir):
    """
    使用轻量级渲染器生成图表：
    1. 调用 LLM 生成结构化图表指令 (DOT / JSON)
    2. 使用 Graphviz 或 Matplotlib 本地渲染
    """
    from core.shared.runtime import check_cancelled
    check_cancelled()

    user_prompt = (
        f"请为以下描述生成一张适合公众号内嵌的高质量技术图表：\n\n"
        f"描述：{description}\n\n"
        f"直接输出适合的代码块，不要废话。"
    )

    response = call_deepseek_with_retry(
        user_prompt,
        system_content=LITE_DIAGRAM_SYSTEM_PROMPT,
        max_retries=1,
        backoff_base=0.5,
    )
    if not response:
        return None

    dtype, code = _extract_code_block(response)
    if not code:
        logger.warning("  [lite] 未提取到有效图表代码")
        return None

    output_path = os.path.join(save_dir, f"diagram_{int(time.time() * 1000)}.png")
    os.makedirs(save_dir, exist_ok=True)

    # Graphviz 流程图
    if dtype == "graphviz":
        from utils.lite_render import render_graphviz
        if render_graphviz(code, output_path):
            return output_path

    # JSON 结构化指令 (formula / comparison / summary)
    if dtype == "json":
        try:
            data = json.loads(code)
        except json.JSONDecodeError as e:
            logger.warning("  [lite] JSON 解析失败: {}", e)
            return None

        chart_type = data.get("type", "")

        if chart_type == "formula":
            from utils.lite_render import render_formula_card
            if render_formula_card(
                title=data.get("title", ""),
                formula_lines=data.get("formulas", []),
                notes=data.get("notes"),
                output_path=output_path,
            ):
                return output_path

        elif chart_type == "comparison":
            from utils.lite_render import render_comparison_card
            if render_comparison_card(
                title=data.get("title", ""),
                columns=data.get("columns", []),
                rows=data.get("rows", []),
                output_path=output_path,
            ):
                return output_path

        elif chart_type == "summary":
            from utils.lite_render import render_text_card
            if render_text_card(
                title=data.get("title", ""),
                bullet_points=data.get("points", []),
                output_path=output_path,
            ):
                return output_path

    logger.debug("  [lite] 类型 '{}' 未被轻量级引擎处理", dtype)
    return None


# ==========================================
#  在线 API 渲染 (Mermaid.ink)
# ==========================================
def _try_api_render(mermaid_code, output_path):
    """
    使用 Mermaid.ink API 在线将 Mermaid 代码转换为 PNG。
    """
    import base64
    from utils.http_client import build_api_session
    
    try:
        mermaid_code = mermaid_code.strip()
        
        # 自动将全局样式模板注入代码，保证高颜值配色
        style_template = (
            "\n"
            "classDef default fill:#1f2937,stroke:#3b82f6,stroke-width:2px,color:#f3f4f6;\n"
            "classDef highlight fill:#1e3a8a,stroke:#60a5fa,stroke-width:2px,color:#ffffff;\n"
            "classDef success fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#d1fae5;\n"
            "classDef warning fill:#78350f,stroke:#f59e0b,stroke-width:2px,color:#fef3c7;\n"
            "classDef danger fill:#7f1d1d,stroke:#ef4444,stroke-width:2px,color:#fee2e2;\n"
        )
        if "classDef" not in mermaid_code:
            # 兼容带有 class 定义的 mermaid 代码结构，附加样式声明
            mermaid_code = mermaid_code + style_template
            
        b64_code = base64.b64encode(mermaid_code.encode('utf-8')).decode('utf-8')
        url = f"https://mermaid.ink/img/{b64_code}"
        
        session = build_api_session()
        res = session.get(url, timeout=20)
        if res.status_code == 200 and len(res.content) > 500:
            if b"Syntax error" in res.content or b"syntax error" in res.content:
                logger.warning("  [mermaid.ink] API 返回包含语法错误的图片，拒绝使用并降级为 HTML 卡片渲染")
                return False
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(res.content)
            logger.info("  [mermaid.ink] API 渲染成功: {} ({:.1f} KB)", os.path.basename(output_path), len(res.content)/1024)
            return True
        else:
            logger.warning("  [mermaid.ink] API 渲染失败，状态码: {}, 响应长度: {}", res.status_code, len(res.content) if res else 0)
    except Exception as e:
        logger.warning("  [mermaid.ink] API 渲染异常: {}", e)
        
    return False


# ==========================================
#  高性能高颜值渲染 Prompts
# ==========================================
UNIFIED_DIAGRAM_SYSTEM_PROMPT = r"""你是一位顶尖的数据可视化与网页排版设计专家。你的任务是将用户的中文描述转化为一张美观、现代、高颜值且适合微信公众号嵌入的技术图表或概念说明卡片。

根据描述内容，选择以下最合适的一种格式输出：

### 1. MERMAID (适合流程图、架构图、脑图、时序图、步骤说明、关系网络、层次依赖)
如果描述涉及"流程"、"步骤"、"架构"、"关系"、"网络"、"脑图"、"依赖"，必须选择此格式。
输出严格的 Mermaid 代码，用 ```mermaid 包裹。
- 必须使用中文标签。
- 节点形状多样化（如圆角矩形 `(文本)`、圆柱 `[(文本)]`、菱形 `{"文本"}`）。
- 必须使用内置样式定义进行美化（在代码尾部使用 classDef 定义样式，并用 ::: 绑定到对应节点上）。
- 示例：
```mermaid
graph TD
    classDef default fill:#1f2937,stroke:#3b82f6,stroke-width:2px,color:#f3f4f6;
    classDef highlight fill:#1e3a8a,stroke:#60a5fa,stroke-width:2px,color:#ffffff;
    
    A[输入数据] --> B(特征提取):::highlight
    B --> C{是否合格}
    C -- 是 --> D[保存结果]
    C -- 否 --> E[抛出异常]:::default
```

### 2. HTML (适合数学公式、核心定理、对比表格、属性PK、要点清单、概念总结卡)
如果不属于流程图/架构图/脑图，必须选择此格式。
输出精美的 HTML+Tailwind CSS 代码，用 ```html 包裹。
- 整个内容必须是一个独立的卡片式容器（如带有 px/py 内边距和现代感圆角阴影的 div），宽度固定为 700px。
- 使用高档深色科技风配色：背景使用深色渐变（如 `from-slate-900 to-slate-950`），文字使用明亮的灰白双色（如 `text-slate-100`、`text-slate-400`）。
- 适当添加现代感设计元素：圆角（`rounded-2xl`）、微弱边框（`border border-slate-800`）、渐变强调文字（`bg-gradient-to-r from-blue-400 to-cyan-400 bg-clip-text text-transparent`）。
- 对于公式：使用 KaTeX 格式，即公式部分用 `$$ ... $$` 或 `$` 包裹，并在卡片中做适当的变量对照与背景说明。
- 示例 1 (公式卡片)：
```html
<div class="w-[700px] p-8 bg-gradient-to-br from-slate-900 to-slate-950 rounded-2xl border border-slate-800 shadow-2xl">
    <h3 class="text-xl font-bold text-slate-100 mb-4 bg-gradient-to-r from-blue-400 to-cyan-400 bg-clip-text text-transparent font-sans">梯度下降更新公式</h3>
    <div class="text-center my-6 text-2xl text-slate-100 font-serif">
        $$w_{t+1} = w_t - \eta \nabla L(w_t)$$
    </div>
    <div class="border-t border-slate-800/80 pt-4 mt-4">
        <p class="text-xs text-slate-400 leading-relaxed font-mono">
            其中：$w$ 表示权重参数，$\eta$ 表示学习率，$\nabla L(w)$ 表示损失函数关于权重的梯度。
        </p>
    </div>
</div>
```
- 示例 2 (对比表格)：
```html
<div class="w-[700px] p-6 bg-gradient-to-b from-slate-900 to-slate-950 rounded-2xl border border-slate-800 shadow-2xl">
    <h3 class="text-lg font-bold text-slate-100 mb-4 flex items-center gap-2 font-sans">
        <span class="w-1.5 h-5 bg-blue-500 rounded-full"></span> 核心算法对比分析
    </h3>
    <table class="w-full text-sm text-left text-slate-300">
        <thead class="text-xs text-slate-400 uppercase bg-slate-900/50">
            <tr>
                <th class="px-4 py-3 rounded-l-lg">特性</th>
                <th class="px-4 py-3">深度学习</th>
                <th class="px-4 py-3 rounded-r-lg">传统ML</th>
            </tr>
        </thead>
        <tbody class="divide-y divide-slate-800/50">
            <tr>
                <td class="px-4 py-3 font-semibold text-slate-200">数据量需求</td>
                <td class="px-4 py-3 text-blue-400">海量数据 (Big Data)</td>
                <td class="px-4 py-3 text-slate-400">中小型数据集</td>
            </tr>
            <tr>
                <td class="px-4 py-3 font-semibold text-slate-200">特征工程</td>
                <td class="px-4 py-3 text-blue-400">端到端自动表征学习</td>
                <td class="px-4 py-3 text-slate-400">手动设计提取特征</td>
            </tr>
        </tbody>
    </table>
</div>
```

## 输出规则
- 直接输出代码块，不要有任何多余解释。
- 绝不允许输出除 MERMAID 和 HTML 以外的格式。
"""


# ==========================================
#  高质量图表渲染引擎 (API + Selenium)
# ==========================================
def _try_high_quality_render(description, save_dir):
    """
    尝试以最高质量渲染图表：
    1. 调用 LLM 生成对应的 Mermaid 或 HTML 代码
    2. 若是 Mermaid：优先通过在线 API 渲染，失败则走本地 Selenium 网页截图
    3. 若是 HTML：直接通过本地 Selenium 网页截图
    """
    from core.shared.runtime import check_cancelled
    check_cancelled()

    user_prompt = (
        f"请为以下描述设计并生成一张适合公众号内嵌的高颜值技术图文卡片或图表：\n\n"
        f"描述：{description}\n\n"
        f"提示：直接输出适合的代码块，不要任何废话。"
    )

    # 强制将图表生成重载为轻量级/快速的 flash 模型以加快生成速度
    from config import LLM_MODEL
    diagram_model = LLM_MODEL.replace("-pro", "-flash").replace("pro", "flash")
    logger.info("  [图表生成] 使用模型 {} 生成高质量图表代码...", diagram_model)

    response = call_deepseek_with_retry(
        user_prompt,
        system_content=UNIFIED_DIAGRAM_SYSTEM_PROMPT,
        max_retries=1,
        backoff_base=0.5,
        model=diagram_model
    )
    if not response:
        return None

    dtype, code = _extract_code_block(response)
    if not code:
        logger.warning("  [高质引擎] 未提取到有效的图表代码")
        return None

    output_path = os.path.join(save_dir, f"diagram_{int(time.time() * 1000)}.png")
    os.makedirs(save_dir, exist_ok=True)

    if dtype == "mermaid":
        # a. 优先尝试 Mermaid.ink API
        if _try_api_render(code, output_path):
            return output_path
            
        # b. API 失败时，降级使用 Selenium 网页截图渲染
        logger.info("  [高质引擎] Mermaid.ink API 渲染未成功，尝试本地 Selenium 降级渲染...")
        try:
            from utils.html_render import render_html_to_png
            html_content = f'<div class="mermaid">\n{code}\n</div>'
            if render_html_to_png(html_content, output_path):
                return output_path
        except Exception as e:
            logger.warning("  [高质引擎] 本地 Selenium 渲染 Mermaid 异常: {}", e)

    elif dtype in ("html", "text", "json"):
        # 使用 Selenium 网页截图渲染 HTML+Tailwind 卡片
        try:
            from utils.html_render import render_html_to_png
            if render_html_to_png(code, output_path):
                return output_path
        except Exception as e:
            logger.warning("  [高质引擎] 本地 Selenium 渲染 HTML 异常: {}", e)

    else:
        logger.warning("  [高质引擎] 不支持的代码格式类型: {}", dtype)

    return None


# ==========================================
#  统一入口：双引擎图表生成
# ==========================================
def generate_diagram(description, save_dir="assets"):
    """
    根据自然语言描述生成图表 PNG。
    双引擎新架构：
    1. 优先使用高质量渲染管线 (Mermaid.ink API + Selenium 网页卡片)
    2. 失败时降级到本地轻量级渲染 (Graphviz + Matplotlib) 作为无浏览器/离线环境兜底
    """
    if not description or not description.strip():
        return None

    os.makedirs(save_dir, exist_ok=True)
    logger.info("📐 正在生成图表: {}", description[:60])

    # 1. 高质量渲染管线 (API + Selenium)
    try:
        path = _try_high_quality_render(description, save_dir)
        if path:
            return path
        logger.info("  高质量引擎渲染未成功，尝试本地轻量级兜底...")
    except Exception as e:
        logger.warning("  高质量引擎异常: {}", e)

    # 2. 轻量级引擎兜底 (Matplotlib + Graphviz)
    try:
        path = _try_lite_render(description, save_dir)
        if path:
            return path
    except Exception as e:
        logger.warning("  轻量级兜底引擎异常: {}", e)

    logger.warning("  ⚠️ 所有图表引擎均失败: {}", description[:50])
    return None


# ==========================================
#  占位符处理 (供 article_utils 调用)
# ==========================================
def extract_diagram_placeholders(text):
    """从文章文本中提取所有图表占位符的描述"""
    return [m.strip() for m in DIAGRAM_PLACEHOLDER_PATTERN.findall(text or "")]


def replace_diagram_placeholder(html_body, description, image_url):
    """替换单个图表占位符为 HTML img 标签或清空"""
    pattern = re.compile(r"【\s*此处绘制图表\s*[：:]\s*" + re.escape(description) + r"\s*】")

    if image_url:
        replacement = (
            '<div style="text-align:center;margin:28px 0;width:100%;">'
            f'<img src="{image_url}" style="width:100%;max-width:800px;border-radius:12px;'
            'box-shadow:0 6px 20px rgba(0,0,0,0.15);" alt="架构示意图">'
            '<div style="max-width:800px;margin:10px auto 0 auto;padding:10px 16px;background:#f8fafc;'
            'border-left:4px solid #2563eb;border-radius:6px;text-align:left;box-sizing:border-box;">'
            f'<span style="font-size:13px;color:#334155;line-height:1.6;font-weight:500;display:block;">'
            f'💡 <strong>图解阅读指南：</strong> {description}</span>'
            '</div></div>'
        )
    else:
        replacement = ""

    return pattern.sub(replacement, html_body)


def _generate_single_diagram(args):
    """
    单个图表的完整生成流程，供线程池并行调用。
    返回 (description, png_path_or_None)
    """
    desc, save_dir = args
    logger.info("  🔄 [并行] 生成图表: {}", desc[:50])
    png_path = generate_diagram(desc, save_dir)
    return desc, png_path


def _upload_and_replace(desc, png_path, publisher):
    """
    单个图表的上传+获取 URL 流程，供线程池并行调用。
    返回 (description, image_url_or_None)
    """
    if not png_path or not publisher:
        return desc, None

    image_url = publisher.upload_news_image(png_path)
    try:
        os.remove(png_path)
    except Exception:
        pass

    if image_url:
        logger.info("  ✅ [并行] 图表已上传: {}", desc[:40])
    else:
        logger.warning("  ⚠️ [并行] 图表上传微信失败: {}", desc[:40])
    return desc, image_url


def process_diagram_placeholders(html_body, publisher, save_dir="assets"):
    """
    处理文章中所有图表占位符：并行生成 → 并行上传微信 → 顺序替换。
    使用 ThreadPoolExecutor 并行加速，最多 3 个并发 worker。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from config import DIAGRAM_PARALLEL_WORKERS

    descriptions = extract_diagram_placeholders(html_body)
    if not descriptions:
        return html_body, 0

    max_workers = min(DIAGRAM_PARALLEL_WORKERS, len(descriptions))
    logger.info("📐 检测到 {} 个图表占位符，启动 {} 个并行 worker 生成...", len(descriptions), max_workers)

    # ---- 阶段 1：并行生成所有图表 PNG ----
    gen_results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_generate_single_diagram, (desc, save_dir)): desc
            for desc in descriptions
        }
        for future in as_completed(futures):
            try:
                desc, png_path = future.result()
                gen_results[desc] = png_path
            except Exception as e:
                desc = futures[future]
                logger.warning("  ⚠️ [并行] 图表生成异常: {} - {}", desc[:40], e)
                gen_results[desc] = None

    # ---- 阶段 2：并行上传到微信 CDN ----
    upload_results = {}
    items_to_upload = [(desc, path) for desc, path in gen_results.items() if path]
    items_failed = [(desc, path) for desc, path in gen_results.items() if not path]

    for desc, _ in items_failed:
        upload_results[desc] = None

    if items_to_upload and publisher:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_upload_and_replace, desc, path, publisher): desc
                for desc, path in items_to_upload
            }
            for future in as_completed(futures):
                try:
                    desc, image_url = future.result()
                    upload_results[desc] = image_url
                except Exception as e:
                    desc = futures[future]
                    logger.warning("  ⚠️ [并行] 图表上传异常: {} - {}", desc[:40], e)
                    upload_results[desc] = None
    elif items_to_upload and not publisher:
        for desc, path in items_to_upload:
            upload_results[desc] = path

    # ---- 阶段 3：顺序替换占位符 ----
    diagram_count = 0
    for desc in descriptions:
        image_url = upload_results.get(desc)
        html_body = replace_diagram_placeholder(html_body, desc, image_url)
        if image_url:
            diagram_count += 1
            logger.info("  ✅ 图表已嵌入文章: {}", desc[:40])
        else:
            logger.warning("  ⚠️ 图表生成失败: {}", desc[:40])

    return html_body, diagram_count
