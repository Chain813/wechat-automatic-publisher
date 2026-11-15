import pytest
from core.hotspots.narrative import (
    ARCHETYPES,
    GOLDEN_HOOKS,
    select_narrative_archetype,
    select_dynamic_hook,
)


class TestSelectNarrativeArchetype:
    """测试叙事母题动态选择机制"""

    def test_policy_topic_matches_investigative_game(self):
        """政策/监管类关键词匹配利益博弈调查型"""
        topics = [
            "美国商务部出台最新AI芯片出口管制新规",
            "欧盟《人工智能法案》正式生效，巨头面临严格合规监管",
            "司法部反垄断调查升级，科技巨头拆分传闻再起",
            "关税政策调整对跨境高科技贸易的深远影响",
        ]
        for topic in topics:
            archetype = select_narrative_archetype(topic)
            assert archetype["id"] == "investigative_game"
            assert "利益博弈" in archetype["name"]
            assert "core_perspective" in archetype
            assert "guidelines" in archetype

    def test_tech_topic_matches_tech_deep_dive(self):
        """技术/架构类关键词匹配极客技术破局型"""
        topics = [
            "DeepSeek-V3 架构革新：MoE 路由与无辅助损失负载均衡解析",
            "开源大模型权重正式开放下载与推理优化指南",
            "量子计算突破经典算力极限：算法演进与硬件瓶颈",
            "新一代 GPU 架构与内存带宽技术深度拆解",
        ]
        for topic in topics:
            archetype = select_narrative_archetype(topic)
            assert archetype["id"] == "tech_deep_dive"
            assert "极客技术" in archetype["name"]
            assert "core_perspective" in archetype
            assert "guidelines" in archetype

    def test_business_topic_matches_business_war(self):
        """商业/产业链类关键词匹配商业产业链攻防型"""
        topics = [
            "台积电与英伟达的供应链博弈与代工产能争夺",
            "AI 独角兽百亿美元估值融资潮与商业化变现困境",
            "全球半导体产业链遭遇价格战与巨头并购重组",
            "云厂商资本开支暴增，巨头打响算力租赁价格战",
        ]
        for topic in topics:
            archetype = select_narrative_archetype(topic)
            assert archetype["id"] == "business_war"
            assert "产业链攻防" in archetype["name"]
            assert "core_perspective" in archetype
            assert "guidelines" in archetype

    def test_default_fallback_matches_narrative_human(self):
        """无特定领域关键词或空缺时，缺省降级为叙事特写与认知逆转型"""
        topics = [
            "一个深夜还在写代码的人的真实独白",
            "站在十字路口的普通人与时代浪潮",
            "周末偶遇的一场关于未来的闲聊",
            "",
            "杂谈日记",
        ]
        for topic in topics:
            archetype = select_narrative_archetype(topic)
            assert archetype["id"] == "narrative_human"
            assert "叙事特写" in archetype["name"] or "认知逆转" in archetype["name"]
            assert "core_perspective" in archetype
            assert "guidelines" in archetype


class TestSelectDynamicHook:
    """测试黄金 Hook 动态抽取机制"""

    def test_hook_returns_valid_structure(self):
        """验证返回的 Hook 数据结构完整"""
        valid_ids = {"counter_intuitive", "cost_and_bill", "critical_scene", "cognitive_reversal"}
        for _ in range(20):
            hook = select_dynamic_hook()
            assert isinstance(hook, dict)
            assert hook["id"] in valid_ids
            assert "name" in hook
            assert "instruction" in hook
            assert "example" in hook

    def test_hook_random_distribution(self):
        """测试 4 类黄金 Hook 随机抽选（50次抽样应覆盖全部4类）"""
        valid_ids = {"counter_intuitive", "cost_and_bill", "critical_scene", "cognitive_reversal"}
        sampled_ids = set()
        for _ in range(60):
            hook = select_dynamic_hook()
            sampled_ids.add(hook["id"])

        assert sampled_ids == valid_ids, f"未能抽样覆盖全部 4 类 Hook，仅抽到: {sampled_ids}"

    def test_hook_with_archetype_hint(self):
        """传入 archetype_id 时同样正常返回有效 Hook"""
        for archetype_id in ARCHETYPES.keys():
            hook = select_dynamic_hook(archetype_id=archetype_id)
            assert hook["id"] in GOLDEN_HOOKS
