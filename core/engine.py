import traceback

from config import WECHAT_APP_ID, WECHAT_APP_SECRET
from core.shared.publisher import WeChatPublisher
from core.shared.article_utils import _print_banner, cleanup_old_assets
from core.hotspots.workflow import run_hotspots_workflow
from core.github.workflow import run_github_workflow
from utils.image_filter import ollama_startup, ollama_shutdown
from core.shared.runtime import check_cancelled, WorkflowCancelled

def sync_local_history_with_wechat(publisher):
    """
    对比本地记录和微信云端草稿/已发布列表，
    如果发现某篇文章已经在云端被删除，则同步清理本地历史，释放被占用的项目或热点。
    """
    import os
    import json
    from loguru import logger
    
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

    # ---- 1. 同步 Hotspots 历史 ----
    hotspots_file = "hotspots_history.json"
    if os.path.exists(hotspots_file):
        try:
            with open(hotspots_file, "r", encoding="utf-8") as f:
                hotspots_data = json.load(f)
            changed = False
            for date, data in hotspots_data.items():
                if not isinstance(data, dict): continue
                results = data.get("results", [])
                valid_results = []
                date_changed = False
                for res in results:
                    topic = res.get("topic")
                    success = res.get("success", False)
                    if success and topic:
                        if is_title_active(topic):
                            valid_results.append(res)
                        else:
                            date_changed = True
                            print(f"  🗑️ 云端已删除，本地释放热点: {topic}")
                    else:
                        valid_results.append(res)
                if date_changed:
                    changed = True
                    data["results"] = valid_results
            if changed:
                with open(hotspots_file, "w", encoding="utf-8") as f:
                    json.dump(hotspots_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"同步 hotspots 历史失败: {e}")

    # ---- 2. 同步 GitHub 历史 ----
    github_records_file = "github_publish_records.json"
    github_history_file = "github_history.json"
    if os.path.exists(github_records_file) and os.path.exists(github_history_file):
        try:
            with open(github_records_file, "r", encoding="utf-8") as f:
                records = json.load(f)
            with open(github_history_file, "r", encoding="utf-8") as f:
                history_repos = json.load(f)
            
            valid_records = []
            repos_to_remove = set()
            for rec in records:
                title = rec.get("title", "")
                repos = rec.get("repos", [])
                if is_title_active(title):
                    valid_records.append(rec)
                else:
                    print(f"  🗑️ 云端已删除，本地释放开源项目: {repos}")
                    repos_to_remove.update(repos)

            changed = bool(repos_to_remove)
            if changed:
                history_repos = [r for r in history_repos if r not in repos_to_remove]
                with open(github_records_file, "w", encoding="utf-8") as f:
                    json.dump(valid_records, f, ensure_ascii=False, indent=2)
                with open(github_history_file, "w", encoding="utf-8") as f:
                    json.dump(history_repos, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"同步 GitHub 历史失败: {e}")


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

        print(f"❌ 未知的任务类型: {task_type}")

    except WorkflowCancelled:
        logger.warning("任务已被用户中断")
        raise
    except Exception as exc:
        logger.exception("系统核心崩溃: {}", exc)
    finally:
        ollama_shutdown()

__all__ = ["run_main"]
