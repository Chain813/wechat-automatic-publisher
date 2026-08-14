from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()

class DailyConcept(Base):
    """
    独立表结构：用于记录每日小知识生成的概念，以防止重复。
    """
    __tablename__ = 'daily_concepts'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    concept_name = Column(String(255), nullable=False, unique=True, index=True)
    domain = Column(String(100), nullable=True)  # 可选：所属领域
    created_at = Column(DateTime, default=datetime.now)
