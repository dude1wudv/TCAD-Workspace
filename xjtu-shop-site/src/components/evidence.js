import '@material/web/labs/card/elevated-card.js';
import '@material/web/chips/filter-chip.js';
import '@material/web/dialog/dialog.js';
import '@material/web/button/text-button.js';
import '@material/web/ripple/ripple.js';
import '@material/web/focus/md-focus-ring.js';
import { icon } from '../shared/icons.js';
import { escapeHtml } from '../shared/site-shell.js';

const labels = {
  zh: {
    eyebrow: 'SCIENTIFIC LEDGER & BOUNDARIES',
    title: '四级证据账本与科学边界',
    intro: '工程跑通不等同于科学合格。系统完整保留进程身份链、防泄漏分组、历史失败与待闭合门槛。',
    hint: '点击卡片查看证据契约',
    modes: ['核心机制', '账本要素', '开放边界'],
    detail: '展开完整契约说明',
    close: '关闭',
    selected: '切换视角',
    document: '科学证据与契约说明',
    scope: '公开页面仅展示脱敏规范与审计摘要；原始 run_id、服务器路径与 58 条封存留出明细保持离线保密。'
  },
  en: {
    eyebrow: 'SCIENTIFIC LEDGER & BOUNDARIES',
    title: '4-Tier Scientific Ledger & Honest Scope',
    intro: 'Engineering completion never equals scientific acceptance. Provenance, leak-free splits, failures, and open gates stay transparent.',
    hint: 'Select a card to inspect contract',
    modes: ['Mechanism', 'Ledger Fields', 'Open Scope'],
    detail: 'Read Full Contract',
    close: 'Close',
    selected: 'Switch perspective',
    document: 'Scientific Evidence & Contract Note',
    scope: 'Only redacted specifications and audited summaries appear publicly; raw run IDs, server paths, and 58 sealed holdout cases remain private.'
  }
};

const content = {
  zh: [
    {
      id: 'ledger',
      iconName: 'ledger',
      title: '四级科学验收账本',
      subtitle: 'COLLECTED ≠ solved ≠ accepted ≠ statistics_eligible',
      tag: '口径隔离',
      overview: [
        '将工程归档（COLLECTED）、求解退出（solved）、科学核验（accepted）与统计资格（statistics_eligible）彻底解耦。',
        'P0 诊断试跑与 396 正式槽位独立计数，绝不混用分母。'
      ],
      fields: ['COLLECTED 归档态', 'solved 终点校验', 'accepted 科学核验', 'statistics_eligible 快照'],
      boundaries: [
        'r0.6 正式进度随 /live.json 实时投影；统计资格快照目前为 not_connected（214 为用途上限）。',
        '历史失败尝试（v2 语法错误、v4 TDR 覆盖、r0.6 早期拒步）永久保留在账本中。'
      ]
    },
    {
      id: 'shield',
      iconName: 'shield',
      title: '进程防伪与输入冻结',
      subtitle: 'PID + start_ticks + boot_id · SHA256SUMS',
      tag: '不可伪造链',
      overview: [
        '每次提交冻结输入 SHA256SUMS 契约，并绑定内核级 PID + start_ticks + boot_id 身份链防止重启错认。',
        'intent_reconciliation 仅凭完整回执闭合未启动意图，绝不盲目重投。'
      ],
      fields: ['输入 SHA256SUMS', 'PID / start_ticks / boot_id', '唯一串行收集锁', 'r06_gate 门禁'],
      boundaries: [
        '虚拟机原厂许可完整性工具曾出现退出 255 异常（短求解可用，完整校验持续跟踪）。',
        'watchdog 仅作阻塞告警，绝不越权强杀活跃求解进程。'
      ]
    },
    {
      id: 'model',
      iconName: 'model',
      title: '防泄漏划分与留出封存',
      subtitle: '连通分量分组 · HR/HP 58 例屏蔽',
      tag: '无偏评价',
      overview: [
        'splits.py 按器件、复用初级粒子与对照来源构建连通分量图做 3 折分组 CV，杜绝跨折信息泄漏。',
        'r0.6 的 58 条 HR/HP 留出案例与封存输运池明细在投影层即被剥离。'
      ],
      fields: ['连通分量划分图', 'HR(28)+HP(30) 封存', '零沉积事件保留', 'Horvitz-Thompson 权重'],
      boundaries: [
        'R → A → F 网络已通过 172 项离线测试，但正式训练与消融实验等待 r0.6 全量合格标签就位。',
        '未完成正式训练前不向外宣称宏观截面预测曲线。'
      ]
    },
    {
      id: 'boundary',
      iconName: 'boundary',
      title: '待闭合门槛与实验缺口',
      subtitle: 'P0 共同门槛 · DDR5 外部对照',
      tag: '诚实边界',
      overview: [
        '明确记录 P0 共同门槛、13 槽满载长时内存峰值统计与外部实测数据缺口，避免外推失真。',
        '所有已发布指标均附样本量、误差口径与物理适用范围。'
      ],
      fields: ['P0 共同门槛收尾', '满载 P95 吞吐统计', '研究台 503 模型占位', 'DDR5 实验缺口 G01–G06'],
      boundaries: [
        '受邀研究台 /desk/ 预测接口目前明确返回 503 model_pending 占位。',
        '课题组 DDR5 原始辐照实验交接（G01–G06）与外部验证仍在推进中。'
      ]
    }
  ],
  en: [
    {
      id: 'ledger',
      iconName: 'ledger',
      title: '4-Tier Acceptance Ledger',
      subtitle: 'COLLECTED ≠ solved ≠ accepted ≠ statistics_eligible',
      tag: 'Strict Split',
      overview: [
        'Decouples engineering archival (COLLECTED), solver exit (solved), scientific acceptance (accepted), and statistical eligibility.',
        'P0 diagnostics stay strictly separate from the 396 formal r0.6 denominator.'
      ],
      fields: ['COLLECTED archival', 'solved endpoint check', 'accepted sign-off', 'statistics_eligible snapshot'],
      boundaries: [
        'Formal r0.6 progress streams live via /live.json; statistics snapshot remains not_connected (214 intent cap).',
        'Historical failures remain permanently immutable in the ledger.'
      ]
    },
    {
      id: 'shield',
      iconName: 'shield',
      title: 'Process Provenance & Hash',
      subtitle: 'PID + start_ticks + boot_id · SHA256SUMS',
      tag: 'Anti-Spoofing',
      overview: [
        'Freezes input SHA256SUMS and pins kernel-level PID + start_ticks + boot_id chains across every run.',
        'Receipt-verified reconciliation closes unlaunched intents without blind resubmission.'
      ],
      fields: ['Input SHA256SUMS', 'PID / start_ticks / boot_id', 'Serial collector lock', 'Fail-closed r06_gate'],
      boundaries: [
        'Legacy VM license integrity tool previously exited 255 while short solves succeeded.',
        'Watchdog emits alerts only and never kills running solvers.'
      ]
    },
    {
      id: 'model',
      iconName: 'model',
      title: 'Leak-Free Splits & Holdout',
      subtitle: 'Connected Components · 58 Sealed Cases',
      tag: 'Unbiased Eval',
      overview: [
        'splits.py clusters shared profiles, primaries, and controls into connected components for 3-fold group CV.',
        'All 58 HR/HP holdout cases are stripped by the projector before public serialization.'
      ],
      fields: ['Component split graph', 'HR(28)+HP(30) sealed', 'Zero-dep retention', 'Horvitz-Thompson weights'],
      boundaries: [
        'R → A → F passes 172 offline tests; formal training awaits full r0.6 accepted cohorts.',
        'No macroscopic cross-section predictions are published prior to formal ablation.'
      ]
    },
    {
      id: 'boundary',
      iconName: 'boundary',
      title: 'Open Gates & Data Gaps',
      subtitle: 'P0 Closure · External DDR5 Data',
      tag: 'Honest Scope',
      overview: [
        'Tracks remaining P0 prerequisites, sustained 13-slot telemetry, and external irradiation dataset validation.',
        'Published metrics always state exact sample counts and tolerances.'
      ],
      fields: ['P0 gate closeout', 'Sustained P95 telemetry', '/desk/ 503 placeholder', 'DDR5 gaps G01–G06'],
      boundaries: [
        'Invited /desk/ prediction endpoints return 503 model_pending until trained weights land.',
        'External DDR5 experimental dataset handover (G01–G06) remains in progress.'
      ]
    }
  ]
};

let selectedId = 'ledger';
let selectedMode = 0;

export function mountEvidence(root, lang) {
  const l = labels[lang];
  const items = content[lang];

  root.innerHTML = `
    <div class="evidence-layout">
      <div class="evidence-left">
        <div class="section-head" style="margin-bottom:14px;">
          <p class="eyebrow">${icon('ledger')} ${escapeHtml(l.eyebrow)}</p>
          <h2>${escapeHtml(l.title)}</h2>
          <p class="lead">${escapeHtml(l.intro)}</p>
        </div>
        <div class="evidence-chips" role="group" aria-label="${escapeHtml(l.selected)}">
          ${l.modes.map((label, index) => `
            <md-filter-chip data-evidence-mode="${index}" label="${escapeHtml(label)}" ${index === selectedMode ? 'selected' : ''}></md-filter-chip>
          `).join('')}
        </div>
        <aside id="evidence-detail" class="evidence-detail" aria-live="polite"></aside>
      </div>

      <div class="evidence-card-grid" role="group" aria-label="${escapeHtml(l.hint)}">
        ${items.map((item, index) => `
          <md-elevated-card class="evidence-card ${item.id === selectedId ? 'is-selected' : ''}" data-evidence-card="${item.id}">
            <div class="evidence-card-top">
              <span class="evidence-icon" aria-hidden="true">${icon(item.iconName)}</span>
              <span class="evidence-index num" aria-hidden="true">0${index + 1}</span>
            </div>
            <div class="evidence-card-copy">
              <h3>${escapeHtml(item.title)}</h3>
              <p>${escapeHtml(item.subtitle)}</p>
            </div>
            <div class="evidence-card-footer">
              <span class="evidence-tag">${escapeHtml(item.tag)}</span>
              <span class="evidence-card-arrow" aria-hidden="true">${icon('arrow')}</span>
            </div>
            <button class="evidence-select" type="button" data-evidence-id="${item.id}" aria-pressed="${item.id === selectedId}" aria-controls="evidence-detail" aria-label="${escapeHtml(item.title)}">
              <md-ripple></md-ripple>
            </button>
          </md-elevated-card>
        `).join('')}
      </div>
    </div>

    <md-dialog quick class="evidence-dialog" aria-label="${escapeHtml(l.document)}">
      <div slot="headline" id="evidence-dialog-title"></div>
      <div slot="content" id="evidence-dialog-content"></div>
      <div slot="actions"><md-text-button id="evidence-dialog-close">${escapeHtml(l.close)}</md-text-button></div>
    </md-dialog>
  `;

  function updateDetail(animate = true) {
    const item = items.find(entry => entry.id === selectedId) || items[0];
    const index = items.indexOf(item);
    root.querySelectorAll('[data-evidence-card]').forEach(card => {
      const match = card.dataset.evidenceCard === item.id;
      card.classList.toggle('is-selected', match);
      card.querySelector('button').setAttribute('aria-pressed', String(match));
    });
    root.querySelectorAll('[data-evidence-mode]').forEach(chip => {
      chip.selected = Number(chip.dataset.evidenceMode) === selectedMode;
    });

    const detail = root.querySelector('#evidence-detail');
    let body = '';
    if (selectedMode === 1) {
      body = `<div class="evidence-field-list">${item.fields.map(field => `<span>${escapeHtml(field)}</span>`).join('')}</div>`;
    } else {
      const lines = selectedMode === 2 ? item.boundaries : item.overview;
      body = `<ul class="evidence-detail-list">${lines.map(line => `<li>${escapeHtml(line)}</li>`).join('')}</ul>`;
    }

    detail.innerHTML = `
      <div class="evidence-detail-heading">
        <span class="evidence-detail-number num">0${index + 1}</span>
        <div>
          <p class="evidence-detail-label">${escapeHtml(l.modes[selectedMode])}</p>
          <h3>${escapeHtml(item.title)}</h3>
        </div>
      </div>
      <div class="evidence-detail-body">${body}</div>
      <md-text-button class="evidence-detail-button">${escapeHtml(l.detail)}<span slot="icon">${icon('arrow')}</span></md-text-button>
    `;

    if (animate && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
      detail.animate([{ opacity: 0.4, transform: 'translateY(4px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 220, easing: 'ease-out' });
    }

    detail.querySelector('md-text-button').addEventListener('click', () => {
      root.querySelector('#evidence-dialog-title').textContent = item.title;
      root.querySelector('#evidence-dialog-content').innerHTML = `
        <p class="dialog-lead">${escapeHtml(item.overview.join(' '))}</p>
        <h4>${escapeHtml(l.modes[1])}</h4>
        <div class="evidence-field-list">${item.fields.map(field => `<span>${escapeHtml(field)}</span>`).join('')}</div>
        <h4>${escapeHtml(l.modes[2])}</h4>
        <ul class="evidence-detail-list">${item.boundaries.map(b => `<li>${escapeHtml(b)}</li>`).join('')}</ul>
        <p class="dialog-scope">${escapeHtml(l.scope)}</p>
      `;
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
