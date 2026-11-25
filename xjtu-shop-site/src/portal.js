import '@material/web/button/filled-button.js';
import '@material/web/button/filled-tonal-button.js';
import '@material/web/button/outlined-button.js';
import '@material/web/button/text-button.js';
import '@material/web/labs/card/elevated-card.js';
import '@material/web/labs/card/outlined-card.js';
import '@material/web/chips/assist-chip.js';
import '@material/web/ripple/ripple.js';

import './shared/tokens.css';
import './portal.css';

import { applyDocumentLang, getLang, setLang } from './shared/i18n.js';
import {
  animateCountUp,
  applyTheme,
  bindReadingProgress,
  bindTopbar,
  escapeHtml,
  getInitialTheme,
  initFocusModality,
  renderFooter,
  renderTopbar
} from './shared/site-shell.js';
import { icon } from './shared/icons.js';
import { portalContent } from './data/portal-content.js';

initFocusModality();

const FRESH_MAX_MS = 180_000;

const state = {
  lang: getLang(),
  theme: getInitialTheme(),
  statusPayload: null,
  statusError: false,
  statusLoading: true,
  hasAnimatedMetrics: false
};

function resolveLiveStatus() {
  const c = portalContent[state.lang].statusBadge;
  if (state.statusLoading && !state.statusPayload) {
    return { toneClass: 'is-stale', label: c.loading, detail: '' };
  }
  const payload = state.statusPayload;
  const generated = Date.parse(payload?.generated_at);
  const thresholdMs = (payload?.health?.freshness?.scheduler_threshold_seconds ?? 180) * 1000;
  const maxAgeMs = Number.isFinite(thresholdMs) && thresholdMs > 0 ? thresholdMs : FRESH_MAX_MS;
  const age = Date.now() - generated;
  const isStale = (state.statusError && !payload) || !payload || !Number.isFinite(generated) || age > maxAgeMs || age < -60_000;
  if (isStale) return { toneClass: 'is-stale', label: c.stale, detail: '' };

  const map = {
    operational: { toneClass: 'is-ok', label: c.operational },
    degraded: { toneClass: 'is-warn', label: c.degraded },
    maintenance: { toneClass: 'is-warn', label: c.maintenance },
    offline: { toneClass: 'is-down', label: c.offline }
  };
  const resolved = map[payload.overall] || { toneClass: 'is-stale', label: c.stale };
  const sim = payload?.health?.simulation;
  const activeCount = sim?.active_tasks ?? payload?.research_summary?.totals?.running ?? payload?.research?.totals?.running;
  const summary = state.lang === 'zh' ? sim?.summary_zh || sim?.summary_en : sim?.summary_en || sim?.summary_zh;
  const detailParts = [];
  if (Number.isFinite(activeCount)) detailParts.push(`${activeCount} ${c.activeTasks}`);
  if (summary) detailParts.push(summary);
  return { ...resolved, detail: detailParts.join(' · ') };
}

function applyLiveStatus() {
  const slot = document.querySelector('#live-status-badge');
  if (!slot) return;
  const { toneClass, label, detail } = resolveLiveStatus();
  slot.innerHTML = `
    <span class="live-status-pill ${toneClass}">
      <span class="live-status-dot" aria-hidden="true"></span>
      <span>${escapeHtml(label)}</span>
    </span>
    ${detail ? `<span class="live-status-detail">${escapeHtml(detail)}</span>` : ''}
  `;
}

function renderPortalCard(card, variant, statusSlotMarkup = '') {
  const isResearch = variant === 'research';
  return `
    <md-elevated-card class="portal-card portal-card--${variant}">
      <div class="portal-card-inner">
        <div class="portal-card-head">
          <span class="portal-domain-tag ${isResearch ? 'is-primary' : 'is-secondary'}">
            ${icon(card.icon)}
            <span class="mono">${escapeHtml(card.domain)}</span>
          </span>
          <span class="pill ${isResearch ? 'primary' : 'teal'}">${escapeHtml(card.tag)}</span>
        </div>

        <div class="portal-card-body">
          <h2>${escapeHtml(card.title)}</h2>
          <p>${escapeHtml(card.description)}</p>
          ${statusSlotMarkup}
        </div>

        <div class="portal-card-actions">
          ${isResearch
            ? `<md-filled-button href="${card.ctaHref}">${escapeHtml(card.ctaLabel)}${icon('arrow', 'slot="icon"')}</md-filled-button>`
            : `<md-filled-tonal-button href="${card.ctaHref}">${escapeHtml(card.ctaLabel)}${icon('arrow', 'slot="icon"')}</md-filled-tonal-button>`}
        </div>
        <div class="portal-quick-links">
          <span class="quick-links-label">${escapeHtml(card.quickLinksTitle)}</span>
          <div class="quick-chips-row">
            ${card.quickLinks.map(link => `
              <md-assist-chip href="${link.href}" label="${escapeHtml(link.label)}">
                ${icon(link.icon, 'slot="icon"')}
              </md-assist-chip>`).join('')}
          </div>
        </div>
      </div>
    </md-elevated-card>
  `;
}

function animateHighlights() {
  const els = document.querySelectorAll('.highlight-num[data-count-target]');
  els.forEach(el => {
    const target = Number(el.dataset.countTarget);
    const suffix = el.dataset.countSuffix || '';
    if (!Number.isFinite(target)) return;
    if (!state.hasAnimatedMetrics) {
      animateCountUp(el, target, { suffix });
    } else {
      el.textContent = `${target}${suffix}`;
    }
  });
  state.hasAnimatedMetrics = true;
}

function render() {
  const c = portalContent[state.lang];
  applyDocumentLang(state.lang, c.meta);

  const statusBadgeSlot = `<div id="live-status-badge" class="live-status-row" aria-live="polite"></div>`;

  document.querySelector('#app').innerHTML = `
    ${renderTopbar({ activePage: 'portal', lang: state.lang, theme: state.theme })}

    <main class="shell portal-main">
      <section class="portal-hero">
        <p class="eyebrow">${icon('radiation')} ${escapeHtml(c.hero.eyebrow)}</p>
        <h1 class="portal-hero-title">${escapeHtml(c.hero.headline)}</h1>
        <p class="formal-title">${escapeHtml(c.hero.formalTitle)}</p>
        <p class="portal-hero-lead">${escapeHtml(c.hero.lead)}</p>
      </section>

      <section class="portal-cards-grid" aria-label="${escapeHtml(c.portalsAriaLabel)}">
        ${renderPortalCard(c.portals.research, 'research')}
        ${renderPortalCard(c.portals.status, 'status', statusBadgeSlot)}
      </section>

      <section class="portal-highlights" aria-label="${escapeHtml(c.highlights.title)}">
        <div class="highlights-head">
          <p class="eyebrow">${escapeHtml(c.highlights.eyebrow)}</p>
          <h2>${escapeHtml(c.highlights.title)}</h2>
        </div>
        <div class="highlights-grid">
          ${c.highlights.items.map(item => `
            <md-outlined-card class="highlight-card">
              <div class="highlight-card-inner">
                <strong class="highlight-num num" data-count-target="${item.target}" data-count-suffix="${escapeHtml(item.suffix)}">${item.target}${escapeHtml(item.suffix)}</strong>
                <span class="highlight-label">${escapeHtml(item.label)}</span>
                <p class="highlight-note">${escapeHtml(item.note)}</p>
              </div>
            </md-outlined-card>`).join('')}
        </div>
      </section>

      <section class="portal-scope-strip" aria-label="${escapeHtml(c.scope.eyebrow)}">
        <div class="scope-row">
          <div class="scope-cell">
            <span class="scope-label">${escapeHtml(c.scope.milestoneLabel)}</span>
            <strong>${escapeHtml(c.scope.milestoneText)}</strong>
          </div>
          <div class="scope-cell">
            <span class="scope-label">${escapeHtml(c.scope.pipelineLabel)}</span>
            <strong>${escapeHtml(c.scope.pipelineText)}</strong>
          </div>
        </div>
        <p class="scope-boundary">${icon('shield')} <span>${escapeHtml(c.scope.boundaryNote)}</span></p>
      </section>
    </main>

    ${renderFooter({ lang: state.lang, activePage: 'portal' })}
  `;

  bindTopbar({
    onToggleLang: () => {
      state.lang = setLang(state.lang === 'zh' ? 'en' : 'zh');
      render();
    },
    onToggleTheme: () => {
      state.theme = applyTheme(state.theme === 'dark' ? 'light' : 'dark');
      render();
    }
  });

  bindReadingProgress();
  applyLiveStatus();
  animateHighlights();
}

async function fetchSnapshot(path) {
  const res = await fetch(path, { cache: 'no-store', signal: AbortSignal.timeout(8000) });
  if (!res.ok) throw new Error(`${path} HTTP ${res.status}`);
  return res.json();
}

async function loadLiveStatus() {
  state.statusLoading = true;
  applyLiveStatus();
  try {
    state.statusPayload = await fetchSnapshot('/live.json').catch(() => fetchSnapshot('/status.json'));
    state.statusError = false;
  } catch {
    state.statusError = true;
  }
  state.statusLoading = false;
  applyLiveStatus();
}

render();
loadLiveStatus();
