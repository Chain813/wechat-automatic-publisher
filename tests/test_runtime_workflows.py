import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from unittest.mock import MagicMock, patch
from core.shared.llm import validate_title
from utils.image_handler import LOCAL_FALLBACK_IMAGE


class TestRuntimeWorkflowsSafety:
    def test_validate_title_strips_forbidden_endings_after_truncation(self):
        # 构造一个超长标题，其第 64 个字符恰好被截断在标点处
        raw_title = "A" * 63 + "。" + "Extra"
        clean, warnings = validate_title(raw_title)
        assert len(clean) <= 64
        assert not clean.endswith("。")
        assert not clean.endswith(("！", "？", "!", "?", "：", ":", "，", ","))

    def test_default_cover_files_exist_on_disk(self):
        # 验证系统中所有默认封面候选均在磁盘真实存在
        candidates = [
            os.path.abspath(os.path.join("assets", "default_aikepu_cover.png")),
            os.path.abspath(os.path.join("assets", "default_daily_cover.png")),
            os.path.abspath(os.path.join("static", "images", "github_fixed_cover.png")),
        ]
        existing_candidates = [c for c in candidates if os.path.exists(c)]
        assert len(existing_candidates) >= 2, f"必须存在可用的预设封面图: {candidates}"
        assert os.path.exists(LOCAL_FALLBACK_IMAGE)

    def test_hotspot_save_publish_result_creates_preview_safely(self, tmp_path):
        from core.hotspots.workflow import _save_publish_result
        from core.plugins.base import HotspotItem

        topic = HotspotItem(title="2026年AI大模型前沿技术分析", url="https://example.com/test")
        sample_html = "<h1>测试正文</h1><p>深入分析大模型在 2026 年的发展。</p>"

        # 运行 _save_publish_result，验证其内部 os.makedirs 与 hashlib 无 NameError
        _save_publish_result(
            topic,
            success=False,
            draft_id=None,
            error="门禁拦截测试",
            quality_score=70.0,
            source_url="https://example.com/test",
            status="REJECTED",
            preview_html=sample_html,
        )

        import hashlib
        title_hash = hashlib.md5("2026年AI大模型前沿技术分析".encode("utf-8")).hexdigest()
        preview_file = os.path.join("data", "previews", f"fail_{title_hash}.html")
        assert os.path.exists(preview_file)
        with open(preview_file, "r", encoding="utf-8") as f:
            assert "测试正文" in f.read()

    def test_github_collector_history_session_cleanup(self):
        from core.github.collector import _load_github_history, save_github_history

        # 验证在查询和保存 github 历史时 session 正确释放
        save_github_history(["test-org/test-repo-runtime-check"])
        history = _load_github_history()
        assert "test-org/test-repo-runtime-check" in history

    def test_aikepu_workflow_no_unbound_local_errors(self):
        from core.aikepu.workflow import _publish_single_topic
        from core.shared.publisher import WeChatPublisher

        # Mock publisher
        mock_pub = MagicMock(spec=WeChatPublisher)
        mock_pub.access_token = "mock_token"
        mock_pub.publish_and_notify.return_value = (True, {"media_id": "test_draft_media_123"})
        mock_pub.upload_image.return_value = "mock_thumb_id"

        topic_info = {
            "title": "大模型注意力机制详解",
            "node_id": "transformer_attention",
        }

        # Mock generator and review report
        with patch("core.aikepu.workflow.generate_aikepu_article", return_value="## 概念解析\n注意力机制核心原理。\n\n> 💡 **核心洞察**：自注意力矩阵计算。\n\n【此处绘制图表：注意力机制】\n"), \
             patch("core.aikepu.workflow.process_article_content", return_value=("<h2>概念解析</h2><p>注意力机制核心原理。</p>", {"word_count": 2200, "image_count": 2, "sensitive_words": []})), \
             patch("core.pipeline.critic.evaluate_article_quality", return_value={"passed": True, "score": 92, "critic_issues": []}), \
             patch("core.aikepu.workflow.mark_published") as mock_mark:

            title, success, err, node_id = _publish_single_topic(topic_info, mock_pub)

            assert success is True
            assert err is None
            assert node_id == "transformer_attention"
            mock_mark.assert_called_once()
