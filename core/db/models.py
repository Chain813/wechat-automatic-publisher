from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()

class ArticleHistory(Base):
    __tablename__ = 'article_history'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False, index=True)
    source_type = Column(String(50), nullable=False, index=True) # e.g. 'hotspots', 'github', 'aikepu'
    publish_date = Column(String(20), nullable=False, index=True) # YYYY-MM-DD
    success_status = Column(Boolean, default=False)
    is_published = Column(Boolean, default=False)
    media_id = Column(String(255), nullable=True)
    error_log = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

