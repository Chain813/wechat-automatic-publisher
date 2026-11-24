"""Local recovery for a completed or ambiguous remote draft request."""
import hashlib
from uuid import uuid4
from sqlalchemy.dialects.sqlite import insert
import os
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

from loguru import logger

from core.db.manager import db_manager
from core.db.models import ArticleHistory


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False, mode="w", encoding="utf-8") as stream:
        temp = Path(stream.name)
        try:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            stream.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def _history(record, status):
    session = db_manager.get_session()
    try:
        attempt_id = record["attempt_id"]
        values = dict(wechat_app_id=record.get("wechat_app_id"), delivery_attempt_id=attempt_id, title=record["title"],
                      source_type=record["source_type"], publish_date=record["publish_date"])
        session.execute(insert(ArticleHistory).values(**values).on_conflict_do_nothing())
        row = session.query(ArticleHistory).filter_by(delivery_attempt_id=attempt_id).one()
        if row.media_id and (row.status in ("APPROVED", "DRAFT") or not record["media_id"]):
            return
        for key in ("title", "media_id", "source_type", "source_url", "quality_score",
                    "thumb_media_id", "publish_date", "error_log", "fact_check_result"):
            setattr(row, key, record[key])
        row.status = status
        row.success_status = status == "DRAFT"
        if status == "DRAFT" and "repos" in record["extra"]:
            from core.db.models import ArticleRepoAssociation
            for repo in record["extra"]["repos"]:
                session.execute(insert(ArticleRepoAssociation).values(article_id=row.id, repo_name=repo)
                                .on_conflict_do_nothing())
        session.commit()
    finally:
        db_manager.remove_session()


def replay_delivery(publisher, delivery):
    """Apply a durable receipt by attempt ID, without contacting WeChat."""
    record = dict(delivery["context"]["workflow_record"], wechat_app_id=delivery.get("account"), attempt_id=delivery["attempt_id"],
                  media_id=delivery.get("media_id"), status=delivery["status"],
                  error_log=delivery.get("errmsg"))
    media = record["media_id"]
    status = record["status"]
    _history(record, "DRAFT_PENDING_RECORD" if media else status)
    name = media or ("fail_" + hashlib.md5(record["title"].encode()).hexdigest())
    if Path(name).name != name or "/" in name or "\\" in name:
        raise ValueError("Invalid preview identifier")
    _write(Path("data/previews") / (name + ".html"), record["html"])
    if media:
        extra = record["extra"]
        if "markdown" in extra:
            filename = extra["markdown_name"]
            if Path(filename).name != filename:
                raise ValueError("Invalid markdown filename")
            _write(Path("data/markdown") / filename, extra["markdown"])
        if "repos" in extra:
            from core.github.collector import save_github_history
            save_github_history(extra["repos"], media_id=media)
        if "node_id" in extra:
            from core.aikepu.workflow import mark_published
            mark_published(extra["node_id"], record["title"], draft_id=media, status="draft",
                           tree_name=extra["tree_name"])
        if "concept" in extra:
            from daily_knowledge.database import record_concept
            record_concept(extra["concept"], extra["domain"])
        _history(record, "DRAFT")
        if delivery.get("account"):
            publisher.mark_delivery_recorded(delivery["attempt_id"])


def publish_article(publisher, task, title, html, thumb, digest, score, *,
                    source_url="", fact="", **extra):
    from core.shared.runtime import check_cancelled

    record = dict(source_type=task, title=title, html=html, source_url=source_url,
                  thumb_media_id=thumb, quality_score=score, publish_date=date.today().isoformat(),
                  fact_check_result=fact, extra=extra)
    identity = source_url or extra.get("concept") or title
    operation_id = task + ":" + hashlib.sha256(identity.encode()).hexdigest()
    context = {"workflow_record": record}
    check_cancelled()
    success, result = publisher.publish_and_notify(title, html, thumb, digest,
                                                  operation_id=operation_id, context=context)
    delivery = dict(result)
    delivery.setdefault("context", context)
    delivery.setdefault("attempt_id", uuid4().hex)
    status = delivery.setdefault("status", "DRAFT_PENDING_RECORD" if success else "FAILED")
    if status == "DRAFT" and delivery.get("media_id"):
        return True, None
    try:
        replay_delivery(publisher, delivery)
    except Exception as exc:
        logger.exception("Local recording incomplete for attempt {}", delivery["attempt_id"])
        if delivery.get("media_id"):
            return False, "DRAFT_PENDING_RECORD: " + str(exc)
        if status != "CLOUD_UNCERTAIN":
            return False, str(exc)
    if status == "CLOUD_UNCERTAIN":
        return False, "CLOUD_UNCERTAIN: " + str(result.get("errmsg") or "")
    return bool(delivery.get("media_id")), None if delivery.get("media_id") else result.get("errmsg", "draft failed")
