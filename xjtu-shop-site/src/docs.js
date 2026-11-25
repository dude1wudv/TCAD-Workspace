import '@material/web/button/filled-button.js';
import '@material/web/button/filled-tonal-button.js';
import '@material/web/button/outlined-button.js';
import '@material/web/button/text-button.js';
import '@material/web/chips/chip-set.js';
import '@material/web/chips/filter-chip.js';
import '@material/web/textfield/outlined-text-field.js';
import '@material/web/labs/card/elevated-card.js';
import '@material/web/labs/card/outlined-card.js';
import '@material/web/labs/card/filled-card.js';
import '@material/web/list/list.js';
import '@material/web/list/list-item.js';
import '@material/web/divider/divider.js';
import '@material/web/fab/fab.js';
import '@material/web/dialog/dialog.js';

import './shared/tokens.css';
import './docs.css';

import {
  applyTheme,
  bindReadingProgress,
  bindTopbar,
  escapeHtml,
  getInitialLang,
  getInitialTheme,
  initFocusModality,
  renderFooter,
  renderTopbar
} from './shared/site-shell.js';
import { icon } from './shared/icons.js';
import { bindSlidingPill, syncSlidingThumb } from './shared/sliding-pill.js';
import { docsContent } from './data/docs-content.js';
import { docsArticles } from './data/docs-articles.js';

initFocusModality();

const CHAPTER_IDS = ['overview', 'geant4', 'tcad-pmi', 'predictor', 'agent-autonomy', 'web-telemetry'];
const CHAPTER_TO_ARTICLE_KEY = {
  'overview': 'overview',
  'geant4': 'geant4',
  'tcad-pmi': 'tcad',
  'predictor': 'ai',
  'agent-autonomy': 'agent',
  'web-telemetry': 'web'
};

function getInitialChapter() {
  const hash = location.hash.replace('#', '');
  if (CHAPTER_IDS.includes(hash)) return hash;
  return 'overview';
}

const state = {
  lang: getInitialLang(),
  theme: getInitialTheme(),
  query: '',
  domain: 'all',
  viewMode: 'reader', // 'reader' | 'catalog'
  activeChapter: getInitialChapter(),
  chapterDirection: 'fade',
  predictorTab: 0,
  expandedArticles: new Set()
};

const uiLabels = {
  zh: {
    catalogTitle: '全部章节与专题索引',
    catalogShort: '00 · 全部索引',
    readerMode: '单章精读',
    catalogMode: '全部索引',
    chapterStepLabel: '技术章节',
    deepSectionTitle: '深度技术专题（点击卡片平滑展开）',
    expandAll: '展开本页专题',
    collapseAll: '全部收起',
    whyLabel: '为什么要解决',
    mechLabel: '核心原理（通俗拆解）',
    engLabel: '关键工程实现',
    evLabel: '实证数据与科学边界',
    focusRead: '弹窗专注阅读',
    closeModal: '关闭',
    prevChapter: '上一章',
    nextChapter: '下一章',
    loopFirstChapter: '回到第 01 章',
    openChapter: '进入精读',
    articlesCount: '篇深度专题',
    matchedArticlesTitle: '匹配的深度技术专题',
    matchedChaptersTitle: '匹配的技术章节'
  },
  en: {
    catalogTitle: 'All Chapters & Deep-Dive Index',
    catalogShort: '00 · All Index',
    readerMode: 'Reader View',
    catalogMode: 'All Index',
    chapterStepLabel: 'Chapter',
    deepSectionTitle: 'Deep-Dive Articles (Click to Expand)',
    expandAll: 'Expand All',
    collapseAll: 'Collapse All',
    whyLabel: 'Why It Matters',
    mechLabel: 'Intuitive Mechanism',
    engLabel: 'Engineering Implementation',
    evLabel: 'Verified Metrics & Scope',
    focusRead: 'Focus Modal',
    closeModal: 'Close',
    prevChapter: 'Previous',
    nextChapter: 'Next Chapter',
    loopFirstChapter: 'Back to Ch. 01',
    openChapter: 'Open Chapter',
    articlesCount: 'deep-dive articles',
    matchedArticlesTitle: 'Matching Deep-Dive Articles',
    matchedChaptersTitle: 'Matching Chapters'
  }
};

function getCopy() {
  return docsContent[state.lang];
}

function getArticlesForChapter(chapterId) {
  const key = CHAPTER_TO_ARTICLE_KEY[chapterId];
  return (docsArticles[state.lang] && docsArticles[state.lang][key]) || [];
}

function getAllArticles() {
  const c = getCopy();
  return c.chapters.flatMap(ch =>
    getArticlesForChapter(ch.id).map(art => ({
      ...art,
      chapterId: ch.id,
      chapterNum: ch.num,
      chapterTitle: ch.title,
      domain: ch.domain
    }))
  );
}

function getFilteredData() {
  const c = getCopy();
  const q = state.query.trim().toLowerCase();

  const chapters = c.chapters.filter(ch => {
    const domainOk = state.domain === 'all' || ch.domain === state.domain;
    if (!domainOk) return false;
    if (!q) return true;
    const arts = getArticlesForChapter(ch.id);
    const haystack = [
      ch.title,
      ch.badge,
      ch.summary,
      ...ch.bullets,
      ...ch.stackTable.flatMap(row => [row.layer, row.tech, row.role, row.status]),
      ...(ch.hasPredictorTabs ? c.predictorTabs.flatMap(t => [t.tab, t.badge, t.formula, t.desc, ...t.specs]) : []),
      ...arts.flatMap(a => [a.title, a.tag, a.tldr, a.why, a.mechanism, ...a.engineering, a.evidence])
    ].join(' ').toLowerCase();
    return haystack.includes(q);
  });

  const articles = getAllArticles().filter(art => {
    const domainOk = state.domain === 'all' || art.domain === state.domain;
    if (!domainOk) return false;
    if (!q) return true;
    const haystack = [
      art.title, art.tag, art.tldr, art.why, art.mechanism, ...art.engineering, art.evidence, art.snippet || ''
    ].join(' ').toLowerCase();
    return haystack.includes(q);
  });

  return { chapters, articles };
}

function renderPredictorStageBody() {
  const c = getCopy();
  const tab = c.predictorTabs[state.predictorTab] || c.predictorTabs[0];
  return `
    <div class="predictor-stage-panel view-enter">
      <div class="predictor-stage-head">
        <span class="pill violet">${escapeHtml(tab.badge)}</span>
        <code class="formula-pill">${escapeHtml(tab.formula)}</code>
      </div>
      <p>${escapeHtml(tab.desc)}</p>
      <ul class="docs-bullets">
        ${tab.specs.map(s => `<li>${escapeHtml(s)}</li>`).join('')}
      </ul>
    </div>
  `;
}

function renderPredictorTabs() {
  const c = getCopy();
  return `
    <div class="predictor-explorer">
      <div class="predictor-tabs-scroll">
        <div class="pill-track predictor-pill-track" id="predictorPillTrack" role="tablist" aria-label="R-A-F Predictor Stages">
          <span class="pill-thumb" aria-hidden="true"></span>
          ${c.predictorTabs.map((item, idx) => `
            <button
              type="button"
              role="tab"
              class="pill-tab ${idx === state.predictorTab ? 'is-active' : ''}"
              aria-selected="${String(idx === state.predictorTab)}"
              data-pill-value="${idx}">
              ${escapeHtml(item.tab)}
            </button>
          `).join('')}
        </div>
      </div>
      <div id="predictorStageBody">${renderPredictorStageBody()}</div>
    </div>
  `;
}

function renderOverviewFlow(lang) {
  const steps = lang === 'zh'
    ? ['Geant4 10.7.3 输运', 'Sentaurus TCAD + 原子 PMI', 'R → A → F 物理网络', 'server-codex-v2 调度', '双频脱敏遥测看板']
    : ['Geant4 10.7.3 Transport', 'Sentaurus TCAD + Atomic PMI', 'R → A → F Network', 'server-codex-v2 Scheduler', 'Dual-Rate Telemetry'];
  return `
    <div class="overview-flow" role="list" aria-label="End-to-end architecture">
      ${steps.map((step, i) => `
        <div class="flow-chip reveal-item" role="listitem">
          <span class="num">0${i + 1}</span>
          <strong>${escapeHtml(step)}</strong>
        </div>
      `).join('')}
    </div>
  `;
}

function renderArticleCard(art) {
  const u = uiLabels[state.lang];
  const expanded = state.expandedArticles.has(art.id);
  return `
    <md-outlined-card class="article-card ${expanded ? 'is-expanded' : ''}" id="${art.id}">
      <button type="button" class="article-toggle" data-article-toggle="${art.id}" aria-expanded="${expanded}">
        <div class="article-toggle-meta">
          <span class="pill primary">${escapeHtml(art.tag)}</span>
          <span class="pill">${escapeHtml(art.readTime)}</span>
        </div>
        <div class="article-toggle-head">
          <h4>${escapeHtml(art.title)}</h4>
          <span class="article-chevron" aria-hidden="true">${icon('chevron')}</span>
        </div>
        <p class="article-tldr">${escapeHtml(art.tldr)}</p>
        <md-ripple></md-ripple>
      </button>

      <div class="article-body-collapse" aria-hidden="${String(!expanded)}">
        <div class="article-body-inner">
          <div class="article-body">
            <div class="article-section">
              <h5>${escapeHtml(u.whyLabel)}</h5>
              <p>${escapeHtml(art.why)}</p>
            </div>
            <div class="article-section">
              <h5>${escapeHtml(u.mechLabel)}</h5>
              <p>${escapeHtml(art.mechanism)}</p>
            </div>
            ${art.snippet ? `<pre class="article-snippet"><code>${escapeHtml(art.snippet)}</code></pre>` : ''}
            <div class="article-section">
              <h5>${escapeHtml(u.engLabel)}</h5>
              <ul class="docs-bullets">
                ${art.engineering.map(pt => `<li>${escapeHtml(pt)}</li>`).join('')}
              </ul>
            </div>
            <div class="article-evidence">
              <div>
                <strong>${escapeHtml(u.evLabel)}：</strong>
                <span>${escapeHtml(art.evidence)}</span>
              </div>
              <md-text-button data-article-modal="${art.id}">
                ${escapeHtml(u.focusRead)}
                <span slot="icon">${icon('docs')}</span>
              </md-text-button>
            </div>
          </div>
        </div>
      </div>
    </md-outlined-card>
  `;
}

function syncDocsSwitcherBar(showCatalog) {
  const bar = document.querySelector('#docsSwitcherBar');
  if (!bar) return;
  const c = getCopy();
  const u = uiLabels[state.lang];
  const chIdx = Math.max(0, c.chapters.findIndex(ch => ch.id === state.activeChapter));
  const currentCh = c.chapters[chIdx] || c.chapters[0];

  bar.innerHTML = `
    <div class="docs-switcher-left">
      <span class="dock-step-badge num">${escapeHtml(u.chapterStepLabel)} ${showCatalog ? '00 / 06' : `${escapeHtml(currentCh.num)} / 0${c.chapters.length}`}</span>
      <div class="capsule-dots" role="tablist" aria-label="${escapeHtml(u.chapterStepLabel)}">
        ${c.chapters.map(ch => `
          <button
            type="button"
            class="capsule-dot ${!showCatalog && ch.id === state.activeChapter ? 'is-active' : ''}"
            aria-label="${escapeHtml(ch.num)} · ${escapeHtml(ch.title)}"
            aria-selected="${String(!showCatalog && ch.id === state.activeChapter)}"
            data-switcher-chapter="${ch.id}">
          </button>
        `).join('')}
      </div>
    </div>
    <div class="docs-switcher-right">
      <div class="pill-track docs-mode-track" id="docsModeTrack" role="tablist" aria-label="View Mode">
        <span class="pill-thumb" aria-hidden="true"></span>
        <button type="button" role="tab" class="pill-tab ${!showCatalog ? 'is-active' : ''}" aria-selected="${String(!showCatalog)}" data-pill-value="reader">${escapeHtml(u.readerMode)}</button>
        <button type="button" role="tab" class="pill-tab ${showCatalog ? 'is-active' : ''}" aria-selected="${String(showCatalog)}" data-pill-value="catalog">${escapeHtml(u.catalogMode)}</button>
      </div>
      <div class="dock-arrows">
        <button type="button" class="dock-arrow-btn" id="docsPrevBtn" aria-label="${escapeHtml(u.prevChapter)}" title="${escapeHtml(u.prevChapter)}">
          ${icon('chevron', 'class="rot-90"')}
        </button>
        <button type="button" class="dock-arrow-btn" id="docsNextBtn" aria-label="${escapeHtml(u.nextChapter)}" title="${escapeHtml(u.nextChapter)}">
          ${icon('chevron', 'class="rot-neg-90"')}
        </button>
      </div>
    </div>
  `;

  bar.querySelectorAll('[data-switcher-chapter]').forEach(dot => {
    dot.addEventListener('click', () => openChapter(dot.dataset.switcherChapter));
  });
  bar.querySelector('#docsPrevBtn')?.addEventListener('click', () => stepChapter(-1));
  bar.querySelector('#docsNextBtn')?.addEventListener('click', () => stepChapter(1));

  const modeTrack = bar.querySelector('#docsModeTrack');
  bindSlidingPill(modeTrack, mode => {
    state.viewMode = mode === 'catalog' ? 'catalog' : 'reader';
    if (state.viewMode === 'reader' && (state.query.trim() || state.domain !== 'all')) {
      state.query = '';
      state.domain = 'all';
      const field = document.querySelector('#docsSearchField');
      if (field) field.value = '';
      document.querySelectorAll('[data-domain-chip]').forEach(chip => {
        chip.selected = chip.dataset.domainChip === 'all';
      });
    }
    renderMainArea();
  });
  syncSlidingThumb(modeTrack, { activeSelector: '.pill-tab.is-active' });
}

function stepChapter(delta) {
  const idx = CHAPTER_IDS.indexOf(state.activeChapter);
  const nextIdx = (idx + delta + CHAPTER_IDS.length) % CHAPTER_IDS.length;
  openChapter(CHAPTER_IDS[nextIdx]);
}

function getChapterAnimClass() {
  if (state.chapterDirection === 'next') return 'view-enter-next';
  if (state.chapterDirection === 'prev') return 'view-enter-prev';
  return 'view-enter';
}

function renderMainArea() {
  const c = getCopy();
  const u = uiLabels[state.lang];
  const { chapters, articles } = getFilteredData();
  const isFiltering = state.query.trim().length > 0 || state.domain !== 'all';
  const showCatalog = state.viewMode === 'catalog' || isFiltering;

  syncDocsSwitcherBar(showCatalog);

  const countEl = document.querySelector('#docsMatchCount');
  if (countEl) {
    countEl.textContent = showCatalog
      ? `${c.hero.matchPrefix}: ${chapters.length} / ${c.chapters.length} · ${articles.length} ${state.lang === 'zh' ? '篇专题' : 'articles'}`
      : `${c.chapters.find(ch => ch.id === state.activeChapter)?.num || '01'} / 06`;
  }

  const clearBtn = document.querySelector('#clearSearchBtn');
  if (clearBtn) {
    clearBtn.hidden = state.query.trim().length === 0;
  }

  // Update Left TOC highlight
  const tocEl = document.querySelector('#docsTocList');
  if (tocEl) {
    tocEl.innerHTML = `
      <md-list-item type="button" data-toc-catalog class="toc-item ${showCatalog ? 'is-active' : ''}">
        <span slot="start" class="toc-num num">00</span>
        <span slot="headline">${escapeHtml(u.catalogShort)}</span>
      </md-list-item>
      <md-divider style="margin:4px 0;"></md-divider>
      ${c.chapters.map(ch => {
        const active = !showCatalog && state.activeChapter === ch.id;
        const visible = !isFiltering || chapters.some(item => item.id === ch.id);
        return `
          <md-list-item type="button" data-toc-chapter="${ch.id}" class="toc-item ${active ? 'is-active' : ''} ${visible ? '' : 'is-dimmed'}">
            <span slot="start" class="toc-num num">${escapeHtml(ch.num)}</span>
            <span slot="headline">${escapeHtml(ch.title)}</span>
          </md-list-item>
        `;
      }).join('')}
    `;
    tocEl.querySelector('[data-toc-catalog]')?.addEventListener('click', () => {
      state.viewMode = 'catalog';
      renderMainArea();
    });
    tocEl.querySelectorAll('[data-toc-chapter]').forEach(el => {
      el.addEventListener('click', () => openChapter(el.dataset.tocChapter));
    });
  }

  const streamEl = document.querySelector('#docsStream');
  if (!streamEl) return;

  if (showCatalog) {
    if (!chapters.length && !articles.length) {
      streamEl.innerHTML = `
        <md-outlined-card class="docs-empty view-enter">
          <div class="docs-empty-inner">
            <h3>${escapeHtml(c.hero.emptyTitle)}</h3>
            <p>${escapeHtml(c.hero.emptyDesc)}</p>
            <md-filled-tonal-button id="emptyResetBtn">${escapeHtml(c.hero.resetFilters)}</md-filled-tonal-button>
          </div>
        </md-outlined-card>
      `;
      streamEl.querySelector('#emptyResetBtn')?.addEventListener('click', resetFilters);
      return;
    }

    streamEl.innerHTML = `
      <div class="catalog-view view-enter">
        <div class="catalog-head">
          <h2>${escapeHtml(u.matchedChaptersTitle)}</h2>
          ${!isFiltering ? '' : `<md-text-button id="clearCatalogFilters">${escapeHtml(c.hero.resetFilters)}</md-text-button>`}
        </div>
        <div class="catalog-chapters-grid">
          ${chapters.map(ch => `
            <md-elevated-card class="catalog-chapter-card reveal-item">
              <button type="button" class="catalog-card-btn" data-open-chapter="${ch.id}">
                <div class="doc-card-head">
                  <span class="doc-num num">${escapeHtml(ch.num)}</span>
                  <span class="pill primary">${escapeHtml(ch.badge)}</span>
                </div>
                <h3>${escapeHtml(ch.title)}</h3>
                <p>${escapeHtml(ch.summary)}</p>
                <span class="catalog-link">${escapeHtml(u.openChapter)} ${icon('arrow')}</span>
                <md-ripple></md-ripple>
              </button>
            </md-elevated-card>
          `).join('')}
        </div>

        <h2 style="margin-top:26px;">${escapeHtml(u.matchedArticlesTitle)} (${articles.length})</h2>
        <div class="catalog-articles-grid">
          ${articles.map(art => `
            <md-outlined-card class="catalog-article-card reveal-item">
              <button type="button" class="catalog-card-btn" data-open-article="${art.id}" data-article-chapter="${art.chapterId}">
                <div class="article-toggle-meta">
                  <span class="pill teal">${escapeHtml(art.chapterNum)}</span>
                  <span class="pill primary">${escapeHtml(art.tag)}</span>
                  <span class="pill">${escapeHtml(art.readTime)}</span>
                </div>
                <h3>${escapeHtml(art.title)}</h3>
                <p>${escapeHtml(art.tldr)}</p>
                <md-ripple></md-ripple>
              </button>
            </md-outlined-card>
          `).join('')}
        </div>
      </div>
    `;

    streamEl.querySelector('#clearCatalogFilters')?.addEventListener('click', resetFilters);
    streamEl.querySelectorAll('[data-open-chapter]').forEach(btn => {
      btn.addEventListener('click', () => openChapter(btn.dataset.openChapter));
    });
    streamEl.querySelectorAll('[data-open-article]').forEach(btn => {
      btn.addEventListener('click', () => {
        state.expandedArticles.add(btn.dataset.openArticle);
        openChapter(btn.dataset.articleChapter, btn.dataset.openArticle);
      });
    });
    return;
  }

  // Single-Chapter Focus Reader
  const ch = c.chapters.find(item => item.id === state.activeChapter) || c.chapters[0];
  const chIdx = c.chapters.indexOf(ch);
  const prevCh = chIdx > 0 ? c.chapters[chIdx - 1] : null;
  const nextCh = chIdx < c.chapters.length - 1 ? c.chapters[chIdx + 1] : c.chapters[0];
  const isLastChapter = chIdx === c.chapters.length - 1;
  const nextArticlesCount = getArticlesForChapter(nextCh.id).length;
  const chArticles = getArticlesForChapter(ch.id);
  const allExpanded = chArticles.length > 0 && chArticles.every(a => state.expandedArticles.has(a.id));

  streamEl.innerHTML = `
    <article id="${ch.id}" class="doc-chapter ${getChapterAnimClass()}">
      <md-elevated-card class="doc-card">
        <div class="doc-card-inner">
          <div class="doc-card-head">
            <span class="doc-num num">${escapeHtml(ch.num)}</span>
            <span class="pill primary">${escapeHtml(ch.badge)}</span>
            <md-text-button id="backToCatalogBtn" style="margin-left:auto;">
              ${escapeHtml(u.catalogMode)}
            </md-text-button>
          </div>
          <h2>${escapeHtml(ch.title)}</h2>
          <p class="doc-summary">${escapeHtml(ch.summary)}</p>

          ${ch.id === 'overview' ? renderOverviewFlow(state.lang) : ''}
          ${ch.hasPredictorTabs ? `<div id="predictorTabsSlot">${renderPredictorTabs()}</div>` : ''}

          <div class="doc-table-wrap">
            <table class="doc-table">
              <thead>
                <tr>
                  <th>${state.lang === 'zh' ? '层级 / 模块' : 'Layer / Module'}</th>
                  <th>${state.lang === 'zh' ? '技术实现' : 'Implementation'}</th>
                  <th>${state.lang === 'zh' ? '工程职责' : 'Role'}</th>
                  <th>${state.lang === 'zh' ? '状态' : 'Status'}</th>
                </tr>
              </thead>
              <tbody>
                ${ch.stackTable.map(row => `
                  <tr>
                    <td><strong>${escapeHtml(row.layer)}</strong></td>
                    <td><code>${escapeHtml(row.tech)}</code></td>
                    <td>${escapeHtml(row.role)}</td>
                    <td><span class="pill teal">${escapeHtml(row.status)}</span></td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>

          <ul class="docs-bullets">
            ${ch.bullets.map(b => `<li>${escapeHtml(b)}</li>`).join('')}
          </ul>
        </div>
      </md-elevated-card>

      <div class="deep-articles-wrap">
        <div class="deep-articles-head">
          <h3>${icon('docs')} ${escapeHtml(u.deepSectionTitle)}</h3>
          <md-text-button id="toggleAllArticlesBtn">
            ${escapeHtml(allExpanded ? u.collapseAll : u.expandAll)}
          </md-text-button>
        </div>
        <div class="articles-stack">
          ${chArticles.map(art => renderArticleCard(art)).join('')}
        </div>
      </div>

      <div class="next-chapter-banner">
        <div class="next-view-meta">
          ${prevCh
            ? `<button type="button" class="pager-back-btn" data-pager-chapter="${prevCh.id}">${icon('chevron', 'class="rot-90"')} <span>${escapeHtml(u.prevChapter)} · ${escapeHtml(prevCh.num)}</span></button>`
            : `<span class="pager-step-pill num">${escapeHtml(u.chapterStepLabel)} ${escapeHtml(ch.num)} / 0${c.chapters.length}</span>`}
          <div class="capsule-dots" role="tablist" aria-label="${escapeHtml(u.chapterStepLabel)}">
            ${c.chapters.map(item => `
              <button
                type="button"
                class="capsule-dot ${item.id === ch.id ? 'is-active' : ''}"
                aria-label="${escapeHtml(item.num)} · ${escapeHtml(item.title)}"
                data-pager-chapter="${item.id}">
              </button>
            `).join('')}
          </div>
        </div>

        <button type="button" class="next-preview-card" data-pager-chapter="${nextCh.id}">
          <div class="next-preview-top">
            <span class="pill primary">${isLastChapter ? escapeHtml(u.loopFirstChapter) : `${escapeHtml(u.nextChapter)} · ${escapeHtml(nextCh.num)} / 0${c.chapters.length}`}</span>
            <span class="pill teal">${nextArticlesCount} ${escapeHtml(u.articlesCount)}</span>
            <span class="next-preview-arrow" style="margin-left:auto;">${icon('arrow')}</span>
          </div>
          <strong>${escapeHtml(nextCh.num)} · ${escapeHtml(nextCh.title)}</strong>
          <p>${escapeHtml(nextCh.summary)}</p>
        </button>
      </div>
    </article>
  `;

  bindPredictorTabs();

  streamEl.querySelector('#backToCatalogBtn')?.addEventListener('click', () => {
    state.viewMode = 'catalog';
    renderMainArea();
  });

  const updateToggleAllBtnLabel = () => {
    const allNowExpanded = chArticles.length > 0 && chArticles.every(a => state.expandedArticles.has(a.id));
    const btn = streamEl.querySelector('#toggleAllArticlesBtn');
    if (btn) btn.textContent = allNowExpanded ? u.collapseAll : u.expandAll;
  };

  streamEl.querySelector('#toggleAllArticlesBtn')?.addEventListener('click', () => {
    const allNowExpanded = chArticles.length > 0 && chArticles.every(a => state.expandedArticles.has(a.id));
    chArticles.forEach(a => {
      if (allNowExpanded) {
        state.expandedArticles.delete(a.id);
      } else {
        state.expandedArticles.add(a.id);
      }
      const card = document.getElementById(a.id);
      const toggle = card?.querySelector('[data-article-toggle]');
      const collapse = card?.querySelector('.article-body-collapse');
      const exp = !allNowExpanded;
      card?.classList.toggle('is-expanded', exp);
      toggle?.setAttribute('aria-expanded', String(exp));
      collapse?.setAttribute('aria-hidden', String(!exp));
    });
    updateToggleAllBtnLabel();
  });

  streamEl.querySelectorAll('[data-article-toggle]').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.articleToggle;
      const exp = !state.expandedArticles.has(id);
      if (exp) {
        state.expandedArticles.add(id);
      } else {
        state.expandedArticles.delete(id);
      }
      const card = document.getElementById(id);
      const collapse = card?.querySelector('.article-body-collapse');
      card?.classList.toggle('is-expanded', exp);
      btn.setAttribute('aria-expanded', String(exp));
      collapse?.setAttribute('aria-hidden', String(!exp));
      updateToggleAllBtnLabel();
    });
  });

  streamEl.querySelectorAll('[data-article-modal]').forEach(btn => {
    btn.addEventListener('click', () => openArticleModal(btn.dataset.articleModal));
  });

  streamEl.querySelectorAll('[data-pager-chapter]').forEach(btn => {
    btn.addEventListener('click', () => openChapter(btn.dataset.pagerChapter));
  });
}

function openChapter(chapterId, scrollToArticleId = null) {
  const oldIdx = CHAPTER_IDS.indexOf(state.activeChapter);
  const newIdx = CHAPTER_IDS.indexOf(chapterId);
  state.chapterDirection = newIdx > oldIdx ? 'next' : newIdx < oldIdx ? 'prev' : 'fade';
  state.query = '';
  state.domain = 'all';
  state.viewMode = 'reader';
  state.activeChapter = chapterId;
  history.replaceState(null, '', `#${chapterId}`);

  const searchField = document.querySelector('#docsSearchField');
  if (searchField) searchField.value = '';
  document.querySelectorAll('[data-domain-chip]').forEach(chip => {
    chip.selected = chip.dataset.domainChip === 'all';
  });

  renderMainArea();

  setTimeout(() => {
    if (scrollToArticleId) {
      document.getElementById(scrollToArticleId)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } else {
      document.querySelector('.docs-workspace')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, 40);
}

function openArticleModal(articleId) {
  const art = getAllArticles().find(a => a.id === articleId);
  if (!art) return;
  const u = uiLabels[state.lang];
  const titleEl = document.querySelector('#articleModalTitle');
  const bodyEl = document.querySelector('#articleModalBody');
  const dialog = document.querySelector('#articleFocusDialog');
  if (!titleEl || !bodyEl || !dialog) return;

  titleEl.textContent = art.title;
  bodyEl.innerHTML = `
    <div class="article-toggle-meta" style="margin-bottom:12px;">
      <span class="pill teal">${escapeHtml(art.chapterNum)} · ${escapeHtml(art.chapterTitle)}</span>
      <span class="pill primary">${escapeHtml(art.tag)}</span>
      <span class="pill">${escapeHtml(art.readTime)}</span>
    </div>
    <p class="modal-tldr">${escapeHtml(art.tldr)}</p>
    <h4>${escapeHtml(u.whyLabel)}</h4>
    <p>${escapeHtml(art.why)}</p>
    <h4>${escapeHtml(u.mechLabel)}</h4>
    <p>${escapeHtml(art.mechanism)}</p>
    ${art.snippet ? `<pre class="article-snippet"><code>${escapeHtml(art.snippet)}</code></pre>` : ''}
    <h4>${escapeHtml(u.engLabel)}</h4>
    <ul class="docs-bullets">${art.engineering.map(pt => `<li>${escapeHtml(pt)}</li>`).join('')}</ul>
    <div class="dialog-scope" style="margin-top:14px;">
      <strong>${escapeHtml(u.evLabel)}：</strong>${escapeHtml(art.evidence)}
    </div>
  `;
  dialog.show();
}

function bindPredictorTabs() {
  const slot = document.querySelector('#predictorTabsSlot');
  if (!slot) return;
  const track = slot.querySelector('#predictorPillTrack');
  bindSlidingPill(track, idxStr => {
    state.predictorTab = Number(idxStr) || 0;
    const body = slot.querySelector('#predictorStageBody');
    if (body) body.innerHTML = renderPredictorStageBody();
  });
  syncSlidingThumb(track, { activeSelector: '.pill-tab.is-active' });
}

function resetFilters() {
  state.query = '';
  state.domain = 'all';
  const field = document.querySelector('#docsSearchField');
  if (field) field.value = '';
  document.querySelectorAll('[data-domain-chip]').forEach(chip => {
    chip.selected = chip.dataset.domainChip === 'all';
  });
  renderMainArea();
}

function render() {
  const c = getCopy();
  const u = uiLabels[state.lang];
  const cheatOpenByDefault = window.innerWidth > 959;
  document.documentElement.lang = state.lang === 'zh' ? 'zh-CN' : 'en';

  document.querySelector('#app').innerHTML = `
    ${renderTopbar({ activePage: 'docs', lang: state.lang, theme: state.theme })}

    <main class="docs-main">
      <section class="docs-hero docs-shell">
        <p class="eyebrow">${icon('docs')} ${escapeHtml(c.hero.eyebrow)}</p>
        <h1 class="docs-hero-title">${escapeHtml(c.hero.title)}</h1>
        <p class="lead">${escapeHtml(c.hero.lead)}</p>

        <div class="docs-toolbar">
          <div class="search-wrap">
            <md-outlined-text-field
              id="docsSearchField"
              label="${escapeHtml(c.hero.searchLabel)}"
              placeholder="${escapeHtml(c.hero.searchPlaceholder)}"
              value="${escapeHtml(state.query)}"
              type="text">
              <span slot="leading-icon">${icon('search')}</span>
              <md-icon-button slot="trailing-icon" id="clearSearchBtn" aria-label="${escapeHtml(c.hero.clearSearch)}" title="${escapeHtml(c.hero.clearSearch)}" ${state.query.trim() ? '' : 'hidden'}>
                ${icon('close')}
              </md-icon-button>
            </md-outlined-text-field>
          </div>
          <div class="toolbar-meta">
            <span class="pill primary" id="docsMatchCount"></span>
            <md-outlined-button id="mobileTocBtn" class="mobile-toc-btn">${escapeHtml(c.hero.openToc)}</md-outlined-button>
          </div>
        </div>

        <md-chip-set class="domain-chips" aria-label="Technology domains">
          ${c.domains.map(d => `
            <md-filter-chip data-domain-chip="${d.id}" label="${escapeHtml(d.label)}" ${state.domain === d.id ? 'selected' : ''}></md-filter-chip>
          `).join('')}
        </md-chip-set>
      </section>

      <section class="docs-workspace docs-shell">
        <aside class="docs-sidebar" aria-label="${escapeHtml(c.hero.tocTitle)}">
          <md-outlined-card class="sidebar-card">
            <div class="sidebar-inner">
              <h3>${escapeHtml(c.hero.tocTitle)}</h3>
              <md-list id="docsTocList"></md-list>
            </div>
          </md-outlined-card>
        </aside>

        <div class="docs-center-col">
          <div class="docs-switcher-bar" id="docsSwitcherBar"></div>
          <div id="docsStream" class="docs-stream"></div>
        </div>

        <aside class="docs-right-rail" aria-label="${escapeHtml(c.hero.cheatTitle)}">
          <md-filled-card class="cheat-card">
            <details class="cheat-details" ${cheatOpenByDefault ? 'open' : ''}>
              <summary class="cheat-summary">
                <span class="cheat-title">${icon('shield')} ${escapeHtml(c.hero.cheatTitle)}</span>
                <span class="cheat-chevron">${icon('chevron')}</span>
              </summary>
              <div class="cheat-inner">
                <dl class="cheat-list">
                  ${c.hero.cheatItems.map(item => `
                    <div class="cheat-row">
                      <dt>${escapeHtml(item.k)}</dt>
                      <dd>${escapeHtml(item.v)}</dd>
                    </div>
                  `).join('')}
                </dl>
                <md-divider></md-divider>
                <div class="cheat-actions">
                  <md-filled-tonal-button href="/">${state.lang === 'zh' ? '返回研究主页' : 'Back to Homepage'}</md-filled-tonal-button>
                  <md-outlined-button href="https://status.xjtu.shop" target="_blank" rel="noopener">${state.lang === 'zh' ? '查看实时状态' : 'Live Status'}</md-outlined-button>
                </div>
              </div>
            </details>
          </md-filled-card>
        </aside>
      </section>
    </main>

    <md-dialog quick id="mobileTocDialog" class="mobile-toc-dialog" aria-label="${escapeHtml(c.hero.tocTitle)}">
      <div slot="headline">${escapeHtml(c.hero.tocTitle)}</div>
      <div slot="content">
        <md-list>
          <md-list-item type="button" data-mobile-catalog>
            <span slot="start" class="toc-num num">00</span>
            <span slot="headline">${escapeHtml(u.catalogShort)}</span>
          </md-list-item>
          <md-divider></md-divider>
          ${c.chapters.map(ch => `
            <md-list-item type="button" data-mobile-chapter="${ch.id}">
              <span slot="start" class="toc-num num">${escapeHtml(ch.num)}</span>
              <span slot="headline">${escapeHtml(ch.title)}</span>
            </md-list-item>
          `).join('')}
        </md-list>
      </div>
      <div slot="actions">
        <md-text-button id="mobileTocClose">${escapeHtml(u.closeModal)}</md-text-button>
      </div>
    </md-dialog>

    <md-dialog quick id="articleFocusDialog" class="article-focus-dialog" aria-label="Article Reader">
      <div slot="headline" id="articleModalTitle"></div>
      <div slot="content" id="articleModalBody"></div>
      <div slot="actions">
        <md-text-button id="articleModalClose">${escapeHtml(u.closeModal)}</md-text-button>
      </div>
    </md-dialog>

    <md-fab id="backTopFab" class="back-top-fab" aria-label="${escapeHtml(c.hero.backTop)}" title="${escapeHtml(c.hero.backTop)}" size="medium">
      ${icon('up', 'slot="icon"')}
    </md-fab>

    ${renderFooter({ lang: state.lang, activePage: 'docs' })}
  `;

  bindTopbar({
    onToggleLang: () => {
      state.lang = state.lang === 'zh' ? 'en' : 'zh';
      localStorage.setItem('xjtu-lang', state.lang);
      render();
    },
    onToggleTheme: () => {
      state.theme = applyTheme(state.theme === 'dark' ? 'light' : 'dark');
      render();
    }
  });
  bindReadingProgress();

  const searchField = document.querySelector('#docsSearchField');
  searchField?.addEventListener('input', event => {
    state.query = event.target.value || '';
    renderMainArea();
  });

  document.querySelector('#clearSearchBtn')?.addEventListener('click', () => {
    state.query = '';
    if (searchField) {
      searchField.value = '';
      searchField.focus();
    }
    renderMainArea();
  });

  document.querySelectorAll('[data-domain-chip]').forEach(chip => {
    chip.addEventListener('click', () => {
      state.domain = chip.dataset.domainChip;
      document.querySelectorAll('[data-domain-chip]').forEach(other => {
        other.selected = other.dataset.domainChip === state.domain;
      });
      renderMainArea();
    });
  });

  const tocDialog = document.querySelector('#mobileTocDialog');
  document.querySelector('#mobileTocBtn')?.addEventListener('click', () => tocDialog?.show());
  document.querySelector('#mobileTocClose')?.addEventListener('click', () => tocDialog?.close());
  tocDialog?.querySelector('[data-mobile-catalog]')?.addEventListener('click', () => {
    state.viewMode = 'catalog';
    tocDialog.close();
    renderMainArea();
  });
  tocDialog?.querySelectorAll('[data-mobile-chapter]').forEach(item => {
    item.addEventListener('click', () => {
      tocDialog.close();
      openChapter(item.dataset.mobileChapter);
    });
  });

  document.querySelector('#articleModalClose')?.addEventListener('click', () => {
    document.querySelector('#articleFocusDialog')?.close();
  });

  const fab = document.querySelector('#backTopFab');
  fab?.addEventListener('click', () => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });
  const syncFab = () => fab?.classList.toggle('is-visible', window.scrollY > 280);
  window.addEventListener('scroll', syncFab, { passive: true });
  syncFab();

  const mqMobile = window.matchMedia('(max-width: 959px)');
  const syncCheatFold = () => {
    const det = document.querySelector('.cheat-details');
    if (det) det.open = !mqMobile.matches;
  };
  mqMobile.addEventListener('change', syncCheatFold);
  syncCheatFold();

  renderMainArea();
}

document.addEventListener('keydown', event => {
  if (event.key === '/' && !['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) {
    const field = document.querySelector('#docsSearchField');
    if (field) {
      event.preventDefault();
      field.focus();
    }
  } else if (event.altKey && (event.key === 'ArrowRight' || event.key === 'ArrowLeft')) {
    event.preventDefault();
    stepChapter(event.key === 'ArrowRight' ? 1 : -1);
  }
});

window.addEventListener('hashchange', () => {
  const hash = location.hash.replace('#', '');
  if (CHAPTER_IDS.includes(hash) && hash !== state.activeChapter) {
    openChapter(hash);
  }
});

render();
