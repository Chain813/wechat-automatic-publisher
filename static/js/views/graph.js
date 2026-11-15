// static/js/views/graph.js
// Knowledge Graph View Controller - Connected Papers DAG Canvas & HUD

import { api, showToast } from '../core/api.js';
import { State } from '../core/state.js';
import { getIcon } from '../core/icons.js';

let graphCache = null;
let activeFilter = 'all';

export function initGraphView() {
  bindTreeControls();
  bindFilterPills();
  bindHudControls();

  loadKnowledgePacks();
  loadGraphData(false);

  window.addEventListener('resize', debounce(() => {
    if (State.currentStage === 'graph' && graphCache) {
      drawConnectors(graphCache.nodes);
    }
  }, 100));
}

function bindTreeControls() {
  const selectTree = document.getElementById('knowledge-tree-select');
  const btnImport = document.getElementById('btn-import-tree');
  const fileInput = document.getElementById('tree-file-input');
  const btnSync = document.getElementById('btn-sync-wechat-skill-tree');
  const btnRefresh = document.getElementById('btn-refresh-skill-tree-view');
  const btnRecommend = document.getElementById('btn-start-recommended-node');

  if (selectTree) {
    selectTree.addEventListener('change', async () => {
      const name = selectTree.value;
      if (!name) return;
      try {
        await api.post('/api/kepu/active', { name });
        showToast('已切换知识体系主题包', 'success');
        loadGraphData(true);
      } catch (_) {}
    });
  }

  if (btnImport && fileInput) {
    btnImport.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', async () => {
      const file = fileInput.files && fileInput.files[0];
      if (!file) return;
      const formData = new FormData();
      formData.append('file', file);
      try {
        const res = await api.upload('/api/kepu/import', formData);
        showToast(res.message || '主题包导入成功', 'success');
        loadKnowledgePacks();
        loadGraphData(true);
      } catch (_) {}
      fileInput.value = '';
    });
  }

  if (btnSync) {
    btnSync.addEventListener('click', async () => {
      btnSync.disabled = true;
      try {
        const res = await api.post('/api/aikepu/sync_wechat');
        showToast(res.message || '微信图文状态已同步', 'success');
        loadGraphData(true);
      } catch (_) {}
      btnSync.disabled = false;
    });
  }

  if (btnRefresh) {
    btnRefresh.addEventListener('click', () => loadGraphData(true));
  }

  if (btnRecommend) {
    btnRecommend.addEventListener('click', async () => {
      if (!graphCache || !Array.isArray(graphCache.available_ids) || graphCache.available_ids.length === 0) {
        showToast('当前暂无待撰写的解锁节点', 'info');
        return;
      }
      const targetId = graphCache.available_ids[0];
      try {
        await api.post('/api/aikepu/generate_node', { node_id: targetId });
        showToast(`已下发推荐节点 [${targetId}] 撰写任务`, 'success');
        State.set({ currentStage: 'console' });
      } catch (_) {}
    });
  }
}

function bindFilterPills() {
  const pills = document.querySelectorAll('.tree-filter-btn[data-filter]');
  pills.forEach(pill => {
    pill.addEventListener('click', () => {
      pills.forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      activeFilter = pill.getAttribute('data-filter') || 'all';
      applyTierFilter(activeFilter);
    });
  });
}

function applyTierFilter(filter) {
  for (let i = 1; i <= 4; i++) {
    const col = document.getElementById(`tier-column-${i}`);
    if (col) {
      if (filter === 'all' || filter === String(i)) {
        col.style.display = 'flex';
      } else {
        col.style.display = 'none';
      }
    }
  }
  if (graphCache) {
    requestAnimationFrame(() => drawConnectors(graphCache.nodes));
  }
}

async function loadKnowledgePacks() {
  try {
    const res = await api.get('/api/kepu/trees');
    const select = document.getElementById('knowledge-tree-select');
    if (!select || !res || !Array.isArray(res.trees)) return;

    select.innerHTML = res.trees.map(tree => {
      const isSelected = tree.id === res.active;
      return `<option value="${escapeHtml(tree.id)}" ${isSelected ? 'selected' : ''}>${escapeHtml(tree.name || tree.id)}</option>`;
    }).join('');
  } catch (_) {}
}

export async function loadGraphData(forceRefresh = false) {
  try {
    const data = await api.get(`/api/aikepu/full_tree?force=${forceRefresh ? 1 : 0}`);
    if (!data || data.status === 'error') {
      showToast(data ? data.message : '获取图谱失败', 'error');
      return;
    }
    graphCache = data;
    renderGraphUI(data);
  } catch (_) {}
}

function renderGraphUI(data) {
  const { published_ids = [], draft_ids = [], available_ids = [], nodes = [], stats = {} } = data;

  const pubCountEl = document.getElementById('legend-published-count');
  const availCountEl = document.getElementById('legend-available-count');
  const lockCountEl = document.getElementById('legend-locked-count');

  if (pubCountEl) pubCountEl.textContent = stats.published_count || published_ids.length;
  if (availCountEl) availCountEl.textContent = stats.available_count || available_ids.length;
  if (lockCountEl) lockCountEl.textContent = stats.locked_count || (nodes.length - published_ids.length - available_ids.length);

  for (let i = 1; i <= 4; i++) {
    const container = document.getElementById(`tier-nodes-${i}`);
    if (container) container.innerHTML = '';
  }

  nodes.forEach(node => {
    const tier = Number(node.tier) || 1;
    const container = document.getElementById(`tier-nodes-${tier}`) || document.getElementById('tier-nodes-1');
    if (!container) return;

    let nodeStatus = 'locked';
    if (published_ids.includes(node.id)) {
      nodeStatus = 'published';
    } else if (draft_ids.includes(node.id)) {
      nodeStatus = 'draft';
    } else if (available_ids.includes(node.id)) {
      nodeStatus = 'available';
    }

    const card = document.createElement('div');
    card.className = `graph-node-card status-${nodeStatus} ${nodeStatus}`;
    card.setAttribute('data-node-id', node.id);
    card.innerHTML = `
      <div class="node-card-head">
        <span class="node-id-tag">${escapeHtml(node.id)}</span>
        <span class="node-status-tag tag-${nodeStatus}">${nodeStatus === 'published' ? '已发布' : nodeStatus === 'draft' ? '草稿' : nodeStatus === 'available' ? '可撰写' : '未解锁'}</span>
      </div>
      <div class="node-title">${escapeHtml(node.title || node.id)}</div>
      <div class="node-footer">
        <span class="node-tier-label">阶梯 ${tier}</span>
        ${nodeStatus === 'available' ? '<span class="node-action-hint">点击核阅</span>' : ''}
      </div>
    `;

    card.addEventListener('click', () => {
      selectNode(node, nodeStatus);
    });

    container.appendChild(card);
  });

  requestAnimationFrame(() => drawConnectors(nodes));
}

function selectNode(node, status) {
  State.set({ selectedNode: node });

  document.querySelectorAll('.graph-node-card').forEach(c => c.classList.remove('selected'));
  const activeCard = document.querySelector(`.graph-node-card[data-node-id="${node.id}"]`);
  if (activeCard) activeCard.classList.add('selected');

  populateHud(node, status);
  openHud();
}

function populateHud(node, status) {
  const badgeEl = document.getElementById('hud-node-badge');
  const idEl = document.getElementById('hud-node-id');
  const statusEl = document.getElementById('hud-node-status');
  const titleEl = document.getElementById('hud-node-title');
  const summaryEl = document.getElementById('hud-node-summary');
  const tagsEl = document.getElementById('hud-node-tags');
  const prereqsEl = document.getElementById('hud-node-prereqs');

  if (badgeEl) badgeEl.textContent = `阶梯 ${node.tier || 1}`;
  if (idEl) idEl.textContent = node.id;
  if (statusEl) {
    statusEl.textContent = status === 'published' ? '已发布' : status === 'draft' ? '草稿箱' : status === 'available' ? '今日推荐' : '锁定中';
    statusEl.className = `hud-status-badge status-${status}`;
  }
  if (titleEl) titleEl.textContent = node.title || node.id;
  if (summaryEl) summaryEl.textContent = node.summary || node.description || '暂无详细大纲，可直接下发大模型撰写。';

  if (tagsEl && Array.isArray(node.tags)) {
    tagsEl.innerHTML = node.tags.map(t => `<span class="hud-tag">${escapeHtml(t)}</span>`).join('');
  }

  if (prereqsEl) {
    const prereqs = Array.isArray(node.prerequisites) ? node.prerequisites : [];
    if (prereqs.length === 0) {
      prereqsEl.innerHTML = '<span class="hud-empty-hint">无前置依赖（启蒙基石）</span>';
    } else {
      prereqsEl.innerHTML = prereqs.map(p => `<span class="hud-prereq-item">${getIcon('check', 12)} ${escapeHtml(p)}</span>`).join('');
    }
  }
}

function bindHudControls() {
  const hud = document.getElementById('graph-hud-inspector');
  const btnToggle = document.getElementById('btn-toggle-hud');
  const backdrop = document.getElementById('hud-close-backdrop');

  const btnMarkPub = document.getElementById('btn-hud-mark-published');
  const btnMarkDraft = document.getElementById('btn-hud-mark-draft');
  const btnMarkReset = document.getElementById('btn-hud-mark-reset');
  const btnGenerate = document.getElementById('btn-hud-generate-node');

  if (btnToggle && hud) {
    btnToggle.addEventListener('click', () => {
      if (hud.classList.contains('collapsed')) openHud();
      else closeHud();
    });
  }

  if (backdrop) backdrop.addEventListener('click', closeHud);

  const handleStatusChange = async (targetStatus) => {
    const node = State.selectedNode;
    if (!node || !node.id) return;
    try {
      const res = await api.post('/api/aikepu/set_node_status', { node_id: node.id, status: targetStatus });
      showToast(res.message || '状态设置成功', 'success');
      loadGraphData(false);
      populateHud(node, targetStatus);
    } catch (_) {}
  };

  if (btnMarkPub) btnMarkPub.addEventListener('click', () => handleStatusChange('published'));
  if (btnMarkDraft) btnMarkDraft.addEventListener('click', () => handleStatusChange('draft'));
  if (btnMarkReset) btnMarkReset.addEventListener('click', () => handleStatusChange('reset'));

  if (btnGenerate) {
    btnGenerate.addEventListener('click', async () => {
      const node = State.selectedNode;
      if (!node || !node.id) return;
      try {
        await api.post('/api/aikepu/generate_node', { node_id: node.id });
        showToast(`已下发撰写任务: ${node.title || node.id}`, 'success');
        State.set({ currentStage: 'console' });
      } catch (_) {}
    });
  }
}

function openHud() {
  const hud = document.getElementById('graph-hud-inspector');
  const backdrop = document.getElementById('hud-close-backdrop');
  if (hud) {
    hud.classList.remove('collapsed');
    hud.classList.add('open-mobile');
    State.set({ hudCollapsed: false });
  }
  if (backdrop && window.innerWidth < 768) {
    backdrop.style.display = 'block';
  }
}

function closeHud() {
  const hud = document.getElementById('graph-hud-inspector');
  const backdrop = document.getElementById('hud-close-backdrop');
  if (hud) {
    hud.classList.add('collapsed');
    hud.classList.remove('open-mobile');
    State.set({ hudCollapsed: true });
  }
  if (backdrop) {
    backdrop.style.display = 'none';
  }
}

function drawConnectors(nodes = []) {
  const svg = document.getElementById('skill-tree-svg-canvas');
  const canvas = document.getElementById('dotgrid-canvas');
  if (!svg || !canvas) return;

  const canvasRect = canvas.getBoundingClientRect();
  svg.setAttribute('width', `${canvas.scrollWidth}px`);
  svg.setAttribute('height', `${canvas.scrollHeight}px`);

  const pubIds = (graphCache && graphCache.published_ids) || [];
  const availIds = (graphCache && graphCache.available_ids) || [];
  const draftIds = (graphCache && graphCache.draft_ids) || [];

  let pathsHtml = '';
  nodes.forEach(node => {
    if (!Array.isArray(node.prerequisites)) return;
    const targetCard = document.querySelector(`.graph-node-card[data-node-id="${node.id}"]`);
    if (!targetCard) return;

    const tRect = targetCard.getBoundingClientRect();
    const tx = tRect.left - canvasRect.left + canvas.scrollLeft;
    const ty = tRect.top - canvasRect.top + canvas.scrollTop + tRect.height / 2;

    const targetStatus = pubIds.includes(node.id) ? 'published' :
                         availIds.includes(node.id) ? 'available' :
                         draftIds.includes(node.id) ? 'draft' : 'locked';

    node.prerequisites.forEach(prereqId => {
      const sourceCard = document.querySelector(`.graph-node-card[data-node-id="${prereqId}"]`);
      if (!sourceCard) return;

      const sRect = sourceCard.getBoundingClientRect();
      const sx = sRect.right - canvasRect.left + canvas.scrollLeft;
      const sy = sRect.top - canvasRect.top + canvas.scrollTop + sRect.height / 2;

      const deltaX = Math.max(40, (tx - sx) / 2);
      const d = `M ${sx} ${sy} C ${sx + deltaX} ${sy}, ${tx - deltaX} ${ty}, ${tx} ${ty}`;
      pathsHtml += `<path d="${d}" class="dag-connector-line status-${targetStatus} ${targetStatus}" fill="none" />`;
    });
  });

  svg.innerHTML = pathsHtml;
}

function debounce(fn, wait) {
  let timer;
  return function (...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), wait);
  };
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
