import os
import re
import hmac
import html as _html
import inspect
import ipaddress
import json as _json
import socket
import threading
import uuid
from collections import deque
from datetime import datetime
from urllib.parse import unquote, urlparse
from flask import Flask, render_template, jsonify, request, redirect
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
app.config['TEMPLATES_AUTO_RELOAD'] = True
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


def _extract_request_token() -> str:
    raw_cookie = request.cookies.get("aw_token", "")
    if raw_cookie:
        return raw_cookie
    auth_header = request.headers.get("Authorization", "")
    return auth_header.replace("Bearer ", "").strip()


def _token_matches(candidate: str) -> bool:
    if not WEBUI_TOKEN.strip() or not candidate:
        return False
    decoded = unquote(candidate)
    return hmac.compare_digest(candidate, WEBUI_TOKEN) or hmac.compare_digest(decoded, WEBUI_TOKEN)


def _render_login_page():
    if os.path.exists("templates/login.html"):
        return render_template("login.html")
    return ("[Security] AutoWeChat Cloud — 需要 token 认证", 401)


@app.after_request
def _apply_cache_headers(response):
    mimetype = (response.mimetype or "").lower()
    if request.path in ("/", "/login") or request.path.startswith("/api/") or mimetype == "text/html":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ---- Token 认证中间件（云端模式） ----
@app.before_request
def _check_auth():
    """云端模式下的简单 token 认证"""
    if not CLOUD_MODE:
        return None

    # 允许健康检查和 API status（用于 Render 健康检查 + GitHub Actions 触发）
    if request.path == "/api/status":
        return None

    # 静态资源与登录页本身无需认证
    if request.path.startswith("/static/"):
        return None
    if request.path == "/login" and request.method in ("GET", "HEAD"):
        return None

    if not WEBUI_TOKEN.strip():
        return jsonify({"status": "error", "message": "Cloud authentication is not configured"}), 503

    # /api/start 允许通过 ?token=xxx 参数验证（GitHub Actions curl 用）
    if request.path == "/api/start" and request.method == "POST":
        token = request.args.get("token", "")
        if _token_matches(token):
            return None

    # 其他页面检查 Cookie 或 Authorization header
    if not _token_matches(_extract_request_token()):
        # 如果是浏览器请求 / 且无 token，显示登录页
        if request.path == "/" and request.method in ("GET", "HEAD"):
            return _render_login_page()
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    return None


VALID_TASK_TYPES = ("hotspots", "github", "aikepu", "daily_knowledge")
_SECRET_CONFIG_KEYS = frozenset({
    "WECHAT_APP_SECRET",
    "LLM_API_KEY",
    "DASHSCOPE_API_KEY",
    "GEMINI_API_KEY",
    "GEMINI_API_KEYS",
    "GEMINI_PROXY_TOKEN",
    "GITHUB_TOKEN",
    "LLM_API_KEYS",
    "DASHSCOPE_API_KEYS",
})


class _WebUILogBuffer:
    """线程安全的非破坏性环形日志缓冲（兼容尚未接入 runtime.LogBuffer 的阶段）"""

    def __init__(self, maxlen: int = 5000):
        self._lock = threading.Lock()
        self._entries = deque(maxlen=maxlen)
        self._seq = 0

    def append(self, message: str):
        text = str(message)
        with self._lock:
            self._seq += 1
            self._entries.append((self._seq, text))

    def sync_from_queue(self):
        drained = []
        while True:
            try:
                drained.append(log_queue.get_nowait())
            except queue.Empty:
                break
        if drained:
            with self._lock:
                for msg in drained:
                    self._seq += 1
                    self._entries.append((self._seq, str(msg)))

    def read_since(self, since=0):
        self.sync_from_queue()
        with self._lock:
            if since is None:
                logs = [msg for _, msg in self._entries]
            else:
                logs = [msg for seq, msg in self._entries if seq > since]
            return logs, self._seq

    get_since = read_since


_fallback_log_buffer = _WebUILogBuffer(maxlen=5000)


def _get_log_buffer():
    import core.shared.runtime as _rt
    runtime_buf = getattr(_rt, "log_buffer", None)
    if runtime_buf is not None and (hasattr(runtime_buf, "read_since") or hasattr(runtime_buf, "get_since")):
        return runtime_buf
    return _fallback_log_buffer


def _read_log_buffer_since(buf, since=0):
    if hasattr(buf, "read_since"):
        return buf.read_since(since)
    return buf.get_since(since)


def _append_webui_log(message: str):
    try:
        log_queue.put_nowait(message)
        return
    except queue.Full:
        logger.warning("日志队列已满，丢弃消息")
        return
    except Exception:
        pass
    buf = _get_log_buffer()
    if hasattr(buf, "put_nowait"):
        buf.put_nowait(message)
    elif hasattr(buf, "append"):
        buf.append(message)


def _is_authenticated_request() -> bool:
    if not CLOUD_MODE:
        return True
    return _token_matches(_extract_request_token())


def _is_safe_public_url(url: str) -> bool:
    """校验 URL 仅指向公网 HTTP/HTTPS 主机，阻断内网/回环/元数据 SSRF。"""
    if not isinstance(url, str):
        return False
    raw = url.strip()
    if not raw or len(raw) > 2048:
        return False
    try:
        parsed = urlparse(raw)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host or host in ("localhost", "localhost.localdomain") or host.endswith(".local"):
        return False

    def _is_blocked_ip(ip_obj) -> bool:
        return bool(
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        )

    try:
        ip_literal = ipaddress.ip_address(host)
        return not _is_blocked_ip(ip_literal)
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip_obj = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if _is_blocked_ip(ip_obj):
            return False
    return True


def _normalize_workflow_outcome(task_type: str, outcome, started_at: str, error: str = "") -> dict:
    finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    base = {
        "run_id": uuid.uuid4().hex[:12],
        "task_type": task_type,
        "status": "success",
        "attempted": 0,
        "succeeded": 0,
        "failed": 0,
        "uncertain": 0,
        "skipped": 0,
        "summary": "",
        "error": error or "",
        "started_at": started_at,
        "finished_at": finished_at,
    }
    if outcome is None:
        if error:
            base["status"] = "failed"
        return base
    if isinstance(outcome, bool):
        base["status"] = "success" if outcome else "failed"
        return base
    to_dict_fn = getattr(outcome, "to_dict", None)
    if callable(to_dict_fn):
        outcome_dict = to_dict_fn()
        if isinstance(outcome_dict, dict):
            outcome = outcome_dict
    if isinstance(outcome, dict):
        merged = dict(base)
        for key, val in outcome.items():
            if val is not None:
                merged[key] = val
        return merged
    for key in ("run_id", "task_type", "status", "attempted", "succeeded", "failed", "uncertain", "skipped", "summary", "error", "started_at", "finished_at"):
        val = getattr(outcome, key, None)
        if val is not None:
            base[key] = val
    return base


class ProcessState:
    is_running = False
    is_paused = False
    current_task = None
    last_run = None
    thread = None
    _lock = threading.Lock()

    @classmethod
    def set_running(cls, value, task_type=None):
        with cls._lock:
            cls.is_running = value
            if value:
                cls.current_task = task_type
            else:
                cls.current_task = None

    @classmethod
    def set_paused(cls, value):
        with cls._lock:
            cls.is_paused = value

    @classmethod
    def set_last_run(cls, run_data):
        with cls._lock:
            cls.last_run = dict(run_data) if isinstance(run_data, dict) else None

    @classmethod
    def get_last_run(cls):
        with cls._lock:
            return dict(cls.last_run) if isinstance(cls.last_run, dict) else None

    @classmethod
    def get_snapshot(cls):
        with cls._lock:
            return (
                cls.is_running,
                cls.is_paused,
                cls.current_task,
                dict(cls.last_run) if isinstance(cls.last_run, dict) else None,
            )

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
            _append_webui_log(f"PRINT | {message.strip()}\n")

    def flush(self):
        self.terminal.flush()


def run_workflow_thread(task_type="hotspots", override_node_id=None):
    from core.shared.runtime import cancel_event, pause_event, WorkflowCancelled
    with _start_lock:
        if ProcessState.is_running:
            logger.warning("已有任务在运行中，跳过本次触发: {}", task_type)
            return
        ProcessState.set_running(True, task_type=task_type)
        ProcessState.set_paused(False)
    cancel_event.clear()
    pause_event.set()  # 确保开始时是运行状态
    old_stdout = sys.stdout
    sys.stdout = PrintRedirector()
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    outcome_dict = None
    try:
        call_kwargs = {"task_type": task_type}
        if override_node_id is not None:
            try:
                if "override_node_id" in inspect.signature(run_main).parameters:
                    call_kwargs["override_node_id"] = override_node_id
            except (TypeError, ValueError):
                pass
        raw_outcome = run_main(**call_kwargs)
        outcome_dict = _normalize_workflow_outcome(task_type, raw_outcome, started_at)
    except WorkflowCancelled:
        outcome_dict = _normalize_workflow_outcome(
            task_type,
            {"status": "cancelled", "summary": "任务已被用户中断"},
            started_at,
        )
        _append_webui_log("SYSTEM | [ABORT] 任务已被用户中断。\n")
    except Exception as e:
        logger.error(f"Workflow failed: {e}")
        outcome_dict = _normalize_workflow_outcome(
            task_type,
            {"status": "failed", "summary": f"工作流异常终止: {e}", "error": str(e)},
            started_at,
            error=str(e),
        )
        _append_webui_log(f"SYSTEM | Workflow crashed: {e}\n")
    finally:
        sys.stdout = old_stdout
        if outcome_dict is not None:
            ProcessState.set_last_run(outcome_dict)
        ProcessState.set_paused(False)
        ProcessState.set_running(False)
        cancel_event.clear()
        final_status = (outcome_dict or {}).get("status", "finished")
        _append_webui_log(f"SYSTEM | Workflow finished (status={final_status}).\n")


def _mask_secret(value):
    """Mask sensitive string, show only first 4 and last 4 chars"""
    if not value or len(value) <= 8:
        return "****" if value else ""
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/login', methods=['GET', 'HEAD'])
def login_page():
    if not CLOUD_MODE or _token_matches(_extract_request_token()):
        return redirect('/')
    return _render_login_page()


# ---- 定时调度 API ----

def _extract_cron_expr(job):
    """从 APScheduler Job 提取 5 段 cron 表达式（回退解析 job.name）。"""
    trigger = getattr(job, "trigger", None)
    if trigger is not None and hasattr(trigger, "fields"):
        try:
            field_map = {f.name: str(f) for f in trigger.fields}
            parts = [
                field_map.get("minute", "*"),
                field_map.get("hour", "*"),
                field_map.get("day", "*"),
                field_map.get("month", "*"),
                field_map.get("day_of_week", "*"),
            ]
            return " ".join(parts)
        except Exception:
            pass
    name = str(getattr(job, "name", "") or "")
    m = re.match(r"^Schedule_[a-zA-Z0-9_]+_(.+)$", name)
    if m:
        return m.group(1).strip()
    return ""


@app.route('/api/schedule/jobs', methods=['GET'])
def get_scheduled_jobs():
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "task_type": job.kwargs.get("task_type", ""),
            "cron_expr": _extract_cron_expr(job),
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
    if task_type not in VALID_TASK_TYPES:
        return jsonify({"status": "error", "message": f"Invalid task_type: {task_type}"}), 400

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
        if task_type not in VALID_TASK_TYPES:
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
    _append_webui_log("SYSTEM | User requested stop...\n")
    return jsonify({"status": "success", "message": "Stop signal sent"})


@app.route('/api/pause', methods=['POST'])
def pause_process():
    if not ProcessState.is_running:
        return jsonify({"status": "error", "message": "No task running"}), 400
    from core.shared.runtime import pause_event
    pause_event.clear()  # 设为暂停状态
    ProcessState.set_paused(True)
    _append_webui_log("SYSTEM | [PAUSE] User requested pause...\n")
    return jsonify({"status": "success", "message": "Paused"})


@app.route('/api/resume', methods=['POST'])
def resume_process():
    if not ProcessState.is_running:
        return jsonify({"status": "error", "message": "No task running"}), 400
    from core.shared.runtime import pause_event
    pause_event.set()  # 恢复运行
    ProcessState.set_paused(False)
    _append_webui_log("SYSTEM | [RESUME] User requested resume...\n")
    return jsonify({"status": "success", "message": "Resumed"})


@app.route('/api/status', methods=['GET'])
def get_status():
    is_running, is_paused, current_task, last_run = ProcessState.get_snapshot()
    # 云端鉴权模式下，未登录探测仅返回最小健康状态，绝不泄漏日志/错误且绝不消费游标缓冲
    if not _is_authenticated_request():
        return jsonify({
            "is_running": is_running,
            "is_paused": is_paused,
            "logs": [],
        })

    buf = _get_log_buffer()
    since_param = request.args.get("since")
    if since_param is not None:
        try:
            since = max(0, int(since_param))
        except (TypeError, ValueError):
            since = 0
        logs, next_cursor = _read_log_buffer_since(buf, since)
    else:
        if hasattr(buf, "drain"):
            logs = buf.drain()
            _, next_cursor = _read_log_buffer_since(buf, 0)
        else:
            logs, next_cursor = _read_log_buffer_since(buf, 0)

    return jsonify({
        "is_running": is_running,
        "is_paused": is_paused,
        "current_task": current_task,
        "last_run": last_run,
        "logs": logs,
        "next_cursor": next_cursor,
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


_default_get_publisher = _get_publisher


class _LocalDeliveryAccessor:
    """纯本地 DeliveryJournal 读写适配器：已知 receipt 写回与待处理列表查询绝不触发微信网络请求。"""

    def __init__(self, app_id: str, journal=None):
        from core.shared.delivery_journal import DeliveryJournal
        self.app_id = app_id
        self.journal = journal if journal is not None else DeliveryJournal()

    def pending_deliveries(self):
        return self.journal.pending(self.app_id)

    def mark_delivery_recorded(self, attempt_id):
        return self.journal.recorded(self.app_id, attempt_id)

    def restore_delivery_preview(self, attempt_id):
        from pathlib import Path
        from core.shared.publisher import WeChatPublisher
        row = self.journal.get(self.app_id, attempt_id)
        source = Path("data/previews") / f"attempt_{row['attempt_id']}.html"
        if source.exists() and row.get("media_id"):
            WeChatPublisher._write_preview(row["media_id"], source.read_text(encoding="utf8"))


def _get_delivery_accessor():
    """返回本地幂等 DeliveryJournal 访问器；若 Publisher 已热初始化或处于测试 mock 态则直接复用。"""
    if _publisher_instance is not None or _get_publisher is not _default_get_publisher:
        try:
            pub = _get_publisher()
            if pub is not None:
                return pub
        except Exception:
            pass
    app_id = os.getenv("WECHAT_APP_ID", "").strip()
    if not app_id:
        try:
            import config as _cfg
            app_id = str(getattr(_cfg, "WECHAT_APP_ID", "") or "").strip()
        except Exception:
            app_id = ""
    return _LocalDeliveryAccessor(app_id)


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
            "LLM_MODEL": os.getenv("LLM_MODEL", "deepseek-v4-flash"),
            "DASHSCOPE_API_KEY": _mask_secret(os.getenv("DASHSCOPE_API_KEY", "")),
            "QWEN_IMAGE_MODEL": os.getenv("QWEN_IMAGE_MODEL", "qwen-image-3.0"),
            "QWEN_VL_MODEL": os.getenv("QWEN_VL_MODEL", "qwen-vl-max"),
            "IMAGE_PROVIDER": os.getenv("IMAGE_PROVIDER", "auto"),
            "IMAGE_GEN_MODEL": os.getenv("IMAGE_GEN_MODEL", "gemini-nano-banana-2.1"),
            "GEMINI_API_KEY": _mask_secret(os.getenv("GEMINI_API_KEY", "")),
            "GEMINI_API_BASE": os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com"),
            "GEMINI_IMAGE_SERVICE_URL": os.getenv("GEMINI_IMAGE_SERVICE_URL", ""),
            "GEMINI_PROXY_TOKEN": _mask_secret(os.getenv("GEMINI_PROXY_TOKEN", "")),
            "GEMINI_IMAGE_MODEL": os.getenv("GEMINI_IMAGE_MODEL", "gemini-nano-banana-2.1"),
            "GEMINI_IMAGE_SIZE": os.getenv("GEMINI_IMAGE_SIZE", "1K"),
            "DIAGRAM_PARALLEL_WORKERS": os.getenv("DIAGRAM_PARALLEL_WORKERS", "5"),
            "MAX_TOPICS_PER_RUN": os.getenv("MAX_TOPICS_PER_RUN", "1"),
            "MAX_AI_IMAGES_PER_ARTICLE": os.getenv("MAX_AI_IMAGES_PER_ARTICLE", "1"),
            "QWEN_IMAGE_DAILY_LIMIT": os.getenv("QWEN_IMAGE_DAILY_LIMIT", "6"),
        })
    else:
        data = request.json
        if not isinstance(data, dict):
            return jsonify({"status": "error", "message": "Invalid request body"}), 400
        if not os.path.exists(env_file):
            import pathlib
            pathlib.Path(env_file).touch()
        for key in ["WECHAT_APP_ID", "WECHAT_APP_SECRET", "LLM_API_KEY",
                     "QYWECHAT_WEBHOOK", "LLM_MODEL", "DASHSCOPE_API_KEY",
                     "QWEN_IMAGE_MODEL", "QWEN_IMAGE_REDRAW_MODEL", "QWEN_VL_MODEL",
                     "IMAGE_PROVIDER", "IMAGE_GEN_MODEL", "GEMINI_API_KEY",
                     "GEMINI_API_BASE", "GEMINI_IMAGE_SERVICE_URL", "GEMINI_PROXY_TOKEN", "GEMINI_IMAGE_MODEL",
                     "GEMINI_IMAGE_SIZE", "DIAGRAM_PARALLEL_WORKERS",
                     "MAX_TOPICS_PER_RUN", "MAX_AI_IMAGES_PER_ARTICLE", "QWEN_IMAGE_DAILY_LIMIT",
                     "GITHUB_TOKEN", "LLM_BASE_URL", "ENABLE_FACT_SEARCH",
                     "BRAND_NAME", "ARTICLE_AUTHOR"]:
            if key not in data:
                continue
            raw_val = str(data[key])
            if key in _SECRET_CONFIG_KEYS and "*" in raw_val:
                continue
            value = raw_val.strip()
            if len(value) > 500 or '\n' in value or '\r' in value:
                continue  # 防止 .env 注入与异常大值
            if key == "IMAGE_PROVIDER":
                value = value.lower()
                if value not in ("auto", "gemini", "qwen"):
                    value = "auto"
            elif key == "GEMINI_IMAGE_SIZE":
                value = value.upper()
                if value not in ("1K", "2K", "4K"):
                    value = "1K"
            set_key(env_file, key, value)
        load_dotenv(env_file, override=True)

        # 重置全局缓存以使新配置生效
        global _publisher_instance
        _publisher_instance = None

        try:
            import config
            config.WECHAT_APP_ID = os.getenv("WECHAT_APP_ID", "")
            config.WECHAT_APP_SECRET = os.getenv("WECHAT_APP_SECRET", "")
            config.LLM_API_KEY = os.getenv("LLM_API_KEY", "")
            config.DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
            if hasattr(config, "QWEN_IMAGE_API_KEY"):
                config.QWEN_IMAGE_API_KEY = os.getenv("QWEN_IMAGE_API_KEY", "") or config.DASHSCOPE_API_KEY
            if hasattr(config, "LLM_API_KEYS"):
                llm_keys_raw = os.getenv("LLM_API_KEYS", "")
                parsed_llm_keys = [k.strip() for k in llm_keys_raw.split(",") if k.strip()]
                if not parsed_llm_keys and config.LLM_API_KEY:
                    parsed_llm_keys = [config.LLM_API_KEY]
                config.LLM_API_KEYS = parsed_llm_keys
            if hasattr(config, "DASHSCOPE_API_KEYS"):
                ds_keys_raw = os.getenv("DASHSCOPE_API_KEYS", "")
                parsed_ds_keys = [k.strip() for k in ds_keys_raw.split(",") if k.strip()]
                if not parsed_ds_keys and config.DASHSCOPE_API_KEY:
                    parsed_ds_keys = [config.DASHSCOPE_API_KEY]
                config.DASHSCOPE_API_KEYS = parsed_ds_keys
            if hasattr(config, "GEMINI_API_KEY"):
                config.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
            if hasattr(config, "GEMINI_API_KEYS"):
                gm_keys_raw = os.getenv("GEMINI_API_KEYS", "")
                parsed_gm_keys = [k.strip() for k in gm_keys_raw.split(",") if k.strip()]
                if not parsed_gm_keys and getattr(config, "GEMINI_API_KEY", ""):
                    parsed_gm_keys = [config.GEMINI_API_KEY]
                config.GEMINI_API_KEYS = parsed_gm_keys
            if hasattr(config, "GEMINI_API_BASE"):
                config.GEMINI_API_BASE = os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com").strip().rstrip("/")
            if hasattr(config, "GEMINI_IMAGE_SERVICE_URL"):
                config.GEMINI_IMAGE_SERVICE_URL = os.getenv("GEMINI_IMAGE_SERVICE_URL", "").strip()
            if hasattr(config, "GEMINI_PROXY_TOKEN"):
                config.GEMINI_PROXY_TOKEN = os.getenv("GEMINI_PROXY_TOKEN", "").strip()
            if hasattr(config, "GEMINI_IMAGE_MODEL"):
                config.GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-nano-banana-2.1").strip()
            if hasattr(config, "GEMINI_IMAGE_SIZE"):
                g_size = os.getenv("GEMINI_IMAGE_SIZE", "1K").strip().upper()
                config.GEMINI_IMAGE_SIZE = g_size if g_size in ("1K", "2K", "4K") else "1K"
            if hasattr(config, "IMAGE_PROVIDER"):
                img_prov = os.getenv("IMAGE_PROVIDER", "auto").strip().lower()
                config.IMAGE_PROVIDER = img_prov if img_prov in ("auto", "gemini", "qwen") else "auto"
            config.QWEN_IMAGE_MODEL = os.getenv("QWEN_IMAGE_MODEL", "qwen-image-3.0")
            config.QWEN_VL_MODEL = os.getenv("QWEN_VL_MODEL", "qwen-vl-max")
            config.QWEN_IMAGE_REDRAW_MODEL = os.getenv("QWEN_IMAGE_REDRAW_MODEL", "qwen-image-3.0-pro")
            config.QYWECHAT_WEBHOOK = os.getenv("QYWECHAT_WEBHOOK", "")
            config.LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")
            config.IMAGE_GEN_MODEL = os.getenv("IMAGE_GEN_MODEL", "gemini-nano-banana-2.1")
            try:
                from utils.image_handler import reset_gemini_key_pool, reset_qwen_key_pool
                reset_gemini_key_pool()
                reset_qwen_key_pool()
            except Exception:
                pass
            config.LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
            config.ENABLE_FACT_SEARCH = os.getenv("ENABLE_FACT_SEARCH", "True").lower() == "true"
            if hasattr(config, "DIAGRAM_PARALLEL_WORKERS"):
                try:
                    config.DIAGRAM_PARALLEL_WORKERS = max(1, min(16, int(os.getenv("DIAGRAM_PARALLEL_WORKERS", "5"))))
                except (TypeError, ValueError):
                    pass
            if hasattr(config, "MAX_TOPICS_PER_RUN"):
                try:
                    config.MAX_TOPICS_PER_RUN = max(1, min(5, int(os.getenv("MAX_TOPICS_PER_RUN", "1"))))
                except (TypeError, ValueError):
                    pass
            if hasattr(config, "MAX_AI_IMAGES_PER_ARTICLE"):
                try:
                    config.MAX_AI_IMAGES_PER_ARTICLE = max(0, min(5, int(os.getenv("MAX_AI_IMAGES_PER_ARTICLE", "1"))))
                except (TypeError, ValueError):
                    pass
            if hasattr(config, "QWEN_IMAGE_DAILY_LIMIT"):
                try:
                    config.QWEN_IMAGE_DAILY_LIMIT = max(0, min(50, int(os.getenv("QWEN_IMAGE_DAILY_LIMIT", "6"))))
                except (TypeError, ValueError):
                    pass
            if hasattr(config, "BRAND_NAME") and os.getenv("BRAND_NAME"):
                config.BRAND_NAME = os.getenv("BRAND_NAME")
            if hasattr(config, "ARTICLE_AUTHOR") and os.getenv("ARTICLE_AUTHOR"):
                config.ARTICLE_AUTHOR = os.getenv("ARTICLE_AUTHOR")
            if hasattr(config, "GITHUB_TOKEN"):
                config.GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

            try:
                from core.shared import searcher as _searcher_mod
                if hasattr(_searcher_mod, "ENABLE_FACT_SEARCH"):
                    _searcher_mod.ENABLE_FACT_SEARCH = config.ENABLE_FACT_SEARCH
            except Exception:
                pass

            try:
                from core.shared.publisher import WeChatPublisher
                reset_tok = getattr(WeChatPublisher, "reset_token_cache", None) or getattr(WeChatPublisher, "clear_token_cache", None)
                if callable(reset_tok):
                    reset_tok()
            except Exception:
                pass

            try:
                from core.shared import llm as _llm_mod
                reset_llm = getattr(_llm_mod, "reset_llm_key_pool", None)
                if callable(reset_llm):
                    reset_llm()
            except Exception:
                pass

            try:
                from utils import image_handler as _img_mod
                reset_qwen = getattr(_img_mod, "reset_qwen_key_pool", None)
                if callable(reset_qwen):
                    reset_qwen()
            except Exception:
                pass

            from core.aikepu.skill_tree import invalidate_published_ids_cache, reset_tree_cache
            invalidate_published_ids_cache()
            reset_tree_cache()
        except Exception as e:
            logger.debug("配置保存刷新依赖配置异常: {}", e)

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
                published_titles = pub.get_published_titles(count=100) or []
        except Exception as e:
            logger.warning("获取已发表标题失败: {}", e)

        def clean_t(t):
            return re.sub(r'[^\w\u4e00-\u9fff]', '', t).lower() if t else ""

        published_titles_clean = {clean_t(pt) for pt in (published_titles or []) if pt}

        # 本地读取当前账号的 DeliveryJournal 待收敛记录（绝不触发额外微信网络调用）
        pending_rows = []
        pending_by_article = {}
        accessor = None
        try:
            accessor = _get_delivery_accessor()
            raw_pending = accessor.pending_deliveries() if callable(getattr(accessor, "pending_deliveries", None)) else []
            if isinstance(raw_pending, list):
                for row in raw_pending:
                    if not isinstance(row, dict):
                        continue
                    ctx = row.get("context") if isinstance(row.get("context"), dict) else {}
                    aid = ctx.get("article_id")
                    op_id = str(row.get("operation_id") or "")
                    if aid is None and op_id.startswith("review_approve:"):
                        try:
                            aid = int(op_id.split(":", 1)[1])
                        except (TypeError, ValueError):
                            aid = None
                    if aid is not None and row.get("attempt_id"):
                        pending_by_article[aid] = row["attempt_id"]
                    pending_rows.append({
                        "attempt_id": row.get("attempt_id"),
                        "operation_id": op_id,
                        "status": row.get("status"),
                        "title": row.get("title"),
                        "media_id": row.get("media_id"),
                        "errmsg": row.get("errmsg"),
                        "article_id": aid,
                    })
        except Exception as pe:
            logger.debug("读取本地 pending_deliveries 失败（忽略）: {}", pe)

        sent_list = []
        unsent_list = []

        history_dict = {}
        for r in records:
            if r.wechat_app_id and r.wechat_app_id != getattr(accessor, "app_id", None):
                continue
            is_published = bool(getattr(r, 'is_published', False))
            if not is_published and r.success_status and r.title:
                is_published = clean_t(r.title) in published_titles_clean

            import hashlib
            title_hash = hashlib.md5(r.title.encode('utf-8')).hexdigest()
            preview_id = r.media_id if r.success_status else f"fail_{title_hash}"

            item_status = getattr(r, 'status', 'PENDING_REVIEW') or 'PENDING_REVIEW'
            has_media = bool(r.media_id)
            attempt_id = (
                getattr(r, 'delivery_attempt_id', None)
                or pending_by_article.get(r.id)
                or _extract_attempt_id_from_error(r.error_log)
            )
            item_data = {
                "id": r.id,
                "topic": r.title,
                "success": bool(r.success_status),
                "is_published": is_published,
                "draft_id": r.media_id,
                "preview_id": preview_id,
                "attempt_id": attempt_id,
                "error": r.error_log,
                "source_type": r.source_type,
                "source_url": getattr(r, 'source_url', None),
                "quality_score": float(getattr(r, 'quality_score', 0.0) or 0.0),
                "status": item_status,
                "can_approve": item_status in ("PENDING_REVIEW", "REJECTED", "FAILED") and not has_media,
                "needs_reconcile": item_status in ("APPROVING", "CLOUD_UNCERTAIN", "DRAFT_PENDING_RECORD"),
                "pending_record": item_status == "DRAFT_PENDING_RECORD",
                "fact_check_result": getattr(r, 'fact_check_result', None),
                "date": r.publish_date,
                "time": r.created_at.strftime("%H:%M:%S") if r.created_at else ""
            }
            
            if r.success_status and is_published:
                sent_list.append(item_data)
            else:
                unsent_list.append(item_data)

            date_str = r.publish_date
            if date_str not in history_dict:
                history_dict[date_str] = {"topics": [], "results": []}
            if r.title not in history_dict[date_str]["topics"]:
                history_dict[date_str]["topics"].append(r.title)
            history_dict[date_str]["results"].append(item_data)

        return jsonify({
            "sent": sent_list,
            "unsent": unsent_list,
            "history": history_dict,
            "pending_deliveries": pending_rows,
        })
    except Exception as e:
        logger.exception("获取历史记录失败: {}", e)
        return jsonify({"sent": [], "unsent": [], "history": {}, "error": str(e)})
    finally:
        db_manager.remove_session()


@app.route('/api/history/mark_published', methods=['POST'])
def mark_published():
    data = request.json or {}
    record_id = data.get("id")
    is_published = data.get("is_published", True)
    if not record_id:
        return jsonify({"status": "error", "message": "缺少文章 ID"}), 400
    try:
        from core.db.models import ArticleHistory
        session = db_manager.get_session()
        record = session.query(ArticleHistory).filter(ArticleHistory.id == record_id).first()
        if not record:
            return jsonify({"status": "error", "message": "记录不存在"}), 404
        record.is_published = is_published
        session.commit()
        return jsonify({"status": "success", "message": "标记更新成功"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        db_manager.remove_session()


_article_locks = {}
_article_locks_guard = threading.Lock()


def _get_article_lock(article_id):
    try:
        key = int(article_id)
    except (TypeError, ValueError):
        key = str(article_id)
    with _article_locks_guard:
        lock = _article_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _article_locks[key] = lock
        return lock


def _parse_aikepu_source_url(source_url):
    """解析 aikepu://tree/<tree>/node/<nid> 或 aikepu://node/<nid> -> (tree_name, node_id)。"""
    from urllib.parse import unquote

    if not source_url:
        return None, ""
    raw = str(source_url).strip()
    m = re.match(r"^aikepu://tree/([^/]+)/node/(.+)$", raw)
    if m:
        return unquote(m.group(1)), unquote(m.group(2))
    if "node/" in raw:
        return None, unquote(raw.split("node/", 1)[-1])
    return None, ""


def _cleanup_pending_records_jsonl(record_id=None, title=None, media_id=None):
    """若存在 data/pending_records.jsonl，则原子移除已补记条目。"""
    pending_path = os.path.join("data", "pending_records.jsonl")
    if not os.path.exists(pending_path):
        return
    try:
        with open(pending_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        kept = []
        changed = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = _json.loads(stripped)
            except Exception:
                kept.append(line)
                continue
            matched = (
                (media_id and obj.get("media_id") == media_id)
                or (record_id is not None and obj.get("article_id") == record_id)
                or (title and obj.get("title") == title)
            )
            if matched:
                changed = True
            else:
                kept.append(line)
        if changed:
            tmp_path = f"{pending_path}.tmp.{uuid.uuid4().hex}"
            with open(tmp_path, "w", encoding="utf-8") as tf:
                tf.writelines(kept)
            os.replace(tmp_path, pending_path)
    except Exception as exc:
        logger.debug("清理 pending_records.jsonl 异常（忽略）: {}", exc)


def _read_pending_repos_from_jsonl(record_id=None, title=None, media_id=None):
    pending_path = os.path.join("data", "pending_records.jsonl")
    if not os.path.exists(pending_path):
        return []
    try:
        with open(pending_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                obj = _json.loads(stripped)
                if (
                    (media_id and obj.get("media_id") == media_id)
                    or (record_id is not None and obj.get("article_id") == record_id)
                    or (title and obj.get("title") == title)
                ):
                    repos = obj.get("repos") or []
                    if isinstance(repos, list):
                        return [r for r in repos if isinstance(r, str) and r]
    except Exception:
        pass
    return []


def _review_operation_id(record_id) -> str:
    """稳定的审核行业务键，用于 DeliveryJournal 跨重试/跨进程去重。"""
    return f"review_approve:{record_id}"


def _extract_attempt_id_from_error(error_log):
    if not error_log:
        return None
    m = re.search(r"\[attempt_id=([A-Za-z0-9_-]+)\]", str(error_log))
    return m.group(1) if m else None


def _format_error_with_attempt(message, attempt_id, has_attempt_column=False):
    text = str(message or "").strip()
    if attempt_id and not has_attempt_column:
        tag = f"[attempt_id={attempt_id}]"
        if tag not in text:
            text = f"{text} {tag}".strip()
    return text or None


def _resolve_attempt_id(record_snapshot, accessor):
    """按发送标识/业务键解析 attempt_id（严禁按标题匹配）。"""
    if record_snapshot:
        col_val = record_snapshot.get("delivery_attempt_id")
        if col_val and str(col_val).strip():
            return str(col_val).strip()
        tag_val = _extract_attempt_id_from_error(record_snapshot.get("error_log"))
        if tag_val:
            return tag_val
    if accessor is not None and callable(getattr(accessor, "pending_deliveries", None)):
        try:
            pending = accessor.pending_deliveries() or []
        except Exception:
            pending = []
        rec_id = record_snapshot.get("id") if record_snapshot else None
        expected_op = _review_operation_id(rec_id) if rec_id is not None else None
        for row in pending:
            if not isinstance(row, dict) or not row.get("attempt_id"):
                continue
            ctx = row.get("context") if isinstance(row.get("context"), dict) else {}
            if expected_op and row.get("operation_id") == expected_op:
                return row["attempt_id"]
            if rec_id is not None and ctx.get("article_id") == rec_id:
                return row["attempt_id"]
    return None


def _mark_journal_recorded_idempotent(accessor, attempt_id, journal_status=None):
    """幂等标记 DeliveryJournal 为已记录（纯本地 SQLite 操作，绝不访问微信）。"""
    if not attempt_id or accessor is None or journal_status == "DRAFT":
        return
    mark_fn = getattr(accessor, "mark_delivery_recorded", None)
    if not callable(mark_fn):
        return
    try:
        mark_fn(attempt_id)
    except KeyError:
        return
    except ValueError:
        # 若 journal 行已是 DRAFT 则视为幂等成功；其他异常向上抛出以保留待补记状态
        journal = getattr(accessor, "journal", None)
        if journal is not None and callable(getattr(journal, "get", None)):
            try:
                cur = journal.get(getattr(accessor, "app_id", ""), attempt_id)
                if isinstance(cur, dict) and cur.get("status") == "DRAFT":
                    return
            except Exception:
                pass
        raise


def _backfill_pending_record(
    record_info,
    media_id,
    accessor=None,
    aikepu_status="draft",
    attempt_id=None,
    journal_status=None,
):
    """已知 receipt 的纯本地幂等补记（技能树 / GitHub 仓库历史 / 本地预览 / DeliveryJournal）。
    绝不向微信发起网络请求；任一核心补记失败时直接抛出异常，由调用方保留 DRAFT_PENDING_RECORD。
    """
    rec_id = record_info.get("id")
    title = record_info.get("title") or ""
    source_type = record_info.get("source_type") or ""
    source_url = record_info.get("source_url") or ""
    eff_attempt = attempt_id or record_info.get("delivery_attempt_id")

    # 1. 若 DeliveryJournal 中存在完整 workflow_record 上下文，直接通过 replay_delivery 纯本地幂等回放
    delivery = None
    if eff_attempt and accessor is not None and getattr(accessor, "journal", None) is not None:
        try:
            delivery = accessor.journal.get(getattr(accessor, "app_id", ""), eff_attempt)
        except KeyError:
            delivery = None
        if isinstance(delivery, dict) and isinstance(delivery.get("context"), dict) and delivery["context"].get("workflow_record"):
            if media_id and not delivery.get("media_id"):
                delivery = dict(delivery, media_id=media_id)
            from core.pipeline.records import replay_delivery
            replay_delivery(accessor, delivery)
            _cleanup_pending_records_jsonl(record_id=rec_id, media_id=media_id)
            return

    # 2. 若本地存在 attempt_<id>.html 预览且尚未写到 <media_id>.html，则纯本地幂等恢复预览
    if eff_attempt and media_id and accessor is not None and callable(getattr(accessor, "restore_delivery_preview", None)):
        attempt_preview = os.path.join("data", "previews", f"attempt_{eff_attempt}.html")
        target_preview = os.path.join("data", "previews", f"{media_id}.html")
        if os.path.exists(attempt_preview) and not os.path.exists(target_preview):
            accessor.restore_delivery_preview(eff_attempt)

    # 3. AI科普 / 知识体系节点状态补记
    if source_type == "aikepu" and source_url:
        tree_name, node_id = _parse_aikepu_source_url(source_url)
        if node_id:
            from core.aikepu.skill_tree import mark_published
            extra_kwargs = {"tree_name": tree_name} if tree_name else {}
            mark_published(node_id, title, draft_id=media_id, status=aikepu_status, **extra_kwargs)

    # 4. GitHub 仓库历史补记
    if source_type == "github":
        repos = []
        try:
            from core.db.models import ArticleRepoAssociation
            s_repo = db_manager.get_session()
            try:
                rows = s_repo.query(ArticleRepoAssociation.repo_name).filter_by(article_id=rec_id).all()
                repos = [r[0] for r in rows if r and r[0]]
            finally:
                db_manager.remove_session()
        except Exception:
            repos = []
        if not repos:
            repos = _read_pending_repos_from_jsonl(record_id=rec_id, media_id=media_id)
        if repos:
            from core.github.collector import save_github_history
            save_github_history(repos, media_id=media_id)

    # 5. Daily Knowledge 概念补记（若 journal context 携带 concept/domain）
    if isinstance(delivery, dict):
        ctx = delivery.get("context") if isinstance(delivery.get("context"), dict) else {}
        if ctx.get("concept") and ctx.get("domain"):
            from daily_knowledge.database import record_concept
            record_concept(ctx["concept"], ctx["domain"])

    # 6. 幂等标记 DeliveryJournal 已记账
    _mark_journal_recorded_idempotent(accessor, eff_attempt, journal_status=journal_status)

    _cleanup_pending_records_jsonl(record_id=rec_id, media_id=media_id)


def _load_local_preview_html(record_id, title, media_id):
    import hashlib
    title_hash = hashlib.md5(title.encode('utf-8')).hexdigest() if title else ""
    candidate_paths = [
        os.path.join("data", "previews", f"{media_id}.html") if media_id else None,
        os.path.join("data", "previews", f"fail_{title_hash}.html") if title_hash else None,
        os.path.join("data", "previews", f"{record_id}.html"),
    ]
    for path in candidate_paths:
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    html_content = f.read()
                if html_content:
                    return html_content
            except Exception:
                pass
    return ""


def _is_uncertain_publish_exception(exc):
    import requests as _requests
    return isinstance(
        exc,
        (
            _requests.exceptions.Timeout,
            _requests.exceptions.ConnectionError,
            TimeoutError,
            ConnectionError,
        ),
    )


def _locked_review(record_id, handler, data):
    from filelock import FileLock, Timeout
    try:
        record_id = int(record_id)
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "无效文章 ID"}), 400
    os.makedirs("data/review_locks", exist_ok=True)
    lock = FileLock(f"data/review_locks/{record_id}.lock")
    try:
        lock.acquire(timeout=0)
    except Timeout:
        return jsonify({"status": "error", "code": "APPROVE_IN_PROGRESS",
                        "review_status": "APPROVING", "article_id": record_id}), 409
    try:
        return handler(data, record_id)
    finally:
        lock.release()


def _prepare_review(record, session, data, accessor):
    account = getattr(accessor, "app_id", None)
    if record.wechat_app_id and record.wechat_app_id != account:
        return jsonify({"status": "error", "code": "ACCOUNT_MISMATCH"}), 409

    # Holding the process-wide filesystem lock proves the previous worker exited.
    stale = record.status == "APPROVING"
    delivery = None
    if stale:
        delivery = accessor.journal.latest_operation(account, _review_operation_id(record.id))
    attempt = (delivery or {}).get("attempt_id") or record.delivery_attempt_id
    if data.get("attempt_id"):
        attempt = attempt or _resolve_attempt_id(
            {"id": record.id, "error_log": record.error_log}, accessor)
        if attempt != data["attempt_id"]:
            return jsonify({"status": "error", "code": "ATTEMPT_MISMATCH"}), 409

    if stale:
        if delivery:
            record.delivery_attempt_id = delivery["attempt_id"]
            record.media_id = delivery.get("media_id")
            record.status = "DRAFT_PENDING_RECORD" if record.media_id else delivery["status"]
        elif record.media_id:
            record.status = "DRAFT_PENDING_RECORD"
        elif record.delivery_attempt_id or not record.wechat_app_id:
            record.status = "CLOUD_UNCERTAIN"
        else:
            record.status = "PENDING_REVIEW"
        session.commit()


@app.route('/api/review/approve', methods=['POST'])
def review_approve():
    data = request.json or {}
    record_id = data.get("id") or data.get("article_id")
    if not record_id:
        return jsonify({"status": "error", "message": "缺少文章 ID"}), 400

    return _locked_review(record_id, _approve_record, data)


def _approve_record(data, record_id):
    from sqlalchemy import or_
    from core.db.models import ArticleHistory

    art_lock = _get_article_lock(record_id)
    record_snapshot = None
    claimed_for_push = False

    # Phase 1: 短锁 + 原子条件 UPDATE 抢占（释放锁与 DB 会话后再执行任何网络 I/O）
    with art_lock:
        try:
            session = db_manager.get_session()
            record = session.query(ArticleHistory).filter(ArticleHistory.id == record_id).first()
            if not record:
                return jsonify({"status": "error", "message": "记录不存在"}), 404

            accessor = _get_delivery_accessor()
            conflict = _prepare_review(record, session, data, accessor)
            if conflict:
                return conflict
            cur_status = getattr(record, "status", "PENDING_REVIEW") or "PENDING_REVIEW"
            record_snapshot = {
                "id": record.id,
                "title": record.title or "",
                "source_type": record.source_type or "",
                "source_url": getattr(record, "source_url", None) or "",
                "publish_date": getattr(record, "publish_date", None) or "",
                "media_id": record.media_id,
                "thumb_media_id": getattr(record, "thumb_media_id", None) or "",
                "delivery_attempt_id": getattr(record, "delivery_attempt_id", None),
                "error_log": record.error_log,
                "status": cur_status,
            }

            # 1) CLOUD_UNCERTAIN 严禁盲推
            if cur_status == "CLOUD_UNCERTAIN":
                return jsonify({
                    "status": "error",
                    "code": "CLOUD_UNCERTAIN_REQUIRES_RECONCILE",
                    "message": "云端建稿结果未知，严禁盲目重推，请先执行「核对草稿箱」",
                    "review_status": "CLOUD_UNCERTAIN",
                    "article_id": record.id,
                }), 409

            # 2) DRAFT_PENDING_RECORD：已知 receipt 写回是纯本地幂等操作，绝不访问微信 API
            if cur_status == "DRAFT_PENDING_RECORD":
                existing_media_id = record_snapshot["media_id"]
                db_manager.remove_session()
                eff_attempt = _resolve_attempt_id(record_snapshot, accessor)
                try:
                    _backfill_pending_record(
                        record_snapshot,
                        existing_media_id,
                        accessor=accessor,
                        aikepu_status="published",
                        attempt_id=eff_attempt,
                    )
                except Exception as bf_err:
                    logger.exception("DRAFT_PENDING_RECORD 补记失败（保持待补记状态）: {}", bf_err)
                    return jsonify({
                        "status": "error",
                        "code": "BACKFILL_FAILED",
                        "message": f"本地补记失败，状态保持 DRAFT_PENDING_RECORD: {bf_err}",
                        "review_status": "DRAFT_PENDING_RECORD",
                        "media_id": existing_media_id,
                        "attempt_id": eff_attempt,
                        "article_id": record_snapshot["id"],
                    }), 500

                session = db_manager.get_session()
                rec = session.query(ArticleHistory).filter(ArticleHistory.id == record_id).first()
                if rec:
                    rec.status = "APPROVED"
                    rec.success_status = True
                    rec.error_log = None
                    if hasattr(rec, "delivery_attempt_id") and eff_attempt:
                        rec.delivery_attempt_id = eff_attempt
                    session.commit()
                return jsonify({
                    "status": "success",
                    "message": "已完成已建稿文章的本地幂等补记并核准通过（未重复建稿）",
                    "backfilled": True,
                    "draft_pushed": False,
                    "media_id": existing_media_id,
                    "attempt_id": eff_attempt,
                    "review_status": "APPROVED",
                    "article_id": record_snapshot["id"],
                })

            # 3) 正在审批中 / 已入草稿箱 / 已核准，拒绝重复建稿
            if cur_status in ("DRAFT", "APPROVED") or (record.media_id and record.success_status):
                return jsonify({
                    "status": "error",
                    "code": "ALREADY_PUSHED",
                    "message": "文章已存在微信草稿记录，无需重复建稿",
                    "review_status": cur_status,
                    "media_id": record.media_id,
                    "article_id": record.id,
                }), 409

            # 4) 原子条件 UPDATE 抢占为 APPROVING
            claimed = (
                session.query(ArticleHistory)
                .filter(
                    ArticleHistory.id == record_id,
                    ArticleHistory.status.in_(("PENDING_REVIEW", "REJECTED", "FAILED")),
                    or_(ArticleHistory.media_id.is_(None), ArticleHistory.media_id == ""),
                )
                .update({"status": "APPROVING", "delivery_attempt_id": None,
                         "wechat_app_id": accessor.app_id if isinstance(accessor.app_id, str) else None}, synchronize_session=False)
            )
            session.commit()
            if claimed != 1:
                return jsonify({
                    "status": "error",
                    "code": "APPROVE_CONFLICT",
                    "message": "文章状态已变更或正在并发核准中，请刷新后重试",
                    "article_id": record_id,
                }), 409
            record_snapshot["delivery_attempt_id"] = None
            claimed_for_push = True
        except Exception as e:
            logger.exception("核准状态抢占失败: {}", e)
            return jsonify({"status": "error", "message": str(e)}), 500
        finally:
            db_manager.remove_session()

    # Phase 2: 锁外执行本地预览读取与微信推送
    try:
        html_content = _load_local_preview_html(
            record_snapshot["id"],
            record_snapshot["title"],
            record_snapshot["media_id"],
        )

        # 无本地预览 HTML 时：按纯人工状态核准收敛（兼容历史纯 DB 审校记录）
        if not html_content:
            if record_snapshot["source_type"] == "aikepu" and record_snapshot["source_url"]:
                try:
                    _backfill_pending_record(
                        record_snapshot,
                        record_snapshot["media_id"],
                        accessor=None,
                        aikepu_status="draft",
                    )
                except Exception as se:
                    logger.debug("同步技能树状态异常: {}", se)

            session = db_manager.get_session()
            try:
                rec = session.query(ArticleHistory).filter(ArticleHistory.id == record_id).first()
                if rec:
                    rec.status = "APPROVED"
                    rec.success_status = True
                    session.commit()
                    final_mid = rec.media_id
                else:
                    final_mid = None
            finally:
                db_manager.remove_session()

            return jsonify({
                "status": "success",
                "message": "文章已人工核准",
                "draft_pushed": False,
                "media_id": final_mid,
                "review_status": "APPROVED",
                "article_id": record_id,
            })

        # 有本地 HTML 内容：真实推送至微信草稿箱，传入稳定 operation_id 与补记 context
        pub = _get_publisher()
        if getattr(pub, "app_id", None) != getattr(accessor, "app_id", None):
            raise RuntimeError("发布账号已变更，请刷新后重试")
        if not pub or not getattr(pub, "access_token", None):
            push_err = "微信发布凭证不可用，推送失败"
            session = db_manager.get_session()
            try:
                rec = session.query(ArticleHistory).filter(ArticleHistory.id == record_id).first()
                if rec:
                    rec.status = "FAILED"
                    rec.success_status = False
                    rec.error_log = push_err
                    session.commit()
            finally:
                db_manager.remove_session()
            return jsonify({
                "status": "error",
                "message": push_err,
                "push_error": push_err,
                "draft_pushed": False,
                "review_status": "FAILED",
                "article_id": record_id,
            }), 502

        thumb_media_id = record_snapshot["thumb_media_id"]
        uploaded_thumb_id = None
        if not thumb_media_id:
            cover_candidates = [
                os.path.abspath(os.path.join("assets", "default_aikepu_cover.png")),
                os.path.abspath(os.path.join("assets", "default_daily_cover.png")),
                os.path.abspath(os.path.join("static", "images", "github_fixed_cover.png")),
            ]
            for c_path in cover_candidates:
                if os.path.exists(c_path):
                    uploaded_id = pub.upload_image(c_path)
                    if uploaded_id:
                        thumb_media_id = uploaded_id
                        uploaded_thumb_id = uploaded_id
                        break

        operation_id = _review_operation_id(record_snapshot["id"])
        backfill_context = {
            "article_id": record_snapshot["id"],
            "source_type": record_snapshot["source_type"],
            "source_url": record_snapshot["source_url"],
            "title": record_snapshot["title"],
            "publish_date": record_snapshot["publish_date"],
            "thumb_media_id": thumb_media_id,
            "review_approve": True,
        }

        try:
            ok, res = pub.publish_and_notify(
                record_snapshot["title"],
                html_content,
                thumb_media_id,
                operation_id=operation_id,
                context=backfill_context,
            )
        except Exception as pe:
            logger.warning("人工核准推送至微信草稿箱异常: {}", pe)
            uncertain = _is_uncertain_publish_exception(pe)
            target_status = "CLOUD_UNCERTAIN" if uncertain else "FAILED"
            push_err = str(pe) or type(pe).__name__
            session = db_manager.get_session()
            try:
                rec = session.query(ArticleHistory).filter(ArticleHistory.id == record_id).first()
                if rec:
                    rec.status = target_status
                    rec.success_status = False
                    rec.error_log = push_err
                    if uploaded_thumb_id:
                        rec.thumb_media_id = uploaded_thumb_id
                    session.commit()
            finally:
                db_manager.remove_session()
            return jsonify({
                "status": "error",
                "code": "CLOUD_UNCERTAIN" if uncertain else "PUSH_FAILED",
                "message": ("微信建稿请求超时/结果未知，请执行「核对草稿箱」" if uncertain else f"推送微信草稿箱失败: {push_err}"),
                "push_error": push_err,
                "draft_pushed": False,
                "review_status": target_status,
                "article_id": record_id,
            }), (409 if uncertain else 502)

        res_dict = res if isinstance(res, dict) else {}
        attempt_id = res_dict.get("attempt_id") or record_snapshot.get("delivery_attempt_id")
        media_id = res_dict.get("media_id")
        journal_status = res_dict.get("status")

        # 只要拿到 media_id，云端草稿已创建，绝不可误判为 FAILED
        if media_id:
            if attempt_id:
                record_snapshot["delivery_attempt_id"] = attempt_id

            # 例如 publisher.restore_delivery_preview 失败返回 (False, {media_id, attempt_id, errmsg})
            if not ok:
                err_text = res_dict.get("errmsg") or "Local preview write failed"
                session = db_manager.get_session()
                try:
                    rec = session.query(ArticleHistory).filter(ArticleHistory.id == record_id).first()
                    if rec:
                        has_col = hasattr(rec, "delivery_attempt_id")
                        rec.status = "DRAFT_PENDING_RECORD"
                        rec.success_status = True
                        rec.media_id = media_id
                        rec.error_log = _format_error_with_attempt(f"DRAFT_PENDING_RECORD: {err_text}", attempt_id, has_col)
                        if uploaded_thumb_id:
                            rec.thumb_media_id = uploaded_thumb_id
                        if has_col and attempt_id:
                            rec.delivery_attempt_id = attempt_id
                        session.commit()
                finally:
                    db_manager.remove_session()
                return jsonify({
                    "status": "error",
                    "code": "DRAFT_PENDING_RECORD",
                    "message": f"微信草稿已创建，但本地写回未完成，请执行「补记本地状态」: {err_text}",
                    "draft_pushed": True,
                    "media_id": media_id,
                    "attempt_id": attempt_id,
                    "review_status": "DRAFT_PENDING_RECORD",
                    "article_id": record_id,
                }), 500

            # 本地幂等补记 + 标记 DeliveryJournal 已记账
            try:
                _backfill_pending_record(
                    record_snapshot,
                    media_id,
                    accessor=pub,
                    aikepu_status="published",
                    attempt_id=attempt_id,
                    journal_status=journal_status,
                )
            except Exception as bf_err:
                logger.exception("推送成功但本地补记失败，转入 DRAFT_PENDING_RECORD: {}", bf_err)
                session = db_manager.get_session()
                try:
                    rec = session.query(ArticleHistory).filter(ArticleHistory.id == record_id).first()
                    if rec:
                        has_col = hasattr(rec, "delivery_attempt_id")
                        rec.status = "DRAFT_PENDING_RECORD"
                        rec.success_status = True
                        rec.media_id = media_id
                        rec.error_log = _format_error_with_attempt(f"DRAFT_PENDING_RECORD: {bf_err}", attempt_id, has_col)
                        if uploaded_thumb_id:
                            rec.thumb_media_id = uploaded_thumb_id
                        if has_col and attempt_id:
                            rec.delivery_attempt_id = attempt_id
                        session.commit()
                finally:
                    db_manager.remove_session()
                return jsonify({
                    "status": "error",
                    "code": "DRAFT_PENDING_RECORD",
                    "message": f"微信草稿已创建，但本地补记失败，请执行「补记本地状态」: {bf_err}",
                    "draft_pushed": True,
                    "media_id": media_id,
                    "attempt_id": attempt_id,
                    "review_status": "DRAFT_PENDING_RECORD",
                    "article_id": record_id,
                }), 500

            session = db_manager.get_session()
            try:
                rec = session.query(ArticleHistory).filter(ArticleHistory.id == record_id).first()
                if rec:
                    rec.status = "APPROVED"
                    rec.success_status = True
                    rec.media_id = media_id
                    rec.error_log = None
                    if uploaded_thumb_id:
                        rec.thumb_media_id = uploaded_thumb_id
                    if hasattr(rec, "delivery_attempt_id") and attempt_id:
                        rec.delivery_attempt_id = attempt_id
                    session.commit()
            finally:
                db_manager.remove_session()

            return jsonify({
                "status": "success",
                "message": "文章已人工核准并成功推送至微信草稿箱",
                "draft_pushed": not bool(res_dict.get("reused")),
                "reused": bool(res_dict.get("reused")),
                "media_id": media_id,
                "attempt_id": attempt_id,
                "review_status": "APPROVED",
                "article_id": record_id,
            })

        # 推送未拿到 media_id：区分 CLOUD_UNCERTAIN 与明确 FAILED
        is_uncertain = journal_status == "CLOUD_UNCERTAIN"
        target_status = "CLOUD_UNCERTAIN" if is_uncertain else "FAILED"
        push_err = str(
            res_dict.get("errmsg")
            or res_dict.get("error")
            or (f"errcode={res_dict.get('errcode')}" if res_dict.get("errcode") else "")
            or res
            or "微信草稿箱推送失败"
        )
        session = db_manager.get_session()
        try:
            rec = session.query(ArticleHistory).filter(ArticleHistory.id == record_id).first()
            if rec:
                has_col = hasattr(rec, "delivery_attempt_id")
                rec.status = target_status
                rec.success_status = False
                rec.error_log = _format_error_with_attempt(push_err, attempt_id if is_uncertain else None, has_col)
                if uploaded_thumb_id:
                    rec.thumb_media_id = uploaded_thumb_id
                if has_col and attempt_id:
                    rec.delivery_attempt_id = attempt_id
                session.commit()
        finally:
            db_manager.remove_session()

        return jsonify({
            "status": "error",
            "code": "CLOUD_UNCERTAIN" if is_uncertain else "PUSH_FAILED",
            "message": ("云端建稿结果未知，请执行「核对草稿箱」" if is_uncertain else f"推送微信草稿箱失败: {push_err}"),
            "push_error": push_err,
            "draft_pushed": False,
            "attempt_id": attempt_id,
            "review_status": target_status,
            "article_id": record_id,
        }), (409 if is_uncertain else 502)
    except Exception as e:
        logger.exception("核准审核失败: {}", e)
        if claimed_for_push:
            try:
                session = db_manager.get_session()
                rec = session.query(ArticleHistory).filter(
                    ArticleHistory.id == record_id,
                    ArticleHistory.status == "APPROVING",
                ).first()
                if rec:
                    rec.status = "FAILED"
                    rec.success_status = False
                    rec.error_log = str(e)
                    session.commit()
            finally:
                db_manager.remove_session()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/review/reconcile', methods=['POST'])
def review_reconcile():
    """对接真实 DeliveryJournal / WeChatPublisher 契约：
    - CLOUD_UNCERTAIN：仅通过 pub.reconcile_delivery(attempt_id) 核对微信正文内本次发送标识（<!--autowechat:attempt_id-->）或本地 fallback receipt，严禁按标题绑定或自动解冻；
    - DRAFT_PENDING_RECORD：已知 receipt 写回是纯本地幂等操作，绝不访问微信 API，补记成功后 mark_delivery_recorded(attempt_id) 并收敛为 DRAFT。
    """
    data = request.json or {}
    record_id = data.get("id") or data.get("article_id")
    explicit_attempt_id = str(data.get("attempt_id") or "").strip() or None
    if not record_id and not explicit_attempt_id:
        return jsonify({"status": "error", "message": "缺少文章 ID 或 attempt_id"}), 400

    from core.db.models import ArticleHistory

    # 支持仅凭 attempt_id 核对尚未落库 ArticleHistory 的 DeliveryJournal 待处理项
    if not record_id and explicit_attempt_id:
        accessor = _get_delivery_accessor()
        try:
            journal_row = accessor.journal.get(getattr(accessor, "app_id", ""), explicit_attempt_id)
        except KeyError:
            return jsonify({"status": "error", "message": "未找到对应的 DeliveryJournal 记录"}), 404
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

        operation = str(journal_row.get("operation_id") or "")
        if operation.startswith("review_approve:"):
            return _locked_review(operation.split(":", 1)[1], _reconcile_record, data)
        session = db_manager.get_session()
        try:
            linked = session.query(ArticleHistory.id).filter_by(
                delivery_attempt_id=explicit_attempt_id).one_or_none()
        finally:
            db_manager.remove_session()
        if linked:
            return _locked_review(linked.id, _reconcile_record, data)
        if journal_row.get("status") == "FAILED":
            return jsonify({"status": "success", "review_status": "FAILED",
                            "attempt_id": explicit_attempt_id, "unlocked": True})
        j_status = journal_row.get("status")
        if j_status == "DRAFT":
            return jsonify({
                "status": "success",
                "message": "该发送记录已收敛完成",
                "found_in_cloud": bool(journal_row.get("media_id")),
                "unlocked": False,
                "backfilled": False,
                "media_id": journal_row.get("media_id"),
                "attempt_id": explicit_attempt_id,
                "review_status": "DRAFT",
            })

        if j_status == "CLOUD_UNCERTAIN":
            pub = _get_publisher()
            if pub.app_id != accessor.app_id:
                return jsonify({"status": "error", "code": "ACCOUNT_MISMATCH"}), 409
            journal_row = pub.reconcile_delivery(explicit_attempt_id)
            j_status = journal_row.get("status")
            if j_status == "CLOUD_UNCERTAIN":
                return jsonify({
                    "status": "success",
                    "message": "未在微信草稿箱正文内匹配到本次发送标识，严禁按标题绑定或自动解冻，保持 CLOUD_UNCERTAIN",
                    "found_in_cloud": False,
                    "unlocked": False,
                    "media_id": None,
                    "attempt_id": explicit_attempt_id,
                    "review_status": "CLOUD_UNCERTAIN",
                })
            if j_status == "FAILED":
                return jsonify({
                    "status": "success",
                    "message": "DeliveryJournal 已确认云端明确拒绝该次建稿",
                    "found_in_cloud": False,
                    "unlocked": True,
                    "media_id": None,
                    "attempt_id": explicit_attempt_id,
                    "review_status": "FAILED",
                })

        # 此时 journal_row 已含确认 media_id（DRAFT_PENDING_RECORD），纯本地幂等回放
        media_id = journal_row.get("media_id")
        ctx = journal_row.get("context") if isinstance(journal_row.get("context"), dict) else {}
        stub_info = {
            "id": ctx.get("article_id"),
            "title": journal_row.get("title") or ctx.get("title") or "",
            "source_type": ctx.get("source_type") or "",
            "source_url": ctx.get("source_url") or "",
            "delivery_attempt_id": explicit_attempt_id,
        }
        try:
            _backfill_pending_record(
                stub_info,
                media_id,
                accessor=accessor,
                aikepu_status="draft",
                attempt_id=explicit_attempt_id,
                journal_status=j_status,
            )
        except Exception as bf_err:
            logger.exception("attempt_id={} 本地幂等补记失败: {}", explicit_attempt_id, bf_err)
            return jsonify({
                "status": "error",
                "code": "BACKFILL_FAILED",
                "message": f"本地补记失败，状态保持 DRAFT_PENDING_RECORD: {bf_err}",
                "media_id": media_id,
                "attempt_id": explicit_attempt_id,
                "review_status": "DRAFT_PENDING_RECORD",
            }), 500

        return jsonify({
            "status": "success",
            "message": "已完成本地幂等补记并标记 DeliveryJournal 收敛",
            "found_in_cloud": True,
            "unlocked": False,
            "backfilled": True,
            "draft_pushed": False,
            "media_id": media_id,
            "attempt_id": explicit_attempt_id,
            "review_status": "DRAFT",
        })

    return _locked_review(record_id, _reconcile_record, data)


def _reconcile_record(data, record_id):
    from core.db.models import ArticleHistory
    art_lock = _get_article_lock(record_id)
    with art_lock:
        try:
            session = db_manager.get_session()
            record = session.query(ArticleHistory).filter(ArticleHistory.id == record_id).first()
            if not record:
                return jsonify({"status": "error", "message": "记录不存在"}), 404

            recovered_claim = record.status == "APPROVING"
            accessor = _get_delivery_accessor()
            conflict = _prepare_review(record, session, data, accessor)
            if conflict:
                return conflict
            cur_status = getattr(record, "status", "PENDING_REVIEW") or "PENDING_REVIEW"
            record_snapshot = {
                "id": record.id,
                "title": record.title or "",
                "source_type": record.source_type or "",
                "source_url": getattr(record, "source_url", None) or "",
                "publish_date": getattr(record, "publish_date", None) or "",
                "media_id": record.media_id,
                "delivery_attempt_id": getattr(record, "delivery_attempt_id", None),
                "error_log": record.error_log,
                "status": cur_status,
            }

            if cur_status in ("DRAFT", "APPROVED"):
                return jsonify({
                    "status": "success",
                    "message": "记录已收敛，无需核对",
                    "found_in_cloud": bool(record.media_id),
                    "unlocked": False,
                    "backfilled": False,
                    "media_id": record.media_id,
                    "review_status": cur_status,
                    "article_id": record.id,
                })

            # 1) DRAFT_PENDING_RECORD：已知 receipt 写回是纯本地幂等操作（绝不接触微信 API）
            if cur_status == "DRAFT_PENDING_RECORD":
                existing_media_id = record_snapshot["media_id"]
                db_manager.remove_session()
                eff_attempt = _resolve_attempt_id(record_snapshot, accessor)
                try:
                    _backfill_pending_record(
                        record_snapshot,
                        existing_media_id,
                        accessor=accessor,
                        aikepu_status="draft",
                        attempt_id=eff_attempt,
                    )
                except Exception as bf_err:
                    logger.exception("reconcile 本地补记失败（保持 DRAFT_PENDING_RECORD）: {}", bf_err)
                    return jsonify({
                        "status": "error",
                        "code": "BACKFILL_FAILED",
                        "message": f"本地补记失败，状态保持 DRAFT_PENDING_RECORD: {bf_err}",
                        "review_status": "DRAFT_PENDING_RECORD",
                        "media_id": existing_media_id,
                        "attempt_id": eff_attempt,
                        "article_id": record_snapshot["id"],
                    }), 500

                session = db_manager.get_session()
                rec = session.query(ArticleHistory).filter(ArticleHistory.id == record_id).first()
                if rec:
                    rec.status = "DRAFT"
                    rec.success_status = True
                    rec.error_log = None
                    if hasattr(rec, "delivery_attempt_id") and eff_attempt:
                        rec.delivery_attempt_id = eff_attempt
                    session.commit()
                return jsonify({
                    "status": "success",
                    "message": "已完成已建稿文章的纯本地幂等补记",
                    "found_in_cloud": True,
                    "unlocked": False,
                    "backfilled": True,
                    "draft_pushed": False,
                    "media_id": existing_media_id,
                    "attempt_id": eff_attempt,
                    "review_status": "DRAFT",
                    "article_id": record_snapshot["id"],
                })

            if cur_status in ("PENDING_REVIEW", "FAILED") and recovered_claim:
                return jsonify({"status": "success", "review_status": cur_status, "unlocked": True})

            if cur_status != "CLOUD_UNCERTAIN":
                return jsonify({
                    "status": "error",
                    "message": f"当前状态 [{cur_status}] 无需执行云端核对",
                    "review_status": cur_status,
                    "article_id": record.id,
                }), 400
        finally:
            db_manager.remove_session()

    # 2) CLOUD_UNCERTAIN：仅通过 pub.reconcile_delivery(attempt_id) 核对微信正文内本次发送标识，严禁按标题绑定
    try:
        attempt_id = _resolve_attempt_id(record_snapshot, accessor)
        if not attempt_id:
            return jsonify({
                "status": "success",
                "message": "缺少本次发送标识 attempt_id；系统严禁按标题绑定草稿或自动解冻，仍保持 CLOUD_UNCERTAIN，请人工登录微信公众平台核查。",
                "found_in_cloud": False,
                "unlocked": False,
                "media_id": None,
                "attempt_id": None,
                "review_status": "CLOUD_UNCERTAIN",
                "article_id": record_id,
            })

        pub = _get_publisher()
        if getattr(pub, "app_id", None) != getattr(accessor, "app_id", None):
            return jsonify({"status": "error", "code": "ACCOUNT_MISMATCH"}), 409
        if not pub or not callable(getattr(pub, "reconcile_delivery", None)):
            return jsonify({
                "status": "error",
                "message": "发布器不可用或不支持 reconcile_delivery(attempt_id)",
                "review_status": "CLOUD_UNCERTAIN",
                "attempt_id": attempt_id,
                "article_id": record_id,
            }), 502

        journal_row = pub.reconcile_delivery(attempt_id)
        if not isinstance(journal_row, dict):
            journal_row = {"status": "CLOUD_UNCERTAIN"}

        j_status = journal_row.get("status")
        found_media_id = journal_row.get("media_id")

        # 命中本次发送标识（或本地 fallback receipt）：先落库已知 receipt，再纯本地幂等补记
        if found_media_id:
            record_snapshot["delivery_attempt_id"] = attempt_id
            session = db_manager.get_session()
            try:
                rec = session.query(ArticleHistory).filter(ArticleHistory.id == record_id).first()
                if rec:
                    has_col = hasattr(rec, "delivery_attempt_id")
                    rec.media_id = found_media_id
                    rec.status = "DRAFT_PENDING_RECORD"
                    rec.success_status = True
                    if has_col:
                        rec.delivery_attempt_id = attempt_id
                    session.commit()
            finally:
                db_manager.remove_session()

            try:
                _backfill_pending_record(
                    record_snapshot,
                    found_media_id,
                    accessor=pub,
                    aikepu_status="draft",
                    attempt_id=attempt_id,
                    journal_status=j_status,
                )
            except Exception as bf_err:
                logger.exception("核对命中发送标识但本地补记失败，保留 DRAFT_PENDING_RECORD: {}", bf_err)
                session = db_manager.get_session()
                try:
                    rec = session.query(ArticleHistory).filter(ArticleHistory.id == record_id).first()
                    if rec:
                        has_col = hasattr(rec, "delivery_attempt_id")
                        rec.media_id = found_media_id
                        rec.status = "DRAFT_PENDING_RECORD"
                        rec.success_status = True
                        rec.error_log = _format_error_with_attempt(f"DRAFT_PENDING_RECORD: {bf_err}", attempt_id, has_col)
                        if has_col:
                            rec.delivery_attempt_id = attempt_id
                        session.commit()
                finally:
                    db_manager.remove_session()
                return jsonify({
                    "status": "error",
                    "code": "DRAFT_PENDING_RECORD",
                    "message": f"已通过正文发送标识找到草稿，但本地补记失败，请重试「补记本地状态」: {bf_err}",
                    "found_in_cloud": True,
                    "unlocked": False,
                    "media_id": found_media_id,
                    "attempt_id": attempt_id,
                    "review_status": "DRAFT_PENDING_RECORD",
                    "article_id": record_id,
                }), 500

            session = db_manager.get_session()
            try:
                rec = session.query(ArticleHistory).filter(ArticleHistory.id == record_id).first()
                if rec:
                    rec.media_id = found_media_id
                    rec.status = "DRAFT"
                    rec.success_status = True
                    rec.error_log = None
                    if hasattr(rec, "delivery_attempt_id"):
                        rec.delivery_attempt_id = attempt_id
                    session.commit()
            finally:
                db_manager.remove_session()

            return jsonify({
                "status": "success",
                "message": "已通过微信正文发送标识核对到对应草稿并完成本地幂等收敛",
                "found_in_cloud": True,
                "unlocked": False,
                "backfilled": True,
                "media_id": found_media_id,
                "attempt_id": attempt_id,
                "review_status": "DRAFT",
                "article_id": record_id,
            })

        # Journal 明确记录微信拒绝（status == FAILED）：同步收敛为 FAILED
        if j_status == "FAILED":
            err_msg = str(journal_row.get("errmsg") or "微信草稿箱明确拒绝本次建稿")
            session = db_manager.get_session()
            try:
                rec = session.query(ArticleHistory).filter(ArticleHistory.id == record_id).first()
                if rec:
                    rec.status = "FAILED"
                    rec.success_status = False
                    rec.error_log = err_msg
                    session.commit()
            finally:
                db_manager.remove_session()
            return jsonify({
                "status": "success",
                "message": "已从 DeliveryJournal 确认云端明确拒绝该次建稿，可重新核准",
                "found_in_cloud": False,
                "unlocked": True,
                "media_id": None,
                "attempt_id": attempt_id,
                "review_status": "FAILED",
                "article_id": record_id,
            })

        # 未在微信正文内匹配到本次发送标识：严禁按标题绑定或自动解冻，始终保持 CLOUD_UNCERTAIN
        return jsonify({
            "status": "success",
            "message": "未在微信草稿箱正文内匹配到本次发送标识（<!--autowechat:...-->）；系统严禁按标题绑定或自动解冻，仍保持 CLOUD_UNCERTAIN 以防重复建稿。",
            "found_in_cloud": False,
            "unlocked": False,
            "media_id": None,
            "attempt_id": attempt_id,
            "review_status": "CLOUD_UNCERTAIN",
            "article_id": record_id,
        })
    except KeyError:
        return jsonify({
            "status": "error",
            "message": "DeliveryJournal 中不存在该 attempt_id（请检查账号绑定或尝试标识）",
            "review_status": "CLOUD_UNCERTAIN",
            "article_id": record_id,
        }), 404
    except Exception as e:
        logger.exception("云端核对异常: {}", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/system/llm_cache_stats', methods=['GET'])
def get_llm_cache_stats():
    try:
        from core.shared.llm import cache_metrics
        return jsonify(cache_metrics.get_stats())
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route('/api/system/warmup_cache', methods=['POST'])
def trigger_warmup():
    try:
        from core.shared.llm import warmup_deepseek_cache
        success = warmup_deepseek_cache()
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


# ---- 知识体系连载（原 AI 科普技能树）主题包管理 ----
@app.route('/api/kepu/trees', methods=['GET'])
def list_kepu_trees():
    """列出全部知识体系主题包"""
    try:
        from core.aikepu.skill_tree import list_knowledge_trees, get_active_tree_name
        packs = list_knowledge_trees()
        return jsonify({"status": "success", "active": get_active_tree_name(), "trees": packs})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/kepu/active', methods=['GET', 'POST'])
def kepu_active_tree():
    """查询/切换当前激活的知识主题包（切换后持久化）"""
    try:
        from core.aikepu.skill_tree import get_active_tree_name, set_active_tree, load_skill_tree
        if request.method == 'POST':
            data = request.get_json(silent=True) or {}
            name = str(data.get("name", "")).strip()
            if not name:
                return jsonify({"status": "error", "message": "缺少 name 参数"}), 400
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
                return jsonify({"status": "error", "message": "非法主题包名"}), 400
            set_active_tree(name)
        active = get_active_tree_name()
        tree = load_skill_tree()
        meta = tree.get("meta") or {}
        return jsonify({
            "status": "success",
            "active": active,
            "title": meta.get("column_name") or meta.get("name") or active,
            "node_count": len(tree.get("nodes", [])),
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/kepu/import', methods=['POST'])
def import_kepu_tree():
    """导入用户自定义知识库 JSON（nodes DAG 结构，校验后保存并激活）"""
    try:
        import json
        from core.aikepu.skill_tree import validate_tree_structure, TREES_DIR, set_active_tree
        file = request.files.get("file")
        if not file:
            return jsonify({"status": "error", "message": "缺少 file 字段（multipart 表单）"}), 400
        raw = file.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except Exception as e:
            return jsonify({"status": "error", "message": f"JSON 解析失败: {e}"}), 400
        ok, err = validate_tree_structure(data)
        if not ok:
            return jsonify({"status": "error", "message": err}), 400
        name = str(request.form.get("name") or "").strip()
        if not name:
            meta = data.get("meta") or {}
            name = str(meta.get("id") or "").strip() or "custom"
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
            return jsonify({"status": "error", "message": "主题包名只能包含字母/数字/下划线/连字符"}), 400
        os.makedirs(TREES_DIR, exist_ok=True)
        path = os.path.join(TREES_DIR, f"{name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        set_active_tree(name)
        logger.info("已导入知识主题包 [{}]: {} 个节点", name, len(data.get("nodes", [])))
        return jsonify({"status": "success", "name": name, "node_count": len(data.get("nodes", []))})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/aikepu/tree_stats', methods=['GET'])
def get_aikepu_tree_stats():
    try:
        force_refresh = request.args.get("force") == "1" or request.args.get("refresh") == "1"
        from core.aikepu.skill_tree import get_skill_tree_stats, get_available_nodes, get_published_ids
        published_ids = get_published_ids(force_refresh=force_refresh)
        available = get_available_nodes(published_ids=published_ids)
        stats = get_skill_tree_stats(published_ids=published_ids, available_nodes=available)
        stats["available_nodes"] = [
            {
                "id": n.get("id"),
                "title": n.get("title"),
                "tags": n.get("tags", []),
                "difficulty": n.get("difficulty", 1)
            }
            for n in available[:5]
        ]
        return jsonify({"status": "success", "stats": stats})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/api/aikepu/full_tree', methods=['GET'])
def get_aikepu_full_tree():
    try:
        force_refresh = request.args.get("force") == "1" or request.args.get("refresh") == "1"
        from core.aikepu.skill_tree import load_skill_tree, get_published_ids, get_draft_ids, get_available_nodes, get_skill_tree_stats, set_node_status
        tree = load_skill_tree()
        published_ids = get_published_ids(force_refresh=force_refresh)
        draft_ids = get_draft_ids()
        available_nodes = get_available_nodes(published_ids=published_ids)
        available_ids = [n["id"] for n in available_nodes]
        stats = get_skill_tree_stats(published_ids=published_ids, available_nodes=available_nodes)
        
        return jsonify({
            "status": "success",
            "meta": tree.get("meta", {}),
            "nodes": tree.get("nodes", []),
            "published_ids": published_ids,
            "draft_ids": draft_ids,
            "available_ids": available_ids,
            "stats": stats
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/api/aikepu/sync_wechat', methods=['POST'])
def sync_aikepu_wechat():
    try:
        from core.aikepu.skill_tree import sync_wechat_status
        result = sync_wechat_status()
        conn_msg = "（已成功连接微信 API）" if result.get("wechat_connected") else "（微信凭证未配置或连接受限，已同步本地与数据库状态）"
        msg = f"微信公众号同步完成{conn_msg}：包含 {result.get('published_titles_count', 0)} 篇已发表推文，{result.get('draft_titles_count', 0)} 篇草稿箱文章。"
        return jsonify({
            "status": "success",
            "message": msg,
            "result": result
        })
    except Exception as e:
        logger.error("同步微信公众号失败: {}", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/aikepu/set_node_status', methods=['POST'])
def set_aikepu_node_status():
    data = request.json or {}
    node_id = data.get("node_id")
    status = data.get("status", "published") # 'published', 'draft', 'reset'
    if not node_id:
        return jsonify({"status": "error", "message": "Missing node_id"}), 400

    try:
        from core.aikepu.skill_tree import set_node_status, get_published_ids, get_available_nodes, get_skill_tree_stats
        success = set_node_status(node_id, status=status)
        published_ids = get_published_ids()
        available_nodes = get_available_nodes(published_ids=published_ids)
        stats = get_skill_tree_stats(published_ids=published_ids, available_nodes=available_nodes)
        return jsonify({
            "status": "success",
            "message": f"节点 [{node_id}] 状态已设置为 {status}",
            "published_ids": published_ids,
            "stats": stats
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/aikepu/generate_node', methods=['POST'])
def generate_specific_node():
    data = request.json or {}
    node_id = str(data.get("node_id") or "").strip()
    if not node_id:
        return jsonify({"status": "error", "message": "Missing node_id"}), 400

    try:
        from core.aikepu.skill_tree import load_skill_tree
        tree = load_skill_tree()
        valid_ids = {n.get("id") for n in (tree.get("nodes") or []) if isinstance(n, dict) and n.get("id")}
        if node_id not in valid_ids:
            return jsonify({"status": "error", "message": f"未知节点 ID: {node_id}"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"校验知识图谱节点失败: {e}"}), 500

    with _start_lock:
        if ProcessState.is_running:
            return jsonify({"status": "error", "message": "工作流正在运行中，请等待完成后再发起"}), 400

        ProcessState.thread = threading.Thread(
            target=run_workflow_thread,
            args=("aikepu",),
            kwargs={"override_node_id": node_id},
            daemon=True,
        )
        ProcessState.thread.start()

    return jsonify({"status": "success", "message": f"已启动指定节点 [{node_id}] 的撰写工作流"})


@app.route('/api/history/delete', methods=['POST'])
def delete_history():
    # 检查当前运行状态：如果是运行中且未暂停，禁止删除以防冲突
    is_running, is_paused = ProcessState.get_state()
    if is_running and not is_paused:
        return jsonify({"status": "error", "message": "任务运行中且未暂停，禁止删除"}), 400
        
    data = request.json or {}
    record_ids = data.get("ids", [])
    single_id = data.get("id")
    
    # 兼容单选和多选
    ids_to_delete = list(record_ids)
    if single_id and single_id not in ids_to_delete:
        ids_to_delete.append(single_id)
        
    if not ids_to_delete:
        return jsonify({"status": "error", "message": "缺少文章 ID"}), 400
        
    try:
        from core.db.models import ArticleHistory
        session = db_manager.get_session()
        
        # 批量查询并删除
        records = session.query(ArticleHistory).filter(ArticleHistory.id.in_(ids_to_delete)).all()
        deleted_count = 0
        
        for record in records:
            # 1. 尝试清理本地的预览 HTML 缓存文件
            import hashlib
            title_hash = hashlib.md5(record.title.encode('utf-8')).hexdigest()
            preview_id = record.media_id if record.success_status else f"fail_{title_hash}"
            local_path = os.path.join("data", "previews", f"{preview_id}.html")
            if os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except Exception:
                    pass

            # 2. 清理 data/markdown/ 中对应的 Markdown 源文件
            try:
                markdown_dir = os.path.join("data", "markdown")
                if os.path.exists(markdown_dir) and record.title:
                    clean_record_title = re.sub(r'[^\w\u4e00-\u9fff]', '', record.title).lower()
                    zh_words = "".join(re.findall(r'[\u4e00-\u9fff]+', record.title))
                    for fname in os.listdir(markdown_dir):
                        if fname.endswith(".md"):
                            stem = os.path.splitext(fname)[0]
                            clean_stem = re.sub(r'[^\w\u4e00-\u9fff]', '', stem).lower()
                            match_full = bool(
                                clean_record_title
                                and clean_stem
                                and (clean_record_title in clean_stem or clean_stem in clean_record_title)
                            )
                            match_zh = len(zh_words) >= 4 and zh_words in fname
                            if match_full or match_zh:
                                md_file_path = os.path.join(markdown_dir, fname)
                                if os.path.exists(md_file_path):
                                    os.remove(md_file_path)
                                    logger.info("  [File] 成功同步删除 data/markdown 关联文档: {}", fname)
            except Exception as md_del_err:
                logger.warning("删除关联 Markdown 文件异常: {}", md_del_err)
            
            if record.source_type == "aikepu" or getattr(record, 'source_type', '') == 'aikepu':
                try:
                    from core.aikepu.skill_tree import remove_node_from_history
                    remove_node_from_history(title=record.title)
                except Exception as ex:
                    logger.warning("删除历史记录时移除 AI科普节点失败: {}", ex)

            session.delete(record)
            deleted_count += 1
            
        session.commit()
        return jsonify({"status": "success", "message": f"成功删除 {deleted_count} 条推文记录"})
    except Exception as e:
        logger.exception("删除文章记录失败: {}", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        db_manager.remove_session()


@app.route('/api/preview/<preview_id>', methods=['GET'])
def preview_draft(preview_id):
    # 安全校验：仅允许合法字符，杜绝目录穿越漏洞
    safe_preview_id = re.sub(r'[^a-zA-Z0-9_\-]', '', preview_id)
    if not safe_preview_id:
        return "Invalid preview_id", 400

    # 1. 尝试从本地 previews 文件夹读取
    local_path = os.path.join("data", "previews", f"{safe_preview_id}.html")
    if os.path.exists(local_path):
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                content = f.read()
            return content
        except Exception as e:
            logger.warning("读取本地预览文件失败: {}", e)

    # 2. 如果本地不存在且不是以 'fail_' 开头，尝试从微信 API 获取（兼容历史已上传草稿）
    if not safe_preview_id.startswith("fail_"):
        try:
            pub = _get_publisher()
            if pub and pub.access_token:
                url = f"https://api.weixin.qq.com/cgi-bin/draft/get?access_token={pub.access_token}"
                res = pub.session.post(url, json={"media_id": safe_preview_id}, timeout=10).json()
                if "news_item" in res and len(res["news_item"]) > 0:
                    item = res["news_item"][0]
                    raw_title = item.get("title", "")
                    safe_title = _html.escape(str(raw_title or ""))
                    body = item.get("content", "")
                    
                    preview_html = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <meta charset="utf-8">
                        <meta name="viewport" content="width=device-width, initial-scale=1.0">
                        <title>{safe_title}</title>
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
                        <h1 style="font-size: 24px; margin-bottom: 20px;">{safe_title}</h1>
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

    fallback_html = """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>草稿预览说明</title>
        <style>
            *, *::before, *::after {
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }
            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
                background-color: #F8F9FB;
                color: #0C0D0E;
                padding: 48px 20px;
                text-align: center;
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            .card {
                max-width: 480px;
                width: 100%;
                margin: 0 auto;
                background: #FFFFFF;
                border: 1px solid rgba(0, 0, 0, 0.06);
                border-radius: 14px;
                padding: 36px 28px;
                box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03), 0 8px 24px rgba(15, 23, 42, 0.05), inset 0 1px 0 0 #FFFFFF;
            }
            .icon-wrapper {
                width: 48px;
                height: 48px;
                border-radius: 12px;
                background: rgba(79, 91, 213, 0.08);
                color: #4F5BD5;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                margin-bottom: 18px;
            }
            h3 {
                margin: 0 0 10px;
                color: #0C0D0E;
                font-size: 17px;
                font-weight: 600;
                letter-spacing: -0.01em;
            }
            p {
                color: #5E6470;
                font-size: 13px;
                line-height: 1.6;
                margin: 6px 0;
            }
            .badge {
                display: inline-block;
                background: rgba(79, 91, 213, 0.08);
                color: #4F5BD5;
                padding: 4px 14px;
                border-radius: 9999px;
                font-size: 12px;
                font-weight: 500;
                margin-top: 20px;
                border: 1px solid rgba(79, 91, 213, 0.25);
            }
        </style>
    </head>
    <body>
        <div class="card">
            <div class="icon-wrapper">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                    <polyline points="14 2 14 8 20 8"></polyline>
                    <line x1="16" y1="13" x2="8" y2="13"></line>
                    <line x1="16" y1="17" x2="8" y2="17"></line>
                </svg>
            </div>
            <h3>微信远端草稿提示</h3>
            <p>该文章记录创建时间较早，或对应微信草稿已被发布/删除/转移。</p>
            <p>系统出于安全保护，未在本地留下额外静态缓存。</p>
            <div class="badge">AutoWeChat 智能防护机制</div>
        </div>
    </body>
    </html>
    """
    return fallback_html, 404


@app.route('/api/sources', methods=['GET'])
def get_sources():
    try:
        from core.hotspots.collector import get_source_health_report
        report = get_source_health_report()
        return jsonify({"sources": report})
    except Exception as e:
        return jsonify({"sources": {}, "error": str(e)})


@app.route('/api/sources/test', methods=['POST', 'GET'])
def test_sources():
    try:
        import concurrent.futures
        import time as _time
        from config import NEWS_SOURCES
        from core.plugins.manager import plugin_manager
        from core.plugins.utils import (
            _mark_source_success,
            _mark_source_failure,
            get_source_health_report,
            reset_source_health,
            _source_health,
            _source_health_lock,
        )

        # 手动探测时清空历史熔断计数，确保所有配置信源都得到真实重测
        reset_source_health()
        plugins = {
            sid: plugin_manager.get_plugin(sid)
            for sid in NEWS_SOURCES
            if plugin_manager.get_plugin(sid) is not None
        }

        def check_plugin(source_id, plugin):
            t0 = _time.monotonic()
            try:
                data = plugin.fetch_data()
                elapsed_ms = int((_time.monotonic() - t0) * 1000)
                if data:
                    _mark_source_success(source_id, latency_ms=elapsed_ms, detail=f"实测 {len(data)} 条")
                else:
                    with _source_health_lock:
                        already_failed = _source_health.get(source_id, {}).get("failures", 0) > 0
                    if not already_failed:
                        _mark_source_failure(source_id, detail="返回空数据")
            except Exception as exc:
                _mark_source_failure(source_id, detail=str(exc)[:80])

        workers = max(1, min(len(plugins), 14))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(check_plugin, sid, p) for sid, p in plugins.items()]
            concurrent.futures.wait(futures, timeout=15)

        report = get_source_health_report()
        return jsonify({"status": "success", "sources": report})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/system/sd_status', methods=['GET'])
def get_sd_status():
    try:
        from utils.image_handler import get_sd_api_url
        sd_url = get_sd_api_url()
        if sd_url:
            return jsonify({
                "connected": True,
                "url": sd_url,
                "mode": "Stable Diffusion WebUI",
                "message": f"已自动连通本地 SD 服务 ({sd_url})"
            })
        else:
            return jsonify({
                "connected": False,
                "url": None,
                "mode": "科技风文字卡片兜底",
                "message": "未检测到本地 SD 服务，已自动激活极速文字卡片兜底系统"
            })
    except Exception as e:
        return jsonify({"connected": False, "error": str(e)})


# ---- 图片工作台 API ----

@app.route('/api/image-studio/prompts', methods=['POST'])
def generate_prompts():
    """接收文章文本，提取占位符并生成 Imagen 3 英文 Prompt"""
    data = request.json or {}
    article_text = data.get("article_text", "")
    article_title = data.get("article_title", "AI Article")

    if not article_text.strip():
        return jsonify({"status": "error", "message": "article_text is empty"}), 400

    try:
        from utils.image_prompt_gen import extract_placeholders, generate_image_prompts
        placeholders = extract_placeholders(article_text)
        if not placeholders:
            return jsonify({"status": "success", "prompts": [], "message": "No image placeholders found"})

        prompts = generate_image_prompts(article_title, placeholders)
        return jsonify({"status": "success", "prompts": prompts})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/image-studio/upload', methods=['POST'])
def upload_studio_image():
    """接收拖拽上传的图片文件，保存到本地并返回可访问路径"""
    if 'image' not in request.files:
        return jsonify({"status": "error", "message": "No image file provided"}), 400

    file = request.files['image']
    raw_index = str(request.form.get('index', '0')).strip()
    if not re.fullmatch(r"\d{1,3}", raw_index):
        return jsonify({"status": "error", "message": "Invalid image index"}), 400
    idx = int(raw_index)
    if idx < 0 or idx > 999:
        return jsonify({"status": "error", "message": "Invalid image index"}), 400

    if not file.filename:
        return jsonify({"status": "error", "message": "Empty filename"}), 400

    import time as _time
    upload_dir = os.path.join("assets", "manual_images")
    os.makedirs(upload_dir, exist_ok=True)

    # 安全文件名
    ext = os.path.splitext(file.filename)[1].lower() or ".png"
    if ext not in ('.png', '.jpg', '.jpeg', '.webp', '.gif'):
        ext = '.png'
    filename = f"img_{idx}_{int(_time.time()*1000)}{ext}"
    filepath = os.path.join(upload_dir, filename)
    file.save(filepath)

    return jsonify({
        "status": "success",
        "index": idx,
        "filename": filename,
        "filepath": filepath,
        "url": f"/static_assets/{filename}"
    })


@app.route('/api/image-studio/redraw', methods=['POST'])
def redraw_article_images():
    """从公众号文章链接抓取参考图，用 Qwen-Image Pro 重绘为全新原创配图（合规二次创作）"""
    data = request.get_json(silent=True) or {}
    article_url = str(data.get("article_url", "")).strip()
    try:
        count = int(data.get("count", 4))
    except (TypeError, ValueError):
        count = 4
    count = max(1, min(count, 6))
    if not article_url.startswith(("http://", "https://")) or not _is_safe_public_url(article_url):
        return jsonify({"status": "error", "message": "请提供合法且可公开访问的文章链接（禁止内网/环回地址）"}), 400

    try:
        from utils.image_handler import scrape_article_images, _save_image_from_url, redraw_reference_image
        refs = scrape_article_images(article_url, limit=count)
        if not refs:
            return jsonify({"status": "error", "message": "未能从文章中抓取到图片（文章可能已删除或需登录访问）"}), 404

        out_dir = os.path.join("assets", "manual_images")
        tmp_dir = os.path.join(out_dir, "_refs")
        os.makedirs(out_dir, exist_ok=True)
        os.makedirs(tmp_dir, exist_ok=True)

        results = []
        for i, ref_url in enumerate(refs[:count]):
            if not _is_safe_public_url(ref_url):
                continue
            ref_path = _save_image_from_url(ref_url, tmp_dir, prefix=f"ref_{i}", timeout=20)
            if not ref_path:
                continue
            out = redraw_reference_image(ref_path, "重绘为微信公众号配图", out_dir, width=900, height=500)
            if out:
                results.append({"index": len(results) + 1, "url": f"/static_assets/{os.path.basename(out)}"})

        if not results:
            return jsonify({
                "status": "error",
                "message": "重绘失败：请检查 GEMINI_API_KEY / DASHSCOPE_API_KEY 及生图模型配置",
            }), 500
        return jsonify({"status": "success", "count": len(results), "images": results})
    except Exception as e:
        logger.exception("参考图重绘失败")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/image-studio/preview', methods=['POST'])
def generate_studio_preview():
    """接收文章文本 + 图片映射关系，返回渲染后的 HTML 预览"""
    data = request.json or {}
    article_text = data.get("article_text", "")
    article_title = data.get("article_title", "AI Article")
    images_mapping = data.get("images", {})  # {"1": "/static_assets/xxx.png", ...}

    if not article_text.strip():
        return jsonify({"status": "error", "message": "article_text is empty"}), 400

    try:
        from utils.image_prompt_gen import render_article_preview
        rendered_html = render_article_preview(article_text, article_title, images_mapping)
        return jsonify({"status": "success", "html": rendered_html})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# 提供 manual_images 目录 of 静态文件服务
@app.route('/static_assets/<path:filename>')
def serve_manual_image(filename):
    from flask import send_from_directory
    return send_from_directory(os.path.join("assets", "manual_images"), filename)


if __name__ == '__main__':
    try:
        if "validate" in inspect.signature(configure_runtime).parameters:
            configure_runtime(validate=False)
        else:
            configure_runtime()
    except Exception:
        configure_runtime()
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)

    if CLOUD_MODE:
        host = "0.0.0.0"
        port = int(os.getenv("PORT", "5000"))
        print("[Cloud]  AutoWeChat Cloud Mode")
        print(f"   Listening on: http://0.0.0.0:{port}")
        if WEBUI_TOKEN:
            print("   Token auth: enabled")
    else:
        host = "127.0.0.1"
        target_port = int(os.getenv("PORT", "5000"))

        def is_port_available(h, p):
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                try:
                    sock.bind((h, p))
                    return True
                except Exception:
                    return False

        port = target_port
        if not is_port_available(host, port):
            for fallback in [5001, 5002, 5050, 8080, 8888]:
                if is_port_available(host, fallback):
                    port = fallback
                    break

        print(f"Web UI started: http://127.0.0.1:{port}")

        # 本地模式：自动打开浏览器
        import webbrowser
        from threading import Timer
        Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()

    app.run(host=host, port=port, debug=False)

