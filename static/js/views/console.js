// static/js/views/console.js
// Console Stage View Controller - Visual Pipeline Execution & Telemetry

import { api, showToast } from '../core/api.js';
import { State, WORKFLOW_STATES } from '../core/state.js';
import { getIcon } from '../core/icons.js';
import { createInitialPipelineModel, parseLogs } from '../core/log-parser.js';

let statusPollTimer = null;
let telemetryPollTimer = null;
let logCursor = 0;
let lastNotifiedRunId = null;

export function initConsoleView() {
  bindWorkflowSelector();
  bindActionButtons();
  bindViewModeToggles();
  bindAccordionToggles();

  const sideOpenTreeBtn = document.getElementById('btn-side-open-tree');
  if (sideOpenTreeBtn) sideOpenTreeBtn.addEventListener('click', () => State.set({ currentStage: 'graph' }));

  State.on('change:activeWorkflow', updateWorkflowSelectorUI);
  State.on('change:logViewMode', updateLogViewModeUI);
  State.on('engine:state', updateEngineButtonsUI);

  updateWorkflowSelectorUI(State.activeWorkflow);
  updateLogViewModeUI(State.logViewMode);
  updateEngineButtonsUI({ current: State.engineState });

  refreshConsoleTelemetry();
  startStatusPolling();
}

function bindWorkflowSelector() {
  document.querySelectorAll('.workflow-seg-btn[data-task]').forEach(btn => {
    btn.addEventListener('click', () => {
      const task = btn.getAttribute('data-task');
      if (task) State.set({ activeWorkflow: task });
    });
  });
}

function updateWorkflowSelectorUI(activeTask) {
  document.querySelectorAll('.workflow-seg-btn[data-task]').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-task') === activeTask);
  });
}

function bindActionButtons() {
  const actions = {
    'btn-start-workflow': async () => {
      try {
        State.transitionEngine(WORKFLOW_STATES.STARTING);
        const res = await api.post('/api/start', { task_type: State.activeWorkflow });
        showToast(res.message || '流水线任务已下发', 'success');
        State.transitionEngine(WORKFLOW_STATES.RUNNING);
      } catch (_) { State.transitionEngine(WORKFLOW_STATES.IDLE); }
    },
    'btn-pause-workflow': async () => {
      try { await api.post('/api/pause'); showToast('已下发暂停信号', 'info'); State.transitionEngine(WORKFLOW_STATES.PAUSED); } catch (_) {}
    },
    'btn-resume-workflow': async () => {
      try { await api.post('/api/resume'); showToast('流水线已恢复执行', 'success'); State.transitionEngine(WORKFLOW_STATES.RUNNING); } catch (_) {}
    },
    'btn-stop-workflow': async () => {
      try { await api.post('/api/stop'); showToast('已下发终止信号', 'warning'); State.transitionEngine(WORKFLOW_STATES.STOPPING); } catch (_) {}
    },
    'btn-open-skill-tree': () => State.set({ currentStage: 'graph' })
  };

  for (const [id, fn] of Object.entries(actions)) {
    const el = document.getElementById(id);
    if (el) el.addEventListener('click', fn);
  }

  const btnWarmup = document.getElementById('btn-warmup-cache');
  if (btnWarmup) {
    btnWarmup.addEventListener('click', async () => {
      btnWarmup.disabled = true;
      try {
        const res = await api.post('/api/system/warmup_cache');
        showToast(res.status === 'success' ? '缓存预热成功，特征已装载' : (res.message || '缓存预热完成'), 'success');
        refreshConsoleTelemetry();
      } catch (_) {} finally { btnWarmup.disabled = false; }
    });
  }
}

function updateEngineButtonsUI({ current }) {
  const isRunning = current === WORKFLOW_STATES.RUNNING;
  const isPaused = current === WORKFLOW_STATES.PAUSED;
  const isStarting = current === WORKFLOW_STATES.STARTING;
  const isStopping = current === WORKFLOW_STATES.STOPPING;
  const isBusy = isRunning || isPaused || isStarting || isStopping;

  const setDisplay = (id, show) => { const el = document.getElementById(id); if (el) el.style.display = show ? 'inline-flex' : 'none'; };
  setDisplay('btn-start-workflow', !isBusy);
  setDisplay('btn-pause-workflow', isRunning);
  setDisplay('btn-resume-workflow', isPaused);
  setDisplay('btn-stop-workflow', isBusy);

  const dot = document.getElementById('status-pill-dot');
  const text = document.getElementById('status-pill-text');
  if (dot && text) {
    dot.className = 'status-dot';
    if (isStarting || isStopping || isRunning) {
      dot.classList.add('running');
      text.textContent = isStarting ? '启动中...' : isStopping ? '正在终止...' : '流水线执行中';
    } else if (isPaused) {
      dot.classList.add('paused');
      text.textContent = '任务已暂停';
    } else if (current === WORKFLOW_STATES.ERROR) {
      dot.classList.add('error');
      text.textContent = '执行失败';
    } else if (current === WORKFLOW_STATES.PARTIAL_SUCCESS) {
      dot.classList.add('paused');
      text.textContent = '部分成功';
    } else if (current === WORKFLOW_STATES.SKIPPED) {
      dot.classList.add('idle');
      text.textContent = '本次跳过';
    } else if (current === WORKFLOW_STATES.CANCELLED) {
      dot.classList.add('idle');
      text.textContent = '已手动中断';
    } else if (current === WORKFLOW_STATES.COMPLETED) {
      dot.classList.add('idle');
      text.textContent = '编排完成';
    } else {
      dot.classList.add('idle');
      text.textContent = '空闲中';
    }
  }
}

function bindViewModeToggles() {
  const btnTimeline = document.getElementById('btn-mode-timeline');
  const btnRaw = document.getElementById('btn-mode-raw');
  const btnClear = document.getElementById('btn-clear-logs');
  if (btnTimeline) btnTimeline.addEventListener('click', () => State.set({ logViewMode: 'timeline' }));
  if (btnRaw) btnRaw.addEventListener('click', () => State.set({ logViewMode: 'raw' }));
  if (btnClear) {
    btnClear.addEventListener('click', () => {
      State.pipelineModel = createInitialPipelineModel();
      renderPipelineArtifacts(State.pipelineModel);
      renderRawLogs(State.pipelineModel.rawLines);
      showToast('控制台日志已清空', 'info');
    });
  }
}

function updateLogViewModeUI(mode) {
  const isTimeline = mode === 'timeline';
  const toggle = (id, active) => { const el = document.getElementById(id); if (el) el.classList.toggle('active', active); };
  toggle('btn-mode-timeline', isTimeline);
  toggle('btn-mode-raw', !isTimeline);
  const timelineView = document.getElementById('pipeline-timeline-view');
  const rawWell = document.getElementById('pipeline-raw-well');
  if (timelineView) timelineView.style.display = isTimeline ? '' : 'none';
  if (rawWell) rawWell.style.display = isTimeline ? 'none' : 'flex';
}

function bindAccordionToggles() {
  document.querySelectorAll('.phase-accordion-header[data-phase]').forEach(h => {
    h.addEventListener('click', () => h.closest('.phase-card')?.classList.toggle('open'));
  });
}

export async function refreshConsoleTelemetry() {
  try {
    const c = await api.get('/api/system/llm_cache_stats');
    if (c && !c.error) {
      const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
      setVal('stat-hit-rate', `${c.hit_rate_pct ?? 0}%`);
      setVal('stat-saved-tokens', `${c.saved_tokens ?? c.hit_tokens ?? 0}`);
      setVal('stat-saved-cny', `¥${c.saved_cny ?? '0.00'}`);
      setVal('stat-latency', `${c.avg_latency_ms ?? c.last_latency_ms ?? 0}ms`);
    }
  } catch (_) {}

  try {
    const t = await api.get('/api/aikepu/tree_stats');
    const st = (t && t.stats) ? t.stats : t;
    if (st && !t?.error) {
      const completed = st.published_count ?? st.published ?? 0;
      const total = st.total_nodes ?? st.total ?? 30;
      const pct = Math.round((completed / (total || 1)) * 100);
      const str = `${completed}/${total} 篇 (${pct}%)`;
      const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
      setVal('skill-tree-ratio', str);
      setVal('side-tree-ratio', str);
      const bar = document.getElementById('skill-tree-progress-bar');
      if (bar) bar.style.width = `${pct}%`;
      if (st.next_recommended_topic) {
        setVal('skill-tree-next-topic', st.next_recommended_topic);
        setVal('side-next-topic', st.next_recommended_topic);
      }
    }
  } catch (_) {}
}

function startStatusPolling() {
  if (statusPollTimer) clearInterval(statusPollTimer);
  if (telemetryPollTimer) clearInterval(telemetryPollTimer);
  statusPollTimer = setInterval(pollPipelineStatus, 1800);
  telemetryPollTimer = setInterval(refreshConsoleTelemetry, 10000);
  pollPipelineStatus();
}

function applyTerminalOutcome(lastRun, wasActive) {
  if (!lastRun || !lastRun.status) {
    if (wasActive) State.transitionEngine(WORKFLOW_STATES.COMPLETED);
    return;
  }
  State.lastRun = lastRun;
  const statusMap = {
    success: [WORKFLOW_STATES.COMPLETED, 'success', '流水线执行完成'],
    partial_success: [WORKFLOW_STATES.PARTIAL_SUCCESS, 'warning', '流水线部分成功，请核查失败或未知项'],
    failed: [WORKFLOW_STATES.ERROR, 'error', '流水线执行失败'],
    skipped: [WORKFLOW_STATES.SKIPPED, 'info', '本次运行已跳过（无新可发布内容）'],
    cancelled: [WORKFLOW_STATES.CANCELLED, 'warning', '流水线已手动中断']
  };
  const [targetState, toastType, defaultMsg] = statusMap[lastRun.status] || [WORKFLOW_STATES.IDLE, 'info', ''];
  if (wasActive || State.engineState !== targetState) State.transitionEngine(targetState);
  const runKey = lastRun.run_id || `${lastRun.status}:${lastRun.finished_at || ''}`;
  if (wasActive && runKey && runKey !== lastNotifiedRunId) {
    lastNotifiedRunId = runKey;
    showToast(lastRun.summary || lastRun.error || defaultMsg, toastType);
  }
}

async function pollPipelineStatus() {
  try {
    const data = await api.get(`/api/status?since=${logCursor}`);
    if (!data) return;
    if (typeof data.next_cursor === 'number') logCursor = data.next_cursor;

    const wasActive = [WORKFLOW_STATES.RUNNING, WORKFLOW_STATES.STARTING, WORKFLOW_STATES.STOPPING, WORKFLOW_STATES.PAUSED].includes(State.engineState);
    if (data.is_paused) State.transitionEngine(WORKFLOW_STATES.PAUSED);
    else if (data.is_running) State.transitionEngine(WORKFLOW_STATES.RUNNING);
    else if (wasActive || data.last_run) applyTerminalOutcome(data.last_run, wasActive);

    if (Array.isArray(data.logs) && data.logs.length > 0) {
      State.pipelineModel = parseLogs(data.logs, State.pipelineModel);
      renderPipelineArtifacts(State.pipelineModel);
      renderRawLogs(State.pipelineModel.rawLines);
    }
  } catch (_) {}
}

function renderPipelineArtifacts(model) {
  renderStepper(model);
  renderPhase1Card(model.phases[1]);
  renderPhase2Card(model.phases[2]);
  renderPhase3Card(model.phases[3]);
  renderPhase4Card(model.phases[4]);

  const sidePhaseBadge = document.getElementById('side-active-phase');
  if (sidePhaseBadge) {
    if (model.activePhase && model.activePhase >= 1 && model.activePhase <= 4) {
      sidePhaseBadge.textContent = `Phase ${model.activePhase} Active`;
      sidePhaseBadge.className = 'badge badge-indigo';
    } else if (model.phases[4]?.status === 'completed') {
      sidePhaseBadge.textContent = 'Completed';
      sidePhaseBadge.className = 'badge badge-success';
    } else {
      sidePhaseBadge.textContent = 'Standby';
      sidePhaseBadge.className = 'badge badge-neutral';
    }
  }
}

function renderStepper(model) {
  const container = document.getElementById('pipeline-stepper');
  if (!container) return;
  const phaseNames = ['01 信源采集去重', '02 深度创作润色', '03 多模配图渲染', '04 事实核查推送'];

  for (let i = 1; i <= 4; i++) {
    const stepEl = container.querySelector(`.step-node[data-phase="${i}"]`);
    if (!stepEl) continue;
    const phase = model.phases[i];
    stepEl.classList.remove('completed', 'active', 'pending');
    stepEl.classList.add(phase.status || 'pending');

    const badgeEl = stepEl.querySelector('.step-node-badge');
    if (badgeEl) {
      badgeEl.textContent = phase.badge || (phase.status === 'completed' ? '已完成' : phase.status === 'active' ? '执行中' : '待命');
      badgeEl.className = `step-node-badge badge ${phase.status === 'completed' ? 'badge-success' : phase.status === 'active' ? 'badge-indigo' : 'badge-neutral'}`;
    }
    const titleEl = stepEl.querySelector('.step-node-title');
    if (titleEl) titleEl.textContent = phaseNames[i - 1];
  }
}

function updatePhaseBadge(badgeId, cardId, phase, idleText, activeText) {
  const badgeEl = document.getElementById(badgeId);
  const card = document.getElementById(cardId);
  const isDone = phase.status === 'completed';
  const isActive = phase.status === 'active';
  if (badgeEl) {
    badgeEl.textContent = phase.badge || (isDone ? '已完成' : isActive ? activeText : idleText);
    badgeEl.className = `badge ${isDone ? 'badge-success' : isActive ? 'badge-indigo' : 'badge-neutral'}`;
  }
  if (card && (isActive || isDone)) card.classList.add('active');
}

function renderPhase1Card(phase) {
  const topicEl = document.getElementById('phase1-locked-topic');
  const countEl = document.getElementById('phase1-source-count');
  const radarEl = document.getElementById('phase1-radar-sources');
  if (topicEl && phase.lockedTopic) topicEl.textContent = `锁定目标选题: ${phase.lockedTopic}`;
  if (countEl && phase.candidatesCount) countEl.textContent = `${phase.candidatesCount} 篇候选`;
  updatePhaseBadge('phase1-status-badge', 'phase-card-1', phase, '就绪', '扫描中');

  if (radarEl) {
    if (phase.status === 'active' || phase.status === 'completed' || (phase.items && phase.items.length > 0)) {
      const count = phase.candidatesCount || (phase.items ? phase.items.length : 14);
      radarEl.innerHTML = `<span class="badge badge-success">${getIcon('check', 11)} 微信历史库 0 冲突</span><span class="badge badge-indigo">${getIcon('radar', 11)} 全网 14 信源扫描</span><span class="badge badge-neutral">${count} 篇候选聚合</span>`;
    } else {
      radarEl.innerHTML = '<span style="color: var(--text-muted);">等待信源扫描任务下发...</span>';
    }
  }
}

function renderPhase2Card(phase) {
  const wordsEl = document.getElementById('phase2-word-count');
  const sectionsEl = document.getElementById('phase2-sections-list');
  if (wordsEl && phase.wordCount) wordsEl.textContent = `${phase.wordCount} 字`;
  updatePhaseBadge('phase2-status-badge', 'phase-card-2', phase, '等待中', '创作中');

  if (sectionsEl && Array.isArray(phase.sections) && phase.sections.length > 0) {
    sectionsEl.innerHTML = phase.sections.map(s => `<div class="phase2-section-item">${getIcon('check', 12)} <span>${escapeHtml(s)}</span></div>`).join('');
  }
}

function renderPhase3Card(phase) {
  const grid = document.getElementById('phase3-slots-grid');
  updatePhaseBadge('phase3-status-badge', 'phase-card-3', phase, '等待中', '渲染中');

  if (grid && Array.isArray(phase.slots)) {
    grid.innerHTML = phase.slots.map(s => {
      const isDone = s.status === 'completed';
      return `
        <div class="asset-slot-card ${isDone ? 'done' : 'waiting'}">
          <div class="slot-head">
            <span class="slot-title">${escapeHtml(s.label)}</span>
            <span class="slot-tag ${isDone ? 'tag-success' : 'tag-muted'}">${isDone ? '就绪' : '等待'}</span>
          </div>
          <div class="slot-detail">${escapeHtml(s.detail || '等待提词流水线')}</div>
        </div>`;
    }).join('');
  }
}

function renderPhase4Card(phase) {
  const scoreEl = document.getElementById('phase4-quality-score');
  const draftEl = document.getElementById('phase4-draft-id');
  const card = document.getElementById('phase-card-4');
  updatePhaseBadge('phase4-status-badge', 'phase-card-4', phase, '等待中', '门禁质检');

  if (scoreEl && phase.qualityScore !== null) scoreEl.textContent = `${phase.qualityScore} 分`;
  if (draftEl && phase.draftId) draftEl.textContent = phase.draftId;
  if (card && phase.status === 'completed') card.classList.add('highlight-completed', 'open');
}

function renderRawLogs(rawLines) {
  const well = document.getElementById('pipeline-raw-well');
  const miniStream = document.getElementById('pipeline-mini-stream');
  if (!Array.isArray(rawLines)) return;

  if (well) {
    well.innerHTML = rawLines.map(line => `<div class="raw-log-line">${escapeHtml(line)}</div>`).join('');
    well.scrollTop = well.scrollHeight;
  }
  if (miniStream) {
    if (rawLines.length === 0) {
      miniStream.innerHTML = '<div class="mini-stream-line muted">系统待命，就绪后实时输出最新流水线事件...</div>';
    } else {
      miniStream.innerHTML = rawLines.slice(-12).map(line => `<div class="mini-stream-line">${escapeHtml(line.trim())}</div>`).join('');
      miniStream.scrollTop = miniStream.scrollHeight;
    }
  }
}

function escapeHtml(str) {
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
