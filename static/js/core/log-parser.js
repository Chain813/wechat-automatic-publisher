// static/js/core/log-parser.js
// Pure reducer parsing /api/logs into a 4-phase structured pipeline model

const EMOJI_REGEX = /[\uD800-\uDBFF][\uDC00-\uDFFF]|[\u2600-\u27BF]|[\u2300-\u23FF]|[\u2B50-\u2B55]|[\u203C-\u2049]|[\uFE00-\uFE0F]/g;

export function stripEmojis(text) {
  if (typeof text !== 'string') return '';
  return text.replace(EMOJI_REGEX, '').trim();
}

export function createInitialPipelineModel() {
  return {
    activePhase: 0,
    currentTopic: '',
    phases: {
      1: {
        status: 'pending',
        badge: '待命',
        items: [],
        sourcesScanned: 0,
        candidatesCount: 0,
        lockedTopic: ''
      },
      2: {
        status: 'pending',
        badge: '待命',
        items: [],
        sections: [],
        wordCount: 0
      },
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
      4: {
        status: 'pending',
        badge: '待命',
        items: [],
        qualityScore: null,
        factCheck: '等待核验',
        draftId: '',
        completed: false
      }
    },
    rawLines: []
  };
}

export function parseLogs(newLines = [], prevModel = null) {
  const model = prevModel ? JSON.parse(JSON.stringify(prevModel)) : createInitialPipelineModel();

  if (!Array.isArray(newLines) || newLines.length === 0) {
    return model;
  }

  for (const raw of newLines) {
    const clean = stripEmojis(raw);
    if (!clean) continue;

    model.rawLines.push(clean);
    if (model.rawLines.length > 500) {
      model.rawLines.shift();
    }

    // Inspect keywords to populate model
    const lower = clean.toLowerCase();

    // Phase 1 keywords
    if (/同步|抓取|热点|github|选定|候选|信源|source|rss/.test(lower)) {
      if (model.phases[1].status === 'pending') {
        model.phases[1].status = 'active';
        model.phases[1].badge = '扫描中';
        model.activePhase = Math.max(model.activePhase, 1);
      }
      model.phases[1].items.push(clean);

      const countMatch = clean.match(/(\d+)\s*篇/);
      if (countMatch) {
        model.phases[1].candidatesCount = parseInt(countMatch[1], 10);
      }
      if (/锁定|选题|topic|标题/.test(lower)) {
        model.phases[1].lockedTopic = clean.replace(/.*?[:：]/, '').trim();
        model.currentTopic = model.phases[1].lockedTopic;
        model.phases[1].status = 'completed';
        model.phases[1].badge = '已完成';
      }
    }

    // Phase 2 keywords
    if (/大纲|章节|deepseek|生成|撰写|润色|map-reduce|token/.test(lower)) {
      if (model.phases[1].status === 'active') {
        model.phases[1].status = 'completed';
        model.phases[1].badge = '已完成';
      }
      if (model.phases[2].status === 'pending') {
        model.phases[2].status = 'active';
        model.phases[2].badge = '创作中';
        model.activePhase = Math.max(model.activePhase, 2);
      }
      model.phases[2].items.push(clean);

      const wordsMatch = clean.match(/(\d{3,5})\s*字/);
      if (wordsMatch) {
        model.phases[2].wordCount = parseInt(wordsMatch[1], 10);
      }
      if (/节|section/.test(lower)) {
        model.phases[2].sections.push(clean);
      }
      if (/完成|100%|就绪/.test(lower)) {
        model.phases[2].status = 'completed';
        model.phases[2].badge = '已完成';
      }
    }

    // Phase 3 keywords
    if (/配图|图片|评分|qwen|sd|渲染|上传|槽位|asset|cdn/.test(lower)) {
      if (model.phases[2].status === 'active') {
        model.phases[2].status = 'completed';
        model.phases[2].badge = '已完成';
      }
      if (model.phases[3].status === 'pending') {
        model.phases[3].status = 'active';
        model.phases[3].badge = '渲染中';
        model.activePhase = Math.max(model.activePhase, 3);
      }
      model.phases[3].items.push(clean);

      if (/槽位\s*1|slot\s*1|封面/.test(lower)) {
        model.phases[3].slots[0].status = 'completed';
        model.phases[3].slots[0].detail = '渲染就绪';
      }
      if (/槽位\s*2|slot\s*2|架构/.test(lower)) {
        model.phases[3].slots[1].status = 'completed';
        model.phases[3].slots[1].detail = '生成就绪';
      }
      if (/槽位\s*3|slot\s*3|热力/.test(lower)) {
        model.phases[3].slots[2].status = 'completed';
        model.phases[3].slots[2].detail = '上传完成';
      }
      if (/全部完成|3\/3/.test(lower)) {
        model.phases[3].status = 'completed';
        model.phases[3].badge = '已完成';
      }
    }

    // Phase 4 keywords
    if (/核查|质量|草稿|draft|成功|批次完成|审核|audit|push/.test(lower)) {
      if (model.phases[3].status === 'active') {
        model.phases[3].status = 'completed';
        model.phases[3].badge = '已完成';
      }
      if (model.phases[4].status === 'pending') {
        model.phases[4].status = 'active';
        model.phases[4].badge = '门禁质检';
        model.activePhase = Math.max(model.activePhase, 4);
      }
      model.phases[4].items.push(clean);

      const scoreMatch = clean.match(/(\d{2}(\.\d)?)\s*分/);
      if (scoreMatch) {
        model.phases[4].qualityScore = parseFloat(scoreMatch[1]);
      }
      const draftMatch = clean.match(/(msg_\w+|wxdraft_\w+)/i);
      if (draftMatch) {
        model.phases[4].draftId = draftMatch[1];
      }
      if (/成功|批次完成|100%|通过/.test(lower)) {
        model.phases[4].status = 'completed';
        model.phases[4].badge = '质检通过';
        model.phases[4].completed = true;
        model.activePhase = 5;
      }
    }
  }

  return model;
}
