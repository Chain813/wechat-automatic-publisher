// static/js/views/studio.js
// Image Studio View Controller - Redraw, Prompt Extraction & Drop-Zone Assets

import { apiPost, apiUpload, showToast } from '../core/api.js';
import { icon } from '../core/icons.js';

let studioPrompts = [];
let currentArticleText = '';

export function initStudioView() {
  bindRedrawBar();
  bindPromptExtraction();
  bindStudioPreview();

  window.addEventListener('autowechat:view-change', (e) => {
    if (e.detail?.view === 'image' && studioPrompts.length === 0) initDefaultSlots();
  });
  initDefaultSlots();
}

function initDefaultSlots() {
  const container = document.getElementById('prompt-cards-container');
  if (!container || studioPrompts.length > 0) return;

  studioPrompts = [
    { index: 1, keyword: '封面题图', prompt: 'Futuristic AI chip architecture, 2.35:1 aspect ratio, subtle neon glow, studio lighting', imageUrl: null, filepath: null },
    { index: 2, keyword: '核心架构图', prompt: 'Isometric system architecture diagram showing data pipeline flows, interconnected glass nodes', imageUrl: null, filepath: null },
    { index: 3, keyword: '场景配图', prompt: 'Modern Scandinavian workplace with engineer reviewing AI articles on tablet, natural daylight', imageUrl: null, filepath: null }
  ];
  renderPromptCards();
}

function bindRedrawBar() {
  const btn = document.getElementById('btn-studio-redraw') || document.getElementById('btn-redraw-all');
  const urlInput = document.getElementById('studio-redraw-url') || document.getElementById('input-redraw-topic');
  const resultsBox = document.getElementById('studio-redraw-results');
  if (!btn || !urlInput) return;

  btn.addEventListener('click', async () => {
    const url = urlInput.value.trim();
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      showToast('请先输入有效的微信公众号文章链接 (http/https)', 'warning');
      return;
    }
    btn.disabled = true;
    const origHtml = btn.innerHTML;
    btn.innerHTML = `${icon('refresh', 14)} 抓图重绘中...`;
    if (resultsBox) resultsBox.innerHTML = `<div style="padding:14px;font-size:13px;color:var(--text-secondary);display:flex;align-items:center;gap:8px;">${icon('refresh', 16)} 正在抓取参考图并使用 Qwen-Image 重绘...</div>`;

    try {
      const data = await apiPost('/api/image-studio/redraw', { article_url: url, count: 4 });
      if (data?.status === 'success' && data.images?.length > 0) {
        if (resultsBox) {
          resultsBox.innerHTML = '';
          const grid = document.createElement('div');
          grid.style.cssText = 'display:flex;gap:10px;flex-wrap:wrap;margin-top:10px;';
          data.images.forEach((img) => {
            const card = document.createElement('div');
            card.style.cssText = 'width:130px;border:1px solid var(--border-color);border-radius:var(--radius-sm);overflow:hidden;background:var(--bg-elevated);cursor:pointer;';
            card.innerHTML = `<img src="${img.url}" style="width:100%;height:80px;object-fit:cover;display:block;" title="点击复制图片链接"><div style="padding:4px 6px;font-size:11px;color:var(--text-secondary);text-align:center;">图 ${img.index} (点击复制)</div>`;
            card.addEventListener('click', () => copyToClipboard(new URL(img.url, window.location.origin).href, '已复制重绘图片链接'));
            grid.appendChild(card);
          });
          resultsBox.appendChild(grid);
        }
        showToast(`参考图重绘完成，成功生成 ${data.images.length} 张原创配图`, 'success');
      } else {
        const msg = data?.message || '未抓取到有效图片或重绘失败';
        if (resultsBox) resultsBox.innerHTML = `<div style="padding:12px;font-size:13px;color:var(--status-danger);">${msg}</div>`;
        showToast(msg, 'error');
      }
    } catch (err) {
      if (resultsBox) resultsBox.innerHTML = `<div style="padding:12px;font-size:13px;color:var(--status-danger);">重绘异常: ${err.message}</div>`;
      showToast(`重绘异常: ${err.message}`, 'error');
    } finally {
      btn.disabled = false;
      btn.innerHTML = origHtml;
    }
  });
}

function bindPromptExtraction() {
  const btn = document.getElementById('btn-generate-prompts') || document.getElementById('btn-extract-prompts');
  const titleInput = document.getElementById('studio-article-title');
  const textInput = document.getElementById('studio-article-text');
  const btnPreview = document.getElementById('btn-studio-preview');
  if (!btn) return;

  btn.addEventListener('click', async () => {
    const title = titleInput?.value.trim() || 'AI Article';
    const text = textInput?.value.trim() || '';
    if (!text) return showToast('请先输入或粘贴正文 Markdown 内容', 'warning');

    currentArticleText = text;
    btn.disabled = true;
    const origHtml = btn.innerHTML;
    btn.innerHTML = `${icon('sparkle', 14)} 正在分析提取...`;

    try {
      const data = await apiPost('/api/image-studio/prompts', { article_title: title, article_text: text });
      if (data?.status === 'success') {
        if (data.prompts?.length > 0) {
          studioPrompts = data.prompts.map((p) => ({ index: p.index, keyword: p.keyword || `插图 ${p.index}`, prompt: p.prompt, imageUrl: null, filepath: null }));
          showToast(`成功提取 ${data.prompts.length} 个配图槽位提示词`, 'success');
        } else {
          showToast('正文中未检测到【此处插入配图】占位符，已保持基础槽位', 'warning');
        }
        renderPromptCards();
        if (btnPreview) btnPreview.style.display = 'inline-flex';
      } else {
        showToast(data?.message || '提取提示词失败', 'error');
      }
    } catch (err) {
      showToast(`提取提示词请求失败: ${err.message}`, 'error');
    } finally {
      btn.disabled = false;
      btn.innerHTML = origHtml;
    }
  });
}

function renderPromptCards() {
  const container = document.getElementById('prompt-cards-container');
  if (!container) return;

  const total = studioPrompts.length;
  const doneCount = studioPrompts.filter((p) => p.imageUrl).length;

  let html = `
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;font-size:12px;color:var(--text-secondary);">
      <span>配图推进度: <strong style="color:var(--text-primary);">${doneCount}/${total}</strong> 槽位已完成</span>
      <span class="badge ${doneCount === total && total > 0 ? 'badge-success' : 'badge-neutral'}">
        ${doneCount === total && total > 0 ? '全部就绪' : '等待配图'}
      </span>
    </div>
  `;

  for (const p of studioPrompts) {
    const has = Boolean(p.imageUrl);
    html += `
      <div class="prompt-slot-card" data-slot-index="${p.index}">
        <div style="display:flex;align-items:center;justify-content:space-between;">
          <div style="display:flex;align-items:center;gap:8px;">
            <span class="badge badge-indigo">槽位 ${p.index}</span>
            <span style="font-weight:600;font-size:13px;color:var(--text-primary);">${escapeHtml(p.keyword)}</span>
          </div>
          <span class="badge ${has ? 'badge-success' : 'badge-neutral'}">${has ? `${icon('check', 11)} 已上传` : '待配图'}</span>
        </div>
        <div style="font-size:12px;line-height:1.45;color:var(--text-secondary);background:var(--bg-subtle);padding:8px 10px;border-radius:var(--radius-sm);word-break:break-word;">${escapeHtml(p.prompt)}</div>
        <div style="display:flex;justify-content:flex-end;">
          <button class="btn btn-secondary btn-sm btn-copy-prompt" data-index="${p.index}">${icon('copy', 12)} 复制 Prompt</button>
        </div>
        <div class="drop-zone ${has ? 'has-image' : ''}" data-drop-index="${p.index}">
          ${has ? `
            <div style="display:flex;flex-direction:column;align-items:center;gap:8px;">
              <img src="${p.imageUrl}" style="max-height:140px;max-width:100%;border-radius:var(--radius-xs);object-fit:contain;">
              <div style="display:flex;gap:8px;">
                <button class="btn btn-secondary btn-sm btn-replace-image" data-index="${p.index}">${icon('refresh', 12)} 替换</button>
                <button class="btn btn-ghost btn-sm btn-remove-image" data-index="${p.index}" style="color:var(--status-danger);">${icon('trash', 12)} 移除</button>
              </div>
            </div>
          ` : `
            <div style="display:flex;flex-direction:column;align-items:center;gap:6px;padding:12px 0;">
              ${icon('upload', 24)}
              <div style="font-size:13px;font-weight:500;color:var(--text-primary);">拖拽图片到此处上传</div>
              <div style="font-size:11px;color:var(--text-muted);">或点击浏览本地文件 (PNG, JPG, WebP)</div>
            </div>
          `}
        </div>
        <input type="file" accept="image/*" style="display:none;" class="file-input-slot" data-index="${p.index}">
      </div>
    `;
  }
  container.innerHTML = html;
  bindSlotEvents(container);
}

function bindSlotEvents(container) {
  container.querySelectorAll('.btn-copy-prompt').forEach((btn) => {
    btn.addEventListener('click', () => {
      const slot = studioPrompts.find((p) => p.index === parseInt(btn.dataset.index, 10));
      if (slot) copyToClipboard(slot.prompt, `已复制槽位 ${slot.index} 的 Prompt`);
    });
  });

  container.querySelectorAll('.btn-remove-image').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const slot = studioPrompts.find((p) => p.index === parseInt(btn.dataset.index, 10));
      if (slot) {
        slot.imageUrl = null; slot.filepath = null;
        renderPromptCards();
        showToast('已移除图片', 'info');
      }
    });
  });

  container.querySelectorAll('.btn-replace-image').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      container.querySelector(`.file-input-slot[data-index="${btn.dataset.index}"]`)?.click();
    });
  });

  container.querySelectorAll('.file-input-slot').forEach((input) => {
    input.addEventListener('change', (e) => {
      const file = e.target.files?.[0];
      if (file) handleUploadFile(file, parseInt(input.dataset.index, 10));
    });
  });

  container.querySelectorAll('.drop-zone').forEach((zone) => {
    const idx = parseInt(zone.dataset.dropIndex, 10);
    zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('dragover'); });
    zone.addEventListener('dragleave', (e) => { e.preventDefault(); zone.classList.remove('dragover'); });
    zone.addEventListener('drop', (e) => {
      e.preventDefault(); zone.classList.remove('dragover');
      const file = e.dataTransfer.files?.[0];
      if (file?.type.startsWith('image/')) handleUploadFile(file, idx);
      else showToast('请拖入有效的图片文件', 'warning');
    });
    zone.addEventListener('click', (e) => {
      if (!e.target.closest('button')) container.querySelector(`.file-input-slot[data-index="${idx}"]`)?.click();
    });
  });
}

async function handleUploadFile(file, index) {
  const slot = studioPrompts.find((p) => p.index === index);
  if (!slot) return;

  const zone = document.querySelector(`.drop-zone[data-drop-index="${index}"]`);
  if (zone) zone.innerHTML = `<div style="padding:16px;font-size:12px;color:var(--text-secondary);display:flex;align-items:center;justify-content:center;gap:8px;">${icon('refresh', 16)} 上传中...</div>`;

  const formData = new FormData();
  formData.append('image', file);
  formData.append('index', String(index));

  try {
    const res = await apiUpload('/api/image-studio/upload', formData);
    if (res?.status === 'success') {
      slot.imageUrl = res.url;
      slot.filepath = res.filepath;
      showToast(`槽位 ${index} 图片上传就绪`, 'success');
    } else {
      showToast(res?.message || '图片上传失败', 'error');
    }
  } catch (err) {
    showToast(`上传网络异常: ${err.message}`, 'error');
  } finally {
    renderPromptCards();
  }
}

function bindStudioPreview() {
  const btn = document.getElementById('btn-studio-preview');
  const titleInput = document.getElementById('studio-article-title');
  const textInput = document.getElementById('studio-article-text');
  if (!btn) return;

  btn.addEventListener('click', async () => {
    const title = titleInput?.value.trim() || 'AI Article';
    const text = textInput?.value.trim() || currentArticleText;
    if (!text) return showToast('文章内容为空，无法预览', 'warning');

    const imagesMapping = {};
    studioPrompts.forEach((p) => { if (p.imageUrl) imagesMapping[String(p.index)] = p.imageUrl; });

    btn.disabled = true;
    const origHtml = btn.innerHTML;
    btn.innerHTML = `${icon('view', 14)} 渲染预览中...`;

    try {
      const data = await apiPost('/api/image-studio/preview', { article_title: title, article_text: text, images: imagesMapping });
      if (data?.status === 'success' && data.html) {
        const modal = document.getElementById('preview-modal');
        const modalTitle = document.getElementById('preview-modal-title');
        const iframe = document.getElementById('preview-iframe');
        if (modal && iframe) {
          if (modalTitle) modalTitle.textContent = title;
          modal.classList.add('open');
          modal.style.display = 'flex';
          const doc = iframe.contentDocument || iframe.contentWindow.document;
          doc.open(); doc.write(data.html); doc.close();
        }
      } else {
        showToast(data?.message || '生成图文预览失败', 'error');
      }
    } catch (err) {
      showToast(`预览渲染异常: ${err.message}`, 'error');
    } finally {
      btn.disabled = false;
      btn.innerHTML = origHtml;
    }
  });
}

function copyToClipboard(text, msg) {
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(() => showToast(msg, 'success')).catch(() => fallbackCopy(text, msg));
  } else {
    fallbackCopy(text, msg);
  }
}

function fallbackCopy(text, msg) {
  const ta = document.createElement('textarea');
  ta.value = text;
  document.body.appendChild(ta);
  ta.select();
  document.execCommand('copy');
  document.body.removeChild(ta);
  showToast(msg, 'success');
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
