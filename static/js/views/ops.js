// static/js/views/ops.js
// Ops Stage View Controller - Source Health Matrix, Cron Scheduler & Settings

import { apiGet, apiPost, showToast } from '../core/api.js';
import { State } from '../core/state.js';
import { icon } from '../core/icons.js';

let activeOpsTab = 'sources';
let sourcesPollTimer = null;

export function initOpsView() {
  bindOpsTabs();
  bindSourcesActions();
  bindScheduleActions();
  bindSettingsForm();

  activeOpsTab = State.currentOpsTab || 'sources';
  switchOpsTab(activeOpsTab);

  window.addEventListener('autowechat:view-change', (e) => {
    if (e.detail?.view === 'ops') loadActiveOpsTab();
    else stopSourcesPolling();
  });

  State.on('change:currentOpsTab', (tab) => {
    if (tab && tab !== activeOpsTab) switchOpsTab(tab);
  });
}

export function loadActiveOpsTab() {
  if (activeOpsTab === 'sources') {
    loadSourcesMatrix();
    startSourcesPolling();
  } else if (activeOpsTab === 'schedule') {
    stopSourcesPolling();
    loadScheduleJobs();
  } else if (activeOpsTab === 'settings') {
    stopSourcesPolling();
    loadSystemSettings();
  }
}

function bindOpsTabs() {
  document.querySelectorAll('[data-ops-tab]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const tab = btn.getAttribute('data-ops-tab');
      if (tab) {
        State.set({ currentOpsTab: tab });
        switchOpsTab(tab);
      }
    });
  });
}

function switchOpsTab(tab) {
  activeOpsTab = tab;
  document.querySelectorAll('[data-ops-tab]').forEach((btn) => {
    btn.classList.toggle('active', btn.getAttribute('data-ops-tab') === tab);
  });

  const subviews = {
    sources: document.getElementById('ops-subview-sources'),
    schedule: document.getElementById('ops-subview-schedule'),
    settings: document.getElementById('ops-subview-settings')
  };
  for (const [k, el] of Object.entries(subviews)) {
    if (el) el.classList.toggle('active', k === tab);
  }
  loadActiveOpsTab();
}

function startSourcesPolling() {
  stopSourcesPolling();
  sourcesPollTimer = setInterval(() => {
    if (State.currentStage === 'ops' && activeOpsTab === 'sources') loadSourcesMatrix(true);
    else stopSourcesPolling();
  }, 5000);
}

function stopSourcesPolling() {
  if (sourcesPollTimer) {
    clearInterval(sourcesPollTimer);
    sourcesPollTimer = null;
  }
}

// --- Subview 1: Source Health Matrix ---
async function loadSourcesMatrix(isBg = false) {
  const container = document.getElementById('sources-matrix-container') || document.querySelector('.sources-matrix-grid');
  if (!container) return;
  if (!isBg) {
    container.innerHTML = `<div style="grid-column:1/-1;padding:24px;text-align:center;color:var(--text-secondary);font-size:13px;">${icon('refresh', 16)} 正在读取信源健康状态...</div>`;
  }

  try {
    const data = await apiGet('/api/sources');
    const sources = data?.sources || {};
    const keys = Object.keys(sources);
    if (keys.length === 0) {
      container.innerHTML = `<div style="grid-column:1/-1;padding:24px;text-align:center;color:var(--text-muted);font-size:13px;">暂无已注册信源数据</div>`;
      return;
    }

    let html = '';
    for (const name of keys) {
      const info = sources[name] || {};
      const status = info.status || 'healthy';
      const isOk = status === 'healthy';
      const isWarn = status === 'degraded';
      const cls = isOk ? 'badge-success' : isWarn ? 'badge-warning' : 'badge-danger';
      const text = isOk ? '健康运行' : isWarn ? '延迟稍高' : '连接异常';
      const dot = isOk ? 'var(--status-success)' : isWarn ? 'var(--status-warning)' : 'var(--status-danger)';

      html += `
        <div class="source-item-card">
          <div class="source-item-header">
            <span class="source-item-name">${escapeHtml(name)}</span>
            <span class="badge ${cls}"><span style="width:5px;height:5px;border-radius:50%;background:${dot};"></span>${text}</span>
          </div>
          <div class="source-item-meta">
            <span>协议: ${escapeHtml(info.type || 'RSS/API')}</span>
            <span class="mono">${info.latency_ms ? `${info.latency_ms}ms` : '就绪'}</span>
          </div>
          ${info.detail ? `<div style="font-size:11px;color:var(--text-muted);line-height:1.3;" class="truncate">${escapeHtml(info.detail)}</div>` : ''}
        </div>`;
    }
    container.innerHTML = html;
  } catch (err) {
    if (!isBg) container.innerHTML = `<div style="grid-column:1/-1;padding:20px;text-align:center;color:var(--status-danger);font-size:13px;">加载信源异常: ${err.message}</div>`;
  }
}

function bindSourcesActions() {
  const btn = document.getElementById('btn-test-sources');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    const origHtml = btn.innerHTML;
    btn.innerHTML = `${icon('refresh', 14)} 探测中...`;
    try {
      const data = await apiPost('/api/sources/test');
      if (data?.status === 'success') {
        showToast('全量信源连通性测试完成', 'success');
        loadSourcesMatrix(false);
      } else {
        showToast(data?.message || '信源检测未通过', 'warning');
      }
    } catch (err) {
      showToast(`信源测试失败: ${err.message}`, 'error');
    } finally {
      btn.disabled = false;
      btn.innerHTML = origHtml;
    }
  });
}

// --- Subview 2: Cron Scheduler ---
async function loadScheduleJobs() {
  const container = document.getElementById('schedule-jobs-container') || document.querySelector('.schedule-jobs-list');
  if (!container) return;
  container.innerHTML = `<div style="padding:24px;text-align:center;color:var(--text-secondary);font-size:13px;">${icon('refresh', 16)} 正在读取定时任务列表...</div>`;

  try {
    const data = await apiGet('/api/schedule/jobs');
    const jobs = data?.jobs || [];
    if (jobs.length === 0) {
      container.innerHTML = `<div style="padding:32px;text-align:center;color:var(--text-muted);font-size:13px;background:var(--bg-elevated);border:1px dashed var(--border-color);border-radius:var(--radius-md);">当前暂无活跃的定时发布任务</div>`;
      return;
    }

    let html = '';
    for (const job of jobs) {
      const active = job.status === 'active';
      html += `
        <div class="schedule-job-card" data-job-id="${job.id}">
          <div style="display:flex;flex-direction:column;gap:4px;">
            <div style="display:flex;align-items:center;gap:8px;">
              <span style="font-weight:600;font-size:13px;color:var(--text-primary);">${escapeHtml(job.task_type || 'hotspots')}</span>
              <span class="badge ${active ? 'badge-success' : 'badge-warning'}">${active ? '运行中' : '已暂停'}</span>
            </div>
            <div style="font-size:11px;color:var(--text-secondary);display:flex;align-items:center;gap:12px;">
              <span>Cron: <code class="mono">${escapeHtml(job.cron_expr || 'N/A')}</code></span>
              <span>下次运行: <span class="mono">${escapeHtml(job.next_run_time || '待调度')}</span></span>
            </div>
          </div>
          <div style="display:flex;align-items:center;gap:6px;">
            <button class="btn btn-secondary btn-sm ${active ? 'btn-pause-job' : 'btn-resume-job'}" data-id="${job.id}">
              ${active ? `${icon('pause', 12)} 暂停` : `${icon('play', 12)} 恢复`}
            </button>
            <button class="btn btn-ghost btn-sm btn-remove-job" data-id="${job.id}" style="color:var(--status-danger);">${icon('trash', 12)} 删除</button>
          </div>
        </div>`;
    }
    container.innerHTML = html;
    bindJobRowActions(container);
  } catch (err) {
    container.innerHTML = `<div style="padding:20px;text-align:center;color:var(--status-danger);font-size:13px;">加载定时任务异常: ${err.message}</div>`;
  }
}

function bindJobRowActions(container) {
  container.querySelectorAll('.btn-pause-job').forEach((btn) => {
    btn.addEventListener('click', async () => {
      try {
        await apiPost('/api/schedule/pause', { job_id: btn.dataset.id });
        showToast('定时任务已暂停', 'info');
        loadScheduleJobs();
      } catch (e) { showToast(`暂停失败: ${e.message}`, 'error'); }
    });
  });

  container.querySelectorAll('.btn-resume-job').forEach((btn) => {
    btn.addEventListener('click', async () => {
      try {
        await apiPost('/api/schedule/resume', { job_id: btn.dataset.id });
        showToast('定时任务已恢复', 'success');
        loadScheduleJobs();
      } catch (e) { showToast(`恢复失败: ${e.message}`, 'error'); }
    });
  });

  container.querySelectorAll('.btn-remove-job').forEach((btn) => {
    btn.addEventListener('click', async () => {
      if (!confirm('确认删除此定时任务？')) return;
      try {
        await apiPost('/api/schedule/remove', { job_id: btn.dataset.id });
        showToast('定时任务已移除', 'info');
        loadScheduleJobs();
      } catch (e) { showToast(`删除失败: ${e.message}`, 'error'); }
    });
  });
}

function bindScheduleActions() {
  const btn = document.getElementById('btn-add-job') || document.getElementById('btn-add-schedule');
  const typeSelect = document.getElementById('schedule-workflow') || document.getElementById('sched-task-type');
  const cronInput = document.getElementById('schedule-time') || document.getElementById('sched-cron');
  if (!btn) return;

  btn.addEventListener('click', async () => {
    const taskType = typeSelect?.value || 'hotspots';
    const cronExpr = cronInput?.value.trim() || '';
    if (!cronExpr) return showToast('请输入合法的 Cron 表达式 (例如: 0 8 * * *)', 'warning');

    btn.disabled = true;
    const origHtml = btn.innerHTML;
    btn.innerHTML = `${icon('clock', 14)} 添加中...`;

    try {
      const res = await apiPost('/api/schedule/add', { task_type: taskType, cron_expr: cronExpr });
      if (res?.status === 'success') {
        showToast('定时发布任务添加成功', 'success');
        if (cronInput) cronInput.value = '';
        loadScheduleJobs();
      } else {
        showToast(res?.message || '添加失败', 'error');
      }
    } catch (err) {
      showToast(`添加任务异常: ${err.message}`, 'error');
    } finally {
      btn.disabled = false;
      btn.innerHTML = origHtml;
    }
  });
}

// --- Subview 3: System Settings ---
async function loadSystemSettings() {
  try {
    const [cfg, sd] = await Promise.all([
      apiGet('/api/config'),
      apiGet('/api/system/sd_status').catch(() => null)
    ]);

    if (cfg) {
      ['wechat-appid', 'wechat-secret', 'llm-apikey', 'dashscope-apikey', 'qywechat-webhook'].forEach((k) => {
        const keyMap = { 'wechat-appid': cfg.WECHAT_APP_ID, 'wechat-secret': cfg.WECHAT_APP_SECRET, 'llm-apikey': cfg.LLM_API_KEY, 'dashscope-apikey': cfg.DASHSCOPE_API_KEY, 'qywechat-webhook': cfg.QYWECHAT_WEBHOOK };
        const el = document.getElementById(k);
        if (el && keyMap[k] !== undefined) el.value = keyMap[k];
      });
      const dWorkers = document.getElementById('diagram-workers');
      if (dWorkers) dWorkers.value = cfg.DIAGRAM_PARALLEL_WORKERS || '5';

      setSelect('llm-model', cfg.LLM_MODEL);
      setSelect('qwen-image-model', cfg.QWEN_IMAGE_MODEL);
      setSelect('qwen-vl-model', cfg.QWEN_VL_MODEL);
      setSelect('image-gen-model', cfg.IMAGE_GEN_MODEL || 'qwen-image-3.0');
    }

    const sdEl = document.getElementById('sd-status-indicator');
    if (sdEl && sd) {
      sdEl.className = `badge ${sd.connected ? 'badge-success' : 'badge-neutral'}`;
      sdEl.textContent = sd.connected ? `已连接 (${sd.url})` : '文字卡片兜底模式';
    }
  } catch (err) {
    showToast(`载入系统配置失败: ${err.message}`, 'error');
  }
}

function setSelect(id, val) {
  const el = document.getElementById(id);
  if (el && val && Array.from(el.options).some((o) => o.value === val)) el.value = val;
}

function bindSettingsForm() {
  const form = document.getElementById('config-form');
  const btn = document.getElementById('btn-save-config') || document.getElementById('btn-save-settings');

  const onSave = async (e) => {
    e?.preventDefault();
    const payload = {
      WECHAT_APP_ID: getVal('wechat-appid'),
      WECHAT_APP_SECRET: getVal('wechat-secret'),
      LLM_API_KEY: getVal('llm-apikey'),
      DASHSCOPE_API_KEY: getVal('dashscope-apikey'),
      LLM_MODEL: getVal('llm-model'),
      QWEN_IMAGE_MODEL: getVal('qwen-image-model'),
      QWEN_VL_MODEL: getVal('qwen-vl-model'),
      IMAGE_GEN_MODEL: getVal('image-gen-model'),
      QYWECHAT_WEBHOOK: getVal('qywechat-webhook'),
      DIAGRAM_PARALLEL_WORKERS: getVal('diagram-workers') || '5'
    };

    if (btn) { btn.disabled = true; btn.textContent = '正在保存...'; }
    try {
      const res = await apiPost('/api/config', payload);
      if (res?.status === 'success') showToast('系统设置已成功保存', 'success');
      else showToast(res?.message || '设置保存未成功', 'warning');
    } catch (err) {
      showToast(`保存异常: ${err.message}`, 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '保存全部设置'; }
    }
  };

  if (form) form.addEventListener('submit', onSave);
  if (btn && (!form || btn.form !== form)) btn.addEventListener('click', onSave);
}

function getVal(id) {
  return document.getElementById(id)?.value.trim() || '';
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
