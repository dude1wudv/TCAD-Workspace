import '@material/web/dialog/dialog.js';
import '@material/web/button/text-button.js';
import '@material/web/iconbutton/icon-button.js';
import '@material/web/list/list.js';
import '@material/web/list/list-item.js';
import '@material/web/divider/divider.js';
import { icon } from './icons.js';

const KEYBOARD_MODALITY_KEYS = new Set([
  'Tab',
  'ArrowLeft',
  'ArrowRight',
  'ArrowUp',
  'ArrowDown',
  'Home',
  'End',
  'Enter',
  ' ',
  'Spacebar',
  'Escape',
  '/'
]);

const INTERACTIVE_SELECTOR = [
  'a',
  'button',
  'summary',
  '[role="button"]',
  '[role="tab"]',
  '[tabindex]',
  'input',
  'textarea',
  'select',
  'md-filled-button',
  'md-filled-tonal-button',
  'md-outlined-button',
  'md-text-button',
  'md-icon-button',
  'md-fab',
  'md-assist-chip',
  'md-filter-chip',
  'md-switch',
  'md-list-item',
  'md-primary-tab',
  'md-secondary-tab',
  'md-outlined-segmented-button',
  'md-outlined-text-field'
].join(',');

function isEditableElement(el) {
  if (!el || typeof el !== 'object') return false;
  const tag = (el.tagName || '').toUpperCase();
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || tag === 'MD-OUTLINED-TEXT-FIELD') {
    return true;
  }
  return Boolean(el.isContentEditable);
}

let focusModalityInitialized = false;

export function isKeyboardModality() {
  return document.documentElement.dataset.inputModality === 'keyboard';
}

export function initFocusModality() {
  if (focusModalityInitialized) return;
  focusModalityInitialized = true;
  const root = document.documentElement;
  if (!root.dataset.inputModality) {
    root.dataset.inputModality = 'pointer';
  }

  const blurActiveIfNonEditable = () => {
    const active = document.activeElement;
    if (active && active !== document.body && active !== root && !isEditableElement(active)) {
      if (typeof active.blur === 'function') {
        active.blur();
      }
    }
  };

  const markPointer = event => {
    root.dataset.inputModality = 'pointer';
    const target = event?.target instanceof Element ? event.target : null;
    if (!target || !target.closest(INTERACTIVE_SELECTOR)) {
      blurActiveIfNonEditable();
    }
  };

  document.addEventListener('pointerdown', markPointer, true);
  document.addEventListener('mousedown', markPointer, true);
  document.addEventListener('touchstart', markPointer, { capture: true, passive: true });

  document.addEventListener(
    'click',
    () => {
      if (root.dataset.inputModality === 'pointer') {
        queueMicrotask(blurActiveIfNonEditable);
      }
    },
    false
  );

  document.addEventListener(
    'keydown',
    event => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (KEYBOARD_MODALITY_KEYS.has(event.key)) {
        root.dataset.inputModality = 'keyboard';
      }
    },
    true
  );

  window.addEventListener('blur', () => {
    blurActiveIfNonEditable();
  });
}

export function animateCountUp(el, target, { suffix = '', duration = 680 } = {}) {
  if (!el) return;
  const end = Number(target);
  if (!Number.isFinite(end)) return;
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
    el.textContent = `${end}${suffix}`;
    return;
  }
  const start = Math.max(0, Math.round(end * 0.35));
  const t0 = performance.now();
  const step = now => {
    const p = Math.min(1, (now - t0) / duration);
    const eased = 1 - Math.pow(1 - p, 3);
    const val = Math.round(start + (end - start) * eased);
    el.textContent = `${val}${suffix}`;
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

export function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

export function getInitialLang() {
  return localStorage.getItem('xjtu-lang') === 'en' ? 'en' : 'zh';
}

export function getInitialTheme() {
  const docTheme = document.documentElement.dataset.theme;
  if (docTheme === 'dark' || docTheme === 'light') return docTheme;
  const saved = localStorage.getItem('xjtu-theme') || localStorage.getItem('xjtu-status-theme');
  if (saved === 'dark' || saved === 'light') return saved;
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function applyTheme(theme) {
  const normalized = theme === 'dark' ? 'dark' : 'light';
  document.documentElement.dataset.theme = normalized;
  localStorage.setItem('xjtu-theme', normalized);
  localStorage.setItem('xjtu-status-theme', normalized);
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', normalized === 'dark' ? '#0c121c' : '#005cbb');
  return normalized;
}

const navCopy = {
  zh: {
    brandSub: 'XJTU · DRAM SEE',
    home: '研究概览',
    results: '仿真成果',
    arch: 'Agent 架构',
    evidence: '证据账本',
    docs: '技术文档',
    status: '服务状态',
    themeToDark: '切换暗色主题',
    themeToLight: '切换亮色主题',
    langSwitch: 'Switch to English',
    langBadge: 'EN',
    menuOpen: '打开导航菜单',
    menuTitle: '站点导航',
    menuClose: '关闭',
    footerTitle: 'AI辅助下的DRAM存储器单粒子效应评估研究',
    footerDesc: '围绕 Geant4 核非弹性输运、Sentaurus TCAD 混合模式器件响应、R→A→F 物理约束预测网络与 server-codex-v2 自主调度的公开研究门户。',
    footerNav: '页面与入口',
    footerBoundary: '公开数据与科学口径',
    footerBoundaryText: '严格区分工程归档、求解完成、科学验收与统计资格；服务器与虚拟机三层磁盘/内存余量互不相加；不公开内部 run_id、路径与封存留出明细。',
    footerCopy: 'tcad.xjtu.shop · 只读公开研究门户'
  },
  en: {
    brandSub: 'XJTU · DRAM SEE',
    home: 'Overview',
    results: 'Results',
    arch: 'Agent Arch',
    evidence: 'Evidence',
    docs: 'Tech Docs',
    status: 'Live Status',
    themeToDark: 'Switch to dark theme',
    themeToLight: 'Switch to light theme',
    langSwitch: '切换至简体中文',
    langBadge: '中',
    menuOpen: 'Open navigation menu',
    menuTitle: 'Navigation',
    menuClose: 'Close',
    footerTitle: 'AI-Assisted Assessment of Single-Event Effects in DRAM Memories',
    footerDesc: 'Public research portal covering Geant4 inelastic transport, Sentaurus TCAD mixed-mode device response, R→A→F physics-constrained prediction, and server-codex-v2 autonomy.',
    footerNav: 'Portals & Sections',
    footerBoundary: 'Public Redaction & Scientific Frame',
    footerBoundaryText: 'Strictly separates collected, solved, accepted, and statistics-eligible counts; three-layer server/VM storage & memory capacities are never summed; internal run IDs, paths, and sealed holdout details remain private.',
    footerCopy: 'tcad.xjtu.shop · Read-only Public Research Portal'
  }
};

export function renderTopbar({ activePage, activeSection = 'overview', lang, theme }) {
  const c = navCopy[lang];
  const isDocs = activePage === 'docs';
  const prefix = isDocs ? '/' : '';
  const containerClass = isDocs ? 'docs-shell' : 'shell';
  const links = [
    { key: 'overview', href: `${prefix}#overview`, label: c.home, active: activePage === 'home' && activeSection === 'overview', iconName: 'simulation' },
    { key: 'results', href: `${prefix}#results`, label: c.results, active: activePage === 'home' && activeSection === 'results', iconName: 'radiation' },
    { key: 'architecture', href: `${prefix}#architecture`, label: c.arch, active: activePage === 'home' && activeSection === 'architecture', iconName: 'agent' },
    { key: 'evidence', href: `${prefix}#evidence`, label: c.evidence, active: activePage === 'home' && activeSection === 'evidence', iconName: 'ledger' },
    { key: 'docs', href: '/docs/', label: c.docs, active: activePage === 'docs', iconName: 'docs' },
    { key: 'status', href: 'https://status.xjtu.shop', label: c.status, active: false, external: true, iconName: 'telemetry' }
  ];

  const themeLabel = theme === 'dark' ? c.themeToLight : c.themeToDark;
  const themeIcon = theme === 'dark' ? 'sun' : 'moon';

  return `
    <header class="topbar">
      <div class="${containerClass} topbar-inner">
        <a class="brand" href="/">
          <span class="brand-mark" aria-hidden="true">X</span>
          <span class="brand-text">
            <span class="brand-name">tcad.xjtu.shop</span>
            <span class="brand-sub">${escapeHtml(c.brandSub)}</span>
          </span>
        </a>
        <nav class="desktop-nav" aria-label="${escapeHtml(c.menuTitle)}">
          ${links.map(link => `
            <a href="${link.href}" data-nav-key="${link.key}" class="${link.active ? 'is-active' : ''}" ${link.external ? 'target="_blank" rel="noopener"' : ''}>
              ${escapeHtml(link.label)}
              ${link.external ? icon('external') : ''}
            </a>
          `).join('')}
        </nav>
        <div class="topbar-actions">
          <md-icon-button id="themeButton" aria-label="${escapeHtml(themeLabel)}" title="${escapeHtml(themeLabel)}">
            ${icon(themeIcon)}
          </md-icon-button>
          <md-icon-button id="languageButton" aria-label="${escapeHtml(c.langSwitch)}" title="${escapeHtml(c.langSwitch)}">
            <span class="language-icon">${escapeHtml(c.langBadge)}</span>
          </md-icon-button>
          <md-icon-button class="menu-trigger" id="mobileMenuButton" aria-label="${escapeHtml(c.menuOpen)}" title="${escapeHtml(c.menuOpen)}">
            ${icon('menu')}
          </md-icon-button>
        </div>
      </div>
      <div class="reading-progress-bar" id="readingProgress" aria-hidden="true"></div>
    </header>
    <md-dialog quick id="mobileNavDialog" class="mobile-nav-dialog" aria-label="${escapeHtml(c.menuTitle)}">
      <div slot="headline">${escapeHtml(c.menuTitle)}</div>
      <div slot="content">
        <md-list class="mobile-nav-list">
          ${links.map(link => `
            <md-list-item type="link" href="${link.href}" ${link.external ? 'target="_blank" rel="noopener"' : ''} data-mobile-nav-link data-nav-key="${link.key}">
              <span slot="start">${icon(link.iconName)}</span>
              <span slot="headline">${escapeHtml(link.label)}</span>
              ${link.external ? `<span slot="end">${icon('external')}</span>` : ''}
            </md-list-item>
          `).join('')}
        </md-list>
      </div>
      <div slot="actions">
        <md-text-button id="mobileNavClose">${escapeHtml(c.menuClose)}</md-text-button>
      </div>
    </md-dialog>
  `;
}

export function setTopbarActive(key) {
  document.querySelectorAll('.desktop-nav a[data-nav-key]').forEach(el => {
    el.classList.toggle('is-active', el.dataset.navKey === key);
  });
}

export function bindTopbar({ onToggleLang, onToggleTheme, onSectionClick }) {
  const themeBtn = document.querySelector('#themeButton');
  const langBtn = document.querySelector('#languageButton');
  const menuBtn = document.querySelector('#mobileMenuButton');
  const dialog = document.querySelector('#mobileNavDialog');
  const closeBtn = document.querySelector('#mobileNavClose');

  themeBtn?.addEventListener('click', () => {
    const restoreFocus = isKeyboardModality();
    onToggleTheme();
    if (restoreFocus) {
      document.querySelector('#themeButton')?.focus({ preventScroll: true });
    }
  });
  langBtn?.addEventListener('click', () => {
    const restoreFocus = isKeyboardModality();
    onToggleLang();
    if (restoreFocus) {
      document.querySelector('#languageButton')?.focus({ preventScroll: true });
    }
  });
  menuBtn?.addEventListener('click', () => dialog?.show());
  closeBtn?.addEventListener('click', () => dialog?.close());

  if (onSectionClick) {
    document.querySelectorAll('.desktop-nav a[data-nav-key], [data-mobile-nav-link]').forEach(el => {
      const key = el.dataset.navKey;
      if (['overview', 'results', 'architecture', 'evidence'].includes(key)) {
        el.addEventListener('click', event => {
          event.preventDefault();
          dialog?.close();
          onSectionClick(key);
        });
      } else {
        el.addEventListener('click', () => dialog?.close());
      }
    });
  } else {
    dialog?.querySelectorAll('[data-mobile-nav-link]').forEach(item => {
      item.addEventListener('click', () => dialog?.close());
    });
  }
}

export function bindReadingProgress() {
  const bar = document.querySelector('#readingProgress');
  if (!bar) return;
  const update = () => {
    const doc = document.documentElement;
    const max = Math.max(1, doc.scrollHeight - window.innerHeight);
    const ratio = Math.min(1, Math.max(0, window.scrollY / max));
    bar.classList.toggle('is-visible', window.scrollY > 24);
    bar.style.transform = `scaleX(${ratio.toFixed(4)})`;
  };
  window.addEventListener('scroll', update, { passive: true });
  update();
}

export function renderFooter({ lang, activePage }) {
  const c = navCopy[lang];
  const isDocs = activePage === 'docs';
  const prefix = isDocs ? '/' : '';
  const containerClass = isDocs ? 'docs-shell' : 'shell';
  return `
    <footer class="site-footer">
      <div class="${containerClass}">
        <div class="footer-grid">
          <div class="footer-brand">
            <div class="brand">
              <span class="brand-mark" aria-hidden="true">X</span>
              <span class="brand-text">
                <span class="brand-name">${escapeHtml(c.footerTitle)}</span>
                <span class="brand-sub">tcad.xjtu.shop · status.xjtu.shop</span>
              </span>
            </div>
            <p>${escapeHtml(c.footerDesc)}</p>
          </div>
          <div class="footer-col">
            <h3>${escapeHtml(c.footerNav)}</h3>
            <a href="${prefix}#overview">${escapeHtml(c.home)}</a>
            <a href="${prefix}#results">${escapeHtml(c.results)}</a>
            <a href="${prefix}#architecture">${escapeHtml(c.arch)}</a>
            <a href="/docs/">${escapeHtml(c.docs)}</a>
            <a href="https://status.xjtu.shop" target="_blank" rel="noopener">${escapeHtml(c.status)} ${icon('external')}</a>
          </div>
          <div class="footer-col">
            <h3>${escapeHtml(c.footerBoundary)}</h3>
            <p style="font-size:13px;color:var(--muted);line-height:1.65;">${escapeHtml(c.footerBoundaryText)}</p>
          </div>
        </div>
        <div class="footer-bottom">
          <span>${escapeHtml(c.footerCopy)}</span>
          <span>Material 3 · @material/web 2.5.0</span>
        </div>
      </div>
    </footer>
  `;
}
