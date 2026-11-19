import '@material/web/labs/card/elevated-card.js';
import '@material/web/chips/filter-chip.js';
import '@material/web/dialog/dialog.js';
import '@material/web/button/text-button.js';
import '@material/web/ripple/ripple.js';
import '@material/web/focus/md-focus-ring.js';

const icons = {
  simulation: '<rect x="6" y="6" width="12" height="12" rx="3"/><path d="M9 1v5m6-5v5M9 18v5m6-5v5M1 9h5m-5 6h5m12-6h5m-5 6h5M9 12h6m-3-3v6"/>',
  archive: '<path d="M4 8h16v12H4zM3 4h18v4H3zM9 12h6m-4 4h2"/>',
  model: '<circle cx="5" cy="12" r="2"/><circle cx="18" cy="5" r="2"/><circle cx="18" cy="19" r="2"/><path d="m7 11 9-5M7 13l9 5m2-11v10"/>',
  demo: '<rect x="2" y="4" width="20" height="16" rx="3"/><path d="M2 9h20m-13 4 3 2-3 2m6 0h3M6 6.5h.01M9 6.5h.01"/>',
  arrow: '<path d="M5 12h14m-6-6 6 6-6 6"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  refresh: '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1"/>',
  chevron: '<path d="m8 10 4 4 4-4"/>'
};

export function icon(name, extra = '') {
  return `<svg ${extra} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.arrow}</svg>`;
}

const labels = {
  zh: {
    eyebrow: 'EXPLORE THE EVIDENCE',
    title: '让每一步有据可循',
    intro: '四类研究材料。一条可追溯链路。',
    hint: '选择卡片探索证据',
    schematic: '研究结构示意',
    modes: ['内容概览', '记录要素', '复现条件'],
    detail: '查看说明',
    close: '完成',
    selected: '当前视角',
    document: '研究材料说明',
    scope: '公开页面介绍证据组织方式。具体研究结果以对应任务记录与验证条件为准。'
  },
  en: {
    eyebrow: 'EXPLORE THE EVIDENCE',
    title: 'Follow the evidence',
    intro: 'Four material types. One traceable chain.',
    hint: 'Select a card to explore',
    schematic: 'Research structure illustration',
    modes: ['Overview', 'Record fields', 'Reproduction'],
    detail: 'Read the note',
    close: 'Done',
    selected: 'Selected view',
    document: 'About these materials',
    scope: 'This page describes how evidence is organized. Research findings follow their task records and validation conditions.'
  }
};

const content = {
  zh: [
    { id: 'simulation', title: '真实仿真', subtitle: '从器件响应回到原始记录', tag: '任务链路',
      description: ['连接器件条件、仿真设置与原始输出。', '每项结果对应一组输入与验证记录。'],
      fields: ['器件条件', '输入参数', '原始输出'],
      reproduction: ['确认输入与求解设置。', '沿原任务链路核对输出与收敛记录。'] },
    { id: 'archive', title: '历史归档', subtitle: '让旧材料保留完整上下文', tag: '来源与条件',
      description: ['按来源与形成条件整理历史材料。', '复用时一并查看参数范围和原有结论。'],
      fields: ['来源版本', '形成条件', '适用范围'],
      reproduction: ['对齐材料版本与形成条件。', '结合原始说明评估当前问题的适用范围。'] },
    { id: 'model', title: '模型预测', subtitle: '连接训练数据与适用范围', tag: '版本与评价',
      description: ['围绕翻转截面与错误率建立预测方法。', '预测结果结合模型版本与独立评价解释。'],
      fields: ['模型版本', '数据划分', '评价条件'],
      reproduction: ['固定数据划分与模型版本。', '记录输入范围并开展独立验证与泛化评价。'] },
    { id: 'demo', title: '接口演示', subtitle: '沿交互流程理解研究链路', tag: '流程示意',
      description: ['用交互页面呈现研究流程与材料关系。', '演示内容按样例语境解读。'],
      fields: ['流程步骤', '样例说明', '输入输出关系'],
      reproduction: ['从样例说明进入对应流程。', '逐步检查输入输出关系与交互反馈。'] }
  ],
  en: [
    { id: 'simulation', title: 'Native simulation', subtitle: 'From device response to source records', tag: 'Task chain',
      description: ['Connect device conditions, simulation settings, and source outputs.', 'Each result follows its inputs and validation records.'],
      fields: ['Device conditions', 'Input parameters', 'Source outputs'],
      reproduction: ['Confirm the inputs and solver settings.', 'Trace the outputs and convergence records through the original task chain.'] },
    { id: 'archive', title: 'Historical archive', subtitle: 'Keep the context with the material', tag: 'Source & context',
      description: ['Organize historical material by source and original conditions.', 'Review its parameter range and conclusions together.'],
      fields: ['Source version', 'Original conditions', 'Scope'],
      reproduction: ['Align the version and original conditions.', 'Use the source notes to assess relevance to the current question.'] },
    { id: 'model', title: 'Model prediction', subtitle: 'Connect training data and scope', tag: 'Version & evaluation',
      description: ['Develop prediction methods for cross-sections and error rates.', 'Interpret predictions alongside model versions and independent evaluation.'],
      fields: ['Model version', 'Data split', 'Evaluation conditions'],
      reproduction: ['Fix the data split and model version.', 'Record the input range and evaluate independent validation and generalization.'] },
    { id: 'demo', title: 'Interface demo', subtitle: 'Explore the research workflow', tag: 'Workflow illustration',
      description: ['Present research steps and material relationships through interaction.', 'Read demonstration content in the context of its sample.'],
      fields: ['Workflow steps', 'Sample notes', 'Input / output links'],
      reproduction: ['Start from the sample notes.', 'Follow the input / output relationships and interaction feedback.'] }
  ]
};

let selectedId = 'simulation';
let selectedMode = 0;

function diagram(index) {
  const drawings = [
    '<path class="diagram-path" d="M0 42H24L32 41L39 16L46 58L54 32L62 42H120"/><path opacity=".25" d="M0 64h120M0 20h120"/>',
    '<rect class="diagram-layer layer-one" x="22" y="12" width="70" height="42" rx="6"/><rect class="diagram-layer layer-two" x="15" y="20" width="70" height="42" rx="6"/><rect class="diagram-layer layer-three" x="8" y="28" width="70" height="42" rx="6"/>',
    '<path class="diagram-path" d="M16 40 57 15 98 40 57 65 16 40M57 15v50M16 40h82"/><g class="diagram-nodes"><circle cx="16" cy="40" r="5"/><circle cx="57" cy="15" r="5"/><circle cx="57" cy="65" r="5"/><circle cx="98" cy="40" r="5"/></g>',
    '<rect x="14" y="15" width="92" height="52" rx="8"/><path opacity=".4" d="M14 29h92M21 22h3m4 0h3"/><path class="diagram-path" d="m35 40 9 8-9 8m21 0h17"/>'
  ];
  return `<svg class="evidence-diagram diagram-${index}" viewBox="0 0 120 80" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">${drawings[index]}</svg>`;
}

export function mountEvidence(root, lang) {
  const l = labels[lang];
  const items = content[lang];
  root.innerHTML = `
    <div class="evidence-decoration" aria-hidden="true">
      <span class="evidence-orbit evidence-orbit-one"></span>
      <span class="evidence-orbit evidence-orbit-two"></span>
      <span class="evidence-signal evidence-signal-one"></span>
      <span class="evidence-signal evidence-signal-two"></span>
    </div>
    <div class="section-heading evidence-intro">
      <p class="eyebrow">${l.eyebrow}</p>
      <h2>${l.title}</h2>
      <p>${l.intro}</p>
      <div class="evidence-map" aria-hidden="true">
        <span class="map-node map-node-source">${icon('simulation')}</span>
        <span class="map-node map-node-model">${icon('model')}</span>
        <span class="map-node map-node-archive">${icon('archive')}</span>
        <span class="map-center">${icon('check')}</span>
        <svg class="map-connections" viewBox="0 0 260 170"><path d="M48 40 130 86 219 34M130 86l49 60" /></svg>
        <span class="map-dot map-dot-one"></span><span class="map-dot map-dot-two"></span>
      </div>
      <span class="evidence-illustration-label">${l.schematic}</span>
      <div class="evidence-chips" role="group" aria-label="${l.selected}">
        ${l.modes.map((label, index) => `<md-filter-chip data-evidence-mode="${index}" label="${label}" ${index === selectedMode ? 'selected' : ''}></md-filter-chip>`).join('')}
      </div>
    </div>
    <div class="evidence-card-grid" role="group" aria-label="${l.hint}">
      ${items.map((item, index) => `
        <md-elevated-card class="evidence-card evidence-card-${index + 1} ${item.id === selectedId ? 'is-selected' : ''}" data-evidence-card="${item.id}">
          <span class="evidence-card-glow" aria-hidden="true"></span>
          <div class="evidence-card-top">
            <span class="evidence-icon" aria-hidden="true">${icon(item.id)}</span>
            <span class="evidence-index" aria-hidden="true">0${index + 1}</span>
          </div>
          ${diagram(index)}
          <div class="evidence-card-copy"><h3>${item.title}</h3><p>${item.subtitle}</p></div>
          <div class="evidence-card-footer">
            <span class="evidence-tag">${item.tag}</span>
            <span class="evidence-card-arrow" aria-hidden="true">${icon('arrow')}</span>
          </div>
          <button class="evidence-select" data-evidence-id="${item.id}" aria-pressed="${item.id === selectedId}" aria-controls="evidence-detail" aria-label="${item.title} · ${l.detail}">
            <md-ripple></md-ripple><md-focus-ring inward></md-focus-ring>
          </button>
        </md-elevated-card>`).join('')}
    </div>
    <aside id="evidence-detail" class="evidence-detail" aria-live="polite"></aside>
    <md-dialog class="evidence-dialog" aria-label="${l.document}">
      <div slot="headline" id="evidence-dialog-title"></div>
      <div slot="content" id="evidence-dialog-content"></div>
      <div slot="actions"><md-text-button id="evidence-dialog-close">${l.close}</md-text-button></div>
    </md-dialog>`;

  function updateDetail(animate = true) {
    const item = items.find(item => item.id === selectedId);
    const index = items.indexOf(item);
    root.querySelectorAll('[data-evidence-card]').forEach(card => {
      card.classList.toggle('is-selected', card.dataset.evidenceCard === selectedId);
      card.querySelector('button').setAttribute('aria-pressed', String(card.dataset.evidenceCard === selectedId));
    });
    root.querySelectorAll('[data-evidence-mode]').forEach(chip => {
      chip.selected = Number(chip.dataset.evidenceMode) === selectedMode;
    });
    const detail = root.querySelector('#evidence-detail');
    const body = selectedMode === 1
      ? `<div class="evidence-field-list">${item.fields.map(field => `<span>${field}</span>`).join('')}</div>`
      : `<p>${(selectedMode === 2 ? item.reproduction : item.description)[0]}</p>`;
    detail.innerHTML = `
      <div class="evidence-detail-heading">
        <span class="evidence-detail-number">0${index + 1}</span>
        <div><p class="evidence-detail-label">${l.modes[selectedMode]}</p><h3>${item.title}</h3></div>
      </div>
      <div class="evidence-detail-body">${body}</div>
      <md-text-button class="evidence-detail-button">${l.detail}<span slot="icon">${icon('arrow')}</span></md-text-button>`;
    detail.dataset.accent = item.id;
    if (animate && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
      detail.animate([{ opacity: .35, transform: 'translateY(5px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 240, easing: 'ease-out' });
    }
    detail.querySelector('md-text-button').addEventListener('click', () => {
      root.querySelector('#evidence-dialog-title').textContent = item.title;
      root.querySelector('#evidence-dialog-content').innerHTML = `
        <p class="dialog-lead">${item.description.join(' ')}</p>
        <h3>${l.modes[1]}</h3>
        <div class="evidence-field-list">${item.fields.map(field => `<span>${field}</span>`).join('')}</div>
        <h3>${l.modes[2]}</h3>
        <p>${item.reproduction.join(' ')}</p>
        <p class="dialog-scope">${l.scope}</p>`;
      root.querySelector('md-dialog').show();
    });
  }

  root.querySelectorAll('[data-evidence-id]').forEach(button => {
    button.addEventListener('click', () => {
      selectedId = button.dataset.evidenceId;
      updateDetail();
    });
  });
  root.querySelectorAll('[data-evidence-mode]').forEach(chip => {
    chip.addEventListener('click', () => {
      selectedMode = Number(chip.dataset.evidenceMode);
      updateDetail();
    });
  });
  root.querySelector('#evidence-dialog-close').addEventListener('click', () => root.querySelector('md-dialog').close());
  updateDetail(false);
}
