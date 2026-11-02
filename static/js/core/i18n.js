// static/js/core/i18n.js
// Bilingual internationalization engine - Zero Emojis

import { State } from './state.js';
import { Storage } from './storage.js';

export const i18nDict = {
  // Navigation
  navConsole: { zh: '总控', en: 'Console' },
  navGraph: { zh: '图谱', en: 'Graph' },
  navAudit: { zh: '审稿', en: 'Audit' },
  navImage: { zh: '配图', en: 'Studio' },
  navOps: { zh: '运维', en: 'Ops' },

  // Workflow Types
  wfHotspots: { zh: '今日热点', en: 'Hotspots' },
  wfGithub: { zh: 'GitHub 趋势', en: 'GitHub' },
  wfSeries: { zh: '体系连载', en: 'Series' },
  wfDaily: { zh: '每日短文', en: 'Daily Brief' },

  // Actions
  btnStart: { zh: '启动编排', en: 'Start Pipeline' },
  btnPause: { zh: '暂停执行', en: 'Pause' },
  btnResume: { zh: '继续执行', en: 'Resume' },
  btnStop: { zh: '终止任务', en: 'Terminate' },
  btnPreheat: { zh: '预热图谱缓存', en: 'Preheat Cache' },
  btnClearLogs: { zh: '清空日志', en: 'Clear Logs' },
  btnTimelineMode: { zh: '可视时间轴', en: 'Timeline' },
  btnRawMode: { zh: '原始流 (Raw)', en: 'Raw Stream' },
  btnSyncWechat: { zh: '微信同步', en: 'WeChat Sync' },
  btnComposeRecommend: { zh: '撰写推荐节点', en: 'Write Recommended' },
  btnBatchDelete: { zh: '批量删除', en: 'Batch Delete' },
  btnBatchApprove: { zh: '一键批量核准推送', en: 'Batch Approve & Push' },
  btnApproveSingle: { zh: '准发', en: 'Approve' },
  btnPreview: { zh: '预览', en: 'Preview' },
  btnReviewPass: { zh: '确认群发排期', en: 'Schedule Push' },
  btnRedrawUrl: { zh: '抓图重绘', en: 'Fetch & Redraw' },
  btnExtractPrompts: { zh: '提取插图提示词', en: 'Extract Prompts' },
  btnSetCover: { zh: '设为封面题图', en: 'Set as Cover' },
  btnTestConnection: { zh: '测试连通性', en: 'Test Connectivity' },
  btnSaveSettings: { zh: '保存全部设置', en: 'Save Settings' },
  btnAddCron: { zh: '添加任务', en: 'Add Job' },

  // Status Labels
  statusIdle: { zh: '空闲就绪', en: 'Idle' },
  statusStarting: { zh: '正在下发...', en: 'Starting...' },
  statusRunning: { zh: '流水线执行中', en: 'Running' },
  statusPaused: { zh: '任务已暂停', en: 'Paused' },
  statusStopping: { zh: '正在终止...', en: 'Stopping...' },
  statusCompleted: { zh: '编排批次完成', en: 'Completed' },
  statusError: { zh: '执行异常', en: 'Error' },

  // Telemetry Labels
  cacheHitRate: { zh: 'Cache 命中率', en: 'Cache Hit Rate' },
  tokensSaved: { zh: '已省 Tokens', en: 'Tokens Saved' },
  costSaved: { zh: '节省资金', en: 'Cost Saved' },
  seriesProgress: { zh: '体系连载', en: 'Series Progress' },
  nextRecommended: { zh: '下一推荐节点', en: 'Next Node' },

  // Phase Names
  phase1Title: { zh: '01 信源采集去重', en: '01 Source Dedupe' },
  phase2Title: { zh: '02 深度创作润色', en: '02 Deep Synthesis' },
  phase3Title: { zh: '03 多模配图渲染', en: '03 Visual Studio' },
  phase4Title: { zh: '04 事实核查推送', en: '04 Fact Audit & Push' },

  // Ops Subviews
  opsTabSources: { zh: '信源健康', en: 'Source Matrix' },
  opsTabCron: { zh: '定时任务', en: 'Scheduled Cron' },
  opsTabSettings: { zh: '系统设置', en: 'System Settings' }
};

export function t(key) {
  const lang = State.activeLanguage || 'zh';
  const entry = i18nDict[key];
  if (!entry) return key;
  return entry[lang] || entry.zh || key;
}

export function applyI18n(container = document) {
  if (typeof document === 'undefined') return;

  const elements = container.querySelectorAll('[data-i18n]');
  for (const el of elements) {
    const key = el.getAttribute('data-i18n');
    if (key && i18nDict[key]) {
      el.textContent = t(key);
    }
  }

  const placeholderEls = container.querySelectorAll('[data-i18n-placeholder]');
  for (const el of placeholderEls) {
    const key = el.getAttribute('data-i18n-placeholder');
    if (key && i18nDict[key]) {
      el.setAttribute('placeholder', t(key));
    }
  }

  const titleEls = container.querySelectorAll('[data-i18n-title]');
  for (const el of titleEls) {
    const key = el.getAttribute('data-i18n-title');
    if (key && i18nDict[key]) {
      el.setAttribute('title', t(key));
    }
  }
}

export function toggleLanguage() {
  const currentLang = State.activeLanguage === 'en' ? 'zh' : 'en';
  State.set({ activeLanguage: currentLang });
  Storage.set('aw_lang', currentLang);
  applyI18n();
  State.emit('lang:changed', currentLang);
  return currentLang;
}
