import '@material/web/button/filled-button.js';
import '@material/web/button/filled-tonal-button.js';
import '@material/web/button/outlined-button.js';
import '@material/web/chips/assist-chip.js';
import '@material/web/iconbutton/icon-button.js';
import '@material/web/progress/linear-progress.js';
import '@material/web/tabs/tabs.js';
import '@material/web/tabs/primary-tab.js';
import { mountEvidence, icon } from './components/evidence.js';
import './styles.css';

const copy = {
  zh: {
    navResearch: '研究主题',
    navRoute: '研究路线',
    navStatus: '服务状态',
    language: 'EN',
    eyebrow: 'XJTU · RADIATION EFFECTS RESEARCH',
    title: 'DRAM 单粒子效应评估',
    formalTitle: 'AI辅助下的DRAM存储器单粒子效应评估研究',
    heroText: '展示研究路线、仿真过程与可追溯证据。',
    routeCta: '查看研究路线',
    statusCta: '查看服务状态',
    stageLabel: '当前阶段',
    stageText: '数据链路持续推进',
    scopeLabel: '研究对象',
    scopeText: 'DDR5 · LPDDR5 · 翻转截面 · 错误率',
    planLabel: '计划进度',
    plannedLabel: '计划',
    solvedLabel: '工程完成',
    runningLabel: '运行中',
    routeEyebrow: 'RESEARCH ROUTE',
    routeTitle: '沿研究链路逐步探索',
    routeIntro: '从文献与数据走向独立验证。',
    routeTabs: ['研究步骤', '证据线索', '验证重点'],
    routeItems: [
      ['01', '文献与数据', '调研评估方法并梳理数据来源。'],
      ['02', 'Geant4 / TCAD', '构建输运与器件响应的仿真链路。'],
      ['03', '截面与错误率', '建立数据驱动的预测与评价方法。'],
      ['04', '独立验证', '对比仿真与实验并评价泛化能力。']
    ],
    routeEvidence: [
      '记录文献来源与数据形成条件。',
      '关联器件参数与原始仿真输出。',
      '保存数据划分与模型版本。',
      '组织独立参考与对比记录。'
    ],
    routeValidation: [
      '核对粒子条件与数据适用范围。',
      '检查求解收敛与物理响应。',
      '开展交叉验证与误差分析。',
      '评估独立样本与泛化表现。'
    ],
    statusEyebrow: 'PLATFORM STATUS',
    statusTitle: '研究服务持续可见',
    statusText: '查看网站与基础运行环境的服务状态。',
    statusLink: '打开状态页',
    boundaryEyebrow: 'PUBLIC FRAME',
    boundaryTitle: '研究过程与证据同行',
    boundaryText: '网页展示研究进展。服务器保留原始任务链路。',
    footer: 'AI辅助下的DRAM存储器单粒子效应评估研究',
    footerStatus: '公开状态',
    liveLoading: '正在读取状态',
    liveUnavailable: '状态等待更新',
    liveStale: '状态等待更新',
    serviceLabels: ['研究展示站', 'TCAD 控制器', '仿真运行环境'],
    serviceDescriptions: ['研究首页与公开状态入口。', '研究流程控制器的服务可用性。', '仿真运行环境的服务可用性。'],
    statusRefresh: '刷新状态',
    statusExpand: '展开服务说明',
    statusCollapse: '收起服务说明',
    statusFull: '完整状态页',
    stateLabels: { operational: '运行正常', degraded: '部分异常', offline: '服务离线', maintenance: '维护中', loading: '正在读取', unknown: '等待更新', stale: '等待更新' },
    statusUpdated: '最近检查',
    structure: '研究链路示意',
    platform: '研究平台',
    nodeLabels: ['粒子输运', '器件响应', '模型预测']
  },
  en: {
    navResearch: 'Research',
    navRoute: 'Route',
    navStatus: 'Service status',
    language: '中',
    eyebrow: 'XJTU · RADIATION EFFECTS RESEARCH',
    title: 'Single-Event Effects in DRAM',
    formalTitle: 'AI-Assisted Assessment of Single-Event Effects in DRAM Memories',
    heroText: 'Explore research paths, simulation process, and traceable evidence.',
    routeCta: 'Explore the route',
    statusCta: 'View service status',
    stageLabel: 'Current stage',
    stageText: 'Data flow in progress',
    scopeLabel: 'Focus',
    scopeText: 'DDR5 · LPDDR5 · Cross-section · Error rate',
    planLabel: 'Plan progress',
    plannedLabel: 'Planned',
    solvedLabel: 'Engineering complete',
    runningLabel: 'Running',
    routeEyebrow: 'RESEARCH ROUTE',
    routeTitle: 'Explore the research chain',
    routeIntro: 'From literature and data to independent validation.',
    routeTabs: ['Research steps', 'Evidence', 'Validation'],
    routeItems: [
      ['01', 'Literature & data', 'Review assessment methods and trace data sources.'],
      ['02', 'Geant4 / TCAD', 'Build the transport and device-response simulation chain.'],
      ['03', 'Cross-section & error rate', 'Develop data-driven prediction and evaluation methods.'],
      ['04', 'Independent validation', 'Compare simulations and experiments to evaluate generalization.']
    ],
    routeEvidence: [
      'Record literature sources and the conditions behind the data.',
      'Connect device parameters with source simulation outputs.',
      'Preserve the data split and model version.',
      'Organize independent references and comparison records.'
    ],
    routeValidation: [
      'Check particle conditions and data scope.',
      'Check convergence and the physical response.',
      'Perform cross-validation and error analysis.',
      'Evaluate independent samples and generalization.'
    ],
    statusEyebrow: 'PLATFORM STATUS',
    statusTitle: 'A view into service health',
    statusText: 'Check the website and supporting research services.',
    statusLink: 'Open status page',
    boundaryEyebrow: 'PUBLIC FRAME',
    boundaryTitle: 'Evidence follows the process',
    boundaryText: 'The page presents progress. The server keeps the original task chain.',
    footer: 'AI-Assisted Assessment of Single-Event Effects in DRAM Memories',
    footerStatus: 'Public status',
    liveLoading: 'Loading status',
    liveUnavailable: 'Awaiting status update',
    liveStale: 'Awaiting status update',
    serviceLabels: ['Research site', 'TCAD controller', 'Simulation runtime'],
    serviceDescriptions: ['The research homepage and public status entry.', 'Service availability of the research workflow controller.', 'Service availability of the simulation environment.'],
    statusRefresh: 'Refresh status',
    statusExpand: 'Expand service note',
    statusCollapse: 'Collapse service note',
    statusFull: 'Full status page',
    stateLabels: { operational: 'Operational', degraded: 'Degraded', offline: 'Offline', maintenance: 'Maintenance', loading: 'Loading', unknown: 'Awaiting update', stale: 'Awaiting update' },
    statusUpdated: 'Last checked',
    structure: 'Research workflow illustration',
    platform: 'Research platform',
    nodeLabels: ['Particle transport', 'Device response', 'Model prediction']
  }
};

const state = { lang: localStorage.getItem('xjtu-lang') === 'en' ? 'en' : 'zh', status: null, statusError: false, statusLoading: false, expandedService: null, routeTab: 0 };

function text(key) {
  return copy[state.lang][key];
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function render() {
  const routeItems = text('routeItems')
    .map(
      ([number, title, body]) => `
        <article class="route-step">
          <div class="route-card-top"><span class="step-number">${number}</span>${icon(['archive', 'simulation', 'model', 'check'][Number(number) - 1])}</div>
          <div>
            <h3>${escapeHtml(title)}</h3>
            <p>${escapeHtml(body)}</p>
          </div>
        </article>`
    )
    .join('');

  document.querySelector('#app').innerHTML = `
    <header class="topbar">
      <div slot="headline" class="brand">
        <span class="brand-mark" aria-hidden="true">X</span>
        <span class="brand-name">xjtu.shop</span>
      </div>
      <nav slot="actionItems" class="desktop-nav" aria-label="${escapeHtml(text('navResearch'))}">
        <a href="#research">${escapeHtml(text('navResearch'))}</a>
        <a href="#route">${escapeHtml(text('navRoute'))}</a>
        <a href="https://status.xjtu.shop" rel="noopener">${escapeHtml(text('navStatus'))}</a>
      </nav>
      <md-icon-button slot="actionItems" id="languageButton" aria-label="${escapeHtml(text('language'))}">
        <span class="language-icon">${escapeHtml(text('language'))}</span>
      </md-icon-button>
    </header>

    <main>
      <section id="research" class="hero shell">
        <div class="hero-copy">
          <md-assist-chip href="#evidence" label="${text('platform')}">${icon('simulation', 'slot="icon"')}</md-assist-chip>
          <p class="eyebrow">${escapeHtml(text('eyebrow'))}</p>
          <h1>${escapeHtml(text('title'))}</h1>
          <p class="formal-title">${escapeHtml(text('formalTitle'))}</p>
          <p class="hero-text">${escapeHtml(text('heroText'))}</p>
          <div class="hero-actions">
            <md-filled-button href="#route">${escapeHtml(text('routeCta'))}</md-filled-button>
            <md-outlined-button href="https://status.xjtu.shop" rel="noopener">${escapeHtml(text('statusCta'))}</md-outlined-button>
          </div>
        </div>
        <div class="hero-visual" role="img" aria-label="${escapeHtml(text('structure'))}">
          <div class="orbit orbit-one"></div>
          <div class="orbit orbit-two"></div>
          <div class="hero-node node-main">
            <span class="node-kicker">DRAM / SEE</span>
            <strong>σ · error rate</strong>
            <span class="node-caption">${text('structure')}</span>
          </div>
          <div class="hero-node node-geant"><span>Geant4</span><small>${text('nodeLabels')[0]}</small></div>
          <div class="hero-node node-tcad"><span>TCAD</span><small>${text('nodeLabels')[1]}</small></div>
          <div class="hero-node node-model"><span>AI model</span><small>${text('nodeLabels')[2]}</small></div>
          <span class="hero-particle particle-one" aria-hidden="true"></span><span class="hero-particle particle-two" aria-hidden="true"></span>
          <div class="hero-grid"></div>
        </div>
      </section>

      <section class="signal-strip shell" aria-label="${escapeHtml(text('stageLabel'))}">
        <div><span class="signal-label">${escapeHtml(text('stageLabel'))}</span><strong id="stage-reading">${escapeHtml(text('stageText'))}</strong></div>
        <div><span class="signal-label" id="plan-label">${escapeHtml(text('scopeLabel'))}</span><strong id="plan-reading">${escapeHtml(text('scopeText'))}</strong></div>
        <div class="live-pill" id="live-status" aria-live="polite"></div>
      </section>

      <section id="route" class="section shell">
        <div class="section-heading">
          <p class="eyebrow">${escapeHtml(text('routeEyebrow'))}</p>
          <h2>${escapeHtml(text('routeTitle'))}</h2>
          <p>${escapeHtml(text('routeIntro'))}</p>
        </div>
        <md-tabs class="route-tabs" aria-label="${escapeHtml(text('routeTitle'))}">
          ${text('routeTabs').map((label, index) => `<md-primary-tab id="route-tab-${index}" aria-controls="route-panel" ${index === state.routeTab ? 'active' : ''}>${label}</md-primary-tab>`).join('')}
        </md-tabs>
        <div class="route-grid" id="route-panel" role="tabpanel" aria-labelledby="route-tab-${state.routeTab}">${routeItems}</div>
      </section>

      <section id="evidence" class="evidence-section shell"></section>

      <section class="status-section shell">
        <div class="status-section-copy">
          <p class="eyebrow">${escapeHtml(text('statusEyebrow'))}</p>
          <h2>${escapeHtml(text('statusTitle'))}</h2>
          <p>${escapeHtml(text('statusText'))}</p>
          <md-filled-button href="https://status.xjtu.shop" rel="noopener">${escapeHtml(text('statusLink'))}</md-filled-button>
        </div>
        <md-elevated-card class="status-preview" id="status-preview"></md-elevated-card>
      </section>

      <section class="boundary-section shell">
        <div>
          <p class="eyebrow">${escapeHtml(text('boundaryEyebrow'))}</p>
          <h2>${escapeHtml(text('boundaryTitle'))}</h2>
        </div>
        <div>
          <p>${escapeHtml(text('boundaryText'))}</p>
          <details class="more-details">
            <summary>${state.lang === 'zh' ? '查看说明' : 'Read the note'}</summary>
            <p>${state.lang === 'zh' ? '仿真由服务器上的原 runner 和受控任务链路负责。网页提供研究路线与公开状态。' : 'Simulations remain managed by the server-side runner and controlled task chain. The page presents the route and public status.'}</p>
          </details>
        </div>
      </section>
    </main>

    <footer class="footer shell">
      <span>${escapeHtml(text('footer'))}</span>
      <a href="https://status.xjtu.shop" rel="noopener">${escapeHtml(text('footerStatus'))} ↗</a>
    </footer>`;

  document.querySelector('#languageButton')?.addEventListener('click', () => {
    state.lang = state.lang === 'zh' ? 'en' : 'zh';
    localStorage.setItem('xjtu-lang', state.lang);
    render();
    document.querySelector('#languageButton').focus();
  });

  document.documentElement.lang = state.lang === 'zh' ? 'zh-CN' : 'en';
  mountEvidence(document.querySelector('#evidence'), state.lang);
  const updateRoute = () => {
    const descriptions = state.routeTab === 0 ? text('routeItems').map(item => item[2]) : text(state.routeTab === 1 ? 'routeEvidence' : 'routeValidation');
    document.querySelectorAll('.route-step p').forEach((p, index) => { p.textContent = descriptions[index]; });
    document.querySelector('#route-panel').setAttribute('aria-labelledby', `route-tab-${state.routeTab}`);
  };
  document.querySelector('.route-tabs').addEventListener('change', event => {
    state.routeTab = event.currentTarget.activeTabIndex;
    updateRoute();
  });
  updateRoute();
  updateStatus();
}

function updateStatus() {
  const previousFocus = document.querySelector('#status-preview')?.contains(document.activeElement) ? document.activeElement?.id : null;
  const generated = Date.parse(state.status?.generated_at);
  const threshold = state.status?.health?.freshness?.scheduler_threshold_seconds ?? 180;
  const stale = state.status && (!Number.isFinite(generated) || Date.now() - generated > threshold * 1000 || generated - Date.now() > 60_000);
  const overall = stale ? 'stale' : state.status?.overall || (state.statusError ? 'unknown' : 'loading');
  const label = text('stateLabels')[overall] || text('stateLabels').unknown;
  const simulation = state.status?.health?.simulation;
  const summary = state.status?.research_summary ?? state.status?.research;
  const stage = state.lang === 'zh' ? simulation?.summary_zh || simulation?.summary_en : simulation?.summary_en || simulation?.summary_zh;
  const stats = summary?.totals;
  const progress = summary ? [summary.revision, ...[
    [stats?.planned ?? summary?.budget?.total_cases, 'plannedLabel'],
    [stats?.solved, 'solvedLabel'],
    [stats?.running ?? simulation?.active_tasks, 'runningLabel'],
  ].filter(([value]) => Number.isFinite(value)).map(([value, caption]) => `${text(caption)} ${value}`)].filter(Boolean) : [];
  document.getElementById('stage-reading').textContent = stage || text('stageText');
  document.getElementById('plan-label').textContent = progress.length ? text('planLabel') : text('scopeLabel');
  document.getElementById('plan-reading').textContent = progress.length ? progress.join(' · ') : text('scopeText');
  document.querySelector('#live-status').innerHTML = `<span class="status-dot ${overall}"></span><span>${escapeHtml(label)}</span>`;
  const serviceIds = ['research-site', 'tcad-controller', 'simulation-runtime'];
  const rows = serviceIds.map((id, index) => {
    const service = state.status?.services?.find(service => service.id === id);
    const health = state.status?.health?.services?.items?.find(item => item.id === id);
    const value = stale ? 'stale' : health?.state || service?.state || 'unknown';
    const expanded = state.expandedService === id;
    const checked = Date.parse(service?.checked_at);
    const checkedTime = Number.isFinite(checked) ? new Intl.DateTimeFormat(state.lang === 'zh' ? 'zh-CN' : 'en', { dateStyle: 'short', timeStyle: 'short' }).format(checked) : '—';
    return `<div class="preview-service ${expanded ? 'is-expanded' : ''}">
      <button class="preview-line" id="preview-toggle-${id}" type="button" data-preview-service="${id}" aria-expanded="${expanded}" aria-controls="preview-note-${id}">
        <span>${text('serviceLabels')[index]}</span>
        <b class="preview-state ${value}">${escapeHtml(text('stateLabels')[value] || text('stateLabels').unknown)}</b>
        <span class="preview-chevron">${icon('chevron')}</span>
        <md-ripple></md-ripple><md-focus-ring inward></md-focus-ring>
      </button>
      <div class="preview-service-note" id="preview-note-${id}" ${expanded ? '' : 'hidden'}>
        <p>${text('serviceDescriptions')[index]}</p>
        <div>${text('statusUpdated')} <time>${checkedTime}</time></div>
      </div>
    </div>`;
  }).join('');
  const time = Number.isFinite(generated) ? new Intl.DateTimeFormat(state.lang === 'zh' ? 'zh-CN' : 'en', { hour: '2-digit', minute: '2-digit' }).format(generated) : '—';
  document.querySelector('#status-preview').innerHTML = `
    <div class="preview-header">
      <span class="status-dot ${overall}"></span>
      <a class="preview-title" href="https://status.xjtu.shop">status.xjtu.shop</a>
      <md-icon-button id="preview-refresh" class="${state.statusLoading ? 'is-refreshing' : ''}" aria-label="${text('statusRefresh')}" title="${text('statusRefresh')}" ${state.statusLoading ? 'disabled' : ''}>${icon('refresh')}</md-icon-button>
    </div>
    ${state.statusLoading ? `<md-linear-progress indeterminate aria-label="${text('liveLoading')}"></md-linear-progress>` : ''}
    ${rows}
    <div class="preview-update"><span>${text('statusUpdated')} <time>${time}</time></span><a href="https://status.xjtu.shop">${text('statusFull')}${icon('arrow')}</a></div>`;
  document.querySelectorAll('[data-preview-service]').forEach(button => {
    button.addEventListener('click', () => {
      const id = button.dataset.previewService;
      state.expandedService = state.expandedService === id ? null : id;
      document.querySelectorAll('[data-preview-service]').forEach(toggle => {
        const expanded = state.expandedService === toggle.dataset.previewService;
        toggle.setAttribute('aria-expanded', String(expanded));
        toggle.closest('.preview-service').classList.toggle('is-expanded', expanded);
        document.querySelector(`#${toggle.getAttribute('aria-controls')}`).hidden = !expanded;
      });
    });
  });
  document.querySelector('#preview-refresh').addEventListener('click', loadStatus);
  if (previousFocus) document.getElementById(previousFocus)?.focus({ preventScroll: true });
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

async function fetchStatus(path) {
  const response = await fetch(path, { cache: 'no-store', signal: AbortSignal.timeout(8000) });
  if (!response.ok) throw new Error(`${path} returned HTTP ${response.status}`);
  const status = await response.json();
  if (!Number.isFinite(Date.parse(status?.generated_at))) throw new Error(`Invalid status payload from ${path}`);
  return status;
}

render();
const refreshVisibleStatus = () => { if (!document.hidden) loadStatus(); };
refreshVisibleStatus();
document.addEventListener('visibilitychange', refreshVisibleStatus);
setInterval(refreshVisibleStatus, 60_000);
