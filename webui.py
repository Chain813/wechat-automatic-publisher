import os
import threading
from flask import Flask, render_template, jsonify, request
from core.shared.runtime import configure_runtime, log_queue
from core.engine import run_main
import queue
import sys
from dotenv import load_dotenv, set_key
from loguru import logger

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor as APSThreadPoolExecutor
from apscheduler.triggers.cron import CronTrigger
from core.db.manager import db_manager

app = Flask(__name__)
_start_lock = threading.Lock()

# ---- APScheduler 配置 ----
_scheduler_jobstores = {
    'default': SQLAlchemyJobStore(engine=db_manager.engine)
}
_scheduler_executors = {
    'default': APSThreadPoolExecutor(2)
}
_scheduler_defaults = {
    'coalesce': True,
    'max_instances': 1
}
scheduler = BackgroundScheduler(
    jobstores=_scheduler_jobstores, 
    executors=_scheduler_executors, 
    job_defaults=_scheduler_defaults
)
scheduler.start()

# ---- 云端模式配置 ----
CLOUD_MODE = os.getenv("CLOUD_MODE", "").strip() == "1"
WEBUI_TOKEN = os.getenv("WEBUI_TOKEN", "").strip()


# ---- Token 认证中间件（云端模式） ----
@app.before_request
def _check_auth():
    """云端模式下的简单 token 认证"""
    if not CLOUD_MODE or not WEBUI_TOKEN:
        return None  # 本地模式或无 token → 跳过认证

    # 允许健康检查和 API status（用于 Render 健康检查 + GitHub Actions 触发）
    if request.path == "/api/status":
        return None

    # /api/start 允许通过 ?token=xxx 参数验证（GitHub Actions curl 用）
    if request.path == "/api/start" and request.method == "POST":
        token = request.args.get("token", "")
        if token == WEBUI_TOKEN:
            return None

    # 其他页面检查 Cookie 或 Authorization header
    token = request.cookies.get("aw_token", "")
    if not token:
        token = request.headers.get("Authorization", "").replace("Bearer ", "")

    if token != WEBUI_TOKEN:
        # 如果是浏览器请求 / 且无 token，显示登录页
        if request.path == "/" and request.method == "GET":
            return render_template("login.html") if os.path.exists("templates/login.html") else ("🔒 AutoWeChat Cloud — 需要 token 认证", 401)
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    return None


class ProcessState:
    is_running = False
    is_paused = False
    thread = None
    _lock = threading.Lock()

    @classmethod
    def set_running(cls, value):
        with cls._lock:
            cls.is_running = value

    @classmethod
    def set_paused(cls, value):
        with cls._lock:
            cls.is_paused = value

    @classmethod
    def get_state(cls):
        with cls._lock:
            return cls.is_running, cls.is_paused


class PrintRedirector:
    def __init__(self):
        self.terminal = sys.stdout

    def write(self, message):
        self.terminal.write(message)
        if message.strip():
            try:
                log_queue.put_nowait(f"PRINT | {message.strip()}\n")
            except queue.Full:
                logger.warning("日志队列已满，丢弃消息")

    def flush(self):
        self.terminal.flush()


def run_workflow_thread(task_type="hotspots"):
    from core.shared.runtime import cancel_event, pause_event, WorkflowCancelled
    ProcessState.set_running(True)
    ProcessState.set_paused(False)
    cancel_event.clear()
    pause_event.set()  # 确保开始时是运行状态
    old_stdout = sys.stdout
    sys.stdout = PrintRedirector()
    try:
        run_main(task_type=task_type)
    except WorkflowCancelled:
        try:
            log_queue.put_nowait("SYSTEM | ⛔ 任务已被用户中断。\n")
        except queue.Full:
            logger.warning("日志队列已满，丢弃消息")
    except Exception as e:
        logger.error(f"Workflow failed: {e}")
        try:
            log_queue.put_nowait(f"SYSTEM | Workflow crashed: {e}\n")
        except queue.Full:
            logger.warning("日志队列已满，丢弃消息")
    finally:
        sys.stdout = old_stdout
        ProcessState.set_running(False)
        cancel_event.clear()
        try:
            log_queue.put_nowait("SYSTEM | Workflow finished.\n")
        except queue.Full:
            logger.warning("日志队列已满，丢弃消息")


def _mask_secret(value):
    """Mask sensitive string, show only first 4 and last 4 chars"""
    if not value or len(value) <= 8:
        return "****" if value else ""
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


@app.route('/')
def index():
    return render_template('index.html')


# ---- 定时调度 API ----

@app.route('/api/schedule/jobs', methods=['GET'])
def get_scheduled_jobs():
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "task_type": job.kwargs.get("task_type", ""),
            "next_run_time": job.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if job.next_run_time else None,
            "status": "paused" if job.next_run_time is None else "active"
        })
    return jsonify({"status": "success", "jobs": jobs})

@app.route('/api/schedule/add', methods=['POST'])
def add_scheduled_job():
    data = request.json or {}
    task_type = data.get("task_type")
    cron_expr = data.get("cron_expr")  # e.g., "0 8 * * *" (minute, hour, day, month, day_of_week)
    
    if not task_type or not cron_expr:
        return jsonify({"status": "error", "message": "Missing task_type or cron_expr"}), 400
        
    try:
        trigger = CronTrigger.from_crontab(cron_expr)
        # 传递 run_workflow_thread 而不是 run_main，以保证其日志和状态被正确捕获
        job = scheduler.add_job(
            func=run_workflow_thread,
            trigger=trigger,
            kwargs={"task_type": task_type},
            name=f"Schedule_{task_type}_{cron_expr}",
            replace_existing=False
        )
        return jsonify({"status": "success", "job_id": job.id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/api/schedule/remove', methods=['POST'])
def remove_scheduled_job():
    data = request.json or {}
    job_id = data.get("job_id")
    if not job_id:
        return jsonify({"status": "error", "message": "Missing job_id"}), 400
        
    try:
        scheduler.remove_job(job_id)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/api/schedule/pause', methods=['POST'])
def pause_scheduled_job():
    data = request.json or {}
    job_id = data.get("job_id")
    if not job_id:
        return jsonify({"status": "error", "message": "Missing job_id"}), 400
    try:
        scheduler.pause_job(job_id)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/api/schedule/resume', methods=['POST'])
def resume_scheduled_job():
    data = request.json or {}
    job_id = data.get("job_id")
    if not job_id:
        return jsonify({"status": "error", "message": "Missing job_id"}), 400
    try:
        scheduler.resume_job(job_id)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400




@app.route('/api/start', methods=['POST'])
def start_process():
    with _start_lock:
        if ProcessState.is_running:
            return jsonify({"status": "error", "message": "Task already running"}), 400
        data = request.json or {}
        task_type = data.get("task_type", "hotspots")
        if task_type not in ("hotspots", "github", "aikepu"):
            return jsonify({"status": "error", "message": f"Invalid task_type: {task_type}"}), 400
        ProcessState.thread = threading.Thread(target=run_workflow_thread, args=(task_type,), daemon=True)
        ProcessState.thread.start()
    return jsonify({"status": "success", "message": "Workflow started"})


@app.route('/api/stop', methods=['POST'])
def stop_process():
    if not ProcessState.is_running:
        return jsonify({"status": "error", "message": "No task running"}), 400
    from core.shared.runtime import cancel_event, pause_event
    pause_event.set()  # 如果是在暂停状态下停止，先释放 wait
    cancel_event.set()
    try:
        log_queue.put_nowait("SYSTEM | User requested stop...\n")
    except queue.Full:
        logger.warning("日志队列已满，丢弃消息")
    return jsonify({"status": "success", "message": "Stop signal sent"})


@app.route('/api/pause', methods=['POST'])
def pause_process():
    if not ProcessState.is_running:
        return jsonify({"status": "error", "message": "No task running"}), 400
    from core.shared.runtime import pause_event
    pause_event.clear()  # 设为暂停状态
    ProcessState.set_paused(True)
    try:
        log_queue.put_nowait("SYSTEM | ⏸️ User requested pause...\n")
    except queue.Full:
        logger.warning("日志队列已满，丢弃消息")
    return jsonify({"status": "success", "message": "Paused"})


@app.route('/api/resume', methods=['POST'])
def resume_process():
    if not ProcessState.is_running:
        return jsonify({"status": "error", "message": "No task running"}), 400
    from core.shared.runtime import pause_event
    pause_event.set()  # 恢复运行
    ProcessState.set_paused(False)
    try:
        log_queue.put_nowait("SYSTEM | ▶️ User requested resume...\n")
    except queue.Full:
        logger.warning("日志队列已满，丢弃消息")
    return jsonify({"status": "success", "message": "Resumed"})


@app.route('/api/status', methods=['GET'])
def get_status():
    logs = []
    while True:
        try:
            msg = log_queue.get_nowait()
            logs.append(msg)
        except queue.Empty:
            break
    return jsonify({
        "is_running": ProcessState.is_running,
        "is_paused": ProcessState.is_paused,
        "logs": logs
    })


_publisher_instance = None
_publisher_lock = threading.Lock()

def _get_publisher():
    global _publisher_instance
    if _publisher_instance is None:
        with _publisher_lock:
            if _publisher_instance is None:
                from config import WECHAT_APP_ID, WECHAT_APP_SECRET
                from core.shared.publisher import WeChatPublisher
                _publisher_instance = WeChatPublisher(WECHAT_APP_ID, WECHAT_APP_SECRET)
    return _publisher_instance


@app.route('/api/config', methods=['GET', 'POST'])
def handle_config():
    env_file = '.env'
    if request.method == 'GET':
        load_dotenv(env_file, override=True)
        return jsonify({
            "WECHAT_APP_ID": os.getenv("WECHAT_APP_ID", ""),
            "WECHAT_APP_SECRET": _mask_secret(os.getenv("WECHAT_APP_SECRET", "")),
            "LLM_API_KEY": _mask_secret(os.getenv("LLM_API_KEY", "")),
            "QYWECHAT_WEBHOOK": os.getenv("QYWECHAT_WEBHOOK", ""),
            "LLM_MODEL": os.getenv("LLM_MODEL", "deepseek-v4-pro"),
            "GEMINI_API_KEY": _mask_secret(os.getenv("GEMINI_API_KEY", "")),
            "DIAGRAM_PARALLEL_WORKERS": os.getenv("DIAGRAM_PARALLEL_WORKERS", "5"),
        })
    else:
        data = request.json
        if not isinstance(data, dict):
            return jsonify({"status": "error", "message": "Invalid request body"}), 400
        if not os.path.exists(env_file):
            import pathlib
            pathlib.Path(env_file).touch()
        for key in ["WECHAT_APP_ID", "WECHAT_APP_SECRET", "LLM_API_KEY",
                     "QYWECHAT_WEBHOOK", "LLM_MODEL", "GEMINI_API_KEY",
                     "DIAGRAM_PARALLEL_WORKERS"]:
            if key in data and "*" not in str(data[key]):
                value = str(data[key]).strip()
                if len(value) > 500 or '\n' in value or '\r' in value:
                    continue  # 防止 .env 注入 and 异常大值
                set_key(env_file, key, value)
        load_dotenv(env_file, override=True)
        
        # 重置全局缓存以使新配置生效
        global _publisher_instance
        _publisher_instance = None
        
        return jsonify({"status": "success", "message": "Config saved"})


@app.route('/api/history', methods=['GET'])
def get_history():
    try:
        from core.db.models import ArticleHistory
        import re
        session = db_manager.get_session()
        
        # 读取本地的所有记录
        records = session.query(ArticleHistory).order_by(ArticleHistory.publish_date.desc(), ArticleHistory.id.desc()).all()
        
        # 获取微信上已发表的标题列表，用来判断是否已发送（即公众号群发出来的意思）
        published_titles = []
        try:
            pub = _get_publisher()
            if pub and pub.access_token:
                published_titles = pub.get_published_titles(count=100)
        except Exception as e:
            logger.warning("获取已发表标题失败: {}", e)

        def clean_t(t):
            return re.sub(r'[^\w\u4e00-\u9fff]', '', t).lower() if t else ""

        published_titles_clean = {clean_t(pt) for pt in published_titles if pt}
        
        data = {}
        for r in records:
            date_str = r.publish_date
            if date_str not in data:
                data[date_str] = {"topics": [], "results": []}
            if r.title not in data[date_str]["topics"]:
                data[date_str]["topics"].append(r.title)
                
            if r.success_status or r.error_log:
                is_published = False
                if r.success_status and r.title:
                    is_published = clean_t(r.title) in published_titles_clean

                import hashlib
                title_hash = hashlib.md5(r.title.encode('utf-8')).hexdigest()
                preview_id = r.media_id if r.success_status else f"fail_{title_hash}"

                data[date_str]["results"].append({
                    "topic": r.title,
                    "success": r.success_status,
                    "is_published": is_published,
                    "draft_id": r.media_id,
                    "preview_id": preview_id,
                    "error": r.error_log,
                    "time": r.created_at.strftime("%H:%M:%S") if r.created_at else ""
                })
        
        return jsonify({"history": data})
    except Exception as e:
        logger.exception("获取历史记录失败: {}", e)
        return jsonify({"history": {}, "error": str(e)})


@app.route('/api/preview/<preview_id>', methods=['GET'])
def preview_draft(preview_id):
    # 1. 尝试从本地 previews 文件夹读取
    local_path = os.path.join("data", "previews", f"{preview_id}.html")
    if os.path.exists(local_path):
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                content = f.read()
            return content
        except Exception as e:
            logger.warning("读取本地预览文件失败: {}", e)

    # 2. 如果本地不存在且不是以 'fail_' 开头，尝试从微信 API 获取（兼容历史已上传草稿）
    if not preview_id.startswith("fail_"):
        try:
            pub = _get_publisher()
            if pub and pub.access_token:
                url = f"https://api.weixin.qq.com/cgi-bin/draft/get?access_token={pub.access_token}"
                res = pub.session.post(url, json={"media_id": preview_id}, timeout=10).json()
                if "news_item" in res and len(res["news_item"]) > 0:
                    item = res["news_item"][0]
                    title = item.get("title", "")
                    body = item.get("content", "")
                    
                    preview_html = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <meta charset="utf-8">
                        <meta name="viewport" content="width=device-width, initial-scale=1.0">
                        <title>{title}</title>
                        <style>
                            body {{
                                font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', 'PingFang SC', 'Microsoft YaHei', Arial, sans-serif;
                                padding: 20px;
                                max-width: 677px;
                                margin: 0 auto;
                                color: #333;
                                line-height: 1.6;
                                background-color: #fff;
                            }}
                            img {{
                                max-width: 100%;
                                height: auto;
                                display: block;
                                margin: 10px auto;
                            }}
                            blockquote {{
                                border-left: 4px solid #ddd;
                                padding-left: 15px;
                                color: #777;
                                margin: 10px 0;
                            }}
                        </style>
                    </head>
                    <body>
                        <h1 style="font-size: 24px; margin-bottom: 20px;">{title}</h1>
                        <div class="content">
                            {body}
                        </div>
                    </body>
                    </html>
                    """
                    # 缓存到本地以便下次快速载入
                    try:
                        os.makedirs(os.path.join("data", "previews"), exist_ok=True)
                        with open(local_path, "w", encoding="utf-8") as f:
                            f.write(preview_html)
                    except Exception:
                        pass
                    return preview_html
        except Exception as e:
            logger.warning("从微信接口获取草稿失败: {}", e)

    return f"<h3>未找到该文章的预览内容</h3><p>可能由于该任务运行在旧版本上（本地未缓存），或者微信端草稿已被群发/发布/删除。</p>", 404


@app.route('/api/sources', methods=['GET'])
def get_sources():
    try:
        from core.hotspots.collector import get_source_health_report
        report = get_source_health_report()
        return jsonify({"sources": report})
    except Exception as e:
        return jsonify({"sources": {}, "error": str(e)})


if __name__ == '__main__':
    configure_runtime()
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)

    # 云端模式：绑 0.0.0.0 + 使用 $PORT
    if CLOUD_MODE:
        host = "0.0.0.0"
        port = int(os.getenv("PORT", "5000"))
        print("☁️  AutoWeChat Cloud Mode")
        print(f"   Listening on: http://0.0.0.0:{port}")
        if WEBUI_TOKEN:
            print("   Token auth: enabled")
    else:
        host = "127.0.0.1"
        port = 5000
        print(f"Web UI started: http://127.0.0.1:{port}")

        # 本地模式：自动打开浏览器
        import webbrowser
        from threading import Timer
        Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()

    app.run(host=host, port=port, debug=False)
