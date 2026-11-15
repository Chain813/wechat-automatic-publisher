# WeChat Article Inline HTML Typesetting & Card Rendering Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the WeChat article inline HTML typesetting engine (`core/shared/article_utils.py`), Headless Selenium renderer (`utils/html_render.py`), diagram generator (`utils/diagram_gen.py`), and pure Python card renderer (`utils/lite_render.py`) to the Linear Modern Light design system (`#4F5BD5`, `#0C0D0E`, `#F8F9FB`), maintaining 100% backward compatibility with all existing tests.

**Architecture:** Maintain strict inline styling for WeChat HTML compatibility (stripping external/embedded styles), transform Markdown tables and code blocks into milled, tactile Linear Modern Light cards with specular chamfers and multi-stop shadows, and unify Selenium/Matplotlib/Graphviz/Mermaid renderers under the shared off-white and indigo palette.

**Tech Stack:** Python 3.11+, Python Markdown (`markdown`), Regular Expressions (`re`), Selenium WebDriver, Matplotlib, Graphviz, Mermaid.ink API, Pytest.

---

## File Structure & Impact Map

| Operation | File Path | Responsibility |
| :--- | :--- | :--- |
| **Create** | `docs/superpowers/specs/2026-11-02-wechat-article-linear-light-typesetting-design.md` | Architecture design specification |
| **Create** | `docs/superpowers/plans/2026-11-02-wechat-article-linear-light-typesetting.md` | Step-by-step implementation plan |
| **Modify** | `core/shared/article_utils.py` | Upgrade inline `<h2>`, `<h3>`, `<blockquote>`, `<pre><code>`, inline `<code>`, `<table>`, and callout card containers to Linear Light |
| **Modify** | `utils/html_render.py` | Upgrade `#render-target` and Mermaid `themeVariables` to Linear Light card mode |
| **Modify** | `utils/diagram_gen.py` | Upgrade prompts (`LITE_DIAGRAM_SYSTEM_PROMPT`, `UNIFIED_DIAGRAM_SYSTEM_PROMPT`), Mermaid API `classDef`, and caption container |
| **Modify** | `utils/lite_render.py` | Upgrade Matplotlib formula, comparison, text cards, and Graphviz fallback to Linear Light palette |
| **Modify** | `tests/test_article_styling.py` | Add comprehensive unit tests covering Linear Light typography, tables, code cards, and renderer configs |

---

## Implementation Tasks

### Task 1: Upgrade `core/shared/article_utils.py` to Linear Modern Light

**Files:**
- Modify: `core/shared/article_utils.py`

- [ ] **Step 1: Upgrade Callout & Diagram Card Containers**
  - In `_build_callout_card`:
    - Upgrade container: `border-radius: 10px; box-shadow: 0 1px 2px rgba(0,0,0,0.03), 0 4px 16px rgba(15,23,42,0.04);`
    - Retain exact hex colors `#ef4444`/`#fef2f2`, `#3b82f6`/`#eff6ff`, `#10b981`/`#f0fdf4`.
  - In `_format_diagram_card`:
    - Upgrade container: `border-radius: 10px; box-shadow: 0 1px 2px rgba(0,0,0,0.03), 0 4px 16px rgba(15,23,42,0.04);`
    - Retain exact `#2563eb`, `#f8fafc` and titles (`📊 核心架构与逻辑拆解`, `📊 核心业务流程拆解`, `📊 核心逻辑与架构解析`).

- [ ] **Step 2: Upgrade Headings and Blockquotes**
  - In `process_article_content`:
    - `<h2>`: `margin-top: 38px; margin-bottom: 22px; padding: 10px 16px; border-left: 4px solid #4F5BD5; background: linear-gradient(90deg, rgba(79,91,213,0.08) 0%, rgba(248,249,251,0) 100%); border-radius: 6px; font-size: 20px; color: #0C0D0E; font-weight: 700; letter-spacing: -0.01em;`
    - `<h3>`: `margin-top: 28px; margin-bottom: 16px; font-size: 17px; color: #0C0D0E; font-weight: 600; border-left: 3px solid #4F5BD5; padding-left: 10px;`
    - `<blockquote>`: `margin: 22px 0; padding: 16px 20px; border: 1px solid rgba(0,0,0,0.06); border-left: 4px solid #4F5BD5; background-color: #F8F9FB; color: #5E6470; border-radius: 8px; font-size: 15px; line-height: 1.75; box-shadow: 0 1px 2px rgba(0,0,0,0.02);` (preserving >220 chars split).

- [ ] **Step 3: Add Markdown Table Inline Post-Processing**
  - Implement regex post-processing for `<table>`:
    - Wrap table in overflow-x protection section.
    - Style `<table>` with `border-collapse: collapse; width: 100%; margin: 22px 0; font-size: 14px; border: 1px solid #E2E8F0; border-radius: 8px; overflow: hidden;`.
    - Style `<th>` with `background-color: #F8F9FB; color: #0C0D0E; font-weight: 600; padding: 10px 12px; border-bottom: 1px solid #E2E8F0; text-align: left;`.
    - Style `<td>` with `padding: 10px 12px; border-bottom: 1px solid #F1F3F7; color: #334155;`.

- [ ] **Step 4: Upgrade Code Blocks and Inline Code**
  - Multi-line `<pre><code>`:
    - Outer container: `background-color: #F8F9FB; color: #0C0D0E; border: 1px solid #E2E8F0; border-radius: 10px; box-shadow: 0 1px 2px rgba(0,0,0,0.03), inset 0 1px 0 rgba(255,255,255,1); margin: 22px 0; overflow: hidden;`
    - Top bar: `#F1F3F7` background, window dots (`#EF4444`, `#F59E0B`, `#10B981`) + `CODE` badge (`#5E6470`).
    - Inner `<pre>`: `margin: 0; padding: 14px 18px; background-color: #F8F9FB; color: #0C0D0E; font-family: Consolas, Monaco, 'Courier New', monospace; font-size: 13.5px; line-height: 1.65; white-space: pre-wrap; word-break: break-all; border: none; overflow-x: auto;`
  - Inline `<code>`:
    - `background-color: #F1F3F7; padding: 2px 6px; border-radius: 4px; color: #4F5BD5; border: 1px solid rgba(79,91,213,0.15); font-size: 0.92em; font-family: Consolas, Monaco, 'Courier New', monospace;`

---

### Task 2: Upgrade Renderers (`utils/html_render.py`, `utils/diagram_gen.py`, `utils/lite_render.py`)

**Files:**
- Modify: `utils/html_render.py`
- Modify: `utils/diagram_gen.py`
- Modify: `utils/lite_render.py`

- [ ] **Step 1: Upgrade `utils/html_render.py`**
  - Update `#render-target`: `background-color: #FFFFFF; color: #0C0D0E; border: 1px solid rgba(0, 0, 0, 0.08); border-radius: 16px; padding: 28px; box-shadow: 0 4px 20px rgba(15, 23, 42, 0.06), 0 1px 2px rgba(0, 0, 0, 0.04);`
  - Update `mermaid.initialize`: `theme: 'base'`, `themeVariables: { background: '#FFFFFF', primaryColor: '#EEF2FF', primaryTextColor: '#0C0D0E', primaryBorderColor: '#4F5BD5', lineColor: '#4F5BD5', secondaryColor: '#F8F9FB', tertiaryColor: '#F1F3F7' }`.

- [ ] **Step 2: Upgrade `utils/diagram_gen.py`**
  - In `LITE_DIAGRAM_SYSTEM_PROMPT`: update Graphviz example to `#F8F9FB`, `#4F5BD5`, `#0C0D0E`.
  - In `_try_api_render`: update `style_template` `classDef` to Linear Light palette.
  - In `UNIFIED_DIAGRAM_SYSTEM_PROMPT`: update Mermaid example and HTML card templates to Linear Modern Light.
  - In `replace_diagram_placeholder`: update reading guide callout to `#F8F9FB` with `#4F5BD5` accent bar.

- [ ] **Step 3: Upgrade `utils/lite_render.py`**
  - In `render_formula_card`: figure/ax `#F8F9FB`, bounding box `#FFFFFF` with `#E2E8F0` border, title `#4F5BD5`, formula text `#0C0D0E`, notes `#5E6470`.
  - In `render_comparison_card`: figure/ax `#F8F9FB`, header `#F1F3F7` with `#0C0D0E`, cells `#FFFFFF` with `#334155`, border `#E2E8F0`, title `#4F5BD5`.
  - In `render_text_card`: figure/ax `#F8F9FB`, card `#FFFFFF` with `#E2E8F0`, title `#4F5BD5`, bullet text `#0C0D0E`.
  - In `render_archify_diagram`: Graphviz fallback `bgcolor="#F8F9FB"`, node `fillcolor="#FFFFFF"`, `color="#4F5BD5"`, `fontcolor="#0C0D0E"`, edge `color="#4F5BD5"`.

---

### Task 3: Expand Test Suite & Verify 100% Passing

**Files:**
- Modify: `tests/test_article_styling.py`

- [ ] **Step 1: Add Unit Tests in `tests/test_article_styling.py`**
  - Test Linear Light `<h2>` and `<h3>` styling (`#4F5BD5`, `#0C0D0E`).
  - Test Linear Sunken Code Block (`#F8F9FB`, `#E2E8F0`, `CODE` badge, traffic lights).
  - Test Markdown table styling (`<table>`, `<th>`, `<td>`).
  - Test callouts upgraded 10px border-radius and tactile shadows.
  - Test `html_render.py` Linear Light constants.
  - Test `lite_render.py` theme consistency.

- [ ] **Step 2: Execute Pytest Suite**
  - Run `pytest tests/test_article_styling.py -v`.
  - Run `pytest tests/ -v`.
  - Verify 100% tests pass.

---

### Task 4: Generate Live Preview Sample & Report Back

- [ ] **Step 1: Generate a Visual Demonstration Sample**
  - Generate an HTML sample containing all styled elements (headings, paragraphs, callouts, tables, code blocks, diagrams) and verify rendering.
- [ ] **Step 2: Send Message to Caller Agent**
  - Send structured report via `send_message` with detailed breakdown of changes, metrics, and verification results.
