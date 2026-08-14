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
            if (targetId === 'skill-tree-view') loadSkillTreeVisualizer();
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
    const moduleStartBtns = document.querySelectorAll('.btn-module-start');
    const activeTaskControls = document.getElementById('active-task-controls');
    const activeTaskLabel = document.getElementById('active-task-label');
    const btnPause = document.getElementById('btn-pause');
    const btnResume = document.getElementById('btn-resume');
    const btnStop = document.getElementById('btn-stop');
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    let isRunning = false;
    let isPaused = false;
    let currentTaskName = '';

    function setRunningState(running, paused = false) {
        isRunning = running;
        isPaused = paused;

        const stopText = currentLang === 'zh' ? '停止' : 'Stop';
        const pauseText = currentLang === 'zh' ? '暂停' : 'Pause';
        const resumeText = currentLang === 'zh' ? '恢复' : 'Resume';

        // Toggle start buttons state
        moduleStartBtns.forEach(btn => {
            btn.disabled = running;
            if (running) {
                btn.style.opacity = '0.5';
                btn.style.cursor = 'not-allowed';
            } else {
                btn.style.opacity = '1';
                btn.style.cursor = 'pointer';
            }
        });

        // Toggle active task controls panel
        if (activeTaskControls) {
            activeTaskControls.style.display = running ? 'flex' : 'none';
        }

        if (btnStop) {
            btnStop.style.display = running ? 'flex' : 'none';
            btnStop.disabled = false;
            btnStop.innerHTML = `<span class="btn-icon">⏹</span> <span data-i18n="btn-stop">${stopText}</span>`;
        }

        if (running) {
            if (activeTaskLabel) {
                activeTaskLabel.textContent = currentLang === 'zh' ? `正在运行: ${currentTaskName}` : `Running: ${currentTaskName}`;
            }
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
            currentTaskName = '';
        }
    }

    moduleStartBtns.forEach(btn => {
        btn.addEventListener('click', async () => {
            if (isRunning) return;
            const taskType = btn.getAttribute('data-task');
            currentTaskName = taskType;
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

    // --- DeepSeek Prompt Cache 监控更新 ---
    async function updateCacheMetrics() {
        try {
            const res = await fetch('/api/system/llm_cache_stats');
            if (!res.ok) return;
            const stats = await res.json();
            
            const hitRateEl = document.getElementById('stat-hit-rate');
            const savedTokensEl = document.getElementById('stat-saved-tokens');
            const savedCnyEl = document.getElementById('stat-saved-cny');
            const latencyEl = document.getElementById('stat-latency');
            const warmIndicator = document.getElementById('cache-warm-indicator');

            if (hitRateEl) hitRateEl.textContent = `${stats.hit_rate_pct || 0.0}%`;
            if (savedTokensEl) savedTokensEl.textContent = (stats.hit_tokens || 0).toLocaleString();
            if (savedCnyEl) savedCnyEl.textContent = `￥${(stats.saved_cny || 0.0).toFixed(4)}`;
            if (latencyEl) latencyEl.textContent = `${stats.last_latency_ms || 0} ms`;

            if (warmIndicator) {
                if (stats.is_warm) {
                    warmIndicator.style.background = 'rgba(16, 185, 129, 0.15)';
                    warmIndicator.style.color = '#10b981';
                    warmIndicator.textContent = currentLang === 'zh' ? '已预热激活' : 'Warm Active';
                } else {
                    warmIndicator.style.background = 'rgba(148, 163, 184, 0.15)';
                    warmIndicator.style.color = '#94a3b8';
                    warmIndicator.textContent = currentLang === 'zh' ? '冷启动节点' : 'Cold Node';
                }
            }
        } catch (e) {
            console.warn('Failed to fetch cache metrics:', e);
        }
    }

    // 一键预热按钮处理
    const btnWarmup = document.getElementById('btn-warmup-cache');
    if (btnWarmup) {
        btnWarmup.addEventListener('click', async () => {
            btnWarmup.disabled = true;
            btnWarmup.textContent = currentLang === 'zh' ? '🔥 预热中...' : 'Warming up...';
            try {
                const res = await fetch('/api/system/warmup_cache', { method: 'POST' });
                const data = await res.json();
                if (data.status === 'success') {
                    appendLog('SYSTEM | 🔥 DeepSeek Cache 预热成功！', 'system');
                    updateCacheMetrics();
                } else {
                    appendLog('ERROR | Cache 预热失败: ' + (data.message || ''), 'error');
                }
            } catch (e) {
                appendLog('ERROR | Cache 预热网络异常: ' + e.message, 'error');
            } finally {
                btnWarmup.disabled = false;
                btnWarmup.innerHTML = '<span>🔥 一键预热缓存</span>';
            }
        });
    }

    // --- AI 科普技能树进度更新 ---
    async function updateSkillTreeStats() {
        try {
            const res = await fetch('/api/aikepu/tree_stats');
            if (!res.ok) return;
            const data = await res.json();
            if (data.status !== 'success' || !data.stats) return;

            const stats = data.stats;
            const published = stats.published_count !== undefined ? stats.published_count : (stats.published !== undefined ? stats.published : 0);
            const total = stats.total_count !== undefined ? stats.total_count : (stats.total !== undefined ? stats.total : 0);
            const ratioEl = document.getElementById('skill-tree-ratio');
            const barEl = document.getElementById('skill-tree-progress-bar');
            const nextTopicEl = document.getElementById('skill-tree-next-topic');

            if (ratioEl) {
                ratioEl.textContent = `进度: ${published}/${total} (${stats.progress_pct}%)`;
            }
            if (barEl) {
                barEl.style.width = `${stats.progress_pct}%`;
            }
            if (nextTopicEl) {
                if (stats.available_nodes && stats.available_nodes.length > 0) {
                    const nextNode = stats.available_nodes[0];
                    const diffBadge = ['', '🌱 入门', '📘 基础', '🔥 进阶', '⚡ 前沿'][nextNode.difficulty] || '';
                    nextTopicEl.textContent = `${nextNode.title} (${diffBadge})`;
                } else if (published >= total && total > 0) {
                    nextTopicEl.textContent = currentLang === 'zh' ? '🎉 全部选题已通关！' : '🎉 All Topics Completed!';
                } else {
                    nextTopicEl.textContent = currentLang === 'zh' ? '待前置节点解锁' : 'Waiting for Prerequisites';
                }
            }
        } catch (e) {
            console.warn('Failed to fetch skill tree stats:', e);
        }
    }

    // --- AI 科普技能树可视化 (HTML + SVG) ---
    let skillTreeDataCache = null;
    let currentFilterTier = 'all';
    let currentModalNode = null;

    async function loadSkillTreeVisualizer(force = false) {
        const container = document.getElementById('skill-tree-columns-container');
        if (!container) return;

        try {
            const url = force ? '/api/aikepu/full_tree?force=1' : '/api/aikepu/full_tree';
            const res = await fetch(url);
            if (!res.ok) return;
            const data = await res.json();
            if (data.status !== 'success') return;

            skillTreeDataCache = data;
            renderSkillTreeGraph();
        } catch (err) {
            console.error('Failed to load full skill tree:', err);
        }
    }

    function renderSkillTreeGraph() {
        if (!skillTreeDataCache) return;

        const { nodes, published_ids, draft_ids, available_ids } = skillTreeDataCache;
        const pubSet = new Set(published_ids || []);
        const draftSet = new Set(draft_ids || []);
        const availSet = new Set(available_ids || []);
        const completedSet = new Set([...pubSet, ...draftSet]);

        // 1. 更新 Legend Counters
        const publishedCountEl = document.getElementById('legend-published-count');
        const availableCountEl = document.getElementById('legend-available-count');
        const lockedCountEl = document.getElementById('legend-locked-count');

        const pubCount = pubSet.size;
        const draftCount = draftSet.size;
        const completedCount = completedSet.size;
        const availCount = availSet.size;
        const lockedCount = Math.max(0, (nodes.length || 30) - completedCount - availCount);

        if (publishedCountEl) {
            publishedCountEl.innerHTML = `${completedCount} <span style="font-size:11px; font-weight:normal; opacity:0.85;">(群发${pubCount}/草稿${draftCount})</span>`;
        }
        if (availableCountEl) availableCountEl.textContent = availCount;
        if (lockedCountEl) lockedCountEl.textContent = lockedCount;

        // 2. 清空 4 个 Tier 列
        for (let i = 1; i <= 4; i++) {
            const el = document.getElementById(`tier-nodes-${i}`);
            if (el) el.innerHTML = '';
        }

        // 3. 渲染 HTML 精简 Node 卡片 (Knowledge Graph Pill Style)
        const nodeElementsMap = {};
        const prereqMap = {};
        const childMap = {};

        nodes.forEach(n => {
            prereqMap[n.id] = n.prerequisites || [];
            (n.prerequisites || []).forEach(p => {
                if (!childMap[p]) childMap[p] = [];
                childMap[p].push(n.id);
            });
        });

        nodes.forEach((node, index) => {
            const difficulty = node.difficulty || 1;
            const tierList = document.getElementById(`tier-nodes-${difficulty}`);
            if (!tierList) return;

            // 过滤判断
            if (currentFilterTier !== 'all' && currentFilterTier !== String(difficulty)) {
                return;
            }

            const isPublished = pubSet.has(node.id);
            const isDraft = !isPublished && draftSet.has(node.id);
            const isAvailable = !isPublished && !isDraft && availSet.has(node.id);
            const isLocked = !isPublished && !isDraft && !isAvailable;

            let statusClass = 'locked';
            let statusText = '🔒 锁定';
            if (isPublished) {
                statusClass = 'published';
                statusText = '✅ 已群发';
            } else if (isDraft) {
                statusClass = 'published';
                statusText = '📝 草稿箱';
            } else if (isAvailable) {
                statusClass = 'available';
                statusText = '⚡ 可生成';
            }

            const card = document.createElement('div');
            card.className = `skill-node-card ${statusClass}`;
            card.setAttribute('data-node-id', node.id);

            const tagsHtml = (node.tags || []).slice(0, 2).map(t => `<span class="node-tag-item">${t}</span>`).join('');

            card.innerHTML = `
                <div class="node-card-top">
                    <span class="node-id-label">#${String(index + 1).padStart(2, '0')} · ${node.id}</span>
                    <span class="node-status-tag ${statusClass}">${statusText}</span>
                </div>
                <div class="node-card-title" title="${node.title}">${node.title}</div>
                <div class="node-card-tags">${tagsHtml}</div>
            `;

            // Hover 效果: 知识图谱前后依赖关系高亮
            card.addEventListener('mouseenter', () => {
                highlightKnowledgeGraphPath(node.id, prereqMap, childMap);
            });
            card.addEventListener('mouseleave', () => {
                resetKnowledgeGraphHighlight();
            });

            // 卡片点击 -> 弹窗详情
            card.addEventListener('click', () => {
                openNodeModal(node, statusClass, statusText);
            });

            tierList.appendChild(card);
            nodeElementsMap[node.id] = card;
        });

        // 4. 延迟渲染 SVG 连线 (等待 DOM Layout 完成)
        requestAnimationFrame(() => {
            setTimeout(() => drawSVGConnections(nodes, nodeElementsMap, completedSet, availSet), 60);
        });
    }

    function highlightKnowledgeGraphPath(hoverId, prereqMap, childMap) {
        const sources = new Set(prereqMap[hoverId] || []);
        const targets = new Set(childMap[hoverId] || []);

        document.querySelectorAll('.skill-node-card').forEach(card => {
            const nid = card.getAttribute('data-node-id');
            if (nid === hoverId) {
                card.classList.add('highlight-source');
            } else if (sources.has(nid)) {
                card.classList.add('highlight-source');
            } else if (targets.has(nid)) {
                card.classList.add('highlight-target');
            } else {
                card.classList.add('dimmed');
            }
        });

        document.querySelectorAll('.tree-svg-path').forEach(path => {
            const parent = path.getAttribute('data-parent');
            const child = path.getAttribute('data-child');
            if ((parent === hoverId || child === hoverId) || (sources.has(parent) && child === hoverId) || (parent === hoverId && targets.has(child))) {
                path.classList.add('highlight');
            } else {
                path.classList.add('dimmed');
            }
        });
    }

    function resetKnowledgeGraphHighlight() {
        document.querySelectorAll('.skill-node-card').forEach(c => {
            c.classList.remove('highlight-source', 'highlight-target', 'dimmed');
        });
        document.querySelectorAll('.tree-svg-path').forEach(p => {
            p.classList.remove('highlight', 'dimmed');
        });
    }

    function drawSVGConnections(nodes, nodeMap, completedSet, availSet) {
        const svg = document.getElementById('skill-tree-svg-canvas');
        const viewport = document.getElementById('skill-tree-viewport');
        if (!svg || !viewport) return;

        svg.innerHTML = '';
        const viewportRect = viewport.getBoundingClientRect();
        
        // 设置 SVG width/height
        svg.setAttribute('width', viewport.scrollWidth);
        svg.setAttribute('height', Math.max(viewport.scrollHeight, 650));

        // 定义 Marker 箭头
        const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
        defs.innerHTML = `
            <marker id="arrow-pub" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#10b981"/>
            </marker>
            <marker id="arrow-avail" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#2563eb"/>
            </marker>
            <marker id="arrow-locked" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8" opacity="0.6"/>
            </marker>
        `;
        svg.appendChild(defs);

        function createRoundedPath(points, r = 12) {
            if (points.length < 2) return '';
            let d = `M ${points[0].x} ${points[0].y}`;
            for (let i = 1; i < points.length - 1; i++) {
                const p0 = points[i - 1], p1 = points[i], p2 = points[i + 1];
                const dx1 = p0.x - p1.x, dy1 = p0.y - p1.y;
                const dx2 = p2.x - p1.x, dy2 = p2.y - p1.y;
                const len1 = Math.hypot(dx1, dy1), len2 = Math.hypot(dx2, dy2);
                const radius = Math.min(r, len1 / 2, len2 / 2);
                
                if (radius === 0) {
                    d += ` L ${p1.x} ${p1.y}`;
                } else {
                    const sX = p1.x + (dx1 / len1) * radius;
                    const sY = p1.y + (dy1 / len1) * radius;
                    const eX = p1.x + (dx2 / len2) * radius;
                    const eY = p1.y + (dy2 / len2) * radius;
                    d += ` L ${sX} ${sY} Q ${p1.x} ${p1.y} ${eX} ${eY}`;
                }
            }
            d += ` L ${points[points.length - 1].x} ${points[points.length - 1].y}`;
            return d;
        }

        function getSafeY(colIndex, targetY, viewportRectTop, viewportScrollTop) {
            const cards = Array.from(document.querySelectorAll(`.skill-tier-column[data-tier="${colIndex}"] .skill-node-card`));
            const midCards = cards.map(c => {
                const r = c.getBoundingClientRect();
                return { top: r.top - viewportRectTop + viewportScrollTop, bottom: r.bottom - viewportRectTop + viewportScrollTop };
            }).sort((a,b) => a.top - b.top);
            
            let bestY = targetY;
            let minDiff = Infinity;
            const gaps = [];
            
            if (midCards.length > 0) gaps.push(midCards[0].top - 30);
            for (let k = 0; k < midCards.length - 1; k++) {
                gaps.push((midCards[k].bottom + midCards[k+1].top) / 2);
            }
            if (midCards.length > 0) gaps.push(midCards[midCards.length-1].bottom + 30);
            if (gaps.length === 0) gaps.push(targetY);
            
            for (const gy of gaps) {
                if (Math.abs(gy - targetY) < minDiff) {
                    minDiff = Math.abs(gy - targetY);
                    bestY = gy;
                }
            }
            return bestY;
        }

        nodes.forEach(node => {
            const childCard = nodeMap[node.id];
            if (!childCard) return;

            const prereqs = node.prerequisites || [];
            prereqs.forEach(prereqId => {
                const parentCard = nodeMap[prereqId];
                if (!parentCard) return;

                const pNode = nodes.find(n => n.id === prereqId);
                const pDiff = pNode.difficulty || 1;
                const cDiff = node.difficulty || 1;

                const parentRect = parentCard.getBoundingClientRect();
                const childRect = childCard.getBoundingClientRect();

                const startX = parentRect.right - viewportRect.left + viewport.scrollLeft;
                const startY = parentRect.top + parentRect.height / 2 - viewportRect.top + viewport.scrollTop;
                
                let endX;
                if (pDiff >= cDiff) {
                    endX = childRect.right - viewportRect.left + viewport.scrollLeft + 8;
                } else {
                    endX = childRect.left - viewportRect.left + viewport.scrollLeft - 8;
                }
                const endY = childRect.top + childRect.height / 2 - viewportRect.top + viewport.scrollTop;

                let points = [{x: startX, y: startY}];

                if (pDiff === cDiff) {
                    points.push({x: startX + 25, y: startY});
                    points.push({x: startX + 25, y: endY});
                } else if (pDiff < cDiff) {
                    let currX = startX;
                    let currY = startY;

                    for (let i = pDiff; i < cDiff; i++) {
                        const thisCol = document.querySelector(`.skill-tier-column[data-tier="${i}"]`);
                        const nextCol = document.querySelector(`.skill-tier-column[data-tier="${i + 1}"]`);
                        
                        let thisRight = thisCol ? thisCol.getBoundingClientRect().right - viewportRect.left + viewport.scrollLeft : currX + 170;
                        let nextLeft = nextCol ? nextCol.getBoundingClientRect().left - viewportRect.left + viewport.scrollLeft : currX + 300;
                        
                        const gutterX = (thisRight + nextLeft) / 2;
                        points.push({x: gutterX, y: currY});
                        currX = gutterX;

                        if (i + 1 < cDiff) {
                            const targetY = startY + (endY - startY) * ((i + 1 - pDiff) / (cDiff - pDiff));
                            const bestY = getSafeY(i + 1, targetY, viewportRect.top, viewport.scrollTop);
                            points.push({x: currX, y: bestY});
                            currY = bestY;
                        } else {
                            points.push({x: currX, y: endY});
                            currY = endY;
                        }
                    }
                } else {
                    // Backward routing (e.g. diff 3 -> diff 2)
                    let currX = startX + 25;
                    points.push({x: currX, y: startY});
                    let currY = startY;

                    for (let i = pDiff; i > cDiff; i--) {
                        const targetY = startY + (endY - startY) * ((pDiff - i + 1) / (pDiff - cDiff + 1));
                        const bestY = getSafeY(i, targetY, viewportRect.top, viewport.scrollTop);
                        points.push({x: currX, y: bestY});
                        currY = bestY;
                        
                        const thisCol = document.querySelector(`.skill-tier-column[data-tier="${i}"]`);
                        const prevCol = document.querySelector(`.skill-tier-column[data-tier="${i - 1}"]`);
                        
                        let thisLeft = thisCol ? thisCol.getBoundingClientRect().left - viewportRect.left + viewport.scrollLeft : currX - 300;
                        let prevRight = prevCol ? prevCol.getBoundingClientRect().right - viewportRect.left + viewport.scrollLeft : currX - 450;
                        
                        const gutterX = (thisLeft + prevRight) / 2;
                        points.push({x: gutterX, y: currY});
                        currX = gutterX;
                    }
                    points.push({x: currX, y: endY});
                }

                points.push({x: endX, y: endY});
                const d = createRoundedPath(points, 12);

                const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                path.setAttribute('d', d);

                // 连线样式判定
                let pathClass = 'locked';
                let markerId = 'arrow-locked';
                if (completedSet.has(prereqId) && completedSet.has(node.id)) {
                    pathClass = 'published';
                    markerId = 'arrow-pub';
                } else if (completedSet.has(prereqId) && availSet.has(node.id)) {
                    pathClass = 'available';
                    markerId = 'arrow-avail';
                }

                path.setAttribute('class', `tree-svg-path ${pathClass}`);
                path.setAttribute('marker-end', `url(#${markerId})`);
                path.setAttribute('data-parent', prereqId);
                path.setAttribute('data-child', node.id);

                svg.appendChild(path);
            });
        });
    }

    function openNodeModal(node, statusClass, statusText) {
        currentModalNode = node;
        const modal = document.getElementById('skill-node-modal');
        if (!modal) return;

        const headingEl = document.getElementById('node-modal-heading');
        const idEl = document.getElementById('node-modal-id');
        const summaryEl = document.getElementById('node-modal-summary');
        const badgeEl = document.getElementById('node-modal-badge');
        const statusBadgeEl = document.getElementById('node-modal-status-badge');
        const tagsContainer = document.getElementById('node-modal-tags');
        const prereqsContainer = document.getElementById('node-modal-prereqs');
        const btnGen = document.getElementById('btn-generate-node-modal');

        if (headingEl) headingEl.textContent = node.title;
        if (idEl) idEl.textContent = `node_id: ${node.id}`;
        if (summaryEl) summaryEl.textContent = node.summary || '暂无摘要描述';
        if (badgeEl) badgeEl.textContent = `Level ${node.difficulty}`;

        if (statusBadgeEl) {
            statusBadgeEl.innerHTML = `<span class="node-status-tag ${statusClass}">${statusText}</span>`;
        }

        if (tagsContainer) {
            tagsContainer.innerHTML = (node.tags || []).map(t => `<span class="node-tag-item">${t}</span>`).join('');
        }

        if (prereqsContainer) {
            const prereqs = node.prerequisites || [];
            if (prereqs.length === 0) {
                prereqsContainer.innerHTML = '<span style="font-size:12px; color:var(--text-secondary);">无先修基础要求（入门节点）</span>';
            } else {
                const pubSet = new Set(skillTreeDataCache?.published_ids || []);
                const draftSet = new Set(skillTreeDataCache?.draft_ids || []);
                const completedSet = new Set([...pubSet, ...draftSet]);
                prereqsContainer.innerHTML = prereqs.map(p => {
                    const isMet = completedSet.has(p);
                    const metBadge = isMet ? '✅ 已解锁' : '🔒 待完成';
                    const colorStyle = isMet ? 'color:#10b981; border:1px solid rgba(16,185,129,0.3); background:rgba(16,185,129,0.08);' : 'color:#f59e0b; border:1px solid rgba(245,158,11,0.3); background:rgba(245,158,11,0.08);';
                    return `<span class="node-tag-item" style="${colorStyle}">${metBadge} · ${p}</span>`;
                }).join(' ');
            }
        }

        // 撰写按钮：始终可用，不锁死
        if (btnGen) {
            const isPub = statusText.includes('已群发');
            const isDraft = statusText.includes('草稿箱');

            btnGen.disabled = false;
            if (isPub) {
                btnGen.innerHTML = '<span class="btn-icon">🔄</span> 重新撰写/覆盖已群发推文';
            } else if (isDraft) {
                btnGen.innerHTML = '<span class="btn-icon">🔄</span> 重新撰写/覆盖草稿箱推文';
            } else {
                btnGen.innerHTML = '<span class="btn-icon">🚀</span> 开始撰写此知识点';
            }
            btnGen.onclick = () => {
                modal.style.display = 'none';
                startGenerateNode(node.id);
            };
        }

        // 手动标记按钮：根据当前状态动态显隐，始终可操作
        const btnPub = document.getElementById('btn-override-published-modal');
        const btnDraft = document.getElementById('btn-override-draft-modal');
        const btnReset = document.getElementById('btn-override-reset-modal');
        if (btnPub) btnPub.style.display = (statusClass === 'published' && statusText.includes('已群发')) ? 'none' : '';
        if (btnDraft) btnDraft.style.display = (statusText.includes('草稿箱')) ? 'none' : '';
        if (btnReset) btnReset.style.display = (statusClass === 'available' || statusClass === 'locked') ? 'none' : '';

        modal.style.display = 'flex';
    }

    async function setNodeStatusOverride(status) {
        if (!currentModalNode || !currentModalNode.id) return;
        const modal = document.getElementById('skill-node-modal');
        try {
            const res = await fetch('/api/aikepu/set_node_status', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ node_id: currentModalNode.id, status: status })
            });
            const data = await res.json();
            if (data.status === 'success') {
                appendLog(`[Skill Tree] 🔧 节点 [${currentModalNode.id}] 状态已设为: ${status}`, 'system');
                if (modal) modal.style.display = 'none';
                loadSkillTreeVisualizer(true);
                updateSkillTreeStats();
            } else {
                alert('节点状态变更失败: ' + (data.message || '未知错误'));
            }
        } catch (e) {
            alert('网络请求失败: ' + e);
        }
    }

    // Modal Status Override Buttons
    const btnOverridePub = document.getElementById('btn-override-published-modal');
    if (btnOverridePub) btnOverridePub.addEventListener('click', () => setNodeStatusOverride('published'));

    const btnOverrideDraft = document.getElementById('btn-override-draft-modal');
    if (btnOverrideDraft) btnOverrideDraft.addEventListener('click', () => setNodeStatusOverride('draft'));

    const btnOverrideReset = document.getElementById('btn-override-reset-modal');
    if (btnOverrideReset) btnOverrideReset.addEventListener('click', () => setNodeStatusOverride('reset'));

    async function startGenerateNode(nodeId) {
        try {
            appendLog(`[Skill Tree] 🚀 用户选中节点 [${nodeId}]，准备发起 AI 科普图文撰写...`, 'system');
            
            // 切换到 Console
            const consoleNav = document.getElementById('nav-console-link');
            if (consoleNav) consoleNav.click();

            // 选中 Task Radio 为 aikepu
            const aikepuRadio = document.querySelector('input[name="task_type"][value="aikepu"]');
            if (aikepuRadio) aikepuRadio.checked = true;

            const res = await fetch('/api/aikepu/generate_node', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ node_id: nodeId })
            });

            const data = await res.json();
            if (data.status === 'success') {
                appendLog(`[Skill Tree] ✅ ${data.message}`, 'system');
            } else {
                appendLog(`[Skill Tree] ❌ 启动失败: ${data.message}`, 'error');
            }
        } catch (e) {
            appendLog(`[Skill Tree] ❌ 请求异常: ${e}`, 'error');
        }
    }

    // 事件绑定: 展开知识树按钮、微信同步按钮、刷新按钮、推荐按钮、Filter按钮、Modal关闭按钮
    const btnOpenSkillTree = document.getElementById('btn-open-skill-tree');
    if (btnOpenSkillTree) {
        btnOpenSkillTree.addEventListener('click', () => {
            const navSkillTree = document.getElementById('nav-skill-tree-link');
            if (navSkillTree) navSkillTree.click();
        });
    }

    const btnSyncWeChatSkillTree = document.getElementById('btn-sync-wechat-skill-tree');
    if (btnSyncWeChatSkillTree) {
        btnSyncWeChatSkillTree.addEventListener('click', async () => {
            appendLog('[Skill Tree] 💬 正在与微信公众号 API 真实线上状态全量同步...', 'system');
            btnSyncWeChatSkillTree.disabled = true;
            try {
                const res = await fetch('/api/aikepu/sync_wechat', { method: 'POST' });
                const data = await res.json();
                if (data.status === 'success') {
                    appendLog(`[Skill Tree] ✅ ${data.message}`, 'system');
                    alert(data.message);
                    loadSkillTreeVisualizer(true);
                    updateSkillTreeStats();
                } else {
                    appendLog(`[Skill Tree] ❌ 微信同步失败: ${data.message}`, 'error');
                    alert('微信同步失败: ' + data.message);
                }
            } catch (e) {
                appendLog(`[Skill Tree] ❌ 微信同步请求异常: ${e}`, 'error');
                alert('微信同步请求异常: ' + e);
            } finally {
                btnSyncWeChatSkillTree.disabled = false;
            }
        });
    }

    const btnRefreshSkillTree = document.getElementById('btn-refresh-skill-tree-view');
    if (btnRefreshSkillTree) {
        btnRefreshSkillTree.addEventListener('click', () => loadSkillTreeVisualizer(true));
    }

    const btnStartRecommended = document.getElementById('btn-start-recommended-node');
    if (btnStartRecommended) {
        btnStartRecommended.addEventListener('click', () => {
            if (skillTreeDataCache && skillTreeDataCache.available_ids && skillTreeDataCache.available_ids.length > 0) {
                startGenerateNode(skillTreeDataCache.available_ids[0]);
            } else {
                alert('当前暂无解锁的可生成节点');
            }
        });
    }

    // Filter Buttons
    document.querySelectorAll('.tree-filter-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tree-filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentFilterTier = btn.getAttribute('data-filter') || 'all';
            renderSkillTreeGraph();
        });
    });

    // Modal Close
    const btnCloseNodeModal = document.getElementById('btn-close-node-modal');
    const btnCancelNodeModal = document.getElementById('btn-cancel-node-modal');
    const skillNodeModal = document.getElementById('skill-node-modal');

    if (btnCloseNodeModal && skillNodeModal) {
        btnCloseNodeModal.addEventListener('click', () => skillNodeModal.style.display = 'none');
    }
    if (btnCancelNodeModal && skillNodeModal) {
        btnCancelNodeModal.addEventListener('click', () => skillNodeModal.style.display = 'none');
    }

    // 页面初始化时自动调一次以载入缓存/渲染拓扑图谱
    loadSkillTreeVisualizer();

    window.addEventListener('resize', () => {
        const skillTreeSec = document.getElementById('skill-tree-view');
        if (skillTreeDataCache && skillTreeSec && skillTreeSec.classList.contains('active')) {
            renderSkillTreeGraph();
        }
    });

    // --- Adaptive Polling ---
    let pollTimer = null;
    function schedulePoll() {
        const interval = isRunning ? 1000 : 5000;
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

                // 每次轮询同步刷新 Prompt Cache 状态与 AI 科普技能树进度
                updateCacheMetrics();
                updateSkillTreeStats();
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
    // 页面初次加载立即触发一次同步
    updateCacheMetrics();
    updateSkillTreeStats();
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
            document.getElementById('image-gen-model').value = data.IMAGE_GEN_MODEL || 'Google Gemini Imagen 3';
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
                    `<span class="badge" style="background:#10B981; color:#ffffff; padding:2px 6px;">${activeBadgeText}</span>` : 
                    `<span class="badge" style="background:#F59E0B; color:#ffffff; padding:2px 6px;">${pausedBadgeText}</span>`;
                
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
