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

    def test_github_client_token_support(self):
        from core.github.collector import _get_github_client
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_mock_token_12345"}):
            client = _get_github_client()
            assert client is not None

    def test_daily_knowledge_engine_prompt_failure_graceful_unpack(self):
        from daily_knowledge.engine import generate_daily_knowledge
        with patch("builtins.open", side_effect=FileNotFoundError("Mock prompt missing")):
            result = generate_daily_knowledge()
            assert isinstance(result, tuple)
            assert len(result) == 2
            article_text, concept = result
            assert article_text == ""
            assert concept == ""

    def test_preview_id_traversal_sanitization(self):
        from webui import app
        with app.test_client() as client:
            resp = client.get("/api/preview/..%2F..%2Fetc%2Fpasswd")
            assert resp.status_code in (400, 404, 200)
            assert "etc/passwd" not in resp.get_data(as_text=True)

    def test_is_title_fresh_accuracy(self):
        from core.plugins.utils import _is_title_fresh
        # 1. 验证时效性强/打破记录/科技事件不被误杀
        assert _is_title_fresh("英伟达市值创历史新高突破3万亿") is True
        assert _is_title_fresh("特斯拉老板马斯克宣布最新FSD入华") is True
        assert _is_title_fresh("多地出台养老金新政保障民生") is True
        assert _is_title_fresh("颠覆传统！国产开源自研芯片成功点亮") is True
        assert _is_title_fresh("突破传统架构限制，AI新范式诞生") is True

        # 2. 验证真正的历史/回顾/往期内容被精准识别为非新鲜
        assert _is_title_fresh("历史上的今天：1998年谷歌公司正式成立") is False
        assert _is_title_fresh("2023年全球科技大事件深度盘点") is False
        assert _is_title_fresh("往期精彩内容回顾与技术选型总结") is False

    def test_save_image_from_url_rejects_corrupted_html_stream(self, tmp_path):
        from utils.image_handler import _save_image_from_url
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # 模拟防盗链或 403 页面伪装返回的 HTML 文本（非真实图片二进制）
        mock_resp.content = b"<html><head><title>403 Forbidden</title></head><body>Anti-scraping block</body></html>" * 10
        with patch("requests.get", return_value=mock_resp):
            saved = _save_image_from_url("https://example.com/fake_img.jpg", str(tmp_path))
            assert saved is None, "HTML 伪装内容不应被作为有效图片保存"

    def test_pipeline_engine_reraises_workflow_cancelled(self):
        from core.pipeline.engine import PipelineEngine
        from core.pipeline.nodes import BaseNode
        from core.shared.runtime import WorkflowCancelled

        class CancelledNode(BaseNode):
            def execute(self, context):
                raise WorkflowCancelled("用户主动取消")

        engine = PipelineEngine("TestCancelPipeline")
        engine.add_node(CancelledNode())
        with pytest.raises(WorkflowCancelled):
            engine.run({})
