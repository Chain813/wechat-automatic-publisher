English | [中文](GLOSSARY.md)

# Glossary

This document provides detailed explanations of technical terms, tool names, and professional concepts used in the AutoWeChat project.

---

## Table of Contents

- [Technical Terms](#technical-terms)
- [Image Terms](#image-terms)
- [GitHub Terms](#github-terms)
- [WeChat Terms](#wechat-terms)

---

## Technical Terms

| Term | Description |
|------|-------------|
| **LLM** | Large Language Model. This project uses DeepSeek as the LLM for article generation, topic filtering, and digest creation |
| **DeepSeek Prompting** | **(NEW)** Prompt engineering optimized specifically for DeepSeek. Combines colloquial tone instructions and layout robustness rules (e.g., leading colon filtering, automatic H2/H3 planning) to ensure professional and readable output |
| **SYSTEM_PROMPT** | System prompt sent to the LLM defining the AI's role, writing style, article structure, and formatting rules. Essentially the AI's "work manual" |
| **pHash** | Perceptual Hash. An image fingerprint algorithm that scales down and converts images to grayscale before computing a hash. Similar images produce similar hashes, enabling duplicate detection even after resizing, cropping, or minor modifications |
| **RapidFuzz** | High-performance fuzzy string matching library. Calculates similarity (0-100%) between titles for deduplication, 10-100x faster than Python's built-in `difflib`. For example, "AI chip ban escalates" and "chip ban escalates again" would score ~75% similarity |
| **ThreadPoolExecutor** | Python's standard library thread pool executor. Parallelizes multiple tasks (e.g., downloading 5 images simultaneously), merging 5 serial downloads into one parallel operation for significantly faster execution |
| **Selenium Stealth Mode** | Browser configuration that disables the `webdriver` flag, sets realistic User-Agent strings, and disables automation detection, making Selenium-controlled Chrome appear as human-operated to bypass anti-scraping measures |
| **icrawler** | Python image crawler framework. Wraps Bing, Baidu, and Google image search engines with filtering by keyword, size, and type |
| **Webhook** | Callback notification mechanism. WeChat group bots provide a Webhook URL; sending HTTP POST requests to it pushes messages to the group. This project auto-sends notifications after successful article publishing |
| **API Token** | Authentication key string for API calls. Different services use different formats: GitHub tokens start with `ghp_`, DeepSeek keys start with `sk-` |
| **Markdown** | Lightweight markup language using `#` for headings, `**` for bold, `>` for quotes, etc. LLM-generated articles use Markdown format, automatically converted to WeChat-compatible HTML |
| **HTML** | HyperText Markup Language, the standard web format. The system converts Markdown articles to HTML with inline styles, adapted to WeChat's rendering engine |
| **Inline Style** | CSS styles written directly on HTML tags (e.g., `style="color: red;"`). WeChat doesn't support external CSS files, so inline styles are the only way to control article formatting |

---

## Image Terms

| Term | Description |
|------|-------------|
| **Pollinations.ai** | Free AI image generation service. Pass English prompts via URL to generate images with no registration or API key needed. E.g., visiting `https://image.pollinations.ai/prompt/a%20cat` generates a cat image |
| **Pexels** | Free high-quality stock photo library with copyright-free images uploaded by professional photographers. 200 free API calls per month, higher quality than search engine results |
| **Stable Diffusion** | **(NEW)** Open-source local image generation model. This project supports the Stable Diffusion WebUI API to generate custom geek-style illustrations for GitHub projects based on DeepSeek-generated prompts |
| **Carbon** | Code screenshot beautification service (carbon.now.sh). Renders code snippets with syntax highlighting, line numbers, and styled backgrounds. The most popular code presentation method in tech blogs and articles |
| **Aspect Ratio** | Width-to-height ratio of an image. WeChat recommends: cover 2.35:1 (900×383px), body image ~16:9 (900×500px). The system auto-crops to fit |
| **Laplacian Variance** | Image sharpness metric. Computes variance after applying the Laplacian operator (second derivative). Blurry images have low variance (<100), sharp images have high variance (>500). No reference image needed |
| **Color Histogram Entropy** | Image color richness metric. Calculates information entropy from color distribution. Solid-color images have entropy near 0, colorful images have higher entropy (>5). Higher entropy images are typically more visually appealing |
| **OCR** | Optical Character Recognition. Detects text content in images. This project uses EasyOCR to measure text density; images with high text ratio (screenshots, PPT slides) are unsuitable as article illustrations |
| **Resize** | Process of cropping and scaling images to WeChat's recommended dimensions. First center-crops to target aspect ratio, then scales to target resolution, then compresses within file size limits (body images: 2MB) |

---

## GitHub Terms

| Term | Description |
|------|-------------|
| **GitHub Trending** | GitHub's official trending page (github.com/trending). Showcases open-source repositories with the most stars in the last 24 hours/7 days/30 days. The primary channel for developers to discover new projects |
| **Star** | GitHub's bookmark feature. Users click the Star button on a project page to show interest or approval. Star count is the core metric for measuring project popularity |
| **README** | Project documentation file in the root directory (usually README.md). Contains project introduction, installation instructions, and usage guide. The first file visitors see |
| **PyGithub** | Python wrapper for GitHub REST API. Provides object-oriented interfaces for accessing GitHub data, e.g., `repo.get_readme()` for README content, `repo.get_topics()` for tags. More stable and type-safe than raw HTTP requests |
| **rich** | Python rich text and formatting library (github.com/Textualize/rich, 56k+ stars). Renders tables, progress bars, tree structures in terminals. This project uses `rich.tree.Tree` to render project directory trees as styled PNG images |
| **diagrams** | Python architecture diagram library (github.com/mingrammer/diagrams, 42k+ stars). Draws cloud architecture and system topology diagrams from Python code, supporting AWS/Azure/GCP/Kubernetes nodes. Outputs PNG/SVG |
| **File Tree** | Hierarchical structure of project files and folders. Shows what files and directories a project contains (e.g., `src/main.py`, `config/`), helping readers quickly understand project composition and tech stack |
| **Architecture Diagram** | System architecture illustration showing component relationships (frontend/backend/database/cache) and data flow, helping understand system design |
| **Personal Access Token (PAT)** | GitHub authentication token created at Settings → Developer settings → Personal access tokens. Used for API authentication with higher rate limits (5000 vs 60 requests/hour for anonymous access) |
| **Graphviz** | Open-source graph visualization software (graphviz.org). The diagrams library depends on it to render architecture diagrams as PNG/SVG files. On Windows, the `bin` directory must be added to the system PATH after installation |
| **API Rate Limit** | GitHub API request frequency limits. Anonymous: 60 requests/hour, authenticated: 5000 requests/hour. Exceeding the limit returns HTTP 403; the system automatically falls back to web scraping |

---

## WeChat Terms

| Term | Description |
|------|-------------|
| **AppID** | WeChat official account's unique application identifier. Found in WeChat admin panel → Development → Basic Configuration. Format: 18-character string starting with `wx` |
| **AppSecret** | WeChat official account's application secret key. Paired with AppID to obtain access_token. Must be kept secure; reset immediately if compromised |
| **access_token** | WeChat API access token. Obtained by exchanging AppID + AppSecret, valid for 2 hours. Required for all WeChat API calls; the system auto-manages and refreshes it |
| **Draft Box** | WeChat official account's article draft storage. The system pushes generated articles to the draft box; operators review and formally publish from the WeChat admin panel. API endpoint: `draft/add` |
| **thumb_media_id** | WeChat material ID. A unique identifier string returned after uploading a cover image to WeChat servers. Passed when creating drafts to associate the cover image |
| **Title Dedup** | Pre-publish check against existing drafts to prevent duplicate articles. 4 strategies: exact match (identical title), fuzzy match (similarity >80%), keyword match (overlapping core keywords), AI semantic match (semantically similar) |
| **Digest** | Brief description shown in article push notifications (max 120 characters). Displayed in WeChat subscription message list, determining whether users click to read the full article |
| **Publishing Flow** | System workflow: ①Generate article HTML → ②Upload cover image to get media_id → ③Create draft via Draft Box API → ④Send enterprise WeChat notification → ⑤Operator reviews and manually publishes |
