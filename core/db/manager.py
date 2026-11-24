import os
import threading

from loguru import logger
from sqlalchemy import create_engine, event
from sqlalchemy.orm import scoped_session, sessionmaker

from core.db.models import Base

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                       "data", "auto_publish.sqlite")

_LEGACY_COLUMNS = {
    "wechat_app_id": "VARCHAR(255)",
    "delivery_attempt_id": "VARCHAR(64)",
    "is_published": "BOOLEAN DEFAULT 0",
    "source_url": "TEXT",
    "quality_score": "FLOAT DEFAULT 0.0",
    "status": "VARCHAR(50) DEFAULT 'PENDING_REVIEW'",
    "thumb_media_id": "VARCHAR(255)",
    "fact_check_result": "TEXT",
}


def migrate_schema(engine):
    # Serialize inspection and DDL across CLI and Web processes.
    with engine.connect() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            Base.metadata.create_all(conn)
            existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(article_history)")}
            for name, definition in _LEGACY_COLUMNS.items():
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE article_history ADD COLUMN {name} {definition}")
            required = set(Base.metadata.tables["article_history"].columns.keys())
            actual = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(article_history)")}
            if required - actual:
                raise RuntimeError(f"article_history missing columns: {sorted(required - actual)}")
            conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_delivery_attempt ON article_history(delivery_attempt_id)")
            # The workflow writes a repo history row with its owning draft media_id.
            # Preserve every ownership transition in the same SQLite transaction.
            for operation in ("INSERT", "UPDATE OF media_id, title, success_status"):
                suffix = operation.split()[0].lower()
                conn.exec_driver_sql(f"""
                    CREATE TRIGGER IF NOT EXISTS link_github_repo_{suffix}
                    AFTER {operation} ON article_history
                    WHEN NEW.source_type = 'github_repo' AND NEW.success_status = 1
                         AND NEW.media_id IS NOT NULL
                    BEGIN
                        INSERT OR IGNORE INTO article_repo_association(article_id, repo_name)
                        SELECT id, NEW.title FROM article_history
                        WHERE source_type = 'github' AND media_id = NEW.media_id;
                    END
                """)
            conn.exec_driver_sql("""
                INSERT OR IGNORE INTO article_repo_association(article_id, repo_name)
                SELECT article.id, repo.title FROM article_history repo
                JOIN article_history article ON article.media_id = repo.media_id
                WHERE repo.source_type = 'github_repo' AND article.source_type = 'github'
                      AND repo.media_id IS NOT NULL AND repo.media_id != ''
            """)
            conn.commit()
        except Exception:
            conn.rollback()
            raise


class DBManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._init_db()
                cls._instance = instance
        return cls._instance

    def _init_db(self):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        self.engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(self.engine, "connect")
        def configure_connection(connection, _record):
            cursor = connection.cursor()
            try:
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

        try:
            migrate_schema(self.engine)
        except Exception:
            logger.exception("SQLite 初始化或迁移失败: {}", DB_PATH)
            self.engine.dispose()
            raise
        self.session_factory = sessionmaker(bind=self.engine)
        self.Session = scoped_session(self.session_factory)

    def get_session(self):
        return self.Session()

    def remove_session(self):
        self.Session.remove()


db_manager = DBManager()
