from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import text

import config
from core.shared.publisher import WeChatPublisher
from core.shared.article_utils import _print_banner, cleanup_old_assets
from core.hotspots.workflow import run_hotspots_workflow
from core.github.workflow import run_github_workflow
from core.aikepu.workflow import run_aikepu_workflow
from daily_knowledge.workflow import run_daily_knowledge_workflow
from core.shared.runtime import WorkflowCancelled, WorkflowOutcome, _validate_config, check_cancelled
from core.db.manager import db_manager
from core.db.models import ArticleHistory, ArticleRepoAssociation


def _release_unowned_repos(session, article_id):
    links = session.query(ArticleRepoAssociation.repo_name).filter_by(article_id=article_id)
    active_links = (session.query(ArticleRepoAssociation.repo_name)
                    .join(ArticleHistory, ArticleHistory.id == ArticleRepoAssociation.article_id)
                    .filter((ArticleHistory.success_status.is_(True)) |
                            (ArticleHistory.status == "DRAFT_PENDING_RECORD")))
    session.query(ArticleHistory).filter(
        ArticleHistory.source_type == "github_repo",
        ArticleHistory.title.in_(links),
        ~ArticleHistory.title.in_(active_links),
    ).update({"success_status": False, "is_published": False}, synchronize_session=False)


def sync_local_history_with_wechat(publisher):
    """Release only version-matched records absent from both complete ID inventories."""
    account = getattr(publisher, "app_id", None)
    if not account:
        return
    with db_manager.session_factory() as session:
        candidates = session.query(ArticleHistory.id, ArticleHistory.media_id).filter(
            ArticleHistory.wechat_app_id == account,
            ArticleHistory.success_status.is_(True),
            ArticleHistory.source_type.in_(("hotspots", "github", "aikepu", "daily_knowledge")),
            ArticleHistory.status.in_(("DRAFT", "APPROVED")),
            ArticleHistory.media_id.isnot(None),
        ).all()
    if not candidates:
        return

    try:
        drafts = publisher._cloud_items("draft")
        published = publisher._cloud_items("freepublish")
        if drafts is None or published is None:
            return
        # freepublish normally supplies article_id, not the originating draft media_id.
        # An unlinked published article could be a missing draft under an edited title.
        if published:
            logger.info("发布列表使用独立的文章 ID，保留可能已转为发布状态的历史")
            return
        active_ids = {entry["media_id"] for entry in drafts}
        if not all(isinstance(value, str) and value for value in active_ids):
            return
    except WorkflowCancelled:
        raise
    except (KeyError, TypeError):
        logger.info("云端记录缺少可比对的草稿 ID，保留本地历史")
        return
    except Exception as exc:
        logger.warning("云端历史快照不可用，保留本地状态: {}", exc)
        return

    missing = [(pk, mid) for pk, mid in candidates if mid and mid not in active_ids]
    if not missing:
        return
    check_cancelled()
    with db_manager.session_factory.begin() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        for article_id, media_id in missing:
            rec = session.query(ArticleHistory).filter(
                ArticleHistory.id == article_id, ArticleHistory.media_id == media_id, ArticleHistory.wechat_app_id == account,
                ArticleHistory.success_status.is_(True), ArticleHistory.status.in_(("DRAFT", "APPROVED")),
            ).one_or_none()
            if rec is None:
                continue
            if rec.delivery_attempt_id:
                try:
                    receipt = publisher.journal.get(account, rec.delivery_attempt_id)
                except KeyError:
                    continue
                if receipt.get("media_id") != media_id or receipt["status"] not in ("DRAFT", "ARCHIVED"):
                    continue
                if rec.source_type == "aikepu":
                    from core.aikepu.skill_tree import remove_confirmed_draft
                    extra = receipt["context"].get("workflow_record", {}).get("extra", {})
                    if extra.get("tree_name") and extra.get("node_id"):
                        remove_confirmed_draft(extra["tree_name"], extra["node_id"], media_id)
                publisher.journal.retire_confirmed_draft(account, rec.delivery_attempt_id, media_id)
            rec.success_status = False
            rec.is_published = False
            rec.status = "FAILED"
            rec.error_log = "完整云端记录中已无该文章"
            if rec.source_type == "github":
                session.flush()
                _release_unowned_repos(session, article_id)
    publisher._draft_titles_cache = None


def run_main(task_type="hotspots", override_node_id=None):
    from core.hotspots.collector import reset_source_health

    started_at = datetime.now(timezone.utc).isoformat()
    try:
        workflows = {"hotspots": run_hotspots_workflow, "github": run_github_workflow,
                     "aikepu": run_aikepu_workflow, "daily_knowledge": run_daily_knowledge_workflow}
        if task_type not in workflows:
            raise ValueError(f"未知的任务类型: {task_type}")
        check_cancelled()
        _validate_config()
        _print_banner()
        cleanup_old_assets("assets")
        reset_source_health()
        publisher = WeChatPublisher(config.WECHAT_APP_ID, config.WECHAT_APP_SECRET)
        if not publisher.access_token:
            raise RuntimeError("微信发布组件初始化失败，请检查公众号凭证配置")
        sync_local_history_with_wechat(publisher)
        check_cancelled()
        kwargs = {"override_node_id": override_node_id} if task_type == "aikepu" and override_node_id is not None else {}
        result = workflows[task_type](publisher, **kwargs)
        if not isinstance(result, WorkflowOutcome):
            raise RuntimeError(f"{task_type} 未返回 WorkflowOutcome")
        result.started_at = started_at
        result.finished_at = datetime.now(timezone.utc).isoformat()
        return result
    except WorkflowCancelled as exc:
        return WorkflowOutcome(task_type=task_type, status="cancelled", started_at=started_at, summary=str(exc))
    except Exception as exc:
        logger.exception("任务执行失败: {}", exc)
        return WorkflowOutcome(task_type=task_type, status="failed", started_at=started_at,
                               error=str(exc), summary="任务执行失败")
    finally:
        db_manager.remove_session()


__all__ = ["run_main"]
