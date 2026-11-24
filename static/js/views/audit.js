// static/js/views/audit.js
// Audit Workbench View Controller - Dual-mode Desktop Table & Mobile Card Feed

import { api, showToast } from '../core/api.js';
import { getIcon } from '../core/icons.js';
import { stripEmojis } from '../core/log-parser.js';

let articlesCache = [];
let currentFilterTab = 'all';

export function initAuditView() {
  bindAuditControls();
  bindPreviewModal();
  loadAuditData();
}

function bindAuditControls() {
  const filterPills = document.querySelectorAll('.audit-filter-pill[data-tab]');
  filterPills.forEach(pill => {
    pill.addEventListener('click', () => {
      filterPills.forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      currentFilterTab = pill.getAttribute('data-tab') || 'all';
      renderArticles(filterArticles(articlesCache, currentFilterTab));
    });
  });

  const btnRefresh = document.getElementById('btn-refresh-history');
  if (btnRefresh) {
    btnRefresh.addEventListener('click', () => loadAuditData());
  }

  const chkSelectAll = document.getElementById('chk-audit-select-all');
  if (chkSelectAll) {
    chkSelectAll.addEventListener('change', () => {
      const isChecked = chkSelectAll.checked;
      const rowCheckboxes = document.querySelectorAll('.chk-article-row');
      rowCheckboxes.forEach(cb => {
        cb.checked = isChecked;
      });
      updateBatchActionsUI();
    });
  }

  const btnDeleteSelected = document.getElementById('btn-delete-selected');
  if (btnDeleteSelected) {
    btnDeleteSelected.addEventListener('click', async () => {
      const selectedIds = getSelectedArticleIds();
      if (selectedIds.length === 0) {
        showToast('请先勾选待删除的文章条目', 'warning');
        return;
      }
      if (!confirm(`确认永久删除选中的 ${selectedIds.length} 篇历史草稿？`)) {
        return;
      }
      try {
        await api.post('/api/history/delete', { ids: selectedIds });
        showToast(`已成功删除 ${selectedIds.length} 篇文章`, 'success');
        loadAuditData();
      } catch (_) {}
    });
  }
}

function bindPreviewModal() {
  const modal = document.getElementById('preview-modal');
  const btnClose = document.getElementById('btn-close-preview-modal');
  const backdrop = document.getElementById('preview-modal-backdrop');

  const closeModal = () => {
    if (modal) {
      modal.classList.remove('open');
      modal.style.display = 'none';
    }
    const iframe = document.getElementById('preview-iframe');
    if (iframe) iframe.src = 'about:blank';
  };

  if (btnClose) btnClose.addEventListener('click', closeModal);
  if (backdrop) backdrop.addEventListener('click', closeModal);
}

export async function loadAuditData() {
  const container = document.getElementById('history-content');
  if (container) {
    container.classList.add('loading-state');
  }

  try {
    const data = await api.get('/api/history');
    if (!data) return;

    articlesCache = normalizeHistoryData(data);
    renderArticles(filterArticles(articlesCache, currentFilterTab));
  } catch (err) {
    if (err?.message !== 'Unauthorized') {
      showToast('加载审稿历史列表失败', 'error');
    }
  } finally {
    if (container) {
      container.classList.remove('loading-state');
    }
  }
}

function normalizeHistoryData(data) {
  const map = new Map();

  const addItems = (list) => {
    if (!Array.isArray(list)) return;
    list.forEach(item => {
      if (item && item.id !== undefined && !map.has(item.id)) {
        const rawTitle = stripEmojis(item.title || item.topic || '无标题草稿');
        const firstLine = rawTitle.split(/\r?\n/)[0].replace(/^#+\s*/, '').trim();
        const cleanTitle = firstLine.length > 72 ? firstLine.slice(0, 72) + '...' : (firstLine || '无标题草稿');
        map.set(item.id, {
          ...item,
          cleanTitle,
          quality_score: Number(item.quality_score) || 0
        });
      }
    });
  };

  addItems(data.unsent);
  addItems(data.sent);

  if (data.history && typeof data.history === 'object') {
    Object.values(data.history).forEach(dayObj => {
      if (dayObj && Array.isArray(dayObj.results)) {
        addItems(dayObj.results);
      }
    });
  }

  return Array.from(map.values()).sort((a, b) => (b.id || 0) - (a.id || 0));
}

function filterArticles(list, tab) {
  const st = (a) => (a.status || 'PENDING_REVIEW').toUpperCase();
  if (tab === 'pending') {
    return list.filter(a => ['PENDING_REVIEW', 'CLOUD_UNCERTAIN', 'DRAFT_PENDING_RECORD', 'APPROVING'].includes(st(a)));
  }
  if (tab === 'approved') return list.filter(a => st(a) === 'APPROVED');
  if (tab === 'unsent') return list.filter(a => !a.is_published);
  if (tab === 'sent') return list.filter(a => Boolean(a.is_published && (a.success ?? a.success_status)));
  return list;
}

function getStatusMeta(a) {
  const st = (a.status || 'PENDING_REVIEW').toUpperCase();
  const map = {
    CLOUD_UNCERTAIN: ['结果未知·禁盲推', 'status-failed'],
    DRAFT_PENDING_RECORD: ['已建稿待补记', 'status-pending'],
    APPROVING: ['核准推送中', 'status-pending'],
    DRAFT: ['草稿已就绪', 'status-approved'],
    APPROVED: ['已核准', 'status-approved'],
    FAILED: ['推送失败', 'status-failed'],
    REJECTED: ['门禁驳回', 'status-failed'],
    PENDING_REVIEW: ['待审校', 'status-pending_review']
  };
  const [label, cls] = map[st] || [a.status || '待审校', `status-${st.toLowerCase()}`];
  return { st, label, cls };
}

function renderPrimaryActionHtml(a, iconSize) {
  const { st } = getStatusMeta(a);
  const attAttr = a.attempt_id ? ` data-attempt-id="${escapeHtml(a.attempt_id)}"` : '';
  if (st === 'CLOUD_UNCERTAIN' || st === 'APPROVING') {
    return `<button class="btn btn-secondary btn-sm btn-audit-reconcile" data-id="${a.id}"${attAttr}>${getIcon('refresh', iconSize)} 核对草稿箱</button>`;
  }
  if (st === 'DRAFT_PENDING_RECORD') {
    return `<button class="btn btn-primary btn-sm btn-audit-reconcile" data-id="${a.id}"${attAttr}>${getIcon('check', iconSize)} 补记本地状态</button>`;
  }
  if (st === 'DRAFT' || st === 'APPROVED' || Boolean(a.draft_id || a.media_id)) {
    return `<span class="badge badge-success">已入草稿箱</span>`;
  }
  return `<button class="btn btn-primary btn-sm btn-audit-approve" data-id="${a.id}">${getIcon('check', iconSize)} 核准推送</button>`;
}

function renderArticles(articles) {
  const container = document.getElementById('history-content');
  if (!container) return;

  if (articles.length === 0) {
    container.innerHTML = `
      <div class="empty-audit-state">
        <div class="empty-icon">${getIcon('audit', 32)}</div>
        <div class="empty-title">当前分类下暂无稿件</div>
        <div class="empty-desc">下发新编排流水线后，生成的微信待审稿件将自动归集在此。</div>
      </div>
    `;
    return;
  }

  const tableHtml = `
    <div class="table-responsive-wrapper">
      <table class="linear-table">
        <thead>
          <tr>
            <th class="th-chk"><input type="checkbox" id="chk-audit-select-all-inner" /></th>
            <th>文章标题与信源</th>
            <th>评分</th>
            <th>事实核验</th>
            <th>流程状态</th>
            <th>时间</th>
            <th class="th-actions">操作</th>
          </tr>
        </thead>
        <tbody>
          ${articles.map(a => renderTableRowHtml(a)).join('')}
        </tbody>
      </table>
    </div>
  `;

  const mobileListHtml = `
    <div class="mobile-audit-list">
      ${articles.map(a => renderMobileCardHtml(a)).join('')}
    </div>
  `;

  container.innerHTML = tableHtml + mobileListHtml;
  bindDynamicRowEvents(container);
}

function renderTableRowHtml(a) {
  const scoreBadge = getScoreBadgeHtml(a.quality_score);
  const rawFact = a.fact_check_result ? stripEmojis(String(a.fact_check_result)).replace(/^[#\s*-]+/, '').trim() : '';
  const shortFact = rawFact ? (rawFact.length > 36 ? rawFact.slice(0, 36) + '...' : rawFact) : '';
  const factBadge = shortFact ? `<span class="badge badge-neutral" title="${escapeHtml(rawFact)}">${escapeHtml(shortFact)}</span>` : '<span class="badge badge-neutral">未配置</span>';
  const previewId = a.preview_id || a.draft_id || a.media_id || a.id;
  const { label, cls } = getStatusMeta(a);

  return `
    <tr data-article-id="${a.id}">
      <td class="td-chk"><input type="checkbox" class="chk-article-row" data-id="${a.id}" /></td>
      <td class="td-title-source">
        <div class="article-title-text">${escapeHtml(a.cleanTitle)}</div>
        <div class="article-source-sub">
          <span class="source-tag">${escapeHtml(a.source_type || '通用')}</span>
          ${a.source_url ? `<a href="${escapeHtml(a.source_url)}" target="_blank" rel="noopener" class="source-link">${getIcon('external', 11)} 原文</a>` : ''}
        </div>
      </td>
      <td>${scoreBadge}</td>
      <td>${factBadge}</td>
      <td><span class="status-pill-small ${cls}" title="${escapeHtml(a.error || '')}">${escapeHtml(label)}</span></td>
      <td class="td-time">${escapeHtml(a.date || '')} ${escapeHtml(a.time || '')}</td>
      <td class="td-actions">
        <button class="btn btn-secondary btn-sm btn-audit-preview" data-preview-id="${escapeHtml(previewId)}" title="预览微信排版">${getIcon('view', 12)} 预览</button>
        ${renderPrimaryActionHtml(a, 12)}
        <button class="btn btn-ghost btn-sm btn-audit-delete" data-id="${a.id}" title="删除此条">${getIcon('trash', 12)}</button>
      </td>
    </tr>
  `;
}

function renderMobileCardHtml(a) {
  const scoreBadge = getScoreBadgeHtml(a.quality_score);
  const previewId = a.preview_id || a.draft_id || a.media_id || a.id;
  const { label } = getStatusMeta(a);

  return `
    <div class="mobile-audit-card" data-article-id="${a.id}">
      <div class="card-head">
        <span class="source-tag">${escapeHtml(a.source_type || '通用')}</span>
        ${scoreBadge}
      </div>
      <div class="card-title">${escapeHtml(a.cleanTitle)}</div>
      <div class="card-meta">
        <span>${escapeHtml(label)}</span>
        <span>${escapeHtml(a.date || '')} ${escapeHtml(a.time || '')}</span>
      </div>
      <div class="card-actions-grid">
        <button class="btn btn-secondary btn-audit-preview" data-preview-id="${escapeHtml(previewId)}">${getIcon('view', 14)} 预览</button>
        ${renderPrimaryActionHtml(a, 14)}
        <button class="btn btn-ghost btn-audit-delete" data-id="${a.id}" title="删除此条">${getIcon('trash', 14)} 删除</button>
      </div>
    </div>
  `;
}

function getScoreBadgeHtml(score) {
  if (score >= 80) return `<span class="score-badge score-success">${score}分</span>`;
  if (score >= 60) return `<span class="score-badge score-warning">${score}分</span>`;
  return `<span class="score-badge score-danger">${score}分</span>`;
}

function bindDynamicRowEvents(container) {
  container.querySelectorAll('.chk-article-row').forEach(cb => {
    cb.addEventListener('change', updateBatchActionsUI);
  });

  const innerSelectAll = container.querySelector('#chk-audit-select-all-inner');
  if (innerSelectAll) {
    innerSelectAll.addEventListener('change', () => {
      const checked = innerSelectAll.checked;
      container.querySelectorAll('.chk-article-row').forEach(cb => { cb.checked = checked; });
      updateBatchActionsUI();
    });
  }

  container.querySelectorAll('.btn-audit-approve').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const id = btn.getAttribute('data-id');
      if (!id) return;
      btn.disabled = true;
      try {
        const res = await api.post('/api/review/approve', { id: Number(id) });
        showToast(res.message || '文章已核准并推送草稿箱', 'success');
        loadAuditData();
      } catch (_) { btn.disabled = false; loadAuditData(); }
    });
  });

  container.querySelectorAll('.btn-audit-reconcile').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const id = btn.getAttribute('data-id');
      const attemptId = btn.getAttribute('data-attempt-id');
      if (!id && !attemptId) return;
      btn.disabled = true;
      try {
        const body = {};
        if (id) body.id = Number(id);
        if (attemptId) body.attempt_id = attemptId;
        const res = await api.post('/api/review/reconcile', body);
        showToast(res.message || '核对已完成', res.review_status === 'CLOUD_UNCERTAIN' ? 'warning' : 'success');
        loadAuditData();
      } catch (_) { btn.disabled = false; }
    });
  });

  container.querySelectorAll('.btn-audit-delete').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const id = btn.getAttribute('data-id');
      if (!id || !confirm('确认删除此篇历史记录？')) return;
      try {
        await api.post('/api/history/delete', { id: Number(id) });
        showToast('已删除文章', 'success');
        loadAuditData();
      } catch (_) {}
    });
  });

  container.querySelectorAll('.btn-audit-preview').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const previewId = btn.getAttribute('data-preview-id');
      if (!previewId) return;
      openPreviewModal(previewId);
    });
  });
}

function updateBatchActionsUI() {
  const selectedCount = getSelectedArticleIds().length;
  const countEl = document.getElementById('selected-articles-count');
  if (countEl) countEl.textContent = String(selectedCount);

  const btnDelete = document.getElementById('btn-delete-selected');
  if (btnDelete) btnDelete.disabled = selectedCount === 0;
}

function getSelectedArticleIds() {
  const checkedBoxes = document.querySelectorAll('.chk-article-row:checked');
  return Array.from(checkedBoxes).map(cb => Number(cb.getAttribute('data-id'))).filter(Boolean);
}

function openPreviewModal(previewId) {
  const modal = document.getElementById('preview-modal');
  const iframe = document.getElementById('preview-iframe');
  if (modal && iframe) {
    iframe.src = `/api/preview/${encodeURIComponent(previewId)}`;
    modal.style.display = 'flex';
    modal.classList.add('open');
  }
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
