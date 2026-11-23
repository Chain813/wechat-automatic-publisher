from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

import config
from core.shared import llm, runtime
from utils import image_handler as images
from utils.key_pool import ApiKeyPool, RateLimiter


@pytest.fixture
def fresh_pools():
    llm.reset_llm_key_pool()
    images.reset_qwen_key_pool()
    yield
    llm.reset_llm_key_pool()
    images.reset_qwen_key_pool()


def test_hot_reload_changes_outgoing_request(monkeypatch, fresh_pools):
    monkeypatch.setattr(config, "LLM_API_KEYS", [])
    monkeypatch.setattr(config, "DASHSCOPE_API_KEYS", [])
    response = Mock()
    response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    post = Mock(return_value=response)
    monkeypatch.setattr(llm.API_SESSION, "post", post)
    for version in ("first", "second"):
        url = f"https://{version}.invalid"
        monkeypatch.setattr(config, "LLM_BASE_URL", url)
        monkeypatch.setattr(config, "LLM_MODEL", version)
        monkeypatch.setattr(config, "LLM_API_KEY", version)
        monkeypatch.setattr(config, "QWEN_IMAGE_API_KEY", version)
        llm.reset_llm_key_pool()
        images.reset_qwen_key_pool()
        assert llm.call_deepseek_with_retry("test") == "ok"
        assert post.call_args.args == (url + "/chat/completions",)
        assert post.call_args.kwargs["headers"]["Authorization"] == f"Bearer {version}"
        assert post.call_args.kwargs["json"]["model"] == version
        assert images._get_qwen_key_pool().get_key() == version


def test_metrics_under_concurrent_updates():
    metrics = llm.LLMCacheMetrics()
    assert metrics.get_stats()["avg_latency_ms"] == 0
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda i: metrics.record(2, 1, i), range(100)))
    stats = metrics.get_stats()
    assert stats["total_requests"] == stats["miss_tokens"] == 100
    assert stats["saved_tokens"] == stats["hit_tokens"] == 200
    assert stats["avg_latency_ms"] == 49.5


@pytest.mark.parametrize("name", ["default_cover.jpg", "static/images/cover.jpg", "diagram.png"])
def test_protected_image_survives_cover_and_body_resize(tmp_path, monkeypatch, name):
    monkeypatch.chdir(tmp_path)
    source = Path(name)
    source.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (100, 90), "blue").save(source)
    original = source.read_bytes()
    cover = images.resize_for_wechat(source, "cover")
    body = images.resize_for_wechat(source, "body")
    assert source.read_bytes() == original
    assert cover != body
    for path, size in [(cover, images.WECHAT_COVER_SIZE), (body, images.WECHAT_BODY_SIZE)]:
        with Image.open(path) as result:
            assert result.format == "JPEG" and result.size == size


def test_cooled_credentials_are_never_sent(monkeypatch):
    import utils.key_pool as pools
    now = [100.0]
    monkeypatch.setattr(pools, "time", Mock(monotonic=lambda: now[0]))
    pool = ApiKeyPool(["one"])
    pool.report_failure("one", 300)
    pool.report_failure("one", 60)
    pool.report_success("one")
    now[0] += 60
    assert pool.get_key() == ""
    post = Mock(side_effect=AssertionError("unexpected HTTP request"))
    monkeypatch.setattr(llm.API_SESSION, "post", post)
    monkeypatch.setattr(llm, "_get_llm_key_pool", lambda: pool)
    assert llm.call_deepseek_with_retry("test") == ""
    post.assert_not_called()
    now[0] += 240
    assert pool.get_key() == "one"


def test_rate_limit_wait_is_interruptible(monkeypatch):
    event = Mock()
    event.is_set.side_effect = [False, False, True]
    monkeypatch.setattr(runtime, "cancel_event", event)
    limiter = RateLimiter(3600)
    limiter.wait()
    with pytest.raises(runtime.WorkflowCancelled):
        limiter.wait()
    event.wait.assert_called_once()


def test_qwen_cancel_after_rate_limit_prevents_second_post(monkeypatch):
    import requests
    pool = ApiKeyPool(["one", "two"])
    monkeypatch.setattr(images, "_get_qwen_key_pool", lambda: pool)
    monkeypatch.setattr(images, "_qwen_image_limiter", RateLimiter(0))
    from threading import Semaphore
    monkeypatch.setattr(images, "_qwen_image_sem", Semaphore(1))
    def limited(*args, **kwargs):
        runtime.cancel_event.set()
        return Mock(status_code=429, text="rate limited")
    post = Mock(side_effect=limited)
    monkeypatch.setattr(requests, "post", post)
    try:
        with pytest.raises(runtime.WorkflowCancelled):
            images._qwen_post_with_rotation("https://example.invalid", {}, 1)
    finally:
        runtime.cancel_event.clear()
    post.assert_called_once()


def test_disabled_sd_skips_discovery(monkeypatch):
    monkeypatch.setattr(config, "SD_ENABLED", False)
    monkeypatch.setattr(images, "detect_sd_api_url", Mock(side_effect=AssertionError))
    assert images._try_local_sd("test", ".") is None
    assert images.get_sd_api_url() is None

def test_last_attempt_auth_failure_cools_key(monkeypatch):
    import requests
    pool = ApiKeyPool(["only"])
    response = requests.Response()
    response.status_code = 403
    post = Mock(return_value=response)
    monkeypatch.setattr(llm, "_get_llm_key_pool", lambda: pool)
    monkeypatch.setattr(llm.API_SESSION, "post", post)
    for _ in range(2):
        assert llm.call_deepseek_with_retry("test", max_retries=1) == ""
    post.assert_called_once()


def test_batch_accepts_multiple_keys_without_single_key(monkeypatch, tmp_path, fresh_pools):
    monkeypatch.setattr(config, "QWEN_IMAGE_API_KEY", "")
    monkeypatch.setattr(config, "DASHSCOPE_API_KEYS", ["one", "two"])
    generate = Mock(return_value=[])
    monkeypatch.setattr(images, "_try_qwen_image_batch", generate)
    assert images.generate_article_images_batch("title", "text", ["topic"], tmp_path) == [None]
    generate.assert_called_once()
