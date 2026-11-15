# AutoWeChat Glossary

This glossary standardizes core domain, architecture, and operations terminology across **AutoWeChat** documentation and contributors.

---

## 1. Core Creation Workflows

| Term | Identifier | Definition |
| :--- | :--- | :--- |
| **Trending Hotspots** | `hotspots` | Collects trending topics across 12 news/tech feeds, applies domain keyword filtering, scrapes full source text, performs live web fact grounding, and drafts deep commentary via dynamic narrative strategies. |
| **GitHub OSS Deep Dive** | `github` | Discovers high-signal repositories from GitHub Trending and API search, inspects READMEs/screenshots, renders architecture visuals, and produces technical walkthroughs. |
| **Knowledge Graph Series** | `aikepu` | Traverses prerequisite-ordered DAG knowledge trees (5 built-in vertical packs) using a 3-phase pipeline: Outline → Flash prompt optimization → parallel `ThreadPoolExecutor` Sub-Agent section workers. |
| **Daily Knowledge** | `daily_knowledge` | Standalone lightweight daily encyclopedia module (`daily_knowledge/`) with topic planning, historical deduplicator, and an isolated SQLite tracking database. |

---

## 2. Quality Assurance & Compliant Publishing

| Term | Identifier | Definition |
| :--- | :--- | :--- |
| **Human-in-the-Loop (HITL)** | Safety Principle | All automated runs push exclusively to the WeChat Official Account **Draft Box**, requiring final human confirmation via the Audit Workbench before broadcasting. |
| **Fact Grounding** | `scraper.py` & `searcher.py` | Combines `trafilatura` full-text source extraction with live DuckDuckGo (HTML/Lite) and Bing web searches (`ENABLE_FACT_SEARCH`) to anchor AI prose in verifiable facts. |
| **Dynamic Narrative Engine** | `narrative.py` | Dynamically pairs 4 structural writing archetypes with 4 opening hooks to eliminate repetitive AI essay templates. |
| **AI Critic Quality Gate** | `critic.py` | Pre-publish evaluation and auto-repair gate that strips AI clichés, injects missing H2 sections, enforces length/title bounds, and quarantines failed drafts (`REJECTED` → `data/previews/fail_*.html` & SQLite). |
| **HITL Audit Workbench** | `audit` WebUI View | Interactive review console backed by `data/auto_publish.sqlite` (WAL mode) allowing editors to preview HTML drafts and push approved articles via `/api/review/approve`. |
| **4-Layer Title Dedup** | `publisher.py` | Deduplicates candidate titles against WeChat Cloud Drafts, published history, and local logs in 4 tiers: exact match → fuzzy similarity → keyword overlap (`>= 0.70`) → AI semantic check. |

---

## 3. Visual Pipeline & Frontend Architecture

| Term | Identifier | Definition |
| :--- | :--- | :--- |
| **Linear Modern Light** | Unified Design System | Clean high-contrast light aesthetic (`#FFFFFF` / `#F8F9FB` surfaces with `#4F5BD5` indigo accents) applied consistently across the WebUI, WeChat rich-text article typesetting, and technical diagrams. |
| **4-Layer Ambient Canvas** | `.ambient-canvas` (`views.css`) | Lightweight CSS-only gradient blob, grid, and noise canvas that replaced the deprecated Three.js 3D WebGL particle background. |
| **Zero-Build ES Modules** | `static/js/` | Native browser ES module frontend (`main.js`, `core/`, `views/`) requiring no bundler, powering 5 views: `console`, `graph`, `audit`, `image`, and `ops`. |
| **100% AI Image Chain** | `image_handler.py` | Pure generative fallback chain (`Qwen-Image-3.0` → Local `Stable Diffusion` → Pillow Linear Light vector cards), with Bing image web scraping disabled in the primary pipeline. |
| **5-Mode Diagram Engine** | `diagram_gen.py` | Parallel visual renderer supporting `Mermaid`, `HTML+Tailwind+KaTeX`, `Graphviz DOT`, and `Matplotlib` structured cards with opaque white backgrounds for WeChat compatibility. |
| **Image Studio** | `image` WebUI View | Interactive tool to extract Markdown image slots, drag-and-drop local uploads, redraw reference images from WeChat article URLs via `Qwen-Image-3.0-Pro`, and render 1:1 mobile previews. |

---

## 4. Customization & Operations Infrastructure

| Term | Identifier | Definition |
| :--- | :--- | :--- |
| **Zero-Interview Customization** | `tools/` | `analyze_account.py` + `build_knowledge_tree.py` workflow that analyzes historical reference articles and automatically generates aligned DAG knowledge trees and writing skill prompts. |
| **Domain Knowledge Packs** | `data/knowledge_trees/` | Five built-in vertical trees (`aikepu`, `career`, `health`, `law`, `tax`) hot-switched via `_active.txt` and paired with domain prompts in `prompts/{slug}_skill.md`. |
| **Key Rotation Pool** | `utils/key_pool.py` | Thread-safe round-robin pool supporting comma-separated `LLM_API_KEYS` and `DASHSCOPE_API_KEYS` with automatic 429 (`120s`) and auth (`300s`) cooldowns. |
| **Prompt Cache Telemetry** | `llm.py` | Live console metrics tracking LLM cache hit rates, saved tokens, and estimated CNY savings. |
| **Control Signals** | `cancel_event` / `pause_event` | `threading.Event` primitives checked across workflow loops and interruptible sleeps to guarantee clean Pause/Resume/Stop behavior. |
| **Cloud Mode** | `CLOUD_MODE=1` | Stateless cloud guard (e.g. GitHub Actions, Render) prioritizing remote WeChat records to prevent ephemeral containers from overwriting history. |
| **GitHub Token** | `GITHUB_TOKEN` | Optional GitHub Personal Access Token (PAT) used to raise API rate limits during `github` repository discovery. |
