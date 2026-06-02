import os
import json
import threading
from flask import Flask, render_template, jsonify, request
from core.shared.runtime import configure_runtime, log_queue
from core.engine import run_main
import queue
import sys
from dotenv import load_dotenv, set_key

app = Flask(__name__)
_start_lock = threading.Lock()


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
        from loguru import logger
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


@app.route('/api/start', methods=['POST'])
def start_process():
    with _start_lock:
        if ProcessState.is_running:
            return jsonify({"status": "error", "message": "Task already running"}), 400
        data = request.json or {}
        task_type = data.get("task_type", "hotspots")
        if task_type not in ("hotspots", "github"):
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
        })
    else:
        data = request.json
        if not isinstance(data, dict):
            return jsonify({"status": "error", "message": "Invalid request body"}), 400
        if not os.path.exists(env_file):
            with open(env_file, 'a') as f:
                pass
        for key in ["WECHAT_APP_ID", "WECHAT_APP_SECRET", "LLM_API_KEY",
                     "QYWECHAT_WEBHOOK", "LLM_MODEL", "GEMINI_API_KEY"]:
            if key in data and "*" not in str(data[key]):
                value = str(data[key]).strip()
                if len(value) > 500 or '\n' in value or '\r' in value:
                    continue  # 防止 .env 注入和异常大值
                set_key(env_file, key, value)
        load_dotenv(env_file, override=True)
        return jsonify({"status": "success", "message": "Config saved"})


@app.route('/api/history', methods=['GET'])
def get_history():
    history_file = 'hotspots_history.json'
    if not os.path.exists(history_file):
        return jsonify({"history": {}})
    try:
        with open(history_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify({"history": data})
    except Exception as e:
        return jsonify({"history": {}, "error": str(e)})


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
    print("Web UI started: http://127.0.0.1:5000")
    
    # 延迟 1 秒后自动打开浏览器，确保 Flask 服务已完全启动
    import webbrowser
    from threading import Timer
    Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    
    app.run(host='127.0.0.1', port=5000, debug=False)
