from unittest.mock import patch

from config import BRAND_NAME
from core.github.processor import generate_github_article
from core.hotspots.processor import _auto_add_placeholders, generate_article
from core.pipeline.critic import auto_repair_article
from core.plugins.base import HotspotItem


def test_hotspot_structure_retry_keeps_original_evidence():
    source = "测试公告仅开放离线导出，未公布上线日期。"
    source_url = "https://example.org/test-announcement"
    search = [{"snippet": "旧版的导出入口仍然保留。", "url": "https://example.org/docs"}]
    topic = HotspotItem(title="离线导出公告", url=source_url, raw_content=source)
    incomplete = "导出操作需要先选择文件。" * 55
    with patch("core.hotspots.processor.call_deepseek", return_value=incomplete) as generate:
        assert generate_article(topic, search_results=search) == ""
    first, retry = [call.args[0] for call in generate.call_args_list[:2]]
    assert source in first
    assert source in retry
    for prompt in (first, retry):
        assert source_url in prompt
        assert search[0]["snippet"] in prompt
        assert search[0]["url"] in prompt
        assert f"**关注「{BRAND_NAME}」。**" in prompt
    assert "小标题不足" in retry


def test_feed_summary_reaches_writer_when_body_and_search_are_empty():
    topic = HotspotItem(title="导出功能更新", summary="公告说明离线文件只读。")
    with patch("core.hotspots.processor.call_deepseek", return_value="") as generate:
        generate_article(topic, search_results=[])
    assert topic.summary in generate.call_args.args[0]


def test_github_writer_uses_repo_materials_and_configured_signature():
    project = {"repo": "example/test", "lang": "Python", "desc": "导出文件。", "readme_excerpt": "Export a CSV."}
    with patch("core.github.processor.call_deepseek_with_retry", return_value="TITLE: 文件导出\nCONTENT:\n正文") as generate:
        body, title = generate_github_article([project])
    prompt = generate.call_args.args[0]
    assert project["readme_excerpt"] in prompt
    assert f"**关注「{BRAND_NAME}」。**" in prompt
    assert f"**关注「{BRAND_NAME}」。**" in generate.call_args.kwargs["system_content"]
    assert body == "正文"
    assert title.endswith(" | 文件导出")


def test_placeholder_fallback_uses_real_section_subjects():
    article = (
        "## 发布公告\n\n## 测试设备\n\n**Starship** 完成测试。\n\n"
        "## 动力系统\n\n测试对象为 **Raptor**。\n\n"
        "## 地面设施\n\n负责保障的是 **Starbase**。"
    )
    result = _auto_add_placeholders(article, "飞行测试公告")
    for subject in ("Starship", "Raptor", "Starbase"):
        assert f"【此处插入配图：{subject}】" in result


def test_critic_removes_empty_lead_without_inventing_claims():
    result, changes = auto_repair_article("毫无疑问，公告尚未披露价格。")
    assert result == "公告尚未披露价格。"
    assert changes


def test_critic_preserves_attributed_words_and_concrete_context():
    original = "公告写道：“毫无疑问，这是一把双刃剑。”\n\n随着接口快速演进，旧版客户端需要升级。"
    assert auto_repair_article(original) == (original, [])


def test_critic_promotes_existing_headings_without_adding_boilerplate():
    paragraph = "核对导出日志中的完成时间。" * 70
    source = f"开篇。\n\n### 日志记录了哪些步骤\n\n{paragraph}\n\n### 如何核对完成时间\n\n{paragraph}"
    repaired, _ = auto_repair_article(source)
    assert "## 日志记录了哪些步骤\n" in repaired
    assert "## 如何核对完成时间\n" in repaired
    assert "###" not in repaired
    assert "未来洞察" not in repaired


def test_critic_keeps_html_intact_when_removing_empty_leads():
    original = '<p class="lead">综上所述，附表列出了版本号。</p><blockquote><p>说白了，能导出。</p></blockquote>'
    repaired, _ = auto_repair_article(original)
    assert repaired == original.replace("综上所述，", "")
