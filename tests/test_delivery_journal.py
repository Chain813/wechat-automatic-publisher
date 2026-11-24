import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
import requests

from core.shared import publisher
from core.shared.delivery_journal import DeliveryJournal
from utils.http_client import build_api_session


def response(payload):
    value = Mock()
    value.json.return_value = payload
    return value


def item(index, content=""):
    return {"media_id": str(index), "content": {"news_item": [
        {"title": "same", "content": content}]}}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    session = Mock()
    session.get.return_value = response({"access_token": "token"})
    monkeypatch.setattr(publisher, "build_api_session", lambda: session)
    monkeypatch.setattr(publisher.WeChatPublisher, "_tokens", {})
    return publisher.WeChatPublisher("app", "secret",
        journal=DeliveryJournal(tmp_path / "journal.db"))


def test_concurrent_duplicate_claims(tmp_path):
    path = tmp_path / "db"
    def claim(_):
        return DeliveryJournal(path).claim("app", "review:42", "title", {})
    with ThreadPoolExecutor(8) as pool:
        claims = list(pool.map(claim, range(24)))
    assert sum(owner for _, owner in claims) == 1
    assert len({row["attempt_id"] for row, _ in claims}) == 1


@pytest.mark.parametrize("fault", [requests.ReadTimeout(), response({"errcode": -1}),
                                   response({}), response(None)])
def test_unknown_never_replays_or_matches_title(client, fault):
    client.session.post.side_effect = [fault, response({"total_count": 1, "item": [item(1)]})]
    first = client.add_draft("same", "body", "cover", operation_id="review:42")
    assert first["status"] == "CLOUD_UNCERTAIN"
    assert "media_id" not in first
    assert client.session.post.call_count == 2
    restart = publisher.WeChatPublisher("app", "secret", journal=DeliveryJournal(client.journal.path))
    again = restart.add_draft("same", "edited", "cover2", operation_id="review:42")
    assert again["attempt_id"] == first["attempt_id"]
    assert client.session.post.call_count == 2


def test_exact_marker_on_second_page(client):
    seen = []
    def post(url, **kwargs):
        if "/draft/add?" in url:
            assert kwargs["allow_redirects"] is False
            seen.append(json.loads(kwargs["data"])["articles"][0]["content"])
            raise requests.ReadTimeout()
        offset = kwargs["json"]["offset"]
        page = [item(i) for i in range(20)] if offset == 0 else [item(20, seen[0])]
        return response({"total_count": 21, "item": page})
    client.session.post.side_effect = post
    row = client.add_draft("same", "body", "cover", operation_id="one", context={"repo": "r"})
    assert row["status"] == "DRAFT_PENDING_RECORD"
    assert row["media_id"] == "20"
    assert client.pending_deliveries()[0]["context"] == {"repo": "r"}
    assert client.reconcile_delivery(row["attempt_id"]) == row
    for _ in range(2):
        assert client.mark_delivery_recorded(row["attempt_id"])["status"] == "DRAFT"
    assert not client.pending_deliveries()
    assert len(seen) == 1


def test_incomplete_page_is_not_an_empty_snapshot(client):
    client.session.post.side_effect = [
        response({"total_count": 21, "item": [item(i) for i in range(20)]}),
        response({"errcode": 48001})]
    assert client.get_draft_titles() is None


def test_only_definitive_token_rejection_is_resent(client):
    client.session.post.side_effect = [response({"errcode": 42001}), response({"media_id": "m"})]
    row = client.add_draft("same", "body", "cover")
    assert row["media_id"] == "m"
    first, second = client.session.post.call_args_list
    assert first.kwargs["data"] == second.kwargs["data"]


def test_secret_rotation_and_account_isolation(client):
    client.session.get.side_effect = [response({"access_token": "rotated"}),
                                      response({"access_token": "other"})]
    assert publisher.WeChatPublisher("app", "secret").access_token == "token"
    assert publisher.WeChatPublisher("app", "new").access_token == "rotated"
    assert publisher.WeChatPublisher("other", "new").access_token == "other"


def test_receipt_survives_primary_write_error(client, monkeypatch):
    client.session.post.return_value = response({"media_id": "m"})
    with monkeypatch.context() as patch:
        patch.setattr(client.journal, "resolve", Mock(side_effect=OSError()))
        row = client.add_draft("same", "body", "cover")
    assert client.reconcile_delivery(row["attempt_id"])["media_id"] == "m"
    client.session.post.assert_called_once()


def test_draft_transport_disables_all_retries():
    with build_api_session() as session:
        assert session.get_adapter("https://api.weixin.qq.com/cgi-bin/draft/add?access_token=t").max_retries.total == 0
        assert "POST" not in session.get_adapter("https://example.com").max_retries.allowed_methods

def test_replayed_review_restores_original_preview(client, monkeypatch, tmp_path):
    client.session.post.return_value = response({"media_id": "draft"})
    notify = Mock()
    monkeypatch.setattr(publisher, "send_to_qywechat", notify)
    first_ok, first = client.publish_and_notify("title", "original", "cover", operation_id="review:1")
    second_ok, second = client.publish_and_notify("title", "edited", "cover", operation_id="review:1")
    assert first_ok and second_ok
    assert first["attempt_id"] == second["attempt_id"]
    assert (tmp_path / "data/previews/draft.html").read_text("utf8") == "original"
    notify.assert_called_once()
    client.session.post.assert_called_once()


def test_receipt_replay_after_history_failure_never_transmits_again(client, monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import scoped_session, sessionmaker
    from types import SimpleNamespace
    from core.db.manager import migrate_schema
    from core.db.models import ArticleHistory
    from core.pipeline import records

    engine = create_engine(f"sqlite:///{tmp_path / 'articles.db'}")
    migrate_schema(engine)
    sessions = scoped_session(sessionmaker(bind=engine))
    monkeypatch.setattr(records, "db_manager", SimpleNamespace(get_session=sessions, remove_session=sessions.remove))
    monkeypatch.setattr(publisher, "send_to_qywechat", Mock())
    client.session.post.return_value = response({"media_id": "cloud-id"})
    args = (client, "hotspots", "topic", "article", "cover", "digest", 80)
    with monkeypatch.context() as patch:
        patch.setattr(records, "_history", Mock(side_effect=OSError("database offline")))
        ok, error = records.publish_article(*args)
        assert not ok and error.startswith("DRAFT_PENDING_RECORD")
    pending, = client.pending_deliveries()
    records.replay_delivery(client, pending)
    records.replay_delivery(client, pending)
    client.session.post.assert_called_once()
    assert not client.pending_deliveries()
    with sessions() as session:
        row = session.query(ArticleHistory).one()
        assert (row.wechat_app_id, row.delivery_attempt_id, row.media_id, row.status) == (
            "app", pending["attempt_id"], "cloud-id", "DRAFT")
    sessions.remove()
    engine.dispose()


def test_cancel_before_transmit_resolves_claim(client, monkeypatch):
    from core.shared.runtime import WorkflowCancelled

    check = Mock(side_effect=[None, WorkflowCancelled("cancel")])
    monkeypatch.setattr(publisher, "check_cancelled", check)
    with pytest.raises(WorkflowCancelled):
        client.add_draft("same", "body", "cover", operation_id="cancelled")
    client.session.post.assert_not_called()
    assert not client.pending_deliveries()


def test_release_requires_exact_settled_receipt(client):
    client.session.post.return_value = response({"media_id": "draft-x"})
    row = client.add_draft("same", "body", "cover", operation_id="topic")
    attempt = row["attempt_id"]
    client.mark_delivery_recorded(attempt)
    for account, media in [("another-account", "draft-x"), ("app", "wrong")]:
        client.journal.retire_confirmed_draft(account, attempt, media)
        assert client.journal.get("app", attempt)["status"] == "DRAFT"
    client.journal.retire_confirmed_draft("app", attempt, "draft-x")
    assert client.journal.get("app", attempt)["status"] == "ARCHIVED"
    _, owner = client.journal.claim("app", "topic", "same", {})
    assert owner
