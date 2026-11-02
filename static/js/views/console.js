// static/js/views/console.js
// Console Stage View Controller - Visual Pipeline Execution & Telemetry

import { api, showToast } from '../core/api.js';
import { State, WORKFLOW_STATES } from '../core/state.js';
import { getIcon } from '../core/icons.js';
import { createInitialPipelineModel, parseLogs } from '../core/log-parser.js';

let statusPollTimer = null;
let telemetryPollTimer = null;

export function initConsoleView() {
  bindWorkflowSelector();
  bindActionButtons();
  bindViewModeToggles();
  bindAccordionToggles();

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
  const buttons = document.querySelectorAll('.workflow-seg-btn[data-task]');
  buttons.forEach(btn => {
    btn.addEventListener('click', () => {
      const task = btn.getAttribute('data-task');
      if (task) {
        State.set({ activeWorkflow: task });
      }
    });
  });
}

function updateWorkflowSelectorUI(activeTask) {
  const buttons = document.querySelectorAll('.workflow-seg-btn[data-task]');
  buttons.forEach(btn => {
    const isSelected = btn.getAttribute('data-task') === activeTask;
    btn.classList.toggle('active', isSelected);
  });
}

function bindActionButtons() {
  const btnStart = document.getElementById('btn-start-workflow');
  const btnPause = document.getElementById('btn-pause-workflow');
  const btnResume = document.getElementById('btn-resume-workflow');
  const btnStop = document.getElementById('btn-stop-workflow');
  const btnWarmup = document.getElementById('btn-warmup-cache');
  const btnOpenTree = document.getElementById('btn-open-skill-tree');

  if (btnStart) {
    btnStart.addEventListener('click', async () => {
      try {
        State.transitionEngine(WORKFLOW_STATES.STARTING);
        const res = await api.post('/api/start', { task_type: State.activeWorkflow });
        showToast(res.message || '流水线任务已下发', 'success');
        State.transitionEngine(WORKFLOW_STATES.RUNNING);
      } catch (err) {
        State.transitionEngine(WORKFLOW_STATES.IDLE);
      }
    });
  }

  if (btnPause) {
    btnPause.addEventListener('click', async () => {
      try {
        await api.post('/api/pause');
        showToast('已下发暂停信号', 'info');
        State.transitionEngine(WORKFLOW_STATES.PAUSED);
      } catch (err) {}
    });
  }

  if (btnResume) {
    btnResume.addEventListener('click', async () => {
      try {
        await api.post('/api/resume');
        showToast('流水线已恢复执行', 'success');
        State.transitionEngine(WORKFLOW_STATES.RUNNING);
      } catch (err) {}
    });
  }

  if (btnStop) {
    btnStop.addEventListener('click', async () => {
      try {
        await api.post('/api/stop');
        showToast('已下发终止信号', 'warning');
        State.transitionEngine(WORKFLOW_STATES.STOPPING);
      } catch (err) {}
    });
  }

  if (btnWarmup) {
    btnWarmup.addEventListener('click', async () => {
      btnWarmup.disabled = true;
      try {
        const res = await api.post('/api/system/warmup_cache');
        if (res.status === 'success') {
          showToast('缓存预热成功，向量特征已装载', 'success');
        } else {
          showToast(res.message || '缓存预热完成', 'info');
        }
        refreshConsoleTelemetry();
      } catch (err) {
      } finally {
        btnWarmup.disabled = false;
      }
    });
  }

  if (btnOpenTree) {
    btnOpenTree.addEventListener('click', () => {
      State.set({ currentStage: 'graph' });
    });
  }
}

function updateEngineButtonsUI({ current }) {
  const btnStart = document.getElementById('btn-start-workflow');
  const btnPause = document.getElementById('btn-pause-workflow');
  const btnResume = document.getElementById('btn-resume-workflow');
  const btnStop = document.getElementById('btn-stop-workflow');

  const isRunning = current === WORKFLOW_STATES.RUNNING;
  const isPaused = current === WORKFLOW_STATES.PAUSED;
  const isStarting = current === WORKFLOW_STATES.STARTING;
  const isStopping = current === WORKFLOW_STATES.STOPPING;

  if (btnStart) btnStart.style.display = isRunning || isPaused || isStarting || isStopping ? 'none' : 'inline-flex';
  if (btnPause) btnPause.style.display = isRunning ? 'inline-flex' : 'none';
  if (btnResume) btnResume.style.display = isPaused ? 'inline-flex' : 'none';
  if (btnStop) btnStop.style.display = isRunning || isPaused || isStarting || isStopping ? 'inline-flex' : 'none';
}

function bindViewModeToggles() {
  const btnTimeline = document.getElementById('btn-mode-timeline');
  const btnRaw = document.getElementById('btn-mode-raw');
  const btnClear = document.getElementById('btn-clear-logs');

  if (btnTimeline) {
    btnTimeline.addEventListener('click', () => {
      State.set({ logViewMode: 'timeline' });
    });
  }
  if (btnRaw) {
    btnRaw.addEventListener('click', () => {
      State.set({ logViewMode: 'raw' });
    });
  }
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
  const btnTimeline = document.getElementById('btn-mode-timeline');
  const btnRaw = document.getElementById('btn-mode-raw');
  const timelineView = document.getElementById('pipeline-timeline-view');
  const rawWell = document.getElementById('pipeline-raw-well');

  const isTimeline = mode === 'timeline';
  if (btnTimeline) btnTimeline.classList.toggle('active', isTimeline);
  if (btnRaw) btnRaw.classList.toggle('active', !isTimeline);

  if (timelineView) timelineView.style.display = isTimeline ? 'flex' : 'none';
  if (rawWell) rawWell.style.display = isTimeline ? 'none' : 'flex';
}

function bindAccordionToggles() {
  const headers = document.querySelectorAll('.phase-accordion-header[data-phase]');
  headers.forEach(h => {
    h.addEventListener('click', () => {
      const card = h.closest('.phase-card');
      if (card) {
        card.classList.toggle('open');
      }
    });
  });
}

export async function refreshConsoleTelemetry() {
  try {
    const cacheStats = await api.get('/api/system/llm_cache_stats');
    if (cacheStats && !cacheStats.error) {
      const hitRateEl = document.getElementById('stat-hit-rate');
      const savedTokensEl = document.getElementById('stat-saved-tokens');
      const savedCnyEl = document.getElementById('stat-saved-cny');
      const latencyEl = document.getElementById('stat-latency');

      if (hitRateEl) hitRateEl.textContent = `${cacheStats.hit_rate_pct || '0'}%`;
      if (savedTokensEl) savedTokensEl.textContent = `${cacheStats.saved_tokens || '0'}`;
      if (savedCnyEl) savedCnyEl.textContent = `¥${cacheStats.saved_cny || '0.00'}`;
      if (latencyEl) latencyEl.textContent = `${cacheStats.avg_latency_ms || '0'}ms`;
    }
  } catch (_) {}

  try {
    const treeStats = await api.get('/api/aikepu/tree_stats');
    if (treeStats && !treeStats.error) {
      const ratioEl = document.getElementById('skill-tree-ratio');
      const barEl = document.getElementById('skill-tree-progress-bar');
      const nextTopicEl = document.getElementById('skill-tree-next-topic');

      const completed = treeStats.published_count || 0;
      const total = treeStats.total_nodes || 30;
      const pct = Math.round((completed / (total || 1)) * 100);

      if (ratioEl) ratioEl.textContent = `${completed}/${total} 篇 (${pct}%)`;
      if (barEl) barEl.style.width = `${pct}%`;
      if (nextTopicEl && treeStats.next_recommended_topic) {
        nextTopicEl.textContent = treeStats.next_recommended_topic;
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

async function pollPipelineStatus() {
  try {
    const data = await api.get('/api/status');
    if (!data) return;

    if (data.is_paused) {
      State.transitionEngine(WORKFLOW_STATES.PAUSED);
    } else if (data.is_running) {
      State.transitionEngine(WORKFLOW_STATES.RUNNING);
    } else {
      if (State.engineState === WORKFLOW_STATES.RUNNING || State.engineState === WORKFLOW_STATES.STOPPING) {
        State.transitionEngine(WORKFLOW_STATES.COMPLETED);
        setTimeout(() => {
          if (State.engineState === WORKFLOW_STATES.COMPLETED) {
            State.transitionEngine(WORKFLOW_STATES.IDLE);
          }
        }, 3000);
      }
    }

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
    }

    const titleEl = stepEl.querySelector('.step-node-title');
    if (titleEl) {
      titleEl.textContent = phaseNames[i - 1];
    }
  }
}

function renderPhase1Card(phase) {
  const topicEl = document.getElementById('phase1-locked-topic');
  const countEl = document.getElementById('phase1-source-count');
  if (topicEl && phase.lockedTopic) {
    topicEl.textContent = phase.lockedTopic;
  }
  if (countEl && phase.candidatesCount) {
    countEl.textContent = `${phase.candidatesCount} 篇候选`;
  }
}

function renderPhase2Card(phase) {
  const wordsEl = document.getElementById('phase2-word-count');
  const sectionsEl = document.getElementById('phase2-sections-list');
  if (wordsEl && phase.wordCount) {
    wordsEl.textContent = `${phase.wordCount} 字`;
  }
  if (sectionsEl && Array.isArray(phase.sections) && phase.sections.length > 0) {
    sectionsEl.innerHTML = phase.sections.map(s => `<div class="phase2-section-item">${getIcon('check', 12)} <span>${escapeHtml(s)}</span></div>`).join('');
  }
}

function renderPhase3Card(phase) {
  const grid = document.getElementById('phase3-slots-grid');
  if (!grid || !Array.isArray(phase.slots)) return;

  grid.innerHTML = phase.slots.map(s => {
    const isDone = s.status === 'completed';
    return `
      <div class="asset-slot-card ${isDone ? 'done' : 'waiting'}">
        <div class="slot-head">
          <span class="slot-title">${escapeHtml(s.label)}</span>
          <span class="slot-tag ${isDone ? 'tag-success' : 'tag-muted'}">${isDone ? '就绪' : '等待'}</span>
        </div>
        <div class="slot-detail">${escapeHtml(s.detail || '等待提词流水线')}</div>
      </div>
    `;
  }).join('');
}

function renderPhase4Card(phase) {
  const scoreEl = document.getElementById('phase4-quality-score');
  const draftEl = document.getElementById('phase4-draft-id');
  const card = document.getElementById('phase-card-4');

  if (scoreEl && phase.qualityScore !== null) {
    scoreEl.textContent = `${phase.qualityScore} 分`;
  }
  if (draftEl && phase.draftId) {
    draftEl.textContent = phase.draftId;
  }
  if (card && phase.status === 'completed') {
    card.classList.add('highlight-completed', 'open');
  }
}

function renderRawLogs(rawLines) {
  const well = document.getElementById('pipeline-raw-well');
  if (!well || !Array.isArray(rawLines)) return;

  well.innerHTML = rawLines.map(line => `<div class="raw-log-line">${escapeHtml(line)}</div>`).join('');
  well.scrollTop = well.scrollHeight;
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
