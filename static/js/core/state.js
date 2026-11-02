// static/js/core/state.js
// Global Reactive State Store & Workflow Finite State Machine

import { Storage } from './storage.js';
import { api } from './api.js';

export const WORKFLOW_STATES = {
  IDLE: 'IDLE',
  STARTING: 'STARTING',
  RUNNING: 'RUNNING',
  PAUSED: 'PAUSED',
  STOPPING: 'STOPPING',
  COMPLETED: 'COMPLETED',
  ERROR: 'ERROR'
};

function createDefaultPipelineModel() {
  return {
    activePhase: 0,
    currentTopic: '',
    phases: {
      1: { status: 'pending', badge: '待命', items: [], sourcesScanned: 0, candidatesCount: 0, lockedTopic: '' },
      2: { status: 'pending', badge: '待命', items: [], sections: [], wordCount: 0 },
      3: {
        status: 'pending',
        badge: '待命',
        items: [],
        slots: [
          { index: 1, label: '槽位 01 · 封面与主图', status: 'pending', score: null, detail: '等待提取' },
          { index: 2, label: '槽位 02 · 核心架构图', status: 'pending', score: null, detail: '等待提取' },
          { index: 3, label: '槽位 03 · 场景配图', status: 'pending', score: null, detail: '等待提取' }
        ]
      },
      4: { status: 'pending', badge: '待命', items: [], qualityScore: null, factCheck: '等待核验', draftId: '', completed: false }
    },
    rawLines: []
  };
}

class StateStore {
  constructor() {
    this.currentStage = Storage.get('aw_stage', 'console');
    this.currentOpsTab = Storage.get('aw_ops_tab', 'sources');
    this.engineState = WORKFLOW_STATES.IDLE;
    this.activeWorkflow = Storage.get('aw_workflow', 'hotspots');
    this.activeLanguage = Storage.get('aw_lang', 'zh');
    this.logViewMode = Storage.get('aw_log_mode', 'timeline');
    this.hudCollapsed = Boolean(Storage.get('aw_hud_collapsed', false));
    this.selectedNode = null;
    this.pipelineModel = createDefaultPipelineModel();

    this._listeners = new Map();
  }

  set(patch = {}) {
    let changed = false;
    for (const [key, value] of Object.entries(patch)) {
      if (this[key] !== value) {
        this[key] = value;
        changed = true;

        if (key === 'currentStage') Storage.set('aw_stage', value);
        if (key === 'currentOpsTab') Storage.set('aw_ops_tab', value);
        if (key === 'activeWorkflow') Storage.set('aw_workflow', value);
        if (key === 'activeLanguage') Storage.set('aw_lang', value);
        if (key === 'logViewMode') Storage.set('aw_log_mode', value);
        if (key === 'hudCollapsed') Storage.set('aw_hud_collapsed', value);

        this.emit(`change:${key}`, value);
      }
    }
    if (changed) {
      this.emit('change', patch);
    }
  }

  on(event, handler) {
    if (!this._listeners.has(event)) {
      this._listeners.set(event, new Set());
    }
    this._listeners.get(event).add(handler);
    return () => this.off(event, handler);
  }

  off(event, handler) {
    if (this._listeners.has(event)) {
      this._listeners.get(event).delete(handler);
    }
  }

  emit(event, payload) {
    if (this._listeners.has(event)) {
      for (const handler of this._listeners.get(event)) {
        try {
          handler(payload);
        } catch (err) {
          console.error(`Error in state listener for event "${event}":`, err);
        }
      }
    }
  }

  transitionEngine(nextState) {
    if (!WORKFLOW_STATES[nextState]) {
      console.warn(`Invalid workflow state transition: ${nextState}`);
      return false;
    }
    const previous = this.engineState;
    this.engineState = nextState;
    this.emit('engine:state', { current: nextState, previous });
    return true;
  }

  async resyncRunningStatus() {
    try {
      const data = await api.get('/api/status');
      const isPaused = Boolean(data && (data.is_paused || data.status === 'paused'));
      const isRunning = Boolean(data && (data.is_running || data.status === 'running'));

      let nextEngineState = WORKFLOW_STATES.IDLE;
      if (isPaused) nextEngineState = WORKFLOW_STATES.PAUSED;
      else if (isRunning) nextEngineState = WORKFLOW_STATES.RUNNING;

      if (this.engineState !== nextEngineState) {
        this.transitionEngine(nextEngineState);
      }
      this.emit('status:resync', data);
      return data;
    } catch (err) {
      console.warn('Status resync failed:', err);
      return null;
    }
  }
}

export const State = new StateStore();
