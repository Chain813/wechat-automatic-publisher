import os
import threading
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from daily_knowledge.models import Base, DailyConcept

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), 
    "data",
    "cache",
    "daily_knowledge",
    "daily_knowledge.sqlite"
)

class DBManager:
    """独立于核心业务的专属数据库管理器"""
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
            connect_args={"check_same_thread": False, "timeout": 30},
            echo=False
        )
        # 自动建表
        Base.metadata.create_all(self.engine)
        
        self.session_factory = sessionmaker(bind=self.engine)
        self.Session = scoped_session(self.session_factory)
        
    def get_session(self):
        return self.Session()
        
    def remove_session(self):
        self.Session.remove()

# Singleton instance for this specific DB
db = DBManager()

def get_recent_concepts(limit: int = 50) -> list[str]:
    """获取最近使用的概念，用于构建 LLM 查重黑名单"""
    session = db.get_session()
    try:
        concepts = session.query(DailyConcept.concept_name)\
            .order_by(DailyConcept.created_at.desc())\
            .limit(limit).all()
        return [c[0] for c in concepts]
    finally:
        session.close()

def record_concept(concept_name: str, domain: str = "") -> None:
    """记录新成功生成的概念"""
    session = db.get_session()
    try:
        # 简单防重：判断如果不存在再插入
        exists = session.query(DailyConcept).filter_by(concept_name=concept_name).first()
        if not exists:
            new_concept = DailyConcept(concept_name=concept_name, domain=domain)
            session.add(new_concept)
            session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()
