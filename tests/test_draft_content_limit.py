import hashlib
import json
from unittest.mock import Mock

import pytest

from core.shared import publisher


@pytest.fixture
def draft_delivery(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    session = Mock()
    session.post.return_value.json.return_value = {"media_id": "test_draft"}
    monkeypatch.setattr(publisher, "build_api_session", lambda: session)
    monkeypatch.setattr(publisher.WeChatPublisher, "_global_access_token", "test_token")
    monkeypatch.setattr(publisher.WeChatPublisher, "_global_token_expires_at", float("inf"))
    notification = Mock()
    monkeypatch.setattr(publisher, "send_to_qywechat", notification)
    client = publisher.WeChatPublisher("test_app", "test_secret")

    # Measure the production wrapper, so changing its styling preserves the boundary test.
    client.add_draft("边界测试", "", "cover")
    wrapper = json.loads(session.post.call_args.kwargs["data"])["articles"][0]["content"]
    body_budget = 10 * 1024 * 1024 - len(wrapper.encode("utf-8"))
    session.reset_mock()
    return client, session, notification, body_budget


def article_of_size(size):
    tags = "<p></p>"
    count, remainder = divmod(size - len(tags), len("文".encode("utf-8")))
    return "<p>" + "文" * count + "a" * remainder + "</p>"


def test_draft_exactly_at_byte_limit_preserves_full_article(draft_delivery):
    client, session, _, body_budget = draft_delivery
    article = article_of_size(body_budget)

    assert client.add_draft("边界测试", article, "cover") == {"media_id": "test_draft"}
    session.post.assert_called_once()
    sent = json.loads(session.post.call_args.kwargs["data"])["articles"][0]["content"]
    assert len(sent.encode("utf-8")) == 10 * 1024 * 1024
    assert article in sent


def test_oversize_draft_keeps_full_preview_for_editing(draft_delivery, tmp_path):
    client, session, notification, body_budget = draft_delivery
    title = "边界测试"
    article = article_of_size(body_budget + 1)

    success, result = client.publish_and_notify(title, article, "cover")

    assert success is False
    assert "10,485,761" in result["errmsg"]
    assert "10 MiB" in result["errmsg"]
    session.post.assert_not_called()
    notification.assert_not_called()
    title_hash = hashlib.md5(title.encode("utf-8")).hexdigest()
    preview = tmp_path / "data" / "previews" / f"fail_{title_hash}.html"
    assert preview.read_text(encoding="utf-8") == article
