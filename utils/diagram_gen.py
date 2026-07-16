"""
============================================================
  图表生成引擎 v1.0
  将自然语言描述 → DeepSeek 生成 Graphviz DOT → 渲染 PNG
  用于 AI科普文章中的流程图、架构图、对比图
============================================================
"""
import os
import re
import time
import subprocess
import tempfile
import requests
from loguru import logger

from core.shared.llm import call_deepseek_with_retry

# 图表占位符正则
DIAGRAM_PLACEHOLDER_PATTERN = re.compile(r"【\s*此处绘制图表\s*[：:]\s*(.*?)\s*】")

DOT_SYSTEM_PROMPT = """你是一位精通 Graphviz DOT 语言的图表设计师。你的任务是将用户的中文描述转化为一张清晰、美观的技术图表。

## 图表类型判定
根据用户描述判断图表类型：
- "流程"/"步骤"/"过程" → 流程图 (digraph, 从上到下，圆角矩形节点)
- "架构"/"结构"/"组成" → 架构图 (digraph, 从左到右，分层)
- "对比"/"区别"/"vs" → 对比图 (两组节点，不同颜色)
- "关系"/"映射"/"对应" → 关系图 (节点+边标注)
- "层次"/"层级" → 层次图 (垂直分层)
- "时间线"/"演进"/"发展" → 时间线图 (水平排列)

## 设计要求
1. 使用现代配色：节点背景 #E8F4FD（浅蓝）、边框 #2196F3（蓝）、文字 #1a1a1a
2. 对比/强调节点用 #FFF3E0（浅橙）背景 + #FF9800（橙）边框
3. 重要节点用圆角 (style=rounded)，次要节点用直角
4. 字号统一 12pt，标题 14pt bold
5. 图片尺寸: 宽 700px 以内，dpi=150
6. 必须包含 graph 级别 label（图表标题）

## 输出格式
直接输出完整的 DOT 代码，用 ```dot 和 ``` 包裹。不要任何解释文字。

## 示例
用户：Transformer 的编码器-解码器架构
输出：
```dot
digraph Transformer {
    rankdir=LR;
    node [fontname="Arial", fontsize=12];
    graph [label="Transformer 架构", fontsize=14, fontname="Arial"];
    
    subgraph cluster_encoder {
        label="编码器 (Encoder)";
        style=filled;
        fillcolor="#E8F4FD";
        node [style=rounded, fillcolor="#FFFFFF", color="#2196F3"];
        input [label="输入嵌入"];
        attn1 [label="多头自注意力"];
        ff1 [label="前馈网络"];
        input -> attn1 -> ff1;
    }
    
    subgraph cluster_decoder {
        label="解码器 (Decoder)";
        style=filled;
        fillcolor="#FFF3E0";
        node [style=rounded, fillcolor="#FFFFFF", color="#FF9800"];
        output [label="输出嵌入"];
        attn2 [label="掩码自注意力"];
        cross [label="交叉注意力"];
        ff2 [label="前馈网络"];
        output -> attn2 -> cross -> ff2;
    }
    
    ff1 -> cross [label="K, V", color="#666666", style=dashed];
}
```
"""


def _sanitize_dot(dot_code: str) -> str:
    """从 LLM 输出中提取 DOT 代码块"""
    # 尝试匹配 ```dot ... ``` 代码块
    match = re.search(r'```dot\s*\n(.*?)\n```', dot_code, re.DOTALL)
    if match:
        return match.group(1).strip()

    # 尝试匹配 ``` ... ``` 代码块
    match = re.search(r'```\s*\n((?:digraph|graph|strict)\s.*?)\n```', dot_code, re.DOTALL)
    if match:
        return match.group(1).strip()

    # 尝试直接匹配 digraph/graph 开头
    match = re.search(r'((?:digraph|graph|strict)\s+\w+\s*\{.*?\})', dot_code, re.DOTALL)
    if match:
        return match.group(1).strip()

    return dot_code.strip()


def _render_dot_to_png(dot_code: str, output_path: str) -> bool:
    """用 QuickChart API 渲染 DOT → PNG"""
    try:
        url = "https://quickchart.io/graphviz"
        payload = {
            "graph": dot_code,
            "format": "png"
        }
        # 使用 POST 请求以支持长 DOT 代码
        response = requests.post(url, json=payload, timeout=30)
        
        if response.status_code == 200:
            with open(output_path, "wb") as f:
                f.write(response.content)
            return True
        else:
            logger.warning("  QuickChart 渲染失败: HTTP {} - {}", response.status_code, response.text[:200])
            return False
            
    except requests.exceptions.Timeout:
        logger.warning("  QuickChart 渲染超时")
        return False
    except Exception as e:
        logger.warning("  QuickChart 渲染异常: {}", e)
        return False


def generate_diagram(description: str, save_dir: str = "assets") -> str | None:
    """
    根据自然语言描述生成技术图表。

    Args:
        description: 图表描述，如 "Transformer编码器-解码器架构"
        save_dir: 保存目录

    Returns:
        PNG 文件路径，失败返回 None
    """
    if not description or not description.strip():
        return None

    os.makedirs(save_dir, exist_ok=True)

    logger.info("📐 正在生成图表: {}", description[:60])

    # 1. DeepSeek 生成 DOT 代码
    user_prompt = f"请为以下描述生成一张技术图表：\n\n{description}\n\n要求：图表清晰、配色专业、适合微信公众号文章内嵌（宽 700px 以内）。"

    try:
        dot_response = call_deepseek_with_retry(
            user_prompt,
            system_content=DOT_SYSTEM_PROMPT,
            max_retries=1,
            backoff_base=0.5,
        )
    except Exception as e:
        logger.warning("  DeepSeek 生成 DOT 失败: {}", e)
        return None

    if not dot_response:
        return None

    # 2. 提取 DOT 代码
    dot_code = _sanitize_dot(dot_response)
    if not dot_code or len(dot_code) < 20:
        logger.warning("  DOT 代码提取失败")
        return None

    logger.debug("  DOT 代码 ({} 字符):\n{}", len(dot_code), dot_code[:300])

    # 3. 渲染 PNG
    output_path = os.path.join(save_dir, f"diagram_{int(time.time())}.png")
    success = _render_dot_to_png(dot_code, output_path)

    if success:
        file_size = os.path.getsize(output_path) / 1024
        logger.info("  ✅ 图表生成成功: {} ({:.1f} KB)", os.path.basename(output_path), file_size)
        return output_path
    else:
        # 清理失败文件
        if os.path.exists(output_path):
            os.remove(output_path)
        return None


def extract_diagram_placeholders(text: str) -> list[str]:
    """从文章文本中提取所有图表占位符的描述"""
    return [m.strip() for m in DIAGRAM_PLACEHOLDER_PATTERN.findall(text or "")]


def replace_diagram_placeholder(html_body: str, description: str, image_url: str | None) -> str:
    """替换单个图表占位符为 HTML img 标签或清空"""
    pattern = re.compile(r"【\s*此处绘制图表\s*[：:]\s*" + re.escape(description) + r"\s*】")

    if image_url:
        replacement = (
            '<p style="text-align:center;margin:24px 0;">'
            f'<img src="{image_url}" style="width:100%;max-width:700px;border-radius:8px;'
            'box-shadow:0 2px 8px rgba(0,0,0,0.08);" alt="图表">'
            f'<br><span style="font-size:12px;color:#999;margin-top:6px;display:inline-block;">'
            f'▲ {description[:50]}</span>'
            '</p>'
        )
    else:
        replacement = ""

    return pattern.sub(replacement, html_body)


def process_diagram_placeholders(html_body: str, publisher, save_dir: str = "assets") -> tuple[str, int]:
    """
    处理文章中所有图表占位符：生成 → 上传微信 → 替换。

    Args:
        html_body: HTML 正文
        publisher: WeChatPublisher 实例（用于上传图片）
        save_dir: 图表临时保存目录

    Returns:
        (处理后的 HTML, 成功生成的图表数)
    """
    descriptions = extract_diagram_placeholders(html_body)
    if not descriptions:
        return html_body, 0

    logger.info("📐 检测到 {} 个图表占位符，开始生成...", len(descriptions))
    diagram_count = 0

    for desc in descriptions:
        logger.info("  生成图表: {}", desc[:50])
        png_path = generate_diagram(desc, save_dir)

        if png_path and publisher:
            # 上传到微信 CDN
            image_url = publisher.upload_image(png_path)
            if image_url:
                html_body = replace_diagram_placeholder(html_body, desc, image_url)
                diagram_count += 1
                logger.info("  ✅ 图表已嵌入文章: {}", desc[:40])
                # 清理本地文件
                try:
                    os.remove(png_path)
                except Exception:
                    pass
            else:
                html_body = replace_diagram_placeholder(html_body, desc, None)
                logger.warning("  ⚠️ 图表上传微信失败: {}", desc[:40])
        elif png_path:
            # 无 publisher 时仅做本地替换测试
            html_body = replace_diagram_placeholder(html_body, desc, png_path)
            diagram_count += 1
        else:
            html_body = replace_diagram_placeholder(html_body, desc, None)
            logger.warning("  ⚠️ 图表生成失败: {}", desc[:40])

    return html_body, diagram_count
