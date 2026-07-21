document.addEventListener('DOMContentLoaded', () => {
    // --- Internationalization (i18n) ---
    const i18n = {
        zh: {
            "nav-console": "控制台",
            "nav-history": "历史记录",
            "nav-sources": "信源健康",
            "nav-schedule": "定时任务",
            "nav-settings": "系统设置",
            
            "console-title": "控制台",
            "console-subtitle": "自动抓取、生成并发布至微信公众号草稿箱",
            "run-workflow-title": "运行工作流",
            "run-workflow-desc": "扫描最新热点/开源项目，使用大模型生成推文，自动匹配精美插图并推送到微信草稿箱。",
            "task-hotspots": "今日热点",
            "task-github": "GitHub 趋势",
            "task-aikepu": "🎓 AI 科普",
            "btn-start": "开始",
            "btn-pause": "暂停",
            "btn-resume": "恢复",
            "btn-stop": "停止",
            "preview-modal-title": "文章预览",
            
            "history-title": "历史记录",
            "history-subtitle": "已发布文章及运行状态统计",
            
            "sources-title": "信源健康",
            "sources-subtitle": "新闻源及接口健康状态",
            
            "schedule-title": "定时任务",
            "schedule-subtitle": "自动调度微信发布任务流程",
            "add-new-task": "添加新任务",
            "sched-task-type-label": "任务类型",
            "sched-cron-label": "Cron 表达式",
            "sched-add-btn": "添加",
            "active-jobs-title": "活动中的定时任务",
            
            "settings-title": "系统设置",
            "settings-subtitle": "系统 API 密钥与公众号配置",
            "label-wechat-appid": "微信 AppID",
            "label-wechat-secret": "微信 AppSecret",
            "label-llm-apikey": "DeepSeek API 密钥",
            "label-gemini-apikey": "Gemini API 密钥 (可选)",
            "label-llm-model": "LLM 模型",
            "label-qywechat-webhook": "企业微信 Webhook (可选)",
            "label-diagram-workers": "图表并行线程数",
            "btn-save-settings": "保存设置",
            
            "status-idle": "空闲",
            "status-running": "运行中",
            "status-paused": "暂停",
            "btn-lang-text": "English",
            "nav-image-studio": "图片工作台",
            "image-studio-title": "图片工作台",
            "image-studio-subtitle": "生成 Imagen 3 提示词，通过拖拽方式直观配置推文插图"
        },
        en: {
            "nav-console": "Console",
            "nav-history": "History",
            "nav-sources": "Sources",
            "nav-schedule": "Schedule",
            "nav-settings": "Settings",
            "preview-modal-title": "Article Preview",
            
            "console-title": "Console",
            "console-subtitle": "Auto fetch, generate, and publish to WeChat",
            "run-workflow-title": "Run Workflow",
            "run-workflow-desc": "Scan hotspots, generate articles with DeepSeek, add images, publish to WeChat drafts.",
            "task-hotspots": "Hotspots",
            "task-github": "GitHub Trending",
            "task-aikepu": "🎓 AI 科普",
            "btn-start": "Start",
            "btn-pause": "Pause",
            "btn-resume": "Resume",
            "btn-stop": "Stop",
            
            "history-title": "History",
            "history-subtitle": "Published articles and results",
            
            "sources-title": "Sources",
            "sources-subtitle": "News source health status",
            
            "schedule-title": "Schedule",
            "schedule-subtitle": "Automate your publishing tasks",
            "add-new-task": "Add New Task",
            "sched-task-type-label": "Task Type",
            "sched-cron-label": "Cron Expression",
            "sched-add-btn": "Add",
            "active-jobs-title": "Active Scheduled Jobs",
            
            "settings-title": "Settings",
            "settings-subtitle": "API keys and configuration",
            "label-wechat-appid": "WeChat AppID",
            "label-wechat-secret": "WeChat AppSecret",
            "label-llm-apikey": "DeepSeek API Key",
            "label-gemini-apikey": "Gemini API Key (optional)",
            "label-llm-model": "LLM Model",
            "label-qywechat-webhook": "QYWeChat Webhook (optional)",
            "label-diagram-workers": "Diagram Parallel Workers",
            "btn-save-settings": "Save",
            
            "status-idle": "Idle",
            "status-running": "Running",
            "status-paused": "Paused",
            "btn-lang-text": "中文",
            "nav-image-studio": "Image Studio",
            "image-studio-title": "Image Studio",
            "image-studio-subtitle": "Generate Imagen 3 prompts and drag-drop images directly into placeholders"
        }
    };

    let currentLang = localStorage.getItem('aw_lang') || 'zh';

    function updateLanguage() {
        const langData = i18n[currentLang];
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            if (langData[key]) {
                el.textContent = langData[key];
            }
        });
        
        // Refresh active panel if loaded dynamic content
        const activeSection = document.querySelector('.view-section.active');
        if (activeSection) {
            const targetId = activeSection.id;
            if (targetId === 'settings') loadSettings();
            if (targetId === 'history') loadHistory();
            if (targetId === 'sources') {
                loadSources();
                if (sourcesPollInterval) clearInterval(sourcesPollInterval);
                sourcesPollInterval = setInterval(loadSources, 3000);
            }
            if (targetId === 'schedule') loadSchedule();
        }

        setRunningState(isRunning, isPaused);
    }

    // --- Navigation ---
    const navItems = document.querySelectorAll('.nav-item');
    const sections = document.querySelectorAll('.view-section');
    let sourcesPollInterval = null;

    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const targetId = item.getAttribute('data-target');
            navItems.forEach(nav => nav.classList.remove('active'));
            item.classList.add('active');
            sections.forEach(sec => sec.classList.toggle('active', sec.id === targetId));
            
            // 切换 Tab 时清除现有的信源健康轮询
            if (sourcesPollInterval) {
                clearInterval(sourcesPollInterval);
                sourcesPollInterval = null;
            }
            
            if (targetId === 'settings') loadSettings();
            if (targetId === 'history') loadHistory();
            if (targetId === 'sources') {
                loadSources();
                // 开启 3 秒一次的实时健康状态轮询
                sourcesPollInterval = setInterval(loadSources, 3000);
            }
            if (targetId === 'schedule') loadSchedule();
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

        const startText = currentLang === 'zh' ? '开始' : 'Start';
        const stopText = currentLang === 'zh' ? '停止' : 'Stop';
        const pauseText = currentLang === 'zh' ? '暂停' : 'Pause';
        const resumeText = currentLang === 'zh' ? '恢复' : 'Resume';

        if (btnStart) {
            btnStart.style.display = running ? 'none' : 'flex';
            btnStart.disabled = running;
            const textSpan = btnStart.querySelector('[data-i18n="btn-start"]');
            if (textSpan) textSpan.textContent = startText;
        }
        if (btnStop) {
            btnStop.style.display = running ? 'flex' : 'none';
            btnStop.disabled = false;
            btnStop.innerHTML = `<span class="btn-icon">⏹</span> <span data-i18n="btn-stop">${stopText}</span>`;
        }

        if (running) {
            if (btnPause) {
                btnPause.style.display = paused ? 'none' : 'flex';
                const textSpan = btnPause.querySelector('[data-i18n="btn-pause"]');
                if (textSpan) textSpan.textContent = pauseText;
            }
            if (btnResume) {
                btnResume.style.display = paused ? 'flex' : 'none';
                const textSpan = btnResume.querySelector('[data-i18n="btn-resume"]');
                if (textSpan) textSpan.textContent = resumeText;
            }
            if (statusDot) statusDot.className = paused ? 'dot idle' : 'dot running';
            if (statusText) {
                statusText.textContent = paused ? i18n[currentLang]['status-paused'] : i18n[currentLang]['status-running'];
            }
        } else {
            if (btnPause) btnPause.style.display = 'none';
            if (btnResume) btnResume.style.display = 'none';
            if (statusDot) statusDot.className = 'dot idle';
            if (statusText) {
                statusText.textContent = i18n[currentLang]['status-idle'];
            }
        }
    }

    btnStart.addEventListener('click', async () => {
        if (isRunning) return;
        const taskType = document.querySelector('input[name="task_type"]:checked').value;
        const startMsg = currentLang === 'zh' ? `正在启动 (${taskType})...` : `Starting (${taskType})...`;
        appendLog(`SYSTEM | ${startMsg}`, 'system');
        try {
            const res = await fetch('/api/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task_type: taskType })
            });
            const data = await res.json();
            if (data.status === 'success') {
                const startedMsg = currentLang === 'zh' ? '工作流已启动' : 'Workflow started';
                appendLog('SYSTEM | ' + startedMsg, 'system');
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
            const stoppingText = currentLang === 'zh' ? '正在停止...' : 'Stopping...';
            btnStop.innerHTML = `<span class="btn-icon">⏳</span> <span>${stoppingText}</span>`;
            const res = await fetch('/api/stop', { method: 'POST' });
            const data = await res.json();
            const stopMsg = currentLang === 'zh' ? '停止信号已发送' : data.message;
            appendLog('SYSTEM | ' + stopMsg, 'system');
        } catch (e) {
            const failedMsg = currentLang === 'zh' ? '停止失败: ' : 'Stop failed: ';
            appendLog('ERROR | ' + failedMsg + e.message, 'error');
            btnStop.disabled = false;
            const stopText = currentLang === 'zh' ? '停止' : 'Stop';
            btnStop.innerHTML = `<span class="btn-icon">⏹</span> <span data-i18n="btn-stop">${stopText}</span>`;
        }
    });

    btnPause.addEventListener('click', async () => {
        try {
            const res = await fetch('/api/pause', { method: 'POST' });
            const data = await res.json();
            const msg = currentLang === 'zh' ? '已发送暂停信号' : data.message;
            appendLog('SYSTEM | ' + msg, 'system');
        } catch (e) {
            const failedMsg = currentLang === 'zh' ? '暂停失败: ' : 'Pause failed: ';
            appendLog('ERROR | ' + failedMsg + e.message, 'error');
        }
    });

    btnResume.addEventListener('click', async () => {
        try {
            const res = await fetch('/api/resume', { method: 'POST' });
            const data = await res.json();
            const msg = currentLang === 'zh' ? '已发送恢复信号' : data.message;
            appendLog('SYSTEM | ' + msg, 'system');
        } catch (e) {
            const failedMsg = currentLang === 'zh' ? '恢复失败: ' : 'Resume failed: ';
            appendLog('ERROR | ' + failedMsg + e.message, 'error');
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
                if (isRunning) {
                    const connLostText = currentLang === 'zh' ? '连接已断开' : 'Connection lost';
                    appendLog('ERROR | ' + connLostText, 'error');
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
            document.getElementById('diagram-workers').value = data.DIAGRAM_PARALLEL_WORKERS || '3';
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
        saveMsg.textContent = currentLang === 'zh' ? '正在保存...' : 'Saving...';
        saveMsg.className = 'save-message';
        try {
            const res = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            const result = await res.json();
            const successText = currentLang === 'zh' ? '设置保存成功!' : 'Saved!';
            const failedText = currentLang === 'zh' ? '保存失败' : 'Failed';
            saveMsg.textContent = result.status === 'success' ? successText : failedText;
            saveMsg.className = 'save-message ' + (result.status === 'success' ? 'success' : 'error');
            setTimeout(() => { saveMsg.textContent = ''; }, 3000);
        } catch (e) {
            const errText = currentLang === 'zh' ? '错误' : 'Error';
            saveMsg.textContent = errText;
            saveMsg.className = 'save-message error';
            setTimeout(() => { saveMsg.textContent = ''; }, 3000);
        }
    });

    // --- History ---
    async function loadHistory() {
        const container = document.getElementById('history-content');
        const loadingText = currentLang === 'zh' ? '正在加载...' : 'Loading...';
        container.innerHTML = `<div class="log-line system">${loadingText}</div>`;
        try {
            const res = await fetch('/api/history');
            const data = await res.json();
            const history = data.history || {};
            const dates = Object.keys(history).sort().reverse();
            if (dates.length === 0) {
                const noHistoryText = currentLang === 'zh' ? '暂无历史记录。' : 'No history yet.';
                container.innerHTML = `<div class="log-line system">${noHistoryText}</div>`;
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

                if (results.length > 0) {
                    html += '<div class="history-results">';
                    results.forEach(r => {
                        const icon = r.success ? '&#10003;' : '&#10007;';
                        const cls = r.success ? 'result-ok' : 'result-fail';
                        const time = r.time || '';
                        const topic = r.topic || '';
                        
                        let statusBadge = '';
                        if (r.success) {
                            if (r.is_published) {
                                const publishedText = currentLang === 'zh' ? '已群发' : 'Published';
                                statusBadge = `<span class="badge-published">${publishedText}</span>`;
                            } else {
                                const draftText = currentLang === 'zh' ? '草稿箱' : 'Draft';
                                statusBadge = `<span class="badge-draft">${draftText}</span>`;
                            }
                        }
                        
                        const draftId = r.draft_id ? ` <span class="draft-id">${r.draft_id}</span>` : '';
                        const error = r.error ? ` <span class="result-error">${r.error}</span>` : '';
                        
                        const previewBtnText = currentLang === 'zh' ? '预览' : 'Preview';
                        const escapedTopic = topic.replace(/"/g, '&quot;');
                        const previewBtn = r.preview_id ? `<button class="btn-preview" data-preview-id="${r.preview_id}" data-title="${escapedTopic}">${previewBtnText}</button>` : '';

                        html += `<div class="result-item ${cls}">
                            <span class="result-icon">${icon}</span>
                            <span class="result-topic">${topic}</span>
                            ${statusBadge}
                            ${draftId}${error}
                            <span class="result-time" style="display: flex; align-items: center; gap: 8px;">
                                ${previewBtn}
                                <span>${time}</span>
                            </span>
                        </div>`;
                    });
                    html += '</div>';
                } else {
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

            // 绑定预览按钮事件
            container.querySelectorAll('.btn-preview').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    const previewId = btn.getAttribute('data-preview-id');
                    const title = btn.getAttribute('data-title');
                    openPreview(previewId, title);
                });
            });
        } catch (e) {
            const failedLoadText = currentLang === 'zh' ? '加载历史记录失败' : 'Failed to load history';
            container.innerHTML = `<div class="log-line error">${failedLoadText}</div>`;
        }
    }

    // --- Preview Modal ---
    const previewModal = document.getElementById('preview-modal');
    const previewModalTitle = document.getElementById('preview-modal-title');
    const previewIframe = document.getElementById('preview-iframe');
    const btnClosePreview = document.getElementById('btn-close-preview');

    function openPreview(previewId, title) {
        if (!previewModal || !previewIframe) return;
        previewModalTitle.textContent = title;
        previewIframe.src = `/api/preview/${previewId}`;
        previewModal.style.display = 'flex';
    }

    function closePreview() {
        if (!previewModal || !previewIframe) return;
        previewModal.style.display = 'none';
        previewIframe.src = 'about:blank';
    }

    if (btnClosePreview) {
        btnClosePreview.addEventListener('click', closePreview);
    }
    if (previewModal) {
        previewModal.addEventListener('click', (e) => {
            if (e.target === previewModal) {
                closePreview();
            }
        });
    }

    // --- Source Health ---
    async function loadSources() {
        const container = document.getElementById('sources-content');
        const loadingText = currentLang === 'zh' ? '正在加载...' : 'Loading...';
        container.innerHTML = `<div class="log-line system">${loadingText}</div>`;
        try {
            const res = await fetch('/api/sources');
            const data = await res.json();
            const sources = data.sources || {};
            const keys = Object.keys(sources);
            if (keys.length === 0) {
                const noSourceText = currentLang === 'zh' ? '暂无数据源健康状态。' : 'No source data.';
                container.innerHTML = `<div class="log-line system">${noSourceText}</div>`;
                return;
            }
            let html = '';
            keys.forEach(name => {
                const info = sources[name];
                const status = info.status || info;
                const cls = status === 'healthy' ? 'source-ok' : status === 'degraded' ? 'source-warn' : 'source-err';
                const icon = status === 'healthy' ? '&#10003;' : status === 'degraded' ? '!' : '&#10007;';
                const statusTextTrans = currentLang === 'zh' ? (status === 'healthy' ? '健康' : status === 'degraded' ? '亚健康' : '异常') : status;
                html += `<div class="source-card glass-panel ${cls}">
                    <div class="source-icon">${icon}</div>
                    <div class="source-name">${name}</div>
                    <div class="source-status">${statusTextTrans}</div>
                    ${info.detail ? `<div class="source-detail">${info.detail}</div>` : ''}
                </div>`;
            });
            container.innerHTML = html;
        } catch (e) {
            const failedLoadText = currentLang === 'zh' ? '加载数据源健康状态失败' : 'Failed to load sources';
            container.innerHTML = `<div class="log-line error">${failedLoadText}</div>`;
        }
    }

    // --- Schedule ---
    async function loadSchedule() {
        const list = document.getElementById('schedule-jobs-list');
        const loadingText = currentLang === 'zh' ? '正在加载定时任务...' : 'Loading jobs...';
        list.innerHTML = `<div class="log-line system">${loadingText}</div>`;
        try {
            const res = await fetch('/api/schedule/jobs');
            const data = await res.json();
            if (data.status !== 'success') throw new Error(data.message);
            
            if (!data.jobs || data.jobs.length === 0) {
                const noJobsText = currentLang === 'zh' ? '暂无活动中的定时任务。' : 'No active scheduled jobs.';
                list.innerHTML = `<div class="log-line system">${noJobsText}</div>`;
                return;
            }
            
            let html = '<table class="table" style="width:100%; text-align:left; border-collapse: collapse; margin-top: 10px;">';
            const headers = currentLang === 'zh' ? ['任务类型', '状态', '下次执行', '操作'] : ['Task Type', 'Status', 'Next Run', 'Actions'];
            html += `<tr style="border-bottom: 1px solid var(--border-color); padding-bottom: 8px;">
                <th style="padding: 10px 8px;">${headers[0]}</th>
                <th style="padding: 10px 8px;">${headers[1]}</th>
                <th style="padding: 10px 8px;">${headers[2]}</th>
                <th style="padding: 10px 8px;">${headers[3]}</th>
            </tr>`;
            
            data.jobs.forEach(job => {
                const activeBadgeText = currentLang === 'zh' ? '运行中' : 'Active';
                const pausedBadgeText = currentLang === 'zh' ? '已暂停' : 'Paused';
                
                const statusBadge = job.status === 'active' ? 
                    `<span class="badge" style="background:#10B981; color:#000; padding:2px 6px;">${activeBadgeText}</span>` : 
                    `<span class="badge" style="background:#F59E0B; color:#000; padding:2px 6px;">${pausedBadgeText}</span>`;
                
                const pauseBtnText = currentLang === 'zh' ? '暂停' : 'Pause';
                const resumeBtnText = currentLang === 'zh' ? '恢复' : 'Resume';
                const deleteBtnText = currentLang === 'zh' ? '删除' : 'Delete';
                
                html += `<tr style="border-bottom: 1px dashed rgba(255,255,255,0.05);">
                    <td style="padding: 12px 8px;">${job.task_type || 'Unknown'}</td>
                    <td style="padding: 12px 8px;">${statusBadge}</td>
                    <td style="padding: 12px 8px;">${job.next_run_time || 'N/A'}</td>
                    <td style="padding: 12px 8px;">
                        ${job.status === 'active' ? 
                            `<button class="btn btn-warning btn-sm" style="display:inline-block; padding: 4px 10px; font-size: 0.8rem; margin-right: 4px;" onclick="window.pauseJob('${job.id}')">${pauseBtnText}</button>` :
                            `<button class="btn btn-success btn-sm" style="display:inline-block; padding: 4px 10px; font-size: 0.8rem; margin-right: 4px;" onclick="window.resumeJob('${job.id}')">${resumeBtnText}</button>`
                        }
                        <button class="btn btn-danger btn-sm" style="display:inline-block; padding: 4px 10px; font-size: 0.8rem;" onclick="window.removeJob('${job.id}')">${deleteBtnText}</button>
                    </td>
                </tr>`;
            });
            html += '</table>';
            list.innerHTML = html;
        } catch (e) {
            const failedLoadText = currentLang === 'zh' ? '加载定时任务失败: ' : 'Failed to load jobs: ';
            list.innerHTML = `<div class="log-line error">${failedLoadText}${e.message}</div>`;
        }
    }

    document.getElementById('btn-add-schedule').addEventListener('click', async () => {
        const taskType = document.getElementById('sched-task-type').value;
        const cronExpr = document.getElementById('sched-cron').value;
        const btn = document.getElementById('btn-add-schedule');
        
        btn.disabled = true;
        const addingText = currentLang === 'zh' ? '正在添加...' : 'Adding...';
        btn.textContent = addingText;
        
        try {
            const res = await fetch('/api/schedule/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task_type: taskType, cron_expr: cronExpr })
            });
            const data = await res.json();
            if (data.status === 'success') {
                const addSuccessText = currentLang === 'zh' ? '定时任务添加成功！' : 'Schedule added successfully!';
                alert(addSuccessText);
                loadSchedule();
            } else {
                const addFailedText = currentLang === 'zh' ? '添加定时任务失败: ' : 'Error adding schedule: ';
                alert(addFailedText + data.message);
            }
        } catch (e) {
            const reqFailedText = currentLang === 'zh' ? '请求失败: ' : 'Request failed: ';
            alert(reqFailedText + e.message);
        } finally {
            btn.disabled = false;
            const addBtnText = currentLang === 'zh' ? '添加' : 'Add';
            btn.textContent = addBtnText;
        }
    });

    window.removeJob = async (jobId) => {
        const confirmText = currentLang === 'zh' ? '确定要删除这个定时任务吗？' : 'Delete this scheduled task?';
        if (!confirm(confirmText)) return;
        try {
            await fetch('/api/schedule/remove', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ job_id: jobId })
            });
            loadSchedule();
        } catch (e) {
            alert('Error: ' + e.message);
        }
    };

    window.pauseJob = async (jobId) => {
        try {
            await fetch('/api/schedule/pause', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ job_id: jobId })
            });
            loadSchedule();
        } catch (e) {
            alert('Error: ' + e.message);
        }
    };

    window.resumeJob = async (jobId) => {
        try {
            await fetch('/api/schedule/resume', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ job_id: jobId })
            });
            loadSchedule();
        } catch (e) {
            alert('Error: ' + e.message);
        }
    };

    // --- Language Toggle Button Event Listener ---
    const btnLangToggle = document.getElementById('btn-lang-toggle');
    if (btnLangToggle) {
        btnLangToggle.addEventListener('click', () => {
            currentLang = currentLang === 'zh' ? 'en' : 'zh';
            localStorage.setItem('aw_lang', currentLang);
            updateLanguage();
        });
    }

    // Initialize UI language
    updateLanguage();
});
