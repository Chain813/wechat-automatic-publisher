import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

# 确保项目根目录在 sys.path 中
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from core.github.collector import (
    SAFE_SCREENSHOT_DOMAINS,
    is_safe_screenshot_url,
    is_qualified_repository,
    take_live_ui_screenshot,
)


class TestIsQualifiedRepository:
    """测试 GitHub 真实性四维过滤器"""

    def test_reject_archived_repository(self):
        """测试已归档 (archived) 仓库被拦截"""
        repo = SimpleNamespace(
            archived=True,
            size=5000,
            stargazers_count=1200,
            forks_count=200,
        )
        qualified, reason = is_qualified_repository(repo)
        assert not qualified
        assert "归档" in reason or "archived" in reason.lower()

    def test_reject_empty_ppt_repository_small_size(self):
        """测试空壳 PPT 仓库（size < 50KB）被拦截"""
        # 尺寸只有 30KB
        repo = SimpleNamespace(
            archived=False,
            size=30,
            stargazers_count=800,
            forks_count=80,
        )
        qualified, reason = is_qualified_repository(repo)
        assert not qualified
        assert "50KB" in reason or "空壳" in reason or "体积" in reason

        # 尺寸为 0KB
        repo_zero = SimpleNamespace(
            archived=False,
            size=0,
            stargazers_count=500,
            forks_count=50,
        )
        qualified_zero, reason_zero = is_qualified_repository(repo_zero)
        assert not qualified_zero
        assert "50KB" in reason_zero or "空壳" in reason_zero

    def test_reject_brush_star_low_fork_ratio(self):
        """测试刷 Star 仓库（forks/stars 比例 < 0.015）被拦截"""
        # 1000 Stars 仅 10 Forks (比例 0.010 < 0.015)
        repo = SimpleNamespace(
            archived=False,
            size=500,
            stargazers_count=1000,
            forks_count=10,
        )
        qualified, reason = is_qualified_repository(repo)
        assert not qualified
        assert "0.015" in reason or "比例过低" in reason or "刷量" in reason

        # 2000 Stars 仅 29 Forks (比例 0.0145 < 0.015)
        repo_edge = SimpleNamespace(
            archived=False,
            size=1000,
            stargazers_count=2000,
            forks_count=29,
        )
        qualified_edge, reason_edge = is_qualified_repository(repo_edge)
        assert not qualified_edge
        assert "0.015" in reason_edge

    def test_accept_qualified_repository(self):
        """测试真实优质开源项目放行"""
        # 1000 Stars, 50 Forks (比例 0.050 >= 0.015), 500KB
        repo = SimpleNamespace(
            archived=False,
            size=500,
            stargazers_count=1000,
            forks_count=50,
        )
        qualified, reason = is_qualified_repository(repo)
        assert qualified
        assert "合格" in reason

        # 边界值：刚满 50KB，比例刚达标 (15/1000 = 0.015)
        repo_boundary = SimpleNamespace(
            archived=False,
            size=50,
            stargazers_count=1000,
            forks_count=15,
        )
        qualified_b, reason_b = is_qualified_repository(repo_boundary)
        assert qualified_b
        assert "合格" in reason_b

    def test_dict_format_compatibility(self):
        """测试对字典格式仓库对象的兼容性"""
        valid_dict = {
            "archived": False,
            "size": 300,
            "stargazers_count": 600,
            "forks_count": 40,
        }
        qualified, _ = is_qualified_repository(valid_dict)
        assert qualified

        archived_dict = {
            "archived": True,
            "size": 300,
            "stargazers_count": 600,
            "forks_count": 40,
        }
        qualified_archived, _ = is_qualified_repository(archived_dict)
        assert not qualified_archived

    def test_none_repository(self):
        """测试 None 对象的健壮性处理"""
        qualified, reason = is_qualified_repository(None)
        assert not qualified


class TestSafeScreenshotUrl:
    """测试外部链接安全沙箱与域名白名单"""

    def test_safe_domains_allowed(self):
        """测试安全域名放行"""
        safe_urls = [
            "https://username.github.io/my-project/",
            "https://my-app.vercel.app",
            "https://preview.netlify.app/docs",
            "https://docs.pages.dev",
            "https://backend.workers.dev",
            "https://my-service.fly.dev",
            "https://api.railway.app",
            "https://webapp.onrender.com",
            "https://huggingface.co/spaces/user/model",
            "https://hf.space/gradio/demo",
            "https://share.streamlit.app/username/app",
        ]
        for url in safe_urls:
            assert is_safe_screenshot_url(url), f"应放行安全链接: {url}"

    def test_unsafe_domains_blocked(self):
        """测试未知可疑域名被严格拦截"""
        unsafe_urls = [
            "https://malicious-phishing-site.com",
            "https://evil.com/login",
            "https://github.io.attacker.org",         # 子域名仿冒
            "https://fake-vercel.app",                 # 字符连字符仿冒
            "http://unknown-startup.io",
            "https://random-domain.xyz",
        ]
        for url in unsafe_urls:
            assert not is_safe_screenshot_url(url), f"应拦截可疑链接: {url}"

    def test_invalid_scheme_and_malformed_urls_blocked(self):
        """测试非法协议与畸形链接拦截"""
        invalid_urls = [
            "javascript:alert('xss')",
            "file:///C:/Windows/System32",
            "ftp://files.github.io/payload",
            "",
            None,
            12345,
            "not_a_url",
        ]
        for url in invalid_urls:
            assert not is_safe_screenshot_url(url), f"应拦截非法输入: {url}"


class TestTakeLiveUiScreenshotSandbox:
    """测试 take_live_ui_screenshot 外部链接沙箱隔离"""

    def test_blocks_unsafe_url_without_calling_selenium(self):
        """测试对非白名单域名坚决不启动 Selenium"""
        with patch("utils.spider.build_stealth_browser") as mock_browser:
            res = take_live_ui_screenshot("test-owner/test-repo", "https://untrusted-site.com/evil")
            assert res is None
            mock_browser.assert_not_called()

    def test_blocks_empty_or_malformed_url(self):
        """测试空链接或非法链接不会启动 Selenium"""
        with patch("utils.spider.build_stealth_browser") as mock_browser:
            assert take_live_ui_screenshot("test/repo", "") is None
            assert take_live_ui_screenshot("test/repo", None) is None
            assert take_live_ui_screenshot("test/repo", "javascript:void(0)") is None
            mock_browser.assert_not_called()
