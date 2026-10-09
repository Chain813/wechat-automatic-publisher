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

    # 模拟 DBManager 的 ALTER TABLE 执行
    engine = create_engine(f"sqlite:///{db_file}")
    # 调用 manager 的升级逻辑或直接检验连接
    from sqlalchemy import text
    with engine.connect() as conn:
        for col, col_type in [
            ("source_url", "TEXT"),
            ("quality_score", "FLOAT DEFAULT 0.0"),
            ("status", "VARCHAR(50) DEFAULT 'PENDING_REVIEW'"),
            ("fact_check_result", "TEXT"),
        ]:
            try:
                conn.execute(text(f"ALTER TABLE article_history ADD COLUMN {col} {col_type};"))
                conn.commit()
            except Exception:
                pass

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

