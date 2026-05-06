import os
import threading
from flask import Flask, render_template, jsonify, request
from core.shared.runtime import configure_runtime, log_queue
from core.engine import run_main
import queue
import time
import sys
from dotenv import load_dotenv, set_key

app = Flask(__name__)

# State to track background process
class ProcessState:
    is_running = False
    thread = None

# We need to capture print statements from workflow.py since it uses `print` heavily
class PrintRedirector:
    def __init__(self):
        self.terminal = sys.stdout

    def write(self, message):
        self.terminal.write(message)
        if message.strip():
            # Create a pseudo-log entry for prints
            from loguru import logger
            # Just push to queue directly if we want
            try:
                log_queue.put_nowait(f"PRINT | {message.strip()}\n")
            except queue.Full:
                pass

    def flush(self):
        self.terminal.flush()

def run_workflow_thread(task_type="hotspots"):
    ProcessState.is_running = True
    
    # Redirect stdout to capture prints
    old_stdout = sys.stdout
    sys.stdout = PrintRedirector()
    
    try:
        run_main(task_type=task_type)
    except Exception as e:
        from loguru import logger
        logger.error(f"Workflow failed: {e}")
        try:
            log_queue.put_nowait(f"SYSTEM | ❌ Workflow crashed: {e}\n")
        except queue.Full:
            pass
    finally:
        sys.stdout = old_stdout
        ProcessState.is_running = False
        try:
            log_queue.put_nowait("SYSTEM | Workflow finished.\n")
        except queue.Full:
            pass

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/start', methods=['POST'])
def start_process():
    if ProcessState.is_running:
        return jsonify({"status": "error", "message": "任务已经在运行中"}), 400
    
    data = request.json or {}
    task_type = data.get("task_type", "hotspots")
    
    ProcessState.thread = threading.Thread(target=run_workflow_thread, args=(task_type,), daemon=True)
    ProcessState.thread.start()
    
    return jsonify({"status": "success", "message": "已启动自动发布流程"})

@app.route('/api/status', methods=['GET'])
def get_status():
    logs = []
    while True:
        try:
            # Non-blocking get
            msg = log_queue.get_nowait()
            logs.append(msg)
        except queue.Empty:
            break
            
    return jsonify({
        "is_running": ProcessState.is_running,
        "logs": logs
    })

@app.route('/api/config', methods=['GET', 'POST'])
def handle_config():
    env_file = '.env'
    if request.method == 'GET':
        # reload dotenv just in case
        load_dotenv(env_file, override=True)
        return jsonify({
            "WECHAT_APP_ID": os.getenv("WECHAT_APP_ID", ""),
            "WECHAT_APP_SECRET": os.getenv("WECHAT_APP_SECRET", ""),
            "LLM_API_KEY": os.getenv("LLM_API_KEY", ""),
            "QYWECHAT_WEBHOOK": os.getenv("QYWECHAT_WEBHOOK", ""),
            "LLM_MODEL": os.getenv("LLM_MODEL", "deepseek-chat"),
        })
    else:
        data = request.json
        if not os.path.exists(env_file):
            open(env_file, 'a').close()
            
        for key in ["WECHAT_APP_ID", "WECHAT_APP_SECRET", "LLM_API_KEY", "QYWECHAT_WEBHOOK", "LLM_MODEL"]:
            if key in data:
                set_key(env_file, key, data[key])
        
        # reload environment
        load_dotenv(env_file, override=True)
        return jsonify({"status": "success", "message": "配置已保存"})

if __name__ == '__main__':
    configure_runtime()
    # Turn off flask's default logging to avoid cluttering our logs
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    
    print("🚀 Web UI 已启动! 请在浏览器中访问: http://127.0.0.1:5000")
    app.run(host='127.0.0.1', port=5000, debug=False)
