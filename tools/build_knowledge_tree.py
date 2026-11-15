"""
============================================================
  定制知识库生成器 — 「内容定制服务」的生产工具
  输入主题简报 → DeepSeek 半自动生成 → 产出两件定制资产：
    1. data/knowledge_trees/{slug}.json  知识 DAG（含每节点专属写作策略）
    2. prompts/{slug}_skill.md           行业写作风格规则（引擎自动按主题加载）

  用法:
    python tools/build_knowledge_tree.py "法律科普" --slug law
         --nodes 12 --audience "小微企业主" --tone "案例驱动、避坑指南" --activate
============================================================
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

from core.shared.llm import call_deepseek_with_retry
from core.aikepu.skill_tree import validate_tree_structure, set_active_tree

SCHEMA_EXAMPLE = json.dumps({
    "meta": {"name": "主题全称", "column_name": "专栏名(2-6字)", "description": "一句话介绍", "version": "1.0"},
    "nodes": [{
        "id": "topic-node-1",
        "title": "吸引点击的标题",
        "tags": ["标签1", "标签2"],
        "prerequisites": [],
        "difficulty": 1,
        "summary": "一句话说清读者读完的收获",
        "custom_prompt": "100-200字专属写作策略：本节的比喻、案例方向、禁止重复的内容边界",
    }],
}, ensure_ascii=False, indent=2)


def _extract_json(text):
    """从 LLM 输出中提取 JSON（容错：代码块 / 前后缀）"""
    if not text:
        return None
    m = re.search(r"```(?:json)?(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1)
    m = re.search(r"[{].*[}]", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except Exception:
        return None


def generate_tree(topic, node_count, audience, tone, profile=None):
    """用 DeepSeek 生成知识 DAG（可选注入客户账号画像，实现风格对齐）"""
    profile_block = ""
    if profile:
        profile_block = f"""

客户账号画像（来自其历史文章自动分析，务必让每个节点的 custom_prompt 贴合以下风格）：
{json.dumps(profile, ensure_ascii=False, indent=2)}"""
    prompt = f"""你是资深知识体系架构师，为主题「{topic}」设计一个用于公众号连载的知识库 DAG（有向无环图）。

背景：目标读者是「{audience}」，期望写作风格是「{tone}」。
{profile_block}

硬性要求：
1. 严格输出 JSON，结构与下面示例一致：
{SCHEMA_EXAMPLE}
2. 节点总数 {node_count} 个，difficulty 取值 1-4（由浅入深，1 最少、4 最多）
3. prerequisites 必须构成 DAG：引用真实存在的 id，入门节点可为空数组
3.5. id 严禁使用 topic-node-N 这类示例占位符，必须是贴合该节点主题的英文短横线短语（小写，如 entity-choice、registered-capital、partner-agreement）
4. title 要吸引点击；summary 一句话说清读者收获
5. custom_prompt 是每个节点的专属写作策略（100-200字）：核心比喻、典型案例方向、与前序节点禁止重复的内容边界
6. 只输出 JSON，不要任何解释文字"""
    res = call_deepseek_with_retry(
        prompt,
        system_content="你是顶级知识体系架构师，严格输出合法 JSON。",
        max_tokens=8192,
    )
    return _extract_json(res)


def _fix_placeholder_ids(data):
    """若 LLM 生成了 topic-node-N 占位 id，按标题生成真实英文 slug 并同步 prerequisites"""
    nodes = data.get("nodes", [])
    if not any(re.fullmatch(r"topic-node-[0-9]+", str(n.get("id", ""))) for n in nodes):
        return False
    brief = json.dumps([{"id": n["id"], "title": n["title"]} for n in nodes], ensure_ascii=False)
    prompt = f"""以下知识库节点的 id 是占位符，请为每个节点生成贴合其标题的英文短横线标识（全小写，如 entity-choice、registered-capital），严格输出 JSON 对象（键为旧 id、值为新 id），不要其他文字：
{brief}"""
    res = call_deepseek_with_retry(prompt, system_content="严格输出 JSON 对象。", max_tokens=1024)
    mapping = _extract_json(res)
    if not isinstance(mapping, dict):
        return False
    for n in nodes:
        old = str(n.get("id", ""))
        if old in mapping and mapping[old]:
            n["id"] = str(mapping[old]).strip()
    for n in nodes:
        n["prerequisites"] = [mapping.get(str(p), p) for p in n.get("prerequisites", [])]
    return True


def generate_skill_file(topic, audience, tone, profile=None):
    """生成行业写作风格规则文件（可选注入客户画像，克隆其风格）"""
    profile_block = ""
    if profile:
        profile_block = f"""

客户账号画像（写作风格规则必须对齐以下分析结果）：
{json.dumps(profile, ensure_ascii=False, indent=2)}"""
    prompt = f"""为公众号专栏「{topic}」（目标读者：{audience}）写一份写作风格规则文件（Markdown），包含以下小节：
{profile_block}
# 写作风格执行细则
- 开头钩子公式（给出 2 个可直接套用的模板）
- 每节必含元素（案例/数据/行动建议）
- 语言风格（口语化程度、金句密度、人称）
- 排他规则（本专栏禁用词、禁用结构、与其他栏目的差异点）
- 读者视角校准（{audience} 最关心什么、最怕什么、什么能让他们转发）
全文控制在 800 字内，直接输出 Markdown 正文。"""
    return call_deepseek_with_retry(
        prompt,
        system_content="你是资深公众号内容总监。",
        max_tokens=2048,
    )


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="定制知识库生成器")
    ap.add_argument("topic", help="主题/行业名，如「法律科普」「财税入门」")
    ap.add_argument("--slug", required=True, help="知识库英文标识（文件名），如 law / tax")
    ap.add_argument("--nodes", type=int, default=12, help="节点数量（默认 12）")
    ap.add_argument("--audience", default=None, help="目标读者画像（缺省时用客户画像自动推断）")
    ap.add_argument("--tone", default=None, help="写作风格关键词（缺省时用客户画像自动推断）")
    ap.add_argument("--samples", default="", help="客户历史文章链接（逗号分隔，自动扒取并分析画像，实现零访谈定制）")
    ap.add_argument("--profile", default="", help="现成的画像 JSON 路径（与 --samples 二选一）")
    ap.add_argument("--activate", action="store_true", help="生成后立即切换为该主题")
    args = ap.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args.slug):
        print("❌ slug 只能包含字母/数字/下划线/连字符")
        sys.exit(1)

    profile = None
    if args.samples:
        try:
            from tools.analyze_account import fetch_article, analyze_style
            urls = [u.strip() for u in args.samples.split(",") if u.strip()]
            print(f"📥 正在扒取 {len(urls)} 篇客户历史文章 ...")
            articles = [(t, b) for u in urls for t, b in [fetch_article(u)] if t or b]
            print(f"🧠 正在分析客户账号画像（{len(articles)} 篇样本）...")
            profile = analyze_style(articles, args.topic)
        except Exception as e:
            print(f"⚠️ 客户画像获取失败（将用默认风格生成）: {e}")
    elif args.profile and os.path.exists(args.profile):
        with open(args.profile, "r", encoding="utf-8") as f:
            profile = json.load(f)
        print(f"📋 已加载画像: {args.profile}")

    if profile:
        print("   画像:", json.dumps({k: profile.get(k) for k in ("domain", "audience", "tone")}, ensure_ascii=False))
        if not args.audience:
            args.audience = profile.get("audience") or "对该领域感兴趣的普通读者"
        if not args.tone:
            args.tone = profile.get("tone") or "通俗易懂、案例驱动"

    args.audience = args.audience or "对该领域感兴趣的普通读者"
    args.tone = args.tone or "通俗易懂、案例驱动"

    print(f"🧠 正在为「{args.topic}」设计 {args.nodes} 节点知识 DAG ...")
    data = generate_tree(args.topic, args.nodes, args.audience, args.tone, profile=profile)
    if not data:
        print("❌ 知识库生成失败（LLM 输出不可解析），请重试或减少节点数")
        sys.exit(1)

    if _fix_placeholder_ids(data):
        print("🔧 已自动修复占位 id 为真实英文标识")

    ok, err = validate_tree_structure(data)
    if not ok:
        print(f"❌ 结构校验失败: {err}")
        sys.exit(1)

    if not isinstance(data.get("meta"), dict):
        data["meta"] = {}
    data["meta"]["name"] = data["meta"].get("name") or args.topic
    data["meta"]["column_name"] = data["meta"].get("column_name") or args.topic[:8]
    data["meta"]["description"] = data["meta"].get("description", f"{args.topic}知识体系连载（{args.audience}）")

    trees_dir = os.path.join("data", "knowledge_trees")
    os.makedirs(trees_dir, exist_ok=True)
    tree_path = os.path.join(trees_dir, f"{args.slug}.json")
    with open(tree_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✅ 知识库已生成: {tree_path} ({len(data['nodes'])} 节点)")

    skill = generate_skill_file(args.topic, args.audience, args.tone, profile=profile)
    if skill:
        skill_path = os.path.join("prompts", f"{args.slug}_skill.md")
        os.makedirs("prompts", exist_ok=True)
        with open(skill_path, "w", encoding="utf-8") as f:
            f.write(skill.strip())
        print(f"✅ 写作风格已生成: {skill_path}")

    print()
    print("📚 节点一览:")
    for n in data["nodes"]:
        pre = ",".join(n.get("prerequisites", [])) or "无"
        print(f"  L{n.get('difficulty', 1)} {n['id']:24s} ← {pre}")

    if args.activate:
        set_active_tree(args.slug)
        print()
        print(f"🚀 已切换激活主题: {args.slug}")

    print()
    print("💡 下一步: WebUI 体系连载页下拉选择该主题包，或运行 python main.py --task aikepu")


if __name__ == "__main__":
    main()
