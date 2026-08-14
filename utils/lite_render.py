"""
============================================================
  轻量级图表渲染引擎 v1.0
  纯 Python 渲染：Graphviz (流程图) + Matplotlib (公式/卡片)
  无需浏览器，适合 CI/CD 和无头服务器环境
============================================================
"""
import os
import textwrap
from loguru import logger

# ==========================================
#  Graphviz 流程图渲染
# ==========================================
def render_graphviz(dot_code, output_path, fmt="png"):
    """
    使用 Graphviz 将 DOT 代码渲染为 PNG。
    需要系统安装 graphviz (apt install graphviz / choco install graphviz)。
    """
    # 动态为 Windows 注入 Graphviz PATH，解决系统安装了 Graphviz 但未添加 PATH 的问题
    graphviz_path = r"C:\Program Files\Graphviz\bin"
    if os.path.exists(graphviz_path) and graphviz_path not in os.environ["PATH"]:
        os.environ["PATH"] += os.path.pathsep + graphviz_path

    try:
        import graphviz
    except ImportError:
        logger.warning("graphviz Python 包未安装")
        return False

    base_path = output_path.rsplit(".", 1)[0] if "." in output_path else output_path
    try:
        # 清理 DOT 代码
        dot_code = dot_code.strip()
        if not dot_code.startswith(("digraph", "graph", "strict")):
            dot_code = f"digraph G {{\n{dot_code}\n}}"

        src = graphviz.Source(dot_code)
        # graphviz.Source.render 会自动添加扩展名
        src.render(base_path, format=fmt, cleanup=True)

        actual_path = f"{base_path}.{fmt}"
        if os.path.exists(actual_path):
            # 如果输出路径和实际路径不同，重命名
            if actual_path != output_path:
                os.replace(actual_path, output_path)
            logger.info("  [graphviz] 渲染成功: {}", os.path.basename(output_path))
            return True
        else:
            if os.path.exists(base_path):
                try:
                    os.remove(base_path)
                except Exception:
                    pass
            return False

    except Exception as e:
        logger.warning("  [graphviz] 渲染失败: {}", e)
        if os.path.exists(base_path):
            try:
                os.remove(base_path)
            except Exception:
                pass
        return False


# ==========================================
#  Matplotlib 公式/卡片渲染
# ==========================================
def render_formula_card(title, formula_lines, notes=None, output_path="formula.png"):
    """
    使用 Matplotlib 渲染数学公式卡片。
    
    Args:
        title: 公式标题
        formula_lines: 公式列表（LaTeX 格式字符串）
        notes: 可选的变量说明列表
        output_path: 输出路径
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import rcParams
    except ImportError:
        logger.warning("matplotlib 未安装")
        return False

    try:
        # 设置中文字体
        rcParams["font.sans-serif"] = [
            "Microsoft YaHei", "SimHei", "PingFang SC",
            "Noto Sans CJK SC", "DejaVu Sans"
        ]
        rcParams["axes.unicode_minus"] = False

        fig, ax = plt.subplots(figsize=(8, max(3, 1.5 + len(formula_lines) * 1.2 + (0.8 if notes else 0))))
        fig.patch.set_facecolor("#0b0e14")
        ax.set_facecolor("#0b0e14")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

        # 绘制圆角背景框
        from matplotlib.patches import FancyBboxPatch
        bg = FancyBboxPatch(
            (0.02, 0.02), 0.96, 0.96,
            boxstyle="round,pad=0.03",
            facecolor="#111827", edgecolor="#1e3a5f",
            linewidth=1.5
        )
        ax.add_patch(bg)

        # 标题
        ax.text(
            0.5, 0.9, title,
            ha="center", va="top",
            fontsize=16, fontweight="bold",
            color="#38bdf8",
        )

        # 公式（每行一个）
        n = len(formula_lines)
        for i, formula in enumerate(formula_lines):
            y = 0.72 - i * (0.5 / max(n, 1))
            ax.text(
                0.5, y, f"${formula}$",
                ha="center", va="center",
                fontsize=18, color="#e2e8f0",
            )

        # 注释
        if notes:
            note_text = "  |  ".join(notes) if isinstance(notes, list) else str(notes)
            ax.text(
                0.5, 0.08, note_text,
                ha="center", va="bottom",
                fontsize=10, color="#94a3b8",
                style="italic",
            )

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        fig.savefig(output_path, dpi=200, bbox_inches="tight", pad_inches=0.1)
        plt.close(fig)

        if os.path.exists(output_path) and os.path.getsize(output_path) > 100:
            logger.info("  [matplotlib] 公式卡片渲染成功: {}", os.path.basename(output_path))
            return True
        return False

    except Exception as e:
        logger.warning("  [matplotlib] 公式卡片渲染失败: {}", e)
        return False


def render_comparison_card(title, columns, rows, output_path="compare.png"):
    """
    使用 Matplotlib 渲染对比表格卡片。

    Args:
        title: 表格标题
        columns: 列名列表，如 ["特性", "深度学习", "传统ML"]
        rows: 二维列表，如 [["数据需求", "大量", "少量"], ...]
        output_path: 输出路径
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import rcParams
    except ImportError:
        logger.warning("matplotlib 未安装")
        return False

    try:
        rcParams["font.sans-serif"] = [
            "Microsoft YaHei", "SimHei", "PingFang SC",
            "Noto Sans CJK SC", "DejaVu Sans"
        ]
        rcParams["axes.unicode_minus"] = False

        n_rows = len(rows)
        fig_height = max(3, 1.5 + n_rows * 0.5)
        fig, ax = plt.subplots(figsize=(8, fig_height))
        fig.patch.set_facecolor("#0b0e14")
        ax.set_facecolor("#0b0e14")
        ax.axis("off")

        # 标题
        ax.set_title(
            title, fontsize=16, fontweight="bold",
            color="#38bdf8", pad=15
        )

        # 创建表格
        cell_colors = []
        for i in range(n_rows):
            row_colors = ["#1e293b"] * len(columns)
            cell_colors.append(row_colors)

        table = ax.table(
            cellText=rows,
            colLabels=columns,
            cellLoc="center",
            loc="center",
            cellColours=cell_colors,
            colColours=["#1e3a5f"] * len(columns),
        )
        table.auto_set_font_size(False)
        table.set_fontsize(11)
        table.scale(1.0, 1.6)

        # 设置单元格样式
        for key, cell in table.get_celld().items():
            cell.set_edgecolor("#334155")
            cell.set_linewidth(0.5)
            row, col = key
            if row == 0:
                cell.set_text_props(color="#e2e8f0", fontweight="bold")
            else:
                cell.set_text_props(color="#cbd5e1")

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        fig.savefig(output_path, dpi=200, bbox_inches="tight", pad_inches=0.2)
        plt.close(fig)

        if os.path.exists(output_path) and os.path.getsize(output_path) > 100:
            logger.info("  [matplotlib] 对比卡片渲染成功: {}", os.path.basename(output_path))
            return True
        return False

    except Exception as e:
        logger.warning("  [matplotlib] 对比卡片渲染失败: {}", e)
        return False


def _wrap_chinese_text(text, max_units=40):
    """
    针对中英混合文本的自适应折行函数：
    中文字符/全角标点计为 2 个单位宽度，英文字符/数字/半角标点计为 1 个单位宽度。
    """
    if not text:
        return ""
    lines = []
    current_line = ""
    current_units = 0

    for char in text:
        unit = 2 if ord(char) > 127 else 1
        if current_units + unit > max_units and current_line:
            lines.append(current_line)
            current_line = char
            current_units = unit
        else:
            current_line += char
            current_units += unit

    if current_line:
        lines.append(current_line)

    return "\n".join(lines)


def render_text_card(title, bullet_points, output_path="card.png"):
    """
    使用 Matplotlib 渲染要点清单卡片。

    Args:
        title: 卡片标题
        bullet_points: 要点列表，如 ["要点1", "要点2", ...]
        output_path: 输出路径
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import rcParams
        from matplotlib.patches import FancyBboxPatch
    except ImportError:
        logger.warning("matplotlib 未安装")
        return False

    try:
        rcParams["font.sans-serif"] = [
            "Microsoft YaHei", "SimHei", "PingFang SC",
            "Noto Sans CJK SC", "DejaVu Sans"
        ]
        rcParams["axes.unicode_minus"] = False

        wrapped_points = [_wrap_chinese_text(point, max_units=40) for point in bullet_points]
        total_lines = sum(len(p.splitlines()) for p in wrapped_points)
        fig_height = max(3, 1.2 + total_lines * 0.45)
        fig, ax = plt.subplots(figsize=(8, fig_height))
        fig.patch.set_facecolor("#0b0e14")
        ax.set_facecolor("#0b0e14")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

        bg = FancyBboxPatch(
            (0.02, 0.02), 0.96, 0.96,
            boxstyle="round,pad=0.03",
            facecolor="#111827", edgecolor="#1e3a5f",
            linewidth=1.5
        )
        ax.add_patch(bg)

        ax.text(
            0.5, 0.92, title,
            ha="center", va="top",
            fontsize=15, fontweight="bold", color="#38bdf8"
        )

        n = len(wrapped_points)
        for i, wrapped in enumerate(wrapped_points):
            y = 0.82 - i * (0.75 / max(n, 1))
            ax.text(
                0.08, y, f"• {wrapped}",
                ha="left", va="top",
                fontsize=11, color="#e2e8f0",
                linespacing=1.4
            )

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        fig.savefig(output_path, dpi=200, bbox_inches="tight", pad_inches=0.1)
        plt.close(fig)

        if os.path.exists(output_path) and os.path.getsize(output_path) > 100:
            logger.info("  [matplotlib] 要点卡片渲染成功: {}", os.path.basename(output_path))
            return True
        return False

    except Exception as e:
        logger.warning("  [matplotlib] 要点卡片渲染失败: {}", e)
        return False


# ==========================================
#  Archify 架构图渲染
# ==========================================
def render_archify_diagram(archify_code, output_path):
    """
    使用 Archify / D2 渲染系统架构图，若系统未安装 Archify，自动平滑转译为 Graphviz 高颜值架构图。
    """
    import shutil
    import subprocess

    # 1. 检查命令行工具 archify / d2
    archify_cli = shutil.which("archify") or shutil.which("d2")
    if archify_cli:
        try:
            cmd = [archify_cli, "-", output_path]
            p = subprocess.run(cmd, input=archify_code.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
            if p.returncode == 0 and os.path.exists(output_path):
                logger.info("  [archify] CLI 原生渲染成功: {}", os.path.basename(output_path))
                return True
        except Exception as e:
            logger.warning("  [archify] CLI 渲染异常，降级平滑转译: {}", e)

    # 2. 降级：自动将 Archify 架构描述转译为 Graphviz 优雅架构图
    try:
        lines = [line.strip() for line in archify_code.strip().splitlines() if line.strip() and not line.strip().startswith("#")]
        edges = []
        nodes = set()

        for line in lines:
            # 匹配 NodeA -> NodeB 或 NodeA -> NodeB: Label
            if "->" in line:
                parts = line.split("->", 1)
                src = parts[0].strip().strip("[]()")
                target_part = parts[1].strip()
                label = ""
                if ":" in target_part:
                    tgt_sub, label = target_part.split(":", 1)
                    dst = tgt_sub.strip().strip("[]()")
                    label = label.strip()
                else:
                    dst = target_part.strip().strip("[]()")
                
                nodes.add(src)
                nodes.add(dst)
                if label:
                    edges.append(f'    "{src}" -> "{dst}" [label="{label}", color="#3b82f6", fontcolor="#93c5fd"];')
                else:
                    edges.append(f'    "{src}" -> "{dst}" [color="#3b82f6"];')

        dot_lines = [
            'digraph Architecture {',
            '    rankdir=LR;',
            '    bgcolor="#0b0e14";',
            '    node [shape=box, style="filled,rounded", fillcolor="#1e293b", color="#3b82f6", fontcolor="#f8fafc", fontname="Microsoft YaHei", fontsize=11, height=0.5, margin="0.2,0.1"];',
            '    edge [penwidth=1.5, fontname="Microsoft YaHei", fontsize=9];'
        ]
        for node in nodes:
            dot_lines.append(f'    "{node}" [label="{node}"];')
        dot_lines.extend(edges)
        dot_lines.append('}')

        converted_dot = "\n".join(dot_lines)
        return render_graphviz(converted_dot, output_path)

    except Exception as e:
        logger.warning("  [archify] 平滑转译渲染失败: {}", e)
        return False

