from concurrent.futures import ThreadPoolExecutor
import queue

import pytest

from core.shared import runtime


def test_independent_log_readers_and_legacy_queue():
    logs = runtime.LogBuffer(maxlen=2)
    for message in ["one", "two", "three"]:
        logs.append(message)
    assert logs.get_nowait() == "two"
    assert logs.drain() == ["three"]
    with pytest.raises(queue.Empty):
        logs.get_nowait()
    assert logs.read_since(0) == (["two", "three"], 3)
    assert logs.read_since(2) == (["three"], 3)


def test_cancellation_wakes_paused_worker_without_resume():
    runtime.pause_event.clear()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(runtime.check_cancelled)
            runtime.cancel_event.set()
            with pytest.raises(runtime.WorkflowCancelled):
                future.result(timeout=2)
    finally:
        runtime.cancel_event.clear()
        runtime.pause_event.set()


def test_config_accepts_multiple_keys_and_allows_settings_bootstrap(monkeypatch):
    import config

    monkeypatch.setattr(config, "WECHAT_APP_ID", "id")
    monkeypatch.setattr(config, "WECHAT_APP_SECRET", "secret")
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    monkeypatch.setattr(config, "LLM_API_KEYS", ["one", "two"])
    assert runtime._validate_config() == []
    monkeypatch.setattr(config, "LLM_API_KEYS", [])
    assert runtime._validate_config(strict=False) == ["LLM_API_KEY"]
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        runtime._validate_config()
