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
        "core_perspective": "对照政策原文与执行细则，说明哪些主体需要改变做法。",
        "guidelines": [
            "交代文件的发布者、状态和适用对象，区分征求意见、通过和生效。",
            "找出一条影响读者的条件或例外，写清它在办理或交付的哪一步起作用。",
            "有证据才分析成本由谁承担。有署名或记录才引述当事人的立场。",
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
        "core_perspective": "找出材料里一项工程改动，顺着输入、处理和输出说明读者能观察到的变化。",
        "guidelines": [
            "材料提供对照测试时，交代基线、单位和测试条件。",
            "借一个具体操作说明接口或设备如何工作。文档没有披露的实现细节留白。",
            "只在资料支持时讨论速度、成本、兼容性等取舍。",
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
        "core_perspective": "沿着订单、交付或付款环节，定位这次变动落在哪一方。",
        "guidelines": [
            "区分公告里的意向、签约和实际交付。",
            "比较财务或销量数字时交代期间、单位与口径。",
            "只有材料写到客户或供应商的具体动作时，才分析它对交易的影响。",
        ]
    },
    "narrative_human": {
        "id": "narrative_human",
        "name": "叙事特写与认知逆转型",
        "keywords": [],
        "core_perspective": "从报道中一个可核对的人物动作或物件讲起，再说明与这个细节有关的问题。",
        "guidelines": [
            "有来源的细节可以还原，未经记录的台词、环境和心理活动留白。",
            "材料没有现场时直接写当事人公开做了什么。",
            "让每一节回答上节留下的具体问题，结尾交代还需等待哪项信息。",
        ]
    }
}

GOLDEN_HOOKS: Dict[str, Dict[str, Any]] = {
    "counter_intuitive": {
        "id": "counter_intuitive",
        "name": "反常识冲突",
        "instruction": "有可比的两项事实时，先说明二者差别与比较条件。缺少对照时，直接写本次变化。",
        "example": "若公告区分申请开放和正式交付，可从两个日期的差别写起。"
    },
    "cost_and_bill": {
        "id": "cost_and_bill",
        "name": "利益账单与代价",
        "instruction": "从资料明载的一项收费、工序或责任转移写起，指出由谁承担。未披露金额时无需估算。",
        "example": "若合同调整了运费承担方，可引出哪一方接下来需要安排运输。"
    },
    "critical_scene": {
        "id": "critical_scene",
        "name": "关键现场特写",
        "instruction": "报道记录了操作或现场细节时，交代出处再写。只有公告时，从公告中的具体动作切入。",
        "example": "若操作手册调整了提交步骤，可从读者现在需要提交哪份材料讲起。"
    },
    "cognitive_reversal": {
        "id": "cognitive_reversal",
        "name": "认知逆转",
        "instruction": "选择一个材料能澄清的具体问题，例如适用对象或生效时间。避免代替公众或业内人士表态。",
        "example": "若说明里写明仅向试点单位开放，可从谁能申请说起。"
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
