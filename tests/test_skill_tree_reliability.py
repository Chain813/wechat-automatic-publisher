import json
import multiprocessing
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from core.aikepu import skill_tree as tree
from core.db.models import ArticleHistory, Base


def _writer(path, prefix, ready, start):
    tree.HISTORY_FILE = path
    ready.put(True)
    start.wait(20)
    for i in range(12):
        tree.mark_published(str(i), prefix, tree_name=prefix)


def test_process_updates_preserve_both_trees(tmp_path):
    path = tmp_path / "history.json"
    ctx = multiprocessing.get_context("spawn")
    ready, start = ctx.Queue(), ctx.Event()
    processes = [ctx.Process(target=_writer, args=(str(path), name, ready, start))
                 for name in ("one", "two")]
    for proc in processes:
        proc.start()
    try:
        for _ in processes:
            ready.get(timeout=30)
        start.set()
        for proc in processes:
            proc.join(30)
            assert proc.exitcode == 0
    finally:
        for proc in processes:
            if proc.is_alive():
                proc.terminate()
                proc.join()
    entries = [entry for day in json.loads(path.read_text()).values() for entry in day]
    assert {(e["tree"], e["node_id"]) for e in entries} == {
        (name, str(i)) for name in ("one", "two") for i in range(12)}


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "history.json"
    monkeypatch.setattr(tree, "HISTORY_FILE", str(path))
    monkeypatch.setattr(tree, "TREES_DIR", str(tmp_path))
    monkeypatch.setattr(tree, "ACTIVE_TREE_FILE", str(tmp_path / "_active.txt"))
    monkeypatch.setenv("KNOWLEDGE_TREE", "aikepu")
    monkeypatch.setattr(tree, "_tree_cache", {})
    monkeypatch.setattr(tree, "_reserved_ids", set())
    for name in ("aikepu", "other"):
        (tmp_path / (name + ".json")).write_text(json.dumps({"nodes": [
            {"id": "intro", "title": "Intro"}, {"id": "next", "title": "Next",
                                                "prerequisites": ["intro"]}]}))
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = scoped_session(sessionmaker(bind=engine))
    manager = SimpleNamespace(get_session=sessions, remove_session=sessions.remove)
    monkeypatch.setitem(sys.modules, "core.db.manager", SimpleNamespace(db_manager=manager))
    yield path, sessions
    sessions.remove()
    engine.dispose()


def test_legacy_and_new_tree_states_are_independent(store):
    path, sessions = store
    path.write_text(json.dumps({"old": [{"node_id": "intro", "status": "draft"}]}))
    tree.set_active_tree("other")
    assert tree.get_active_tree_name() == "other"
    assert tree.get_draft_ids() == []
    assert tree.set_node_status("intro", "published")
    record = sessions().query(ArticleHistory).one()
    assert record.publish_date and record.status == "APPROVED"
    assert tree.get_draft_ids(["Next"]) == []
    assert tree.get_published_ids() == ["intro"]
    assert tree.get_published_ids(tree_name="aikepu") == []
    assert tree.get_draft_ids(tree_name="aikepu") == ["intro"]
    tree.reconcile_history_file(["unrelated"])
    assert tree.set_node_status("intro", "reset")
    assert tree.get_published_ids() == []
    assert tree.get_draft_ids(tree_name="aikepu") == ["intro"]


def test_override_cache_and_stats(store):
    stats = tree.get_skill_tree_stats()
    assert (stats["total_nodes"], stats["available_count"], stats["locked_count"],
            stats["next_recommended_topic"]) == (2, 1, 1, "Intro")
    assert tree.select_next_topic("missing") is None
    assert tree.select_next_topic("next")["tree_name"] == "aikepu"
    tree.reset_tree_cache()
    assert tree.select_next_topic("next") is None
    assert tree.select_next_topic("next", "other")["node_id"] == "next"
    tree.release_reserved("next", "aikepu")
    assert tree.select_next_topic("next")["node_id"] == "next"


def test_corrupt_history_is_preserved(store):
    path, _ = store
    path.write_bytes(b"{broken")
    with pytest.raises(ValueError):
        tree.mark_published("intro", "Intro")
    assert path.read_bytes() == b"{broken"
    assert next(path.parent.glob("history.json.corrupt.*")).read_bytes() == b"{broken"
