from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from core import engine
from core.db.manager import migrate_schema
from core.db.models import ArticleHistory, ArticleRepoAssociation
from core.shared.runtime import WorkflowCancelled, WorkflowOutcome


@pytest.fixture
def database(tmp_path, monkeypatch):
    db = create_engine(f"sqlite:///{tmp_path / 'history.sqlite'}")
    migrate_schema(db)
    factory = sessionmaker(bind=db)
    monkeypatch.setattr(engine, "db_manager", SimpleNamespace(session_factory=factory, remove_session=lambda: None))
    yield factory
    db.dispose()


def add_row(session, title, kind, media_id=None, account="test-account"):
    row = ArticleHistory(title=title, source_type=kind, media_id=media_id, wechat_app_id=account,
                         status="DRAFT", publish_date="2026-11-23", success_status=True)
    session.add(row)
    session.flush()
    return row.id


@pytest.mark.parametrize("published_complete", [False, True])
def test_sync_requires_complete_ids_and_releases_only_unowned_links(database, published_complete):
    with database.begin() as s:
        removed = add_row(s, "same title", "github", "gone")
        kept = add_row(s, "same title", "github", "still-live")
        foreign = add_row(s, "foreign", "github", "other-draft", "another-account")
        unscoped = add_row(s, "old", "github", "legacy-id", None)
        legacy = add_row(s, "no ID", "github")
        for name in ("shared", "released", "unrelated"):
            add_row(s, name, "github_repo")
        for article_id, name in [(removed, "shared"), (removed, "released"), (kept, "shared")]:
            s.add(ArticleRepoAssociation(article_id=article_id, repo_name=name))
    pages = {"draft": [{"media_id": "still-live"}], "freepublish": [] if published_complete else None}
    publisher = SimpleNamespace(app_id="test-account", _cloud_items=pages.get)
    engine.sync_local_history_with_wechat(publisher)
    with database() as s:
        assert s.get(ArticleHistory, removed).success_status == (not published_complete)
        assert s.get(ArticleHistory, foreign).success_status
        assert s.get(ArticleHistory, unscoped).success_status
        assert s.get(ArticleHistory, kept).success_status
        assert s.get(ArticleHistory, legacy).success_status
        repos = {r.title: r.success_status for r in s.query(ArticleHistory).filter_by(source_type="github_repo")}
        assert repos == {"shared": True, "released": not published_complete, "unrelated": True}


def test_legacy_migration_is_repeatable(tmp_path):
    db = create_engine(f"sqlite:///{tmp_path / 'old.sqlite'}")
    with db.begin() as c:
        c.exec_driver_sql("CREATE TABLE article_history (id INTEGER PRIMARY KEY, title TEXT, source_type TEXT, "
                          "publish_date TEXT, success_status BOOLEAN, media_id TEXT, error_log TEXT, created_at DATETIME)")
        c.exec_driver_sql("INSERT INTO article_history (id,title) VALUES (1,'old')")
    migrate_schema(db)
    migrate_schema(db)
    with db.connect() as c:
        assert c.exec_driver_sql("SELECT title,status FROM article_history").one() == ("old", "PENDING_REVIEW")
    assert inspect(db).has_table("article_repo_association")
    db.dispose()


def test_invalid_schema_rolls_back(tmp_path):
    db = create_engine(f"sqlite:///{tmp_path / 'broken.sqlite'}")
    with db.begin() as c:
        c.exec_driver_sql("CREATE TABLE article_history (id INTEGER PRIMARY KEY)")
    with pytest.raises(RuntimeError, match="missing columns"):
        migrate_schema(db)
    assert not inspect(db).has_table("article_repo_association")
    db.dispose()


def test_run_main_outcome_and_override(database, monkeypatch):
    publisher = SimpleNamespace(access_token="token")
    monkeypatch.setattr(engine, "_validate_config", lambda: None)
    monkeypatch.setattr(engine, "_print_banner", lambda: None)
    monkeypatch.setattr(engine, "cleanup_old_assets", lambda path: None)
    monkeypatch.setattr(engine, "WeChatPublisher", lambda *args: publisher)
    expected = WorkflowOutcome(task_type="aikepu", status="partial_success", attempted=2, succeeded=1, failed=1)

    def workflow(client, override_node_id):
        assert client is publisher and override_node_id == "intro"
        return expected

    monkeypatch.setattr(engine, "run_aikepu_workflow", workflow)
    assert engine.run_main("aikepu", override_node_id="intro") is expected
    assert engine.run_main("unknown").status == "failed"

    def cancel():
        raise WorkflowCancelled("stop")

    monkeypatch.setattr(engine, "check_cancelled", cancel)
    assert engine.run_main("aikepu").status == "cancelled"

def test_article_id_is_not_a_draft_identity(database):
    with database.begin() as session:
        article = add_row(session, "old title", "github", "draft-id")
    pages = {"draft": [], "freepublish": [{"article_id": "published-id"}]}
    engine.sync_local_history_with_wechat(SimpleNamespace(_cloud_items=pages.get))
    with database() as session:
        assert session.get(ArticleHistory, article).success_status


def test_workflow_repo_writes_track_multiple_owners(database):
    with database.begin() as session:
        first = add_row(session, "A", "github", "draft-a")
        second = add_row(session, "B", "github", "draft-b")
        repo = add_row(session, "org/project", "github_repo", "draft-a")
        session.get(ArticleHistory, repo).media_id = "draft-b"
    with database() as session:
        links = session.query(ArticleRepoAssociation).all()
        assert {(link.article_id, link.repo_name) for link in links} == {
            (first, "org/project"), (second, "org/project")
        }


def test_configuration_failure_before_publisher(database, monkeypatch):
    def invalid():
        raise ValueError("missing credentials")
    monkeypatch.setattr(engine, "_validate_config", invalid)
    outcome = engine.run_main("github")
    assert (outcome.status, outcome.error) == ("failed", "missing credentials")
    assert outcome.started_at <= outcome.finished_at
