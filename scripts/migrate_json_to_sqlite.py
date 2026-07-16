import os
import json
import sys
from datetime import datetime

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db.manager import db_manager
from core.db.models import ArticleHistory

def migrate_hotspots():
    history_file = 'hotspots_history.json'
    if not os.path.exists(history_file):
        print(f"No {history_file} found.")
        return
        
    try:
        with open(history_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Failed to read {history_file}: {e}")
        return
        
    session = db_manager.get_session()
    migrated_count = 0
    
    for date_str, entries in data.items():
        if isinstance(entries, list):
            # Old format: just a list of strings
            for topic in entries:
                existing = session.query(ArticleHistory).filter_by(title=topic, source_type="hotspots").first()
                if not existing:
                    ah = ArticleHistory(
                        title=topic,
                        source_type="hotspots",
                        publish_date=date_str,
                        success_status=True,
                        media_id=None,
                        error_log=None
                    )
                    session.add(ah)
                    migrated_count += 1
        elif isinstance(entries, dict):
            # New format: {"topics": [...], "results": [...]}
            results = entries.get("results", [])
            # Convert results to a dictionary for quick lookup
            res_dict = {r.get("topic"): r for r in results}
            
            topics = entries.get("topics", [])
            for topic in topics:
                res = res_dict.get(topic)
                success = True if res and res.get("success") else False
                media_id = res.get("draft_id") if res else None
                error_log = res.get("error") if res else None
                
                existing = session.query(ArticleHistory).filter_by(title=topic, source_type="hotspots").first()
                if not existing:
                    ah = ArticleHistory(
                        title=topic,
                        source_type="hotspots",
                        publish_date=date_str,
                        success_status=success,
                        media_id=media_id,
                        error_log=error_log
                    )
                    session.add(ah)
                    migrated_count += 1
                    
    session.commit()
    print(f"Successfully migrated {migrated_count} hotspot records to SQLite.")
    
def migrate_github():
    history_file = 'github_publish_records.json'
    if not os.path.exists(history_file):
        print(f"No {history_file} found.")
        return
        
    try:
        with open(history_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Failed to read {history_file}: {e}")
        return
        
    session = db_manager.get_session()
    migrated_count = 0
    
    for record in data:
        # [{"date": "2026-06-13", "title": "GitHub今日热榜...", "draft_id": "xxx"}]
        title = record.get("title")
        date_str = record.get("date", "2026-01-01")
        draft_id = record.get("draft_id")
        if not title: continue
        
        existing = session.query(ArticleHistory).filter_by(title=title, source_type="github").first()
        if not existing:
            ah = ArticleHistory(
                title=title,
                source_type="github",
                publish_date=date_str,
                success_status=True,
                media_id=draft_id,
                error_log=None
            )
            session.add(ah)
            migrated_count += 1
            
    session.commit()
    print(f"Successfully migrated {migrated_count} github records to SQLite.")

if __name__ == "__main__":
    print("Starting migration to SQLite...")
    migrate_hotspots()
    migrate_github()
    print("Migration complete!")
