/**
 * ============================================================
 *   Image Studio — 图片工作台前端交互逻辑
 *   支持拖拽上传图片到对应占位符位置
 * ============================================================
 */

(function () {
    'use strict';

    // State
    let studioPrompts = [];    // [{index, keyword, prompt, imageUrl?, filepath?}]
    let studioArticleText = '';

    // DOM refs (lazy init)
    function $id(id) { return document.getElementById(id); }

    // ---- 初始化 ----
    function initImageStudio() {
        const btnGenerate = $id('btn-generate-prompts');
        if (btnGenerate) {
            btnGenerate.addEventListener('click', onGeneratePrompts);
        }
        const btnPreview = $id('btn-studio-preview');
        if (btnPreview) {
            btnPreview.addEventListener('click', onPreviewArticle);
        }
    }

    // ---- 生成提示词 ----
    async function onGeneratePrompts() {
        const titleInput = $id('studio-article-title');
        const textInput = $id('studio-article-text');
        const cardsContainer = $id('prompt-cards-container');
        const btnPreview = $id('btn-studio-preview');

        const articleTitle = titleInput ? titleInput.value.trim() : '';
        const articleText = textInput ? textInput.value.trim() : '';

        if (!articleText) {
            showStudioToast('请先粘贴文章内容', 'warning');
            return;
        }

        studioArticleText = articleText;
        if (btnPreview) btnPreview.style.display = 'none';

        // Show loading
        cardsContainer.innerHTML = `
            <div class="studio-loading">
                <div class="studio-spinner"></div>
                <span>正在生成英文提示词...</span>
            </div>
        `;

        try {
            const resp = await fetch('/api/image-studio/prompts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    article_title: articleTitle || 'AI Article',
                    article_text: articleText
                })
            });

            const data = await resp.json();

            if (data.status !== 'success') {
                cardsContainer.innerHTML = `
                    <div class="studio-empty">
                        <div class="studio-empty-icon">⚠️</div>
                        <div class="studio-empty-text">${data.message || '生成失败'}</div>
                    </div>
                `;
                return;
            }

            if (!data.prompts || data.prompts.length === 0) {
                cardsContainer.innerHTML = `
                    <div class="studio-empty">
                        <div class="studio-empty-icon">📄</div>
                        <div class="studio-empty-text">未检测到配图占位符</div>
                        <div class="studio-empty-hint">请确保文章中包含 【此处插入配图：描述】 格式的占位符</div>
                    </div>
                `;
                return;
            }

            studioPrompts = data.prompts.map(p => ({ ...p, imageUrl: null, filepath: null }));
            renderPromptCards();
            if (btnPreview) btnPreview.style.display = 'inline-flex';

        } catch (err) {
            cardsContainer.innerHTML = `
                <div class="studio-empty">
                    <div class="studio-empty-icon">❌</div>
                    <div class="studio-empty-text">网络错误: ${err.message}</div>
                </div>
            `;
        }
    }

    // ---- 预览文章 ----
    async function onPreviewArticle() {
        const titleInput = $id('studio-article-title');
        const articleTitle = titleInput ? titleInput.value.trim() : '';
        
        if (!studioArticleText) {
            showStudioToast('请先生成提示词并粘贴文章内容', 'warning');
            return;
        }

        const imagesMapping = {};
        for (const p of studioPrompts) {
            if (p.imageUrl) {
                imagesMapping[p.index.toString()] = p.imageUrl;
            }
        }

        const btnPreview = $id('btn-studio-preview');
        const origHtml = btnPreview.innerHTML;
        btnPreview.innerHTML = `<span>⌛ 正在渲染...</span>`;
        btnPreview.disabled = true;

        try {
            const resp = await fetch('/api/image-studio/preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    article_title: articleTitle || 'AI Article',
                    article_text: studioArticleText,
                    images: imagesMapping
                })
            });

            const data = await resp.json();

            if (data.status === 'success') {
                const previewModal = $id('preview-modal');
                const previewModalTitle = $id('preview-modal-title');
                const previewIframe = $id('preview-iframe');

                if (previewModal && previewIframe) {
                    if (previewModalTitle) {
                        previewModalTitle.textContent = articleTitle || '文章预览';
                    }
                    previewModal.style.display = 'flex';

                    const doc = previewIframe.contentDocument || previewIframe.contentWindow.document;
                    doc.open();
                    doc.write(data.html);
                    doc.close();
                } else {
                    showStudioToast('无法找到预览弹窗组件', 'error');
                }
            } else {
                showStudioToast(`渲染预览失败: ${data.message}`, 'error');
            }
        } catch (err) {
            showStudioToast(`预览错误: ${err.message}`, 'error');
        } finally {
            btnPreview.innerHTML = origHtml;
            btnPreview.disabled = false;
        }
    }

    // ---- 渲染提示词卡片 ----
    function renderPromptCards() {
        const container = $id('prompt-cards-container');
        if (!container) return;

        const doneCount = studioPrompts.filter(p => p.imageUrl).length;
        const totalCount = studioPrompts.length;

        let html = '';

        // 进度条
        if (totalCount > 0) {
            const pct = Math.round((doneCount / totalCount) * 100);
            html += `
                <div class="studio-progress">
                    <div class="studio-progress-bar">
                        <div class="studio-progress-fill" style="width:${pct}%"></div>
                    </div>
                    <div class="studio-progress-text">${doneCount}/${totalCount} 张已完成</div>
                </div>
            `;
        }

        // 卡片网格
        html += '<div class="prompt-cards-grid">';
        for (const p of studioPrompts) {
            const hasImage = !!p.imageUrl;
            const statusCls = hasImage ? 'status-done' : 'status-pending';
            const statusText = hasImage ? '✓ 已配图' : '待配图';

            html += `
                <div class="prompt-card" data-index="${p.index}">
                    <div class="prompt-card-header">
                        <div style="display:flex;align-items:center;">
                            <span class="prompt-card-index">${p.index}</span>
                            <span class="prompt-card-keyword">${escapeHtml(p.keyword)}</span>
                        </div>
                        <span class="prompt-card-status ${statusCls}">${statusText}</span>
                    </div>
                    <div class="prompt-text" title="点击复制">${escapeHtml(p.prompt)}</div>
                    <div style="display:flex;justify-content:flex-end;margin-bottom:10px;">
                        <button class="prompt-card-copy-btn" onclick="window._studioCopyPrompt(${p.index})">📋 复制 Prompt</button>
                    </div>
                    <div class="drop-zone ${hasImage ? 'has-image' : ''}" 
                         data-index="${p.index}"
                         id="drop-zone-${p.index}">
                        ${hasImage ? `
                            <img src="${p.imageUrl}" class="drop-zone-preview" alt="Preview">
                            <div class="drop-zone-actions">
                                <button class="btn-replace" onclick="window._studioTriggerReplace(${p.index})">🔄 替换</button>
                                <button class="btn-remove" onclick="window._studioRemoveImage(${p.index})">🗑️ 移除</button>
                            </div>
                        ` : `
                            <div class="drop-zone-icon">📥</div>
                            <div class="drop-zone-text">拖拽图片到此处</div>
                            <div class="drop-zone-hint">或点击选择文件</div>
                        `}
                    </div>
                    <input type="file" accept="image/*" style="display:none" 
                           id="file-input-${p.index}" 
                           onchange="window._studioFileSelected(event, ${p.index})">
                </div>
            `;
        }
        html += '</div>';

        container.innerHTML = html;

        // Bind drag-and-drop events
        bindDropZoneEvents();
    }

    // ---- 绑定拖拽事件 ----
    function bindDropZoneEvents() {
        document.querySelectorAll('.drop-zone').forEach(zone => {
            const idx = parseInt(zone.dataset.index);

            zone.addEventListener('dragover', (e) => {
                e.preventDefault();
                e.stopPropagation();
                zone.classList.add('drag-over');
            });

            zone.addEventListener('dragleave', (e) => {
                e.preventDefault();
                e.stopPropagation();
                zone.classList.remove('drag-over');
            });

            zone.addEventListener('drop', (e) => {
                e.preventDefault();
                e.stopPropagation();
                zone.classList.remove('drag-over');

                const file = e.dataTransfer.files[0];
                if (file && file.type.startsWith('image/')) {
                    uploadImage(file, idx);
                } else {
                    showStudioToast('请拖入图片文件', 'warning');
                }
            });

            // 点击选择文件
            zone.addEventListener('click', (e) => {
                if (e.target.closest('.drop-zone-actions')) return;
                const fileInput = $id(`file-input-${idx}`);
                if (fileInput) fileInput.click();
            });
        });
    }

    // ---- 上传图片 ----
    async function uploadImage(file, index) {
        const zone = $id(`drop-zone-${index}`);
        if (!zone) return;

        // Show uploading state
        zone.innerHTML = `
            <div class="studio-loading" style="padding:16px;">
                <div class="studio-spinner"></div>
                <span>上传中...</span>
            </div>
        `;

        const formData = new FormData();
        formData.append('image', file);
        formData.append('index', index.toString());

        try {
            const resp = await fetch('/api/image-studio/upload', {
                method: 'POST',
                body: formData
            });

            const data = await resp.json();

            if (data.status === 'success') {
                // Update state
                const prompt = studioPrompts.find(p => p.index === index);
                if (prompt) {
                    prompt.imageUrl = data.url;
                    prompt.filepath = data.filepath;
                }
                renderPromptCards();
                showStudioToast(`图片 #${index} 上传成功`, 'success');
            } else {
                showStudioToast(`上传失败: ${data.message}`, 'error');
                renderPromptCards();
            }
        } catch (err) {
            showStudioToast(`上传错误: ${err.message}`, 'error');
            renderPromptCards();
        }
    }

    // ---- 公开方法 (onclick) ----
    window._studioCopyPrompt = function (index) {
        const prompt = studioPrompts.find(p => p.index === index);
        if (prompt) {
            navigator.clipboard.writeText(prompt.prompt).then(() => {
                showStudioToast('Prompt 已复制到剪贴板', 'success');
            }).catch(() => {
                // Fallback
                const ta = document.createElement('textarea');
                ta.value = prompt.prompt;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
                showStudioToast('Prompt 已复制', 'success');
            });
        }
    };

    window._studioTriggerReplace = function (index) {
        const fileInput = $id(`file-input-${index}`);
        if (fileInput) fileInput.click();
    };

    window._studioRemoveImage = function (index) {
        const prompt = studioPrompts.find(p => p.index === index);
        if (prompt) {
            prompt.imageUrl = null;
            prompt.filepath = null;
        }
        renderPromptCards();
    };

    window._studioFileSelected = function (event, index) {
        const file = event.target.files[0];
        if (file && file.type.startsWith('image/')) {
            uploadImage(file, index);
        }
    };

    // ---- Toast 通知 ----
    function showStudioToast(message, type) {
        let toast = document.querySelector('.studio-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.className = 'studio-toast';
            toast.style.cssText = `
                position: fixed; bottom: 24px; right: 24px; z-index: 9999;
                padding: 10px 20px; border-radius: 10px; font-size: 13px;
                color: white; opacity: 0; transition: opacity 0.3s;
                box-shadow: 0 4px 16px rgba(0,0,0,0.3);
            `;
            document.body.appendChild(toast);
        }

        const colors = {
            success: '#10b981',
            error: '#ef4444',
            warning: '#f59e0b'
        };
        toast.style.background = colors[type] || '#6366f1';
        toast.textContent = message;
        toast.style.opacity = '1';

        clearTimeout(toast._timer);
        toast._timer = setTimeout(() => {
            toast.style.opacity = '0';
        }, 2500);
    }

    // ---- Utils ----
    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // ---- Auto-init ----
    // Hook into the existing nav system — when image-studio tab is shown, init
    const observer = new MutationObserver(() => {
        const section = $id('image-studio');
        if (section && section.classList.contains('active')) {
            initImageStudio();
            observer.disconnect();
        }
    });

    // Start observing after DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            initImageStudio();
            observer.observe(document.body, { attributes: true, subtree: true, attributeFilter: ['class'] });
        });
    } else {
        initImageStudio();
        observer.observe(document.body, { attributes: true, subtree: true, attributeFilter: ['class'] });
    }

})();
