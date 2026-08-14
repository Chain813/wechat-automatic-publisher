from loguru import logger

from config import WECHAT_APP_ID, WECHAT_APP_SECRET
from core.shared.publisher import WeChatPublisher
from core.shared.article_utils import _print_banner, cleanup_old_assets
from core.hotspots.workflow import run_hotspots_workflow
from core.github.workflow import run_github_workflow
from core.aikepu.workflow import run_aikepu_workflow
from daily_knowledge.workflow import run_daily_knowledge_workflow
from utils.image_filter import ollama_startup, ollama_shutdown
from core.shared.runtime import check_cancelled, WorkflowCancelled

def sync_local_history_with_wechat(publisher):
    """
    对比本地 SQLite 记录和微信云端草稿/已发布列表，
    如果发现某篇文章已经在云端被删除，则同步清理本地 SQLite 历史，释放被占用的项目或热点。
    """
    from loguru import logger
    from core.db.manager import db_manager
    from core.db.models import ArticleHistory
    
    print("\n🔄 正在同步云端状态，检测是否有推文被删除...")
    try:
        active_titles = publisher.get_all_active_titles()
    except Exception as e:
        logger.warning(f"获取微信状态失败，跳过历史同步: {e}")
        return

    def is_title_active(title):
        for act in active_titles:
            if title in act or act in title:
                return True
        return False

    try:
        session = db_manager.get_session()
        # 查询所有成功发布的本地文章记录（包括 hotspots, github, aikepu）
        records = session.query(ArticleHistory).filter(
            ArticleHistory.success_status.is_(True),
            ArticleHistory.source_type.in_(["hotspots", "github", "aikepu"])
        ).all()

        changed = False
        for rec in records:
            if not is_title_active(rec.title):
                print(f"  🗑️ 云端已删除，本地释放文章: {rec.title}")
                rec.success_status = False
                rec.is_published = False
                changed = True
                
                # 如果是 AI 科普推文被删除，自动重置并回滚技能树对应节点
                if rec.source_type == "aikepu":
                    try:
                        from core.aikepu.skill_tree import remove_node_from_history
                        remove_node_from_history(title=rec.title)
                        print(f"    🔄 已同步重置技能树对应节点历史: {rec.title}")
                    except Exception as ak_err:
                        logger.warning("同步重置 AI 科普技能节点失败: {}", ak_err)

                # 如果是 GitHub 文章，同时释放当天记录 of github_repo 库历史
                if rec.source_type == "github":
                    repo_records = session.query(ArticleHistory).filter(
                        ArticleHistory.source_type == "github_repo",
                        ArticleHistory.publish_date == rec.publish_date,
                        ArticleHistory.success_status.is_(True)
                    ).all()
                    for r_rec in repo_records:
                        print(f"    🗑️ 同时释放当天开源项目历史: {r_rec.title}")
                        r_rec.success_status = False
                        r_rec.is_published = False
        
        if changed:
            session.commit()
            # 同步重置发布器的本地标题缓存，使其在接下来的运行中生效
            publisher._draft_titles_cache = None
            print("✅ 本地 SQLite 历史同步完成。")
        else:
            print("✅ 未检测到被删除的云端推文，无需同步。")
            
        db_manager.remove_session()
    except Exception as e:
        logger.exception("同步云端状态至本地 SQLite 失败: {}", e)


def run_main(task_type="hotspots"):
    from core.hotspots.collector import reset_source_health

    _print_banner()
    cleanup_old_assets("assets")
    reset_source_health()

    try:
        ollama_startup()
        publisher = WeChatPublisher(WECHAT_APP_ID, WECHAT_APP_SECRET)
        if not publisher.access_token:
            print("❌ 微信发布组件初始化失败，请检查公众号凭证配置。")
            return

        check_cancelled()
        
        sync_local_history_with_wechat(publisher)

        if task_type == "github":
            run_github_workflow(publisher)
            return

        if task_type == "hotspots":
            run_hotspots_workflow(publisher)
            return

        if task_type == "aikepu":
            run_aikepu_workflow(publisher)
            return

        if task_type == "daily_knowledge":
            run_daily_knowledge_workflow(publisher)
            return

        print(f"❌ 未知的任务类型: {task_type}")

    except WorkflowCancelled:
        logger.warning("任务已被用户中断")
        raise
    except Exception as exc:
        logger.exception("系统核心崩溃: {}", exc)
    finally:
        ollama_shutdown()

__all__ = ["run_main"]
