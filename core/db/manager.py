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
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.Session = scoped_session(self.session_factory)
        
    def get_session(self):
        return self.Session()
        
    def remove_session(self):
        self.Session.remove()

# Singleton instance
db_manager = DBManager()
