// static/js/main.js
// AutoWeChat Main ES Module Entry Point - Zero Emojis

import { State } from './core/state.js';
import { applyI18n, toggleLanguage } from './core/i18n.js';
import { initConsoleView } from './views/console.js';
import { initGraphView } from './views/graph.js';
import { initAuditView } from './views/audit.js';
import { initStudioView } from './views/studio.js';
import { initOpsView } from './views/ops.js';

document.addEventListener('DOMContentLoaded', () => {
  // Handle Login Page flow
  const loginForm = document.getElementById('login-form') || document.querySelector('.login-box form');
  if (loginForm) {
    initLoginFlow(loginForm);
    return;
  }

  // Handle Main Console Application flow
  const appShell = document.querySelector('.app-shell');
  if (appShell) {
    initAppFlow();
  }
});

function initLoginFlow(form) {
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const tokenInput = document.getElementById('token') || form.querySelector('input[type="password"]') || form.querySelector('input');
    const errorEl = document.getElementById('error') || form.querySelector('.error');
    const pwd = tokenInput ? tokenInput.value.trim() : '';

    if (!pwd) {
      if (errorEl) {
        errorEl.textContent = '请输入访问 Token';
        errorEl.style.display = 'block';
      }
      return;
    }

    const secureAttr = window.location.protocol === 'https:' ? '; Secure' : '';
    document.cookie = `aw_token=${encodeURIComponent(pwd)}; path=/; max-age=604800; SameSite=Lax${secureAttr}`;

    try {
      const res = await fetch('/api/config', { cache: 'no-store' });
      if (res.ok) {
        window.location.replace('/');
      } else {
        if (errorEl) {
          errorEl.textContent = 'Token 校验失败，请核对后重试';
          errorEl.style.display = 'block';
        }
      }
    } catch (_) {
      if (errorEl) {
        errorEl.textContent = '网络连接异常，无法连通服务';
        errorEl.style.display = 'block';
      }
    }
  });
}

function initAppFlow() {
  applyI18n();

  initConsoleView();
  initGraphView();
  initAuditView();
  initStudioView();
  initOpsView();

  bindNavigation();
  bindLanguageToggles();
  bindGlobalModals();
  bindVisibilityResync();

  const initialStage = State.currentStage || 'console';
  switchViewStage(initialStage, false);

  State.resyncRunningStatus();
}

function bindNavigation() {
  const topPills = document.querySelectorAll('.topbar .nav-pill[data-view]');
  const dockItems = document.querySelectorAll('.mobile-bottom-dock .dock-item[data-view]');

  const handleNavClick = (view) => {
    if (view && view !== State.currentStage) {
      State.set({ currentStage: view });
      switchViewStage(view, true);
    }
  };

  topPills.forEach((pill) => {
    pill.addEventListener('click', (e) => {
      e.preventDefault();
      handleNavClick(pill.getAttribute('data-view'));
    });
  });

  dockItems.forEach((item) => {
    item.addEventListener('click', (e) => {
      e.preventDefault();
      handleNavClick(item.getAttribute('data-view'));
    });
  });

  State.on('change:currentStage', (view) => {
    switchViewStage(view, false);
  });
}

function switchViewStage(view, emitEvent = true) {
  const topPills = document.querySelectorAll('.topbar .nav-pill[data-view]');
  const dockItems = document.querySelectorAll('.mobile-bottom-dock .dock-item[data-view]');

  topPills.forEach((pill) => {
    pill.classList.toggle('active', pill.getAttribute('data-view') === view);
  });

  dockItems.forEach((item) => {
    item.classList.toggle('active', item.getAttribute('data-view') === view);
  });

  const stageMap = {
    console: document.getElementById('view-console'),
    graph: document.getElementById('view-graph'),
    audit: document.getElementById('view-audit'),
    image: document.getElementById('view-image'),
    ops: document.getElementById('view-ops')
  };

  for (const [key, el] of Object.entries(stageMap)) {
    if (el) {
      el.classList.toggle('active', key === view);
    }
  }

  if (emitEvent) {
    window.dispatchEvent(new CustomEvent('autowechat:view-change', { detail: { view } }));
  }
}

function bindLanguageToggles() {
  const btnDesktop = document.getElementById('btn-lang-toggle');
  const btnMobile = document.getElementById('btn-lang-toggle-mobile');

  const updateLabels = (lang) => {
    const label = lang === 'zh' ? 'EN' : '中文';
    if (btnDesktop) btnDesktop.textContent = label;
    if (btnMobile) btnMobile.textContent = label;
  };

  updateLabels(State.activeLanguage || 'zh');

  const onToggle = () => {
    const next = toggleLanguage();
    updateLabels(next);
  };

  if (btnDesktop) btnDesktop.addEventListener('click', onToggle);
  if (btnMobile) btnMobile.addEventListener('click', onToggle);
}

function bindGlobalModals() {
  const closeButtons = document.querySelectorAll('[data-modal-close], .btn-close-modal, #btn-close-preview');
  closeButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      closeAllModals();
    });
  });

  const overlays = document.querySelectorAll('.modal-overlay');
  overlays.forEach((overlay) => {
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) {
        closeAllModals();
      }
    });
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeAllModals();
    }
  });
}

function closeAllModals() {
  document.querySelectorAll('.modal-overlay').forEach((modal) => {
    modal.classList.remove('open');
    modal.style.display = 'none';
  });

  const previewIframe = document.getElementById('preview-iframe');
  if (previewIframe) {
    previewIframe.src = 'about:blank';
  }
}

let _lastSessionCheckAt = 0;

async function verifySessionOrRedirect(force = false) {
  const now = Date.now();
  if (!force && now - _lastSessionCheckAt < 10000) return;
  _lastSessionCheckAt = now;
  try {
    const res = await fetch('/api/config', { cache: 'no-store' });
    if (res.status === 401 && !window.__awRedirectingToLogin) {
      window.__awRedirectingToLogin = true;
      window.location.replace('/login');
    }
  } catch (_) {
    // Ignore transient offline errors during resume
  }
}

function bindVisibilityResync() {
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      verifySessionOrRedirect(false);
      State.resyncRunningStatus();
    }
  });
  window.addEventListener('pageshow', (event) => {
    verifySessionOrRedirect(Boolean(event.persisted));
    if (event.persisted) {
      State.resyncRunningStatus();
    }
  });
}
