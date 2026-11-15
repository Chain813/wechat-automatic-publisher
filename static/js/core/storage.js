// static/js/core/storage.js
// Safe LocalStorage wrapper with memory fallback

const memoryStore = new Map();

function hasLocalStorage() {
  try {
    const testKey = '__aw_storage_test__';
    window.localStorage.setItem(testKey, '1');
    window.localStorage.removeItem(testKey);
    return true;
  } catch (e) {
    return false;
  }
}

const isLocalStorageAvailable = typeof window !== 'undefined' && hasLocalStorage();

export const Storage = {
  get(key, defaultValue = null) {
    try {
      if (isLocalStorageAvailable) {
        const item = window.localStorage.getItem(key);
        if (item === null) return defaultValue;
        try {
          return JSON.parse(item);
        } catch (_) {
          return item;
        }
      } else {
        if (memoryStore.has(key)) {
          return memoryStore.get(key);
        }
        return defaultValue;
      }
    } catch (err) {
      console.warn(`Storage get error for key "${key}":`, err);
      return defaultValue;
    }
  },

  set(key, value) {
    try {
      const serialized = typeof value === 'string' ? value : JSON.stringify(value);
      if (isLocalStorageAvailable) {
        window.localStorage.setItem(key, serialized);
      } else {
        memoryStore.set(key, value);
      }
      return true;
    } catch (err) {
      console.warn(`Storage set error for key "${key}", falling back to memory:`, err);
      memoryStore.set(key, value);
      return false;
    }
  },

  remove(key) {
    try {
      if (isLocalStorageAvailable) {
        window.localStorage.removeItem(key);
      }
      memoryStore.delete(key);
      return true;
    } catch (err) {
      console.warn(`Storage remove error for key "${key}":`, err);
      memoryStore.delete(key);
      return false;
    }
  }
};
