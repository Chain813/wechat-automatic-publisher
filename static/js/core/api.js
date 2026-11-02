// static/js/core/api.js
// RESTful Fetch wrapper with mutation lock and toast notifications

const mutationLocks = new Map();
const MUTATION_LOCK_DURATION_MS = 3000;

export function showToast(message, type = 'info') {
  if (typeof document === 'undefined') return;

  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = `toast-item toast-${type}`;
  toast.textContent = message;

  container.appendChild(toast);

  setTimeout(() => {
    toast.classList.add('fade-out');
    setTimeout(() => {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    }, 240);
  }, 3200);
}

function computeBodyHash(body) {
  if (!body) return '';
  if (typeof body === 'string') return body.slice(0, 100);
  if (body instanceof FormData) return 'formdata';
  try {
    return JSON.stringify(body).slice(0, 100);
  } catch (_) {
    return 'object';
  }
}

export async function request(url, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  const isMutation = ['POST', 'PUT', 'DELETE'].includes(method);
  const isPollingUrl = url.includes('/api/status') || url.includes('/api/logs');

  if (isMutation && !isPollingUrl) {
    const lockKey = `${method}:${url}:${computeBodyHash(options.body)}`;
    const now = Date.now();
    const lastTrigger = mutationLocks.get(lockKey) || 0;

    if (now - lastTrigger < MUTATION_LOCK_DURATION_MS) {
      const remainingSec = Math.ceil((MUTATION_LOCK_DURATION_MS - (now - lastTrigger)) / 1000);
      showToast(`操作过于频繁，请等待 ${remainingSec} 秒后再试`, 'warning');
      throw new Error(`Duplicate submission blocked: ${lockKey}`);
    }
    mutationLocks.set(lockKey, now);
  }

  const headers = {
    Accept: 'application/json',
    ...(options.headers || {})
  };

  const config = {
    ...options,
    method,
    headers
  };

  if (options.body && !(options.body instanceof FormData) && typeof options.body === 'object') {
    config.headers['Content-Type'] = 'application/json';
    config.body = JSON.stringify(options.body);
  }

  try {
    const response = await fetch(url, config);

    if (response.status === 401) {
      showToast('登录态已失效，正在跳转认证页...', 'warning');
      setTimeout(() => {
        window.location.href = '/';
      }, 800);
      throw new Error('Unauthorized');
    }

    const contentType = response.headers.get('content-type') || '';
    let data;

    if (contentType.includes('application/json')) {
      data = await response.json();
    } else {
      const text = await response.text();
      data = { text };
    }

    if (!response.ok) {
      const errorMsg = data.message || data.error || `HTTP ${response.status}`;
      showToast(errorMsg, 'error');
      const err = new Error(errorMsg);
      err.status = response.status;
      err.data = data;
      throw err;
    }

    return data;
  } catch (error) {
    if (error.message !== 'Unauthorized' && !error.message.startsWith('Duplicate submission blocked')) {
      console.error(`Request failed: ${method} ${url}`, error);
    }
    throw error;
  }
}

export const api = {
  get(url, options = {}) {
    return request(url, { ...options, method: 'GET' });
  },

  post(url, data = null, options = {}) {
    return request(url, { ...options, method: 'POST', body: data });
  },

  upload(url, formData, options = {}) {
    return request(url, {
      ...options,
      method: 'POST',
      body: formData
    });
  }
};

export const apiGet = api.get;
export const apiPost = api.post;
export const apiUpload = api.upload;

