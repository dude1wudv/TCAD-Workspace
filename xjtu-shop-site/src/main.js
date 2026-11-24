import '@material/web/button/filled-button.js';
import '@material/web/button/filled-tonal-button.js';
import '@material/web/button/outlined-button.js';
import '@material/web/button/text-button.js';
import '@material/web/chips/assist-chip.js';
import '@material/web/progress/linear-progress.js';
import '@material/web/labs/card/elevated-card.js';
import '@material/web/labs/card/outlined-card.js';
import '@material/web/ripple/ripple.js';

import './shared/tokens.css';
import './styles.css';

import {
  applyTheme,
  bindReadingProgress,
  bindTopbar,
  escapeHtml,
  getInitialLang,
  getInitialTheme,
  initFocusModality,
  isKeyboardModality,
  renderFooter,
  renderTopbar,
  setTopbarActive
} from './shared/site-shell.js';
import { icon } from './shared/icons.js';
import { bindSlidingPill, syncSlidingThumb } from './shared/sliding-pill.js';
import { homeContent } from './data/home-content.js';
import { createDramSimulator } from './components/dram-simulator.js';
import { mountAgentArchitecture } from './components/agent-architecture.js';
import { renderResearchCharts } from './components/research-charts.js';
import { mountEvidence } from './components/evidence.js';

initFocusModality();

const WORKBENCH_VIEWS = ['results', 'architecture', 'evidence', 'status'];
const VIEW_ICONS = {
  results: 'radiation',
  architecture: 'agent',
  evidence: 'ledger',
  status: 'telemetry'
};

function getInitialView() {
  const hash = location.hash.replace('#', '');
  if (WORKBENCH_VIEWS.includes(hash)) return hash;
  return 'results';
}

const state = {
  lang: getInitialLang(),
  theme: getInitialTheme(),
  activeView: getInitialView(),
  viewDirection: 'fade',
  archTab: 0,
  archNode: 'controller',
  archScenario: 'admission',
  showGuardrails: false,
  resultStage: 2,
  status: null,
  statusError: false,
  statusLoading: false,
  expandedService: null
};

const dramSim = createDramSimulator({
  lang: state.lang,
  copy: homeContent
});

function getCopy() {
  return homeContent[state.lang];
}

function getViewAnimClass() {
  if (state.viewDirection === 'next') return 'view-enter-next';
  if (state.viewDirection === 'prev') return 'view-enter-prev';
  return 'view-enter';
}

function renderResultsStage() {
  const c = getCopy();
  const stage = c.results.stages[state.resultStage] || c.results.stages[0];
  return `
    <md-elevated-card class="stage-showcase view-enter">
      <div class="stage-showcase-inner">
        <div class="stage-showcase-head">
          <div>
            <span class="pill ${stage.statusTone}">${escapeHtml(stage.status)}</span>
            <h3>${escapeHtml(stage.title)}</h3>
          </div>
        </div>
        <p class="stage-summary">${escapeHtml(stage.summary)}</p>
        <div class="stage-kpi-grid">
          ${stage.metrics.map(m => `
            <div class="stage-kpi reveal-item">
              <span class="stage-kpi-label">${escapeHtml(m.label)}</span>
              <strong class="stage-kpi-val num">${escapeHtml(m.value)}</strong>
              <small>${escapeHtml(m.note)}</small>
            </div>
          `).join('')}
        </div>
        <ul class="stage-highlights">
          ${stage.highlights.map(h => `<li>${icon('check')}<span>${escapeHtml(h)}</span></li>`).join('')}
        </ul>
      </div>
    </md-elevated-card>
  `;
}

function renderWorkbenchPager() {
  const wb = getCopy().workbench;
  const idx = WORKBENCH_VIEWS.indexOf(state.activeView);
  const prev = idx > 0 ? wb.views[idx - 1] : null;
  const next = idx < wb.views.length - 1 ? wb.views[idx + 1] : wb.views[0];
  const isLast = idx === wb.views.length - 1;

  return `
    <div class="next-view-banner reveal-item">
      <div class="next-view-meta">
        ${prev
          ? `<button type="button" class="pager-back-btn" data-switch-view="${prev.id}">${icon('chevron', 'class="rot-90"')} <span>${escapeHtml(wb.prevLabel)} · ${escapeHtml(prev.num)}</span></button>`
          : `<span class="pager-step-pill num">${escapeHtml(wb.stepLabel)} 01 / 0${wb.views.length}</span>`}
        <div class="capsule-dots" role="tablist" aria-label="${escapeHtml(wb.stepLabel)}">
          ${wb.views.map(v => `
            <button
              type="button"
              class="capsule-dot ${v.id === state.activeView ? 'is-active' : ''}"
              aria-label="${escapeHtml(v.num)} · ${escapeHtml(v.short)}"
              aria-selected="${String(v.id === state.activeView)}"
              data-switch-view="${v.id}">
            </button>
          `).join('')}
        </div>
      </div>

      <div class="next-view-cards">
        <button type="button" class="next-preview-card" data-switch-view="${next.id}">
          <div class="next-preview-top">
            <span class="pill primary">${isLast ? escapeHtml(wb.loopBackLabel) : `${escapeHtml(wb.nextLabel)} · ${escapeHtml(next.num)} / 0${wb.views.length}`}</span>
            <span class="next-preview-arrow">${icon('arrow')}</span>
          </div>
          <strong>${escapeHtml(next.short)} · ${escapeHtml(next.caption)}</strong>
          <p>${escapeHtml(next.teaser)}</p>
        </button>
        ${isLast ? `
          <a class="next-preview-card next-preview-docs" href="/docs/">
            <div class="next-preview-top">
              <span class="pill teal">/docs/ · 6 Chapters</span>
              <span class="next-preview-arrow">${icon('arrow')}</span>
            </div>
            <strong>${escapeHtml(wb.jumpDocsLabel)}</strong>
            <p>${escapeHtml(getCopy().techBridge.lead)}</p>
          </a>
        ` : ''}
      </div>
    </div>
  `;
}

function renderActiveView() {
  const c = getCopy();
  const body = document.querySelector('#workbenchBody');
  if (!body) return;
  const animClass = getViewAnimClass();

  if (state.activeView === 'results') {
    body.innerHTML = `
      <div class="view-pane ${animClass}">
        <div class="section-head">
          <p class="eyebrow">${icon('radiation')} ${escapeHtml(c.results.eyebrow)}</p>
          <h2>${escapeHtml(c.results.title)}</h2>
          <p class="lead">${escapeHtml(c.results.lead)}</p>
        </div>
        <div class="stage-selector-wrap">
          <div class="pill-track results-stage-track" id="resultsStageTrack" role="tablist" aria-label="${escapeHtml(c.results.title)}">
            <span class="pill-thumb" aria-hidden="true"></span>
            ${c.results.stages.map((st, idx) => `
              <button
                type="button"
                role="tab"
                class="pill-tab ${idx === state.resultStage ? 'is-active' : ''}"
                aria-selected="${String(idx === state.resultStage)}"
                data-pill-value="${idx}">
                ${escapeHtml(st.tab)}
              </button>
            `).join('')}
          </div>
        </div>
        <div id="results-stage-slot">${renderResultsStage()}</div>
        <div id="research-charts-slot" class="charts-slot"></div>
        ${renderWorkbenchPager()}
      </div>
    `;
    const stageTrack = document.querySelector('#resultsStageTrack');
    bindSlidingPill(stageTrack, val => {
      state.resultStage = Number(val) || 0;
      const slot = document.querySelector('#results-stage-slot');
      if (slot) slot.innerHTML = renderResultsStage();
    });
    syncSlidingThumb(stageTrack, { activeSelector: '.pill-tab.is-active' });
    renderResearchCharts(document.querySelector('#research-charts-slot'), state.lang, state.status);
  } else if (state.activeView === 'architecture') {
    body.innerHTML = `
      <div class="view-pane ${animClass}">
        <div id="architectureMount"></div>
        ${renderWorkbenchPager()}
      </div>
    `;
    const redrawArch = () => mountAgentArchitecture(document.querySelector('#architectureMount'), getCopy(), state, redrawArch);
    redrawArch();
  } else if (state.activeView === 'evidence') {
    body.innerHTML = `
      <div class="view-pane ${animClass}">
        <div id="evidenceMount"></div>
        ${renderWorkbenchPager()}
      </div>
    `;
    mountEvidence(document.querySelector('#evidenceMount'), state.lang);
  } else {
    body.innerHTML = `
      <div class="view-pane ${animClass}">
        <div class="status-grid">
          <div class="section-head" style="margin-bottom:0;">
            <p class="eyebrow">${icon('telemetry')} ${escapeHtml(c.status.eyebrow)}</p>
            <h2>${escapeHtml(c.status.title)}</h2>
            <p class="lead">${escapeHtml(c.status.lead)}</p>
            <div class="hero-actions" style="margin-top:8px;">
              <md-filled-button href="https://status.xjtu.shop" target="_blank" rel="noopener">${escapeHtml(c.status.openStatus)}</md-filled-button>
              <md-outlined-button href="/docs/#web-telemetry">${escapeHtml(c.status.openDocs)}</md-outlined-button>
            </div>
          </div>
          <md-elevated-card class="status-preview" id="status-preview"></md-elevated-card>
        </div>

        <div class="bridge-divider">
          <div class="bridge-head" style="margin-top:34px;margin-bottom:18px;">
            <div class="section-head" style="margin-bottom:0;">
              <p class="eyebrow">${icon('code')} ${escapeHtml(c.techBridge.eyebrow)}</p>
              <h3>${escapeHtml(c.techBridge.title)}</h3>
              <p class="lead">${escapeHtml(c.techBridge.lead)}</p>
            </div>
            <md-filled-tonal-button href="/docs/">${escapeHtml(c.techBridge.cta)} ${icon('arrow', 'slot="icon"')}</md-filled-tonal-button>
          </div>
          <div class="bridge-grid">
            ${c.techBridge.items.map(item => `
              <md-outlined-card class="bridge-card reveal-item">
                <a class="bridge-link" href="/docs/#${item.anchor}">
                  <span class="pill primary">${escapeHtml(item.badge)}</span>
                  <h3>${escapeHtml(item.title)}</h3>
                  <p>${escapeHtml(item.desc)}</p>
                  <span class="bridge-cta">${state.lang === 'zh' ? '阅读章节' : 'Read chapter'} ${icon('arrow')}</span>
                  <md-ripple></md-ripple>
                </a>
              </md-outlined-card>
            `).join('')}
          </div>
        </div>
        ${renderWorkbenchPager()}
      </div>
    `;
    updateStatus();
  }

  body.querySelectorAll('[data-switch-view]').forEach(btn => {
    btn.addEventListener('click', () => switchWorkbenchView(btn.dataset.switchView, true));
  });
}

function syncWorkbenchDock() {
  const wb = getCopy().workbench;
  const idx = Math.max(0, WORKBENCH_VIEWS.indexOf(state.activeView));
  const counterEl = document.querySelector('#dockStepCounter');
  if (counterEl) {
    counterEl.textContent = `${wb.stepLabel} 0${idx + 1} / 0${wb.views.length}`;
  }
  const rail = document.querySelector('#workbenchRail');
  if (rail) {
    rail.querySelectorAll('.stage-tab').forEach(btn => {
      const isMatch = btn.dataset.pillValue === state.activeView;
      btn.classList.toggle('is-active', isMatch);
      btn.setAttribute('aria-selected', String(isMatch));
    });
    syncSlidingThumb(rail, { activeSelector: '.stage-tab.is-active', scrollIntoView: true });
  }
  document.querySelectorAll('#dockDots .capsule-dot').forEach(dot => {
    const isMatch = dot.dataset.switchView === state.activeView;
    dot.classList.toggle('is-active', isMatch);
    dot.setAttribute('aria-selected', String(isMatch));
  });
}

function switchWorkbenchView(viewId, scrollToDock = true) {
  if (!WORKBENCH_VIEWS.includes(viewId)) return;
  const oldIdx = WORKBENCH_VIEWS.indexOf(state.activeView);
  const newIdx = WORKBENCH_VIEWS.indexOf(viewId);
  state.viewDirection = newIdx > oldIdx ? 'next' : newIdx < oldIdx ? 'prev' : 'fade';
  state.activeView = viewId;
  history.replaceState(null, '', `#${viewId}`);
  syncWorkbenchDock();
  setTopbarActive(viewId);
  renderActiveView();
  if (scrollToDock) {
    document.querySelector('#workbench')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

function stepWorkbench(delta, scrollToDock = true) {
  const idx = WORKBENCH_VIEWS.indexOf(state.activeView);
  const nextIdx = (idx + delta + WORKBENCH_VIEWS.length) % WORKBENCH_VIEWS.length;
  switchWorkbenchView(WORKBENCH_VIEWS[nextIdx], scrollToDock);
}

function render() {
  const c = getCopy();
  const wb = c.workbench;
  const activeIdx = Math.max(0, WORKBENCH_VIEWS.indexOf(state.activeView));
  document.documentElement.lang = state.lang === 'zh' ? 'zh-CN' : 'en';

  document.querySelector('#app').innerHTML = `
    ${renderTopbar({ activePage: 'home', activeSection: state.activeView, lang: state.lang, theme: state.theme })}

    <main>
      <section id="overview" class="hero shell">
        <div class="hero-copy">
          <md-assist-chip href="/docs/" label="${escapeHtml(c.hero.chip)}">
            ${icon('docs', 'slot="icon"')}
          </md-assist-chip>
          <p class="eyebrow">${escapeHtml(c.hero.eyebrow)}</p>
          <h1 class="hero-display-title">${escapeHtml(c.hero.title)}</h1>
          <p class="formal-title">${escapeHtml(c.hero.formalTitle)}</p>
          <p class="hero-lead">${escapeHtml(c.hero.lead)}</p>
          <div class="hero-actions">
            <md-filled-button id="heroExploreBtn">${escapeHtml(c.hero.ctaPrimary)}</md-filled-button>
            <md-filled-tonal-button href="/docs/">${escapeHtml(c.hero.ctaDocs)}</md-filled-tonal-button>
            <md-outlined-button href="https://status.xjtu.shop" target="_blank" rel="noopener">${escapeHtml(c.hero.ctaStatus)}</md-outlined-button>
          </div>
        </div>
        <div id="hero-blueprint-slot"></div>
      </section>

      <section class="signal-strip shell" aria-label="${escapeHtml(c.signals.stageLabel)}">
        <div class="signal-cell">
          <span class="signal-label">${escapeHtml(c.signals.stageLabel)}</span>
          <strong id="stage-reading">${escapeHtml(c.signals.stageFallback)}</strong>
        </div>
        <div class="signal-cell">
          <span class="signal-label">${escapeHtml(c.signals.matrixLabel)}</span>
          <strong id="plan-reading" class="num">${escapeHtml(c.signals.matrixFallback)}</strong>
        </div>
        <div class="signal-cell">
          <span class="signal-label">${escapeHtml(c.signals.milestoneLabel)}</span>
          <strong>${escapeHtml(c.signals.milestoneText)}</strong>
        </div>
        <div class="signal-cell signal-health">
          <span class="signal-label">${escapeHtml(c.signals.healthLabel)}</span>
          <div class="live-pill" id="live-status" aria-live="polite"></div>
        </div>
      </section>

      <section id="workbench" class="workbench-shell shell">
        <div class="workbench-dock" id="workbenchDock">
          <div class="dock-meta-row">
            <div class="dock-meta-left">
              <span class="dock-step-badge num" id="dockStepCounter">${escapeHtml(wb.stepLabel)} 0${activeIdx + 1} / 0${wb.views.length}</span>
              <div class="capsule-dots" id="dockDots" role="tablist" aria-label="${escapeHtml(wb.stepLabel)}">
                ${wb.views.map(v => `
                  <button
                    type="button"
                    class="capsule-dot ${v.id === state.activeView ? 'is-active' : ''}"
                    aria-label="${escapeHtml(v.num)} · ${escapeHtml(v.short)}"
                    aria-selected="${String(v.id === state.activeView)}"
                    data-switch-view="${v.id}">
                  </button>
                `).join('')}
              </div>
            </div>
            <div class="dock-meta-right">
              <span class="dock-kbd-hint mono">${escapeHtml(wb.keyboardHint)}</span>
              <div class="dock-arrows">
                <button type="button" class="dock-arrow-btn" id="dockPrevBtn" aria-label="${escapeHtml(wb.prevLabel)}" title="${escapeHtml(wb.prevLabel)}">
                  ${icon('chevron', 'class="rot-90"')}
                </button>
                <button type="button" class="dock-arrow-btn" id="dockNextBtn" aria-label="${escapeHtml(wb.nextLabel)}" title="${escapeHtml(wb.nextLabel)}">
                  ${icon('chevron', 'class="rot-neg-90"')}
                </button>
              </div>
            </div>
          </div>

          <div class="stage-track" id="workbenchRail" role="tablist" aria-label="${escapeHtml(wb.stepLabel)}">
            <span class="stage-thumb" aria-hidden="true"></span>
            ${wb.views.map(v => {
              const isMatch = v.id === state.activeView;
              return `
                <button
                  type="button"
                  role="tab"
                  class="stage-tab ${isMatch ? 'is-active' : ''}"
                  aria-selected="${String(isMatch)}"
                  data-pill-value="${v.id}">
                  <span class="stage-tab-num mono">${escapeHtml(v.num)}</span>
                  <span class="stage-tab-body">
                    <span class="stage-tab-title">
                      ${icon(VIEW_ICONS[v.id])}
                      <strong>${escapeHtml(v.short)}</strong>
                    </span>
                    <small>${escapeHtml(v.caption)}</small>
                  </span>
                </button>
              `;
            }).join('')}
          </div>
        </div>

        <div id="workbenchBody" class="workbench-body"></div>
      </section>
    </main>

    ${renderFooter({ lang: state.lang, activePage: 'home' })}
  `;

  dramSim.mount(document.querySelector('#hero-blueprint-slot'), state.lang);

  bindTopbar({
    onToggleLang: () => {
      state.lang = state.lang === 'zh' ? 'en' : 'zh';
      localStorage.setItem('xjtu-lang', state.lang);
      render();
    },
    onToggleTheme: () => {
      state.theme = applyTheme(state.theme === 'dark' ? 'light' : 'dark');
      render();
      dramSim.redrawTheme();
    },
    onSectionClick: key => {
      if (key === 'overview') {
        setTopbarActive('overview');
        window.scrollTo({ top: 0, behavior: 'smooth' });
        history.replaceState(null, '', '#overview');
      } else {
        switchWorkbenchView(key, true);
      }
    }
  });
  bindReadingProgress();

  document.querySelector('#heroExploreBtn')?.addEventListener('click', () => {
    switchWorkbenchView('results', true);
  });

  document.querySelectorAll('#dockDots [data-switch-view]').forEach(btn => {
    btn.addEventListener('click', () => switchWorkbenchView(btn.dataset.switchView, true));
  });

  document.querySelector('#dockPrevBtn')?.addEventListener('click', () => stepWorkbench(-1, true));
  document.querySelector('#dockNextBtn')?.addEventListener('click', () => stepWorkbench(1, true));

  const rail = document.querySelector('#workbenchRail');
  bindSlidingPill(rail, viewId => {
    if (viewId && viewId !== state.activeView) {
      switchWorkbenchView(viewId, false);
    }
  }, { buttonSelector: '.stage-tab', scrollActiveOnSelect: true });
  syncWorkbenchDock();

  renderActiveView();
  updateStatus();
}

function updateStatus() {
  const c = getCopy();
  const generated = Date.parse(state.status?.generated_at);
  const threshold = state.status?.health?.freshness?.scheduler_threshold_seconds ?? 180;
  const stale = state.status && (
    !Number.isFinite(generated) ||
    Date.now() - generated > threshold * 1000 ||
    generated - Date.now() > 60_000
  );
  const overall = stale ? 'stale' : state.status?.overall || (state.statusError ? 'unknown' : 'loading');
  const overallLabel = c.status.stateLabels[overall] || c.status.stateLabels.unknown;

  const simulation = state.status?.health?.simulation;
  const summary = state.status?.research_summary ?? state.status?.research;
  const stageText = state.lang === 'zh'
    ? simulation?.summary_zh || simulation?.summary_en
    : simulation?.summary_en || simulation?.summary_zh;

  const stats = summary?.totals;
  const progressParts = summary ? [
    summary.revision,
    Number.isFinite(stats?.planned) ? `${c.signals.planned} ${stats.planned}` : null,
    Number.isFinite(stats?.solved) ? `${c.signals.solved} ${stats.solved}` : null,
    Number.isFinite(stats?.accepted) ? `${c.signals.accepted} ${stats.accepted}` : null,
    Number.isFinite(stats?.running ?? simulation?.active_tasks) ? `${c.signals.running} ${stats?.running ?? simulation?.active_tasks}` : null
  ].filter(Boolean) : [];

  const stageEl = document.getElementById('stage-reading');
  const planEl = document.getElementById('plan-reading');
  const liveEl = document.getElementById('live-status');
  if (stageEl) stageEl.textContent = stageText || c.signals.stageFallback;
  if (planEl) planEl.textContent = progressParts.length ? progressParts.join(' · ') : c.signals.matrixFallback;
  if (liveEl) liveEl.innerHTML = `<span class="status-dot ${overall}"></span><span>${escapeHtml(overallLabel)}</span>`;

  if (state.activeView === 'results') {
    const chartsSlot = document.querySelector('#research-charts-slot');
    if (chartsSlot) renderResearchCharts(chartsSlot, state.lang, state.status);
  }

  const previewEl = document.querySelector('#status-preview');
  if (!previewEl) return;

  const previousFocus = isKeyboardModality() && previewEl.contains(document.activeElement)
    ? document.activeElement?.id
    : null;

  const rows = c.status.services.map(svcDef => {
    const service = state.status?.services?.find(s => s.id === svcDef.id);
    const health = state.status?.health?.services?.items?.find(i => i.id === svcDef.id);
    const value = stale ? 'stale' : health?.state || service?.state || 'unknown';
    const expanded = state.expandedService === svcDef.id;
    const checked = Date.parse(service?.checked_at);
    const checkedTime = Number.isFinite(checked)
      ? new Intl.DateTimeFormat(state.lang === 'zh' ? 'zh-CN' : 'en', { dateStyle: 'short', timeStyle: 'short' }).format(checked)
      : '—';

    return `
      <div class="preview-service ${expanded ? 'is-expanded' : ''}">
        <button class="preview-line" id="preview-toggle-${svcDef.id}" type="button" data-preview-service="${svcDef.id}" aria-expanded="${expanded}" aria-controls="preview-note-${svcDef.id}">
          <span>${escapeHtml(svcDef.name)}</span>
          <b class="preview-state ${value}">${escapeHtml(c.status.stateLabels[value] || c.status.stateLabels.unknown)}</b>
          <span class="preview-chevron">${icon('chevron')}</span>
          <md-ripple></md-ripple>
        </button>
        <div class="preview-service-note" id="preview-note-${svcDef.id}" ${expanded ? '' : 'hidden'}>
          <p>${escapeHtml(svcDef.desc)}</p>
          <div>${escapeHtml(c.status.updated)} <time>${checkedTime}</time></div>
        </div>
      </div>
    `;
  }).join('');

  const updatedTime = Number.isFinite(generated)
    ? new Intl.DateTimeFormat(state.lang === 'zh' ? 'zh-CN' : 'en', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(generated)
    : '—';

  previewEl.innerHTML = `
    <div class="preview-inner">
      <div class="preview-header">
        <span class="status-dot ${overall}"></span>
        <a class="preview-title" href="https://status.xjtu.shop" target="_blank" rel="noopener">${escapeHtml(c.status.previewTitle)}</a>
        <span class="pill ${overall === 'operational' ? 'good' : overall === 'loading' ? 'primary' : 'warn'}">${escapeHtml(overallLabel)}</span>
        <md-icon-button id="preview-refresh" class="${state.statusLoading ? 'is-refreshing' : ''}" aria-label="${escapeHtml(c.status.refresh)}" title="${escapeHtml(c.status.refresh)}" ${state.statusLoading ? 'disabled' : ''}>
          ${icon('refresh')}
        </md-icon-button>
      </div>
      ${state.statusLoading ? `<md-linear-progress indeterminate aria-label="${escapeHtml(c.status.loading)}"></md-linear-progress>` : ''}
      ${rows}
      <div class="preview-update">
        <span>${escapeHtml(c.status.updated)} <time>${updatedTime}</time></span>
        <a href="https://status.xjtu.shop" target="_blank" rel="noopener">${escapeHtml(c.status.fullBoard)} ${icon('external')}</a>
      </div>
    </div>
  `;

  previewEl.querySelectorAll('[data-preview-service]').forEach(button => {
    button.addEventListener('click', () => {
      const id = button.dataset.previewService;
      state.expandedService = state.expandedService === id ? null : id;
      previewEl.querySelectorAll('[data-preview-service]').forEach(toggle => {
        const exp = state.expandedService === toggle.dataset.previewService;
        toggle.setAttribute('aria-expanded', String(exp));
        toggle.closest('.preview-service').classList.toggle('is-expanded', exp);
        document.querySelector(`#${toggle.getAttribute('aria-controls')}`).hidden = !exp;
      });
    });
  });

  previewEl.querySelector('#preview-refresh')?.addEventListener('click', loadStatus);
  if (previousFocus) document.getElementById(previousFocus)?.focus({ preventScroll: true });
}

async function fetchStatus(path) {
  const response = await fetch(path, { cache: 'no-store', signal: AbortSignal.timeout(8000) });
  if (!response.ok) throw new Error(`${path} returned HTTP ${response.status}`);
  const payload = await response.json();
  if (!Number.isFinite(Date.parse(payload?.generated_at))) throw new Error(`Invalid payload from ${path}`);
  return payload;
}

async function loadStatus() {
  if (state.statusLoading) return;
  state.statusLoading = true;
  updateStatus();
  try {
    state.status = await fetchStatus('/live.json').catch(() => fetchStatus('/status.json'));
    state.statusError = false;
  } catch {
    state.statusError = true;
  }
  state.statusLoading = false;
  updateStatus();
}

window.addEventListener('hashchange', () => {
  const hash = location.hash.replace('#', '');
  if (WORKBENCH_VIEWS.includes(hash) && hash !== state.activeView) {
    switchWorkbenchView(hash, true);
  }
});

document.addEventListener('keydown', event => {
  if (event.altKey && (event.key === 'ArrowRight' || event.key === 'ArrowLeft')) {
    event.preventDefault();
    stepWorkbench(event.key === 'ArrowRight' ? 1 : -1, true);
  }
});

render();
const refreshVisibleStatus = () => {
  if (!document.hidden) loadStatus();
};
refreshVisibleStatus();
document.addEventListener('visibilitychange', refreshVisibleStatus);
setInterval(refreshVisibleStatus, 60_000);
