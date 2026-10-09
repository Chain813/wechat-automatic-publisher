import os
import threading
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from core.db.models import Base

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "auto_publish.sqlite")

class DBManager:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(DBManager, cls).__new__(cls)
                cls._instance._init_db()
        return cls._instance
        
    def _init_db(self):
        db_dir = os.path.dirname(DB_PATH)
        if not os.path.exists(db_dir):
            os.makedirs(db_dir)
            
        self.engine = create_engine(
            f"sqlite:///{DB_PATH}",
            connect_args={"check_same_thread": False},
            echo=False
        )
        from sqlalchemy import text
        Base.metadata.create_all(self.engine)
        try:
            with self.engine.connect() as conn:
                existing_cols = set()
                try:
                    result = conn.execute(text("PRAGMA table_info(article_history);")).fetchall()
                    existing_cols = {row[1] for row in result}
                except Exception:
                    pass

                columns_to_add = [
                    ("is_published", "BOOLEAN DEFAULT 0"),
                    ("source_url", "TEXT"),
                    ("quality_score", "FLOAT DEFAULT 0.0"),
                    ("status", "VARCHAR(50) DEFAULT 'PENDING_REVIEW'"),
                    ("fact_check_result", "TEXT"),
                ]
                for col_name, col_def in columns_to_add:
                    if not existing_cols or col_name not in existing_cols:
                        try:
                            conn.execute(text(f"ALTER TABLE article_history ADD COLUMN {col_name} {col_def};"))
                            conn.commit()
                        except Exception:
                            pass
        except Exception:
            pass
        self.session_factory = sessionmaker(bind=self.engine)
        self.Session = scoped_session(self.session_factory)
        
    def get_session(self):
        return self.Session()
        
    def remove_session(self):
        self.Session.remove()

# Singleton instance
db_manager = DBManager()
