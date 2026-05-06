document.addEventListener('DOMContentLoaded', () => {
    // Navigation Logic
    const navItems = document.querySelectorAll('.nav-item');
    const sections = document.querySelectorAll('.view-section');

    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const targetId = item.getAttribute('data-target');
            
            navItems.forEach(nav => nav.classList.remove('active'));
            item.classList.add('active');

            sections.forEach(sec => {
                if(sec.id === targetId) {
                    sec.classList.add('active');
                } else {
                    sec.classList.remove('active');
                }
            });

            if (targetId === 'settings') {
                loadSettings();
            }
        });
    });

    // Terminal Logic
    const logConsole = document.getElementById('log-console');
    const btnClearLogs = document.getElementById('btn-clear-logs');

    function appendLog(message, type = 'info') {
        const line = document.createElement('div');
        line.className = `log-line ${type}`;
        
        // Basic escaping
        const escaped = message.replace(/</g, "&lt;").replace(/>/g, "&gt;");
        
        // Colorize based on content loosely
        let finalHtml = escaped;
        if(escaped.includes('INFO')) {
            line.classList.add('info');
        } else if (escaped.includes('WARNING')) {
            line.classList.add('warning');
        } else if (escaped.includes('ERROR') || escaped.includes('失败') || escaped.includes('异常')) {
            line.classList.add('error');
        } else if (escaped.includes('PRINT |')) {
            finalHtml = escaped.replace('PRINT | ', '');
        } else if (escaped.includes('SYSTEM |')) {
            line.classList.add('system');
            finalHtml = escaped.replace('SYSTEM | ', '');
        }

        line.innerHTML = finalHtml;
        logConsole.appendChild(line);
        logConsole.scrollTop = logConsole.scrollHeight;
    }

    btnClearLogs.addEventListener('click', () => {
        logConsole.innerHTML = '<div class="log-line system">日志已清空...</div>';
    });

    // Process Control Logic
    const btnStart = document.getElementById('btn-start');
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    let isRunning = false;
    let pollInterval = null;

    function setRunningState(state) {
        isRunning = state;
        if(isRunning) {
            btnStart.disabled = true;
            btnStart.innerHTML = '<span class="btn-icon">⏳</span> 任务运行中...';
            statusDot.className = 'dot running';
            statusText.textContent = '系统运行中 (Running)';
        } else {
            btnStart.disabled = false;
            btnStart.innerHTML = '<span class="btn-icon">▶</span> 开始执行任务';
            statusDot.className = 'dot idle';
            statusText.textContent = '系统就绪 (Idle)';
        }
    }

    btnStart.addEventListener('click', async () => {
        if(isRunning) return;
        
        try {
            const taskType = document.querySelector('input[name="task_type"]:checked').value;
            appendLog(`SYSTEM | 正在发送启动指令 (任务类型: ${taskType})...`, 'system');
            const res = await fetch('/api/start', { 
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task_type: taskType })
            });
            const data = await res.json();
            
            if(data.status === 'success') {
                appendLog('SYSTEM | ' + data.message, 'system');
                setRunningState(true);
            } else {
                appendLog('ERROR | ' + data.message, 'error');
            }
        } catch(e) {
            appendLog('ERROR | 请求失败: ' + e.message, 'error');
        }
    });

    // Polling Status and Logs
    async function pollStatus() {
        try {
            const res = await fetch('/api/status');
            if(!res.ok) return;
            const data = await res.json();
            
            if(data.logs && data.logs.length > 0) {
                data.logs.forEach(log => appendLog(log));
            }

            if(data.is_running !== isRunning) {
                setRunningState(data.is_running);
            }

        } catch(e) {
            // Silently ignore polling errors
        }
    }

    pollInterval = setInterval(pollStatus, 1000);

    // Settings Logic
    const configForm = document.getElementById('config-form');
    const saveMsg = document.getElementById('save-msg');

    async function loadSettings() {
        try {
            const res = await fetch('/api/config');
            const data = await res.json();
            
            document.getElementById('wechat-appid').value = data.WECHAT_APP_ID || '';
            document.getElementById('wechat-secret').value = data.WECHAT_APP_SECRET || '';
            document.getElementById('llm-apikey').value = data.LLM_API_KEY || '';
            document.getElementById('qywechat-webhook').value = data.QYWECHAT_WEBHOOK || '';
            
            const modelSelect = document.getElementById('llm-model');
            if(data.LLM_MODEL && [...modelSelect.options].some(o => o.value === data.LLM_MODEL)) {
                modelSelect.value = data.LLM_MODEL;
            }
        } catch (e) {
            console.error('Failed to load settings', e);
        }
    }

    configForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const formData = new FormData(configForm);
        const data = Object.fromEntries(formData.entries());
        
        saveMsg.textContent = '保存中...';
        saveMsg.className = 'save-message';

        try {
            const res = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            const result = await res.json();
            
            if(result.status === 'success') {
                saveMsg.textContent = '✅ ' + result.message;
                saveMsg.className = 'save-message success';
            } else {
                saveMsg.textContent = '❌ 保存失败';
                saveMsg.className = 'save-message error';
            }
            
            setTimeout(() => { saveMsg.textContent = ''; }, 3000);
        } catch (e) {
            saveMsg.textContent = '❌ 请求异常';
            saveMsg.className = 'save-message error';
            setTimeout(() => { saveMsg.textContent = ''; }, 3000);
        }
    });
});
