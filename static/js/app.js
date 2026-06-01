document.addEventListener('DOMContentLoaded', () => {
    // --- Navigation ---
    const navItems = document.querySelectorAll('.nav-item');
    const sections = document.querySelectorAll('.view-section');

    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const targetId = item.getAttribute('data-target');
            navItems.forEach(nav => nav.classList.remove('active'));
            item.classList.add('active');
            sections.forEach(sec => sec.classList.toggle('active', sec.id === targetId));
            if (targetId === 'settings') loadSettings();
            if (targetId === 'history') loadHistory();
            if (targetId === 'sources') loadSources();
        });
    });

    // --- Terminal ---
    const logConsole = document.getElementById('log-console');
    const btnClear = document.getElementById('btn-clear-logs');

    function appendLog(message, type = 'info') {
        const line = document.createElement('div');
        line.className = 'log-line ' + type;
        const escaped = message.replace(/</g, "&lt;").replace(/>/g, "&gt;");
        let html = escaped;
        if (escaped.includes('WARNING')) line.className = 'log-line warning';
        else if (escaped.includes('ERROR') || escaped.includes('failed') || escaped.includes('crash')) line.className = 'log-line error';
        else if (escaped.includes('PRINT |')) { html = escaped.replace('PRINT | ', ''); line.className = 'log-line'; }
        else if (escaped.includes('SYSTEM |')) { html = escaped.replace('SYSTEM | ', ''); line.className = 'log-line system'; }
        line.innerHTML = html;
        logConsole.appendChild(line);
        logConsole.scrollTop = logConsole.scrollHeight;
    }

    btnClear.addEventListener('click', () => {
        logConsole.innerHTML = '<div class="log-line system">Logs cleared.</div>';
    });

    // --- Process Control ---
    const btnStart = document.getElementById('btn-start');
    const btnPause = document.getElementById('btn-pause');
    const btnResume = document.getElementById('btn-resume');
    const btnStop = document.getElementById('btn-stop');
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    let isRunning = false;
    let isPaused = false;

    function setRunningState(running, paused = false) {
        isRunning = running;
        isPaused = paused;

        if (btnStart) btnStart.style.display = running ? 'none' : 'flex';
        if (btnStop) {
            btnStop.style.display = running ? 'flex' : 'none';
            btnStop.disabled = false;
            btnStop.innerHTML = '<span class="btn-icon">⏹</span> Stop';
        }

        if (running) {
            if (btnPause) btnPause.style.display = paused ? 'none' : 'flex';
            if (btnResume) btnResume.style.display = paused ? 'flex' : 'none';
            if (statusDot) statusDot.className = paused ? 'dot idle' : 'dot running';
            if (statusText) statusText.textContent = paused ? 'Paused' : 'Running';
        } else {
            if (btnPause) btnPause.style.display = 'none';
            if (btnResume) btnResume.style.display = 'none';
            if (statusDot) statusDot.className = 'dot idle';
            if (statusText) statusText.textContent = 'Idle';
        }
        if (btnStart) btnStart.disabled = running;
    }

    btnStart.addEventListener('click', async () => {
        if (isRunning) return;
        const taskType = document.querySelector('input[name="task_type"]:checked').value;
        appendLog(`SYSTEM | Starting (${taskType})...`, 'system');
        try {
            const res = await fetch('/api/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task_type: taskType })
            });
            const data = await res.json();
            if (data.status === 'success') {
                appendLog('SYSTEM | ' + data.message, 'system');
                setRunningState(true);
            } else {
                appendLog('ERROR | ' + data.message, 'error');
            }
        } catch (e) {
            appendLog('ERROR | ' + e.message, 'error');
        }
    });

    btnStop.addEventListener('click', async () => {
        try {
            btnStop.disabled = true;
            btnStop.textContent = '⏳ Stopping...';
            const res = await fetch('/api/stop', { method: 'POST' });
            const data = await res.json();
            appendLog('SYSTEM | ' + data.message, 'system');
            // 不立即切状态，等下一次 poll 确认后端真正结束
        } catch (e) {
            appendLog('ERROR | Stop failed: ' + e.message, 'error');
            btnStop.disabled = false;
            btnStop.innerHTML = '<span class="btn-icon">⏹</span> Stop';
        }
    });

    btnPause.addEventListener('click', async () => {
        try {
            const res = await fetch('/api/pause', { method: 'POST' });
            const data = await res.json();
            appendLog('SYSTEM | ' + data.message, 'system');
        } catch (e) {
            appendLog('ERROR | Pause failed: ' + e.message, 'error');
        }
    });

    btnResume.addEventListener('click', async () => {
        try {
            const res = await fetch('/api/resume', { method: 'POST' });
            const data = await res.json();
            appendLog('SYSTEM | ' + data.message, 'system');
        } catch (e) {
            appendLog('ERROR | Resume failed: ' + e.message, 'error');
        }
    });

    // --- Adaptive Polling ---
    let pollTimer = null;
    function schedulePoll() {
        const interval = isRunning ? 1000 : 8000;
        pollTimer = setTimeout(async () => {
            try {
                const res = await fetch('/api/status');
                if (!res.ok) return;
                const data = await res.json();
                if (data.logs && data.logs.length > 0) {
                    data.logs.forEach(log => appendLog(log));
                }
                if (data.is_running !== isRunning || data.is_paused !== isPaused) {
                    setRunningState(data.is_running, data.is_paused);
                }
            } catch (e) {
                // server down, show once
                if (isRunning) {
                    appendLog('ERROR | Connection lost', 'error');
                    setRunningState(false);
                }
            }
            schedulePoll();
        }, interval);
    }
    schedulePoll();

    // --- Settings ---
    const configForm = document.getElementById('config-form');
    const saveMsg = document.getElementById('save-msg');

    async function loadSettings() {
        try {
            const res = await fetch('/api/config');
            const data = await res.json();
            document.getElementById('wechat-appid').value = data.WECHAT_APP_ID || '';
            document.getElementById('wechat-secret').value = data.WECHAT_APP_SECRET || '';
            document.getElementById('llm-apikey').value = data.LLM_API_KEY || '';
            document.getElementById('gemini-apikey').value = data.GEMINI_API_KEY || '';
            document.getElementById('qywechat-webhook').value = data.QYWECHAT_WEBHOOK || '';
            const sel = document.getElementById('llm-model');
            if (data.LLM_MODEL && [...sel.options].some(o => o.value === data.LLM_MODEL)) {
                sel.value = data.LLM_MODEL;
            }
        } catch (e) {
            console.error('Load settings failed', e);
        }
    }

    configForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = new FormData(configForm);
        const data = Object.fromEntries(formData.entries());
        saveMsg.textContent = 'Saving...';
        saveMsg.className = 'save-message';
        try {
            const res = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            const result = await res.json();
            saveMsg.textContent = result.status === 'success' ? 'Saved!' : 'Failed';
            saveMsg.className = 'save-message ' + (result.status === 'success' ? 'success' : 'error');
            setTimeout(() => { saveMsg.textContent = ''; }, 3000);
        } catch (e) {
            saveMsg.textContent = 'Error';
            saveMsg.className = 'save-message error';
            setTimeout(() => { saveMsg.textContent = ''; }, 3000);
        }
    });

    // --- History ---
    async function loadHistory() {
        const container = document.getElementById('history-content');
        container.innerHTML = '<div class="log-line system">Loading...</div>';
        try {
            const res = await fetch('/api/history');
            const data = await res.json();
            const history = data.history || {};
            const dates = Object.keys(history).sort().reverse();
            if (dates.length === 0) {
                container.innerHTML = '<div class="log-line system">No history yet.</div>';
                return;
            }
            let html = '';
            dates.forEach(date => {
                const entry = history[date];
                const results = entry.results || [];
                const topics = entry.topics || entry;
                const items = Array.isArray(topics) ? topics : [];

                html += `<div class="history-day">
                    <div class="history-date">${date}</div>`;

                // 显示发布结果（如果有详细数据）
                if (results.length > 0) {
                    html += '<div class="history-results">';
                    results.forEach(r => {
                        const icon = r.success ? '&#10003;' : '&#10007;';
                        const cls = r.success ? 'result-ok' : 'result-fail';
                        const time = r.time || '';
                        const topic = r.topic || '';
                        const draftId = r.draft_id ? ` <span class="draft-id">${r.draft_id}</span>` : '';
                        const error = r.error ? ` <span class="result-error">${r.error}</span>` : '';
                        html += `<div class="result-item ${cls}">
                            <span class="result-icon">${icon}</span>
                            <span class="result-topic">${topic}</span>
                            ${draftId}${error}
                            <span class="result-time">${time}</span>
                        </div>`;
                    });
                    html += '</div>';
                } else {
                    // 兼容旧格式：只有 topics 列表
                    html += '<div class="history-topics">';
                    items.forEach(t => {
                        const name = typeof t === 'string' ? t : (t.title || t.topic || JSON.stringify(t));
                        html += `<span class="topic-tag">${name}</span>`;
                    });
                    html += '</div>';
                }
                html += '</div>';
            });
            container.innerHTML = html;
        } catch (e) {
            container.innerHTML = '<div class="log-line error">Failed to load history</div>';
        }
    }

    // --- Source Health ---
    async function loadSources() {
        const container = document.getElementById('sources-content');
        container.innerHTML = '<div class="log-line system">Loading...</div>';
        try {
            const res = await fetch('/api/sources');
            const data = await res.json();
            const sources = data.sources || {};
            const keys = Object.keys(sources);
            if (keys.length === 0) {
                container.innerHTML = '<div class="log-line system">No source data.</div>';
                return;
            }
            let html = '';
            keys.forEach(name => {
                const info = sources[name];
                const status = info.status || info;
                const cls = status === 'healthy' ? 'source-ok' : status === 'degraded' ? 'source-warn' : 'source-err';
                const icon = status === 'healthy' ? '&#10003;' : status === 'degraded' ? '!' : '&#10007;';
                html += `<div class="source-card glass-panel ${cls}">
                    <div class="source-icon">${icon}</div>
                    <div class="source-name">${name}</div>
                    <div class="source-status">${status}</div>
                    ${info.detail ? `<div class="source-detail">${info.detail}</div>` : ''}
                </div>`;
            });
            container.innerHTML = html;
        } catch (e) {
            container.innerHTML = '<div class="log-line error">Failed to load sources</div>';
        }
    }
});
