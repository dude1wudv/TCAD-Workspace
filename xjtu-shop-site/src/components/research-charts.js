import '@material/web/labs/card/outlined-card.js';
import { escapeHtml } from '../shared/site-shell.js';
import { bindSlidingPill, syncSlidingThumb } from '../shared/sliding-pill.js';

const chartCopy = {
  zh: {
    tabs: [
      'r0.6 实时矩阵与四级口径',
      'v3 128 算例与代理精度',
      'D1 栅耦合偏置抵消'
    ],
    r06Title: 'r0.6 396 正式槽位实时进度与四级口径',
    r06Sub: '各分区计数实时绑定 /live.json；P0 诊断独立统计，58 条 HR/HP 留出严格封存。',
    cohorts: [
      { id: 'Z', label: 'Z · 零源基线', planned: 26, tone: 'teal' },
      { id: 'T', label: 'T · 主训队列', planned: 68, tone: 'primary' },
      { id: 'S', label: 'S · 统计抽样', planned: 150, tone: 'violet' },
      { id: 'R', label: 'R · 代表校验', planned: 12, tone: 'good' },
      { id: 'AL', label: 'AL · 主动学习', planned: 82, tone: 'warn' },
      { id: 'HR+HP', label: 'HR/HP · 封存留出', planned: 58, tone: 'muted' }
    ],
    funnelTitle: '四级科学口径漏斗（互不混用）',
    funnel: [
      { label: '正式计划槽位 (Planned)', key: 'planned', tone: 'primary' },
      { label: '工程归档 (Archived)', key: 'archived', tone: 'teal' },
      { label: '求解完成 (Solved)', key: 'solved', tone: 'violet' },
      { label: '科学验收 (Accepted)', key: 'accepted', tone: 'good' },
      { label: '统计资格 (214 用途上限 · 快照待接入)', key: 'eligible', tone: 'warn' }
    ],
    p0Label: '独立 P0 诊断（不计入 396 分母）',
    v3Title: 'v3 128 算例分类结构与代理 MAE 对比',
    v3Sub: '50 Ω 预充 128 主响应判别构成（左）与物理特征岭回归相比均值基线的 MAE 降幅（右）。',
    v3Decision: [
      { label: '正确判别', count: 96, pct: '75.0%', tone: 'good' },
      { label: '判据误读', count: 20, pct: '15.6%', tone: 'bad' },
      { label: '临界区', count: 8, pct: '6.3%', tone: 'warn' },
      { label: '数值不确定', count: 4, pct: '3.1%', tone: 'muted' }
    ],
    v3Mae: [
      { label: '均值基线 (b0/b1)', pct: 100, text: '18.3 – 20.1 mV', tone: 'bad' },
      { label: 'Holdout L=0.25 (b0)', pct: 16, text: '0.527 mV', tone: 'primary' },
      { label: 'Holdout L=0.25 (b1)', pct: 17, text: '0.550 mV', tone: 'primary' },
      { label: '外推 L=0.45 (b0)', pct: 13, text: '0.405 mV', tone: 'good' },
      { label: '外推 L=0.45 (b1)', pct: 12, text: '0.388 mV', tone: 'good' }
    ],
    d1Title: 'D1 读出偏置机理与匹配中性参考消除实测',
    d1Sub: '字线开启时栅极/衬底净注入 +1.32~+1.46 fC 导致正偏；同条件中性参考单元抑制约 98% 共模误差。',
    d1Items: [
      { label: 'WL 关闭对照', pct: 4, text: '-0.005 mV', tone: 'teal', note: '无字线耦合注入' },
      { label: '固定 0.5V 单端参考', pct: 100, text: '+12.01 ~ +13.24 mV', tone: 'bad', note: '栅极耦合 +1.464 fC 主导' },
      { label: 'v3 匹配中性参考单元', pct: 7, text: '-0.259 mV', tone: 'good', note: '共模偏移精密对消' }
    ]
  },
  en: {
    tabs: [
      'r0.6 Live Matrix & 4-Tier Ledger',
      'v3 128-Case & Surrogate MAE',
      'D1 Readout Offset Cancellation'
    ],
    r06Title: 'r0.6 396-Slot Live Cohort Progress & 4-Tier Ledger',
    r06Sub: 'Counts update live from /live.json; P0 diagnostics stay separate and 58 HR/HP holdout cases remain sealed.',
    cohorts: [
      { id: 'Z', label: 'Z · Zero-Source', planned: 26, tone: 'teal' },
      { id: 'T', label: 'T · Train Cohort', planned: 68, tone: 'primary' },
      { id: 'S', label: 'S · Stratified', planned: 150, tone: 'violet' },
      { id: 'R', label: 'R · Replicate', planned: 12, tone: 'good' },
      { id: 'AL', label: 'AL · Active Learn', planned: 82, tone: 'warn' },
      { id: 'HR+HP', label: 'HR/HP · Sealed', planned: 58, tone: 'muted' }
    ],
    funnelTitle: '4-Tier Acceptance Funnel (Strictly Separate)',
    funnel: [
      { label: 'Formal Planned Slots', key: 'planned', tone: 'primary' },
      { label: 'Archived / Collected', key: 'archived', tone: 'teal' },
      { label: 'Solved (Exit 0)', key: 'solved', tone: 'violet' },
      { label: 'Scientifically Accepted', key: 'accepted', tone: 'good' },
      { label: 'Statistics Eligible (Cap 214 · Snapshot Pending)', key: 'eligible', tone: 'warn' }
    ],
    p0Label: 'Separate P0 Diagnostics (Excluded from 396 denominator)',
    v3Title: 'v3 128-Case Breakdown & Ridge Surrogate MAE Reduction',
    v3Sub: '5 mV classification breakdown (left) and ΔM MAE vs mean baseline (right).',
    v3Decision: [
      { label: 'Correct', count: 96, pct: '75.0%', tone: 'good' },
      { label: 'Misread', count: 20, pct: '15.6%', tone: 'bad' },
      { label: 'Marginal', count: 8, pct: '6.3%', tone: 'warn' },
      { label: 'Uncertain', count: 4, pct: '3.1%', tone: 'muted' }
    ],
    v3Mae: [
      { label: 'Mean Baseline (b0/b1)', pct: 100, text: '18.3 – 20.1 mV', tone: 'bad' },
      { label: 'Holdout L=0.25 (b0)', pct: 16, text: '0.527 mV', tone: 'primary' },
      { label: 'Holdout L=0.25 (b1)', pct: 17, text: '0.550 mV', tone: 'primary' },
      { label: 'Extrap L=0.45 (b0)', pct: 13, text: '0.405 mV', tone: 'good' },
      { label: 'Extrap L=0.45 (b1)', pct: 12, text: '0.388 mV', tone: 'good' }
    ],
    d1Title: 'D1 Readout Offset Physics & Neutral Reference Cancellation',
    d1Sub: 'WL turn-on injects +1.32 to +1.46 fC net charge; matched neutral cells suppress 98% of the offset.',
    d1Items: [
      { label: 'WL-Off Control', pct: 4, text: '-0.005 mV', tone: 'teal', note: 'No WL coupling injection' },
      { label: 'Fixed 0.5V Single Ref', pct: 100, text: '+12.01 ~ +13.24 mV', tone: 'bad', note: 'Gate coupling +1.464 fC' },
      { label: 'v3 Matched Neutral Cell', pct: 7, text: '-0.259 mV', tone: 'good', note: 'Common-mode cancelled' }
    ]
  }
};

let activeChartTab = 0;

function renderR06Panel(c, lang, liveStatus) {
  const summary = liveStatus?.research_summary ?? liveStatus?.research;
  const blocks = summary?.blocks || [];
  const counts = summary?.counts || {};
  const totals = summary?.totals;
  const p0 = summary?.diagnostics?.P0;

  const funnelCounts = {
    planned: Number.isFinite(totals?.planned) ? totals.planned : 396,
    archived: Number.isFinite(totals?.archived) ? totals.archived : 0,
    solved: Number.isFinite(totals?.solved) ? totals.solved : 0,
    accepted: Number.isFinite(totals?.accepted) ? totals.accepted : 0,
    eligible: Number.isFinite(summary?.budget?.statistics_eligible_cases) ? summary.budget.statistics_eligible_cases : 0
  };

  return `
    <div class="chart-inner r06-grid">
      <div>
        <h3>${escapeHtml(c.r06Title)}</h3>
        <p class="chart-sub">${escapeHtml(c.r06Sub)}</p>
        <div class="cohort-bars">
          ${c.cohorts.map(cohort => {
            let accepted = 0;
            let running = 0;
            let planned = cohort.planned;
            if (cohort.id === 'HR+HP') {
              const hr = counts.HR || blocks.find(b => b.id === 'HR');
              const hp = counts.HP || blocks.find(b => b.id === 'HP');
              planned = (hr?.planned ?? 28) + (hp?.planned ?? 30);
            } else {
              const entry = counts[cohort.id] || blocks.find(b => b.id === cohort.id);
              if (entry) {
                planned = entry.planned ?? cohort.planned;
                accepted = entry.accepted ?? 0;
                running = entry.running ?? 0;
              }
            }
            const quotaPct = Math.round((planned / 150) * 100);
            const accPct = planned > 0 ? Math.round((accepted / planned) * 100) : 0;
            const statusText = cohort.id === 'HR+HP'
              ? (lang === 'zh' ? `${planned} 封存` : `${planned} sealed`)
              : `${accepted} / ${planned}${running ? (lang === 'zh' ? ` · ${running} 运行` : ` · ${running} run`) : ''}`;

            return `
              <div class="cohort-row">
                <div class="cohort-meta">
                  <span>${escapeHtml(cohort.label)}</span>
                  <strong class="num">${escapeHtml(statusText)}</strong>
                </div>
                <div class="cohort-track" title="Planned quota ${planned}">
                  <span class="cohort-quota" style="width:${quotaPct}%"></span>
                  ${accepted > 0 ? `<span class="cohort-fill fill-${cohort.tone}" style="width:${Math.max(4, Math.round((quotaPct * accPct) / 100))}%"></span>` : ''}
                </div>
              </div>
            `;
          }).join('')}
        </div>
        <div class="p0-chip-row">
          <span class="pill warn">
            ${escapeHtml(c.p0Label)}${p0 ? `: ${p0.planned ?? 0} planned · ${p0.solved ?? 0} solved · ${p0.running ?? 0} running` : ''}
          </span>
        </div>
      </div>

      <div class="funnel-box">
        <h4>${escapeHtml(c.funnelTitle)}</h4>
        <div class="funnel-list">
          ${c.funnel.map(step => {
            const val = funnelCounts[step.key];
            const pct = val > 0 ? Math.max(5, Math.min(100, Math.round((val / 396) * 100))) : 0;
            return `
              <div class="funnel-item">
                <div class="funnel-row-head">
                  <span>${escapeHtml(step.label)}</span>
                  <strong class="num">${val}</strong>
                </div>
                <div class="funnel-track">
                  <span class="funnel-fill fill-${step.tone}" style="width:${pct}%"></span>
                </div>
              </div>
            `;
          }).join('')}
        </div>
      </div>
    </div>
  `;
}

function renderV3Panel(c) {
  return `
    <div class="chart-inner r06-grid">
      <div>
        <h3>${escapeHtml(c.v3Title)}</h3>
        <p class="chart-sub">${escapeHtml(c.v3Sub)}</p>
        <div class="stacked-bar-wrap">
          <div class="stacked-bar">
            ${c.v3Decision.map(seg => `
              <span class="stacked-seg seg-${seg.tone}" style="width:${(seg.count / 128) * 100}%" title="${escapeHtml(seg.label)}: ${seg.count} (${seg.pct})"></span>
            `).join('')}
          </div>
          <div class="stacked-legend">
            ${c.v3Decision.map(seg => `
              <span><i class="dot-${seg.tone}"></i>${escapeHtml(seg.label)} <strong class="num">${seg.count}</strong> (${seg.pct})</span>
            `).join('')}
          </div>
        </div>
      </div>
      <div class="metric-bars-list">
        ${c.v3Mae.map(item => `
          <div class="metric-bar-row">
            <div class="metric-bar-head">
              <span>${escapeHtml(item.label)}</span>
              <strong class="num">${escapeHtml(item.text)}</strong>
            </div>
            <div class="cohort-track">
              <span class="cohort-fill fill-${item.tone}" style="width:${item.pct}%"></span>
            </div>
          </div>
        `).join('')}
      </div>
    </div>
  `;
}

function renderD1Panel(c) {
  return `
    <div class="chart-inner">
      <h3>${escapeHtml(c.d1Title)}</h3>
      <p class="chart-sub">${escapeHtml(c.d1Sub)}</p>
      <div class="metric-bars-list d1-bars">
        ${c.d1Items.map(item => `
          <div class="metric-bar-row">
            <div class="metric-bar-head">
              <span><strong>${escapeHtml(item.label)}</strong> · <small style="color:var(--muted)">${escapeHtml(item.note)}</small></span>
              <strong class="num">${escapeHtml(item.text)}</strong>
            </div>
            <div class="cohort-track">
              <span class="cohort-fill fill-${item.tone}" style="width:${item.pct}%"></span>
            </div>
          </div>
        `).join('')}
      </div>
    </div>
  `;
}

export function renderResearchCharts(root, lang, liveStatus) {
  const c = chartCopy[lang];
  const panels = [
    () => renderR06Panel(c, lang, liveStatus),
    () => renderV3Panel(c),
    () => renderD1Panel(c)
  ];

  root.innerHTML = `
    <md-outlined-card class="chart-card">
      <div class="chart-tabs-bar">
        <div class="pill-track chart-pill-track" id="researchChartTrack" role="tablist" aria-label="Science Figures">
          <span class="pill-thumb" aria-hidden="true"></span>
          ${c.tabs.map((label, idx) => `
            <button
              type="button"
              role="tab"
              class="pill-tab ${idx === activeChartTab ? 'is-active' : ''}"
              aria-selected="${String(idx === activeChartTab)}"
              data-pill-value="${idx}">
              ${escapeHtml(label)}
            </button>
          `).join('')}
        </div>
      </div>
      <div id="researchChartBody" class="view-enter">
        ${(panels[activeChartTab] || panels[0])()}
      </div>
    </md-outlined-card>
  `;

  const chartTrack = root.querySelector('#researchChartTrack');
  bindSlidingPill(chartTrack, val => {
    activeChartTab = Number(val) || 0;
    const body = root.querySelector('#researchChartBody');
    if (body) {
      body.classList.remove('view-enter');
      void body.offsetWidth;
      body.innerHTML = (panels[activeChartTab] || panels[0])();
      body.classList.add('view-enter');
    }
  });
  syncSlidingThumb(chartTrack, { activeSelector: '.pill-tab.is-active' });
}
