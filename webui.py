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


class ProcessState:
    is_running = False
    is_paused = False
    thread = None


class PrintRedirector:
    def __init__(self):
        self.terminal = sys.stdout

    def write(self, message):
        self.terminal.write(message)
        if message.strip():
            try:
                log_queue.put_nowait(f"PRINT | {message.strip()}\n")
            except queue.Full:
                pass

    def flush(self):
        self.terminal.flush()


def run_workflow_thread(task_type="hotspots"):
    from core.shared.runtime import cancel_event, pause_event, WorkflowCancelled
    ProcessState.is_running = True
    ProcessState.is_paused = False
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
            pass
    except Exception as e:
        from loguru import logger
        logger.error(f"Workflow failed: {e}")
        try:
            log_queue.put_nowait(f"SYSTEM | Workflow crashed: {e}\n")
        except queue.Full:
            pass
    finally:
        sys.stdout = old_stdout
        ProcessState.is_running = False
        cancel_event.clear()
        try:
            log_queue.put_nowait("SYSTEM | Workflow finished.\n")
        except queue.Full:
            pass


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
    if ProcessState.is_running:
        return jsonify({"status": "error", "message": "Task already running"}), 400
    data = request.json or {}
    task_type = data.get("task_type", "hotspots")
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
        pass
    return jsonify({"status": "success", "message": "Stop signal sent"})


@app.route('/api/pause', methods=['POST'])
def pause_process():
    if not ProcessState.is_running:
        return jsonify({"status": "error", "message": "No task running"}), 400
    from core.shared.runtime import pause_event
    pause_event.clear()  # 设为暂停状态
    ProcessState.is_paused = True
    try:
        log_queue.put_nowait("SYSTEM | ⏸️ User requested pause...\n")
    except queue.Full:
        pass
    return jsonify({"status": "success", "message": "Paused"})


@app.route('/api/resume', methods=['POST'])
def resume_process():
    if not ProcessState.is_running:
        return jsonify({"status": "error", "message": "No task running"}), 400
    from core.shared.runtime import pause_event
    pause_event.set()  # 恢复运行
    ProcessState.is_paused = False
    try:
        log_queue.put_nowait("SYSTEM | ▶️ User requested resume...\n")
    except queue.Full:
        pass
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
        if not os.path.exists(env_file):
            with open(env_file, 'a') as f:
                pass
        for key in ["WECHAT_APP_ID", "WECHAT_APP_SECRET", "LLM_API_KEY",
                     "QYWECHAT_WEBHOOK", "LLM_MODEL", "GEMINI_API_KEY"]:
            if key in data and "*" not in data[key]:
                set_key(env_file, key, data[key])
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
    app.run(host='127.0.0.1', port=5000, debug=False)
