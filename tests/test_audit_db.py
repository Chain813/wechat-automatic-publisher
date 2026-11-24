import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.db.models import Base, ArticleHistory


def test_article_history_audit_fields_crud():
    """测试 ArticleHistory 中保存和查询新增的审计字段"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # 1. 测试默认值
    record_default = ArticleHistory(
        title="Test Default Audit Fields",
        source_type="hotspots",
        publish_date="2026-10-08",
        success_status=False,
    )
    session.add(record_default)
    session.commit()

    saved_default = session.query(ArticleHistory).filter_by(title="Test Default Audit Fields").first()
    assert saved_default is not None
    assert saved_default.quality_score == 0.0
    assert saved_default.status == "PENDING_REVIEW"
    assert saved_default.source_url is None
    assert saved_default.fact_check_result is None

    # 2. 测试显式赋值保存与查询
    record_custom = ArticleHistory(
        title="Test Custom Audit Fields",
        source_type="github",
        publish_date="2026-10-08",
        success_status=True,
        source_url="https://github.com/trending/awesome-ai",
        quality_score=92.5,
        status="APPROVED",
        fact_check_result="Verified by 3 sources. High credibility.",
    )
    session.add(record_custom)
    session.commit()

    saved_custom = session.query(ArticleHistory).filter_by(title="Test Custom Audit Fields").first()
    assert saved_custom is not None
    assert saved_custom.source_url == "https://github.com/trending/awesome-ai"
    assert saved_custom.quality_score == pytest.approx(92.5)
    assert saved_custom.status == "APPROVED"
    assert saved_custom.fact_check_result == "Verified by 3 sources. High credibility."

    session.close()


def test_db_migration_alter_table(tmp_path):
    """测试 SQLite 旧表结构自动升级兼容性（ALTER TABLE 检查）"""
    import sqlite3
    from core.db.manager import DBManager

    db_file = tmp_path / "test_legacy.sqlite"
    # 创建一个旧版本的表，缺少新字段
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE article_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title VARCHAR(255) NOT NULL,
            source_type VARCHAR(50) NOT NULL,
            publish_date VARCHAR(20) NOT NULL,
            success_status BOOLEAN DEFAULT 0,
            is_published BOOLEAN DEFAULT 0,
            media_id VARCHAR(255),
            error_log TEXT,
            created_at DATETIME
        )
    """)
    conn.commit()
    conn.close()

    from core.db.manager import migrate_schema
    engine = create_engine(f"sqlite:///{db_file}")
    migrate_schema(engine)

    # 验证新列已成功添加，可以正常插入和查询
    Session = sessionmaker(bind=engine)
    session = Session()
    item = ArticleHistory(
        title="Migrated Test",
        source_type="aikepu",
        publish_date="2026-10-08",
        source_url="https://example.com/item",
        quality_score=88.0,
        status="PENDING_REVIEW",
        fact_check_result="OK",
    )
    session.add(item)
    session.commit()

    queried = session.query(ArticleHistory).filter_by(title="Migrated Test").first()
    assert queried.quality_score == 88.0
    assert queried.status == "PENDING_REVIEW"
    assert queried.source_url == "https://example.com/item"
    assert queried.fact_check_result == "OK"
    session.close()


def test_api_history_audit_fields():
    """测试 /api/history 返回新增审计字段"""
    from webui import app
    from core.db.manager import db_manager
    session = db_manager.get_session()

    test_article = ArticleHistory(
        title="WebUI History Audit Test Article",
        source_type="hotspots",
        publish_date="2026-10-08",
        success_status=True,
        source_url="https://news.ycombinator.com/item?id=123",
        quality_score=95.0,
        status="APPROVED",
        fact_check_result="Verified via HN",
    )
    session.add(test_article)
    session.commit()
    art_id = test_article.id

    client = app.test_client()
    resp = client.get("/api/history")
    assert resp.status_code == 200
    data = resp.get_json()

    # 在 sent 或 unsent 中找到对应文章
    all_items = data.get("sent", []) + data.get("unsent", [])
    matched = next((item for item in all_items if item.get("id") == art_id), None)
    assert matched is not None
    assert matched["quality_score"] == pytest.approx(95.0)
    assert matched["source_url"] == "https://news.ycombinator.com/item?id=123"
    assert matched["status"] == "APPROVED"
    assert matched["fact_check_result"] == "Verified via HN"

    # 清理测试数据
    session.query(ArticleHistory).filter(ArticleHistory.id == art_id).delete()
    session.commit()
    db_manager.remove_session()


def test_api_review_approve():
    """测试 /api/review/approve 人工核准待审文章"""
    from webui import app
    from core.db.manager import db_manager
    session = db_manager.get_session()

    test_article = ArticleHistory(
        title="Review Approve Test Article",
        source_type="github",
        publish_date="2026-10-08",
        success_status=False,
        source_url="https://github.com/test/repo",
        quality_score=87.5,
        status="PENDING_REVIEW",
        fact_check_result="Pending Review",
    )
    session.add(test_article)
    session.commit()
    art_id = test_article.id

    client = app.test_client()

    # 1. 缺少 ID
    resp_bad = client.post("/api/review/approve", json={})
    assert resp_bad.status_code == 400

    # 2. 不存在的 ID
    resp_404 = client.post("/api/review/approve", json={"id": 9999999})
    assert resp_404.status_code == 404

    # 3. 成功核准
    resp_ok = client.post("/api/review/approve", json={"id": art_id})
    assert resp_ok.status_code == 200
    res_data = resp_ok.get_json()
    assert res_data["status"] == "success"
    assert res_data["review_status"] == "APPROVED"

    # 校验数据库中状态已变为 APPROVED
    refreshed = session.query(ArticleHistory).filter(ArticleHistory.id == art_id).first()
    assert refreshed.status == "APPROVED"
    assert refreshed.success_status is True

    # 清理测试数据
    session.delete(refreshed)
    session.commit()
    db_manager.remove_session()


def test_sqlite_wal_and_busy_timeout():
    """测试 SQLite 连接已正确应用 WAL 模式与 30s busy_timeout"""
    from core.db.manager import db_manager
    from sqlalchemy import text

    with db_manager.engine.connect() as conn:
        journal_mode = conn.execute(text("PRAGMA journal_mode;")).scalar()
        busy_timeout = conn.execute(text("PRAGMA busy_timeout;")).scalar()

        assert str(journal_mode).lower() == "wal"
        assert int(busy_timeout) >= 30000


def test_semantic_check_hotspot_item_safety():
    """测试当查重入参为 HotspotItem 对象时，不发生崩溃且 Prompt 中为纯字符串"""
    from core.plugins.base import HotspotItem
    from core.shared.publisher import _select_semantic_candidates, _ai_semantic_check
    from unittest.mock import patch

    item = HotspotItem(
        title="测试量子计算突破最新进展",
        url="https://example.com/quantum",
        summary="量子计算突破"
    )
    existing = ["量子计算最新进展回顾", "大模型技术全解", "无人驾驶新规"]

    # 1. 验证粗筛候选返回，无 TypeError
    candidates = _select_semantic_candidates(item, existing)
    assert isinstance(candidates, list)
    assert "量子计算最新进展回顾" in candidates

    # 2. 验证 AI 查重 Prompt 不包含 HotspotItem 的 repr
    captured_prompts = []
    def fake_llm(prompt, **kwargs):
        captured_prompts.append(prompt)
        return "重复|1"

    with patch("core.shared.llm.call_deepseek_with_retry", side_effect=fake_llm):
        is_dup, matched = _ai_semantic_check(item, existing)
        assert is_dup is True
        assert matched == "量子计算最新进展回顾"
        assert len(captured_prompts) == 1
        prompt_text = captured_prompts[0]
        # 严格防御：Prompt 待发布话题中不能出现 HotspotItem 类名
        assert "待发布话题：「测试量子计算突破最新进展」" in prompt_text
        assert "HotspotItem(" not in prompt_text


def test_multithread_sqlite_concurrency():
    """测试多线程高并发写入 SQLite 时不会抛出 database locked 错误"""
    import threading
    from core.db.manager import db_manager
    from core.db.models import ArticleHistory

    errors = []
    created_ids = []
    lock = threading.Lock()

    def worker(worker_id):
        try:
            session = db_manager.get_session()
            ah = ArticleHistory(
                title=f"Concurrent Test Article {worker_id}",
                source_type="hotspots",
                publish_date="2026-10-12",
                success_status=True,
                status="DRAFT"
            )
            session.add(ah)
            session.commit()
            with lock:
                created_ids.append(ah.id)
        except Exception as e:
            with lock:
                errors.append(e)
        finally:
            db_manager.remove_session()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 校验所有线程写入成功，0 报错
    assert len(errors) == 0, f"并发写入报错: {errors}"
    assert len(created_ids) == 10

    # 清理测试数据
    clean_session = db_manager.get_session()
    clean_session.query(ArticleHistory).filter(ArticleHistory.id.in_(created_ids)).delete(synchronize_session=False)
    clean_session.commit()
    db_manager.remove_session()


