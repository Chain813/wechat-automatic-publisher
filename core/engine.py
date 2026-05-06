import traceback

from config import WECHAT_APP_ID, WECHAT_APP_SECRET
from core.shared.publisher import WeChatPublisher
from core.shared.article_utils import _print_banner, cleanup_old_assets
from core.hotspots.workflow import run_hotspots_workflow
from core.github.workflow import run_github_workflow
from utils.image_filter import ollama_startup, ollama_shutdown

def run_main(task_type="hotspots"):
    _print_banner()
    cleanup_old_assets("assets")
    ollama_startup()

    try:
        publisher = WeChatPublisher(WECHAT_APP_ID, WECHAT_APP_SECRET)
        if not publisher.access_token:
            print("❌ 微信发布组件初始化失败，请检查公众号凭证配置。")
            return

        if task_type == "github":
            run_github_workflow(publisher)
            return

        if task_type == "hotspots":
            run_hotspots_workflow(publisher)
            return

        print(f"❌ 未知的任务类型: {task_type}")

    except Exception as exc:
        print(f"\n💥 系统核心崩溃：{exc}")
        traceback.print_exc()
    finally:
        ollama_shutdown()

__all__ = ["run_main"]
