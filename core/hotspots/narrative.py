"""
动态叙事弧与反套路多风格叙事引擎 (Narrative Engine)
用于消除硬编码大纲，赋予公众号深度热点文章差异化的叙事张力与动态风格。
"""

import copy
import random
from typing import Dict, Any, Optional

ARCHETYPES: Dict[str, Dict[str, Any]] = {
    "investigative_game": {
        "id": "investigative_game",
        "name": "利益博弈调查型",
        "keywords": [
            "政策", "法案", "监管", "制裁", "关税", "出口管制", "司法", "部委",
            "调查", "封锁", "禁令", "垄断", "合规", "国家战略", "地缘", "政商",
            "禁令", "博弈", "白宫", "商务部"
        ],
        "core_perspective": "从利益分配与权力博弈切入。穿透官方公关话术，追问：谁是真正获利者？谁在付出隐形成本？表面声明与私下妥协的温差在哪里？",
        "guidelines": [
            "严禁空洞的宏观口号，必须穿透到具体的受损方和受益方利益账单；",
            "深入拆解政策出台背后的政商推手、行业游说以及跨国权衡；",
            "二级小标题必须是一针见血的动态洞察金句，直指博弈焦点，绝不能出现'政策背景'、'深远影响'等标签；",
            "全篇保持冷峻、克制但刀刀见血的调查记者笔调。"
        ]
    },
    "tech_deep_dive": {
        "id": "tech_deep_dive",
        "name": "极客技术破局型",
        "keywords": [
            "架构", "算法", "大模型", "模型", "算力", "芯片", "开源", "sota",
            "量子", "显卡", "gpu", "参数", "论文", "工程", "底层", "推理",
            "训练", "负载均衡", "硬件", "编译器", "基准", "微架构"
        ],
        "core_perspective": "从工程权衡（Trade-offs）与第一性原理切入。拒绝黑盒神话与虚假狂欢，拆解真实的技术瓶颈、架构取舍与数学/硬件物理边界。",
        "guidelines": [
            "讲透'过去为什么做不到、这次究竟改了哪个核心变量'，以及'为了换取这个指标牺牲了什么'；",
            "杜绝纯学术黑话堆砌与通稿复述，用精妙直观的工程与物理直觉将技术链路讲得通透生动；",
            "二级小标题必须提炼核心工程矛盾或架构突破金句，严禁出现'技术解析'、'原理解析'等刻板标签；",
            "把硬核技术的残酷工程现实与破局者的巧思展现得淋漓尽致。"
        ]
    },
    "business_war": {
        "id": "business_war",
        "name": "商业产业链攻防型",
        "keywords": [
            "商业", "产业链", "供应链", "融资", "财报", "估值", "市场份额",
            "营收", "利润", "巨头", "收购", "代工", "客户", "价格战", "商业化",
            "资本", "上市", "订单", "出货量", "毛利", "开支", "市值"
        ],
        "core_perspective": "从供需格局、单位经济模型（Unit Economics）与生态卡位切入。撕开企业宣传包装，直击产业链上下游的生死攻防。",
        "guidelines": [
            "算清真实商业账本：现金流消耗速率、毛利率悬崖、客户替换成本；",
            "生动展现巨头与挑战者之间的连环攻防、渠道反水、代工绑定与生态围剿；",
            "二级小标题必须提炼为充满商业张力的对抗型金句，严禁出现'商业分析'、'行业现状'等陈词滥调；",
            "从刺客打法与护城河失守的视角重塑商业战局。"
        ]
    },
    "narrative_human": {
        "id": "narrative_human",
        "name": "叙事特写与认知逆转型",
        "keywords": [],
        "core_perspective": "从关键现场特写与大众认知逆转切入。用具体场景、戏剧性反差或微观切片撕开宏大叙事，带来颠覆性的视角重构。",
        "guidelines": [
            "以充满电影感的微观场景特写切入，从微小缝隙引出时代巨变；",
            "步步推进、层层剥茧，彻底推翻大众原本深信不疑的普遍认知或直觉定论；",
            "二级小标题必须是具有文学张力与思维反转的动态洞察金句，严禁出现'背景介绍'、'总结概括'等标签；",
            "让读者在层层认知刷新中获得顿悟快感。"
        ]
    }
}

GOLDEN_HOOKS: Dict[str, Dict[str, Any]] = {
    "counter_intuitive": {
        "id": "counter_intuitive",
        "name": "反常识冲突",
        "instruction": "开篇直接抛出一个打破大众直觉或既有常识的数据、事实或反直觉结论，瞬间制造强烈的认知冲突与求知欲。",
        "example": "“所有人都以为这是一场毫无悬念的救赎，但行业深处的真实数字却指向了一个完全相反的深渊。”"
    },
    "cost_and_bill": {
        "id": "cost_and_bill",
        "name": "利益账单与代价",
        "instruction": "开篇直接拉出一份具体的隐秘账单：谁在悄悄承担天价代价？谁在狂欢？用冷酷的数字与隐形成本直击核心。",
        "example": "“短短 72 小时内，行业龙头为此支付的隐形代价，已经超过了过去三年研发预算的总和。”"
    },
    "critical_scene": {
        "id": "critical_scene",
        "name": "关键现场特写",
        "instruction": "开篇如电影镜头般切入一个极具戏剧性或紧绷感的微观现场、机房深夜、会议室对话或关键操作瞬间，让读者迅速沉浸。",
        "example": "“凌晨三点，位于西雅图核心数据中心的一场紧急连线，悄然按下了整个行业格局重组的计时器。”"
    },
    "cognitive_reversal": {
        "id": "cognitive_reversal",
        "name": "认知逆转",
        "instruction": "先呈现大众普遍深信不疑的某种舆论定论，随后用一句话无情拆解，指出真正的本质恰恰相反。",
        "example": "“大众眼中的划时代突破，在真正的行业老兵眼里，不过是一场精心策划的战术撤退。”"
    }
}


def select_narrative_archetype(topic: str) -> Dict[str, Any]:
    """
    根据话题关键词动态匹配叙事母题（按关键词命中热度打分）：
    - 政策/监管/制裁类 -> 利益博弈型 (investigative_game)
    - 架构/技术/算法类 -> 极客技术型 (tech_deep_dive)
    - 商业/产业链/财报类 -> 产业链攻防型 (business_war)
    - 缺省/其他 -> 叙事特写型 (narrative_human)
    """
    if not topic:
        return copy.deepcopy(ARCHETYPES["narrative_human"])

    topic_lower = topic.lower()

    # 对三大母题计算关键词命中得分
    scores = {}
    for arch_id in ["investigative_game", "tech_deep_dive", "business_war"]:
        score = sum(1 for kw in ARCHETYPES[arch_id]["keywords"] if kw in topic_lower)
        scores[arch_id] = score

    best_arch, best_score = max(scores.items(), key=lambda item: item[1])

    if best_score > 0:
        return copy.deepcopy(ARCHETYPES[best_arch])

    # 4. 缺省降级为叙事特写与认知逆转型
    return copy.deepcopy(ARCHETYPES["narrative_human"])


def select_dynamic_hook(archetype_id: Optional[str] = None) -> Dict[str, Any]:
    """
    从 4 类黄金 Hook 中随机抽选开篇 Hook 模板。
    archetype_id 为可选参数，确保接口向前兼容。
    """
    hook_key = random.choice(list(GOLDEN_HOOKS.keys()))
    return copy.deepcopy(GOLDEN_HOOKS[hook_key])


def build_narrative_instructions(archetype: Dict[str, Any], hook: Dict[str, Any]) -> str:
    """
    将选定的母题和 Hook 组装为可注入 Prompt 的结构化写作指引
    """
    guidelines_text = "\n".join(f"- {g}" for g in archetype.get("guidelines", []))
    return (
        f"### 本篇动态叙事架构：【{archetype.get('name')}】\n"
        f"**核心观察视角**：{archetype.get('core_perspective')}\n"
        f"**叙事推进法则**：\n{guidelines_text}\n\n"
        f"### 开篇黄金切入法则：【{hook.get('name')}】\n"
        f"**开篇手法要求**：{hook.get('instruction')}\n"
        f"**风格示范参考**：{hook.get('example')}\n"
    )
