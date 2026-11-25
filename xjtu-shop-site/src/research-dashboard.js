const view = { cohort: null, query: '', filter: 'all', limit: 12, budgetTab: null };
const words = {
  zh: {
    paperProgress: '论文 v2 渐进进度', paperChapters: '已完成章节', paperBuild: '最近编译', paperSprint: '最近冲刺',
    paperBuildOk: '成功', paperBuildFailed: '失败', paperBuildUnknown: '未知',
    title: '科研计划', core: '核心计划', reserve: '备用计划', control: '无粒子对照',
    blocks: '研究区块', zeroCases: '无粒子基线', locked: '封存', loadingCases: '等待公开逐例清单',
    publicCases: '条公开案例', search: '搜索案例', searchHint: '搜索案例 ID、器件、辐照条件或 B0/B1',
    caseFilter: '案例状态筛选', matches: '匹配', statisticsSnapshotUnknown: '统计资格快照待核对',
    node_count: '网格节点',
    planned: '计划槽位', solved: '归档已核验', archived: '归档已核验', accepted: '科学验收通过', running: '运行中', remaining: '待验收',
    solver_finished: '求解结束 · 待收集', missing_data: '缺数据', missing_zero_control: '缺零源对照', under_review: '待核对', slot_isolated: '单槽隔离', failedAttempts: '失败尝试',
    total: '完整计划', Z: 'Z 无粒子基线', T: 'T 阈值校准', S: 'S 分层响应', R: 'R 随机校准',
    HR: 'HR 辐照留出', HP: 'HP 器件留出', AL: 'AL 主动学习',
    statisticsIntent: '统计用途上限', statisticsSnapshotPending: '统计资格快照待接入', statisticsSnapshotConnected: '统计资格快照已接入',
    statisticsEligible: '统计资格通过', manifestEligible: '清单资格标记', radiation: '辐照条件',
    statisticsPublicCount: '公开统计用途案例', statisticsScopeHint: '公开区块（S、R）含统计用途案例；其余位于封存留出区块，不展示逐例明细。',
    publicCount: '公开', closePanel: '收起',
    sealed: '封存中，仅显示区块汇总',
    p0: 'P0 前置诊断', p0Badge: '独立记录', p0Note: '诊断单独记录，不计入正式计划完成数。正式基线须有对应案例和验收证据。',
    notesTitle: '统计口径与说明',
    recorded: '已登记',
    pending: '待执行', failed: '仿真失败', all: '全部', issues: '处理中', empty: '暂无匹配记录',
    pairs: '配对事件', parameters: '计划参数', cases: '逐例清单', more: '展开更多',
    proof: '求解结束以原任务退出证据为准。归档数含已核验的失败归档。科学验收须有逐例证据，统计资格另按快照核定。',
    currentActivity: '当前动态', recentOutcomes: '最近结果', idle: '当前空闲', activityStale: '调度观测待更新', noOutcomes: '暂无近期结果',
    completed: '归档已核验', collecting: '待收集', uncollected: '已退出待收集', healthy: '正常推进', stalled: '停滞预警',
    fine_step: '微步收敛', slow_convergence: '慢收敛', collection_overdue: '收集超时', verified_success: '归档已核验', verified_failure: '失败归档已核验',
    verified_interrupted: '已中断', awaiting_collection: '待收集', sealedTask: '封存留出任务', unmatchedTask: '未关联任务',
    projectionStale: '科研投影待更新（展示上一份成功快照）',
    maintenanceNotes: '维护备注（人工记录）', oldNote: '备注已过期', updateUnknown: '更新时间未知',
    log: '日志',
    codex: 'Codex', next: '下一步', evidence: '已关联证据',
    preparing: '输入准备', transport: '粒子输运', device: '器件求解',
    analysis: '结果分析', validation: '验证', none: '常规推进', newton_nonconvergence: '牛顿不收敛',
    mesh_quality: '网格质量', license_wait: '许可等待', resource_pressure: '资源压力',
    input_validation: '输入校验', solver_failure: '求解异常',
    investigating: '定位中', fixing: '解决中', prepared: '方案就绪', retesting: '复验中',
    monitoring: '观察中', resolved: '已记录', attempts: '尝试', profile: '器件',
    unknown: '待确认', waiting: '等待正式清单', relative: '相对比例',
    energy_MeV: '能量', theta_deg: '入射 θ', phi_deg: '入射 φ', temperature_K: '温度',
    source_window_origin: '源窗口起点', source_window_x_direction: '源窗口 X 方向', source_window_y_direction: '源窗口 Y 方向',
    source_window_width_coord: '源窗口宽度', source_window_height_coord: '源窗口高度',
    source_variant: '源类型', source_window_unit: '坐标说明', particle_injection: '粒子注入', transient_final_ns: '瞬态终点',
    integrator: '积分方法', main_max_step_ns: '普通最大步长', edge_max_step_ns: '边沿最大步长', write_patterns: '写入模式',
    read_target: '读出节点', bl_precharge_V: '位线预充电', device_geometry: '器件外形', parameterUnavailable: '未提供',
    input_coordinate_space: '输入坐标单位', particle_free_control: '无粒子对照', not_injected: '未注入', mesh_dimensions_unavailable: '网格输入',
    Lg_relative: 'Lg', Wfin_relative: 'Wfin', Tox_relative: 'Tox', NA_relative: 'NA', ND_relative: 'ND', Hjc_nm: '结深',
    Lg_scale: 'Lg', Wfin_scale: 'Wfin', Tox_scale: 'Tox', NA_scale: 'NA', ND_scale: 'ND',
    requested_threads: '数值线程', numerical_threads: '数值线程', grid_points: '网格点', research_samples: '新增科研样本', stored_bit: '存储位',
  },
  en: {
    paperProgress: 'Thesis v2 progress', paperChapters: 'Chapters completed', paperBuild: 'Latest build', paperSprint: 'Latest sprint',
    paperBuildOk: 'Passed', paperBuildFailed: 'Failed', paperBuildUnknown: 'Unknown',
    title: 'Research plan', core: 'Core plan', reserve: 'Reserve', control: 'Particle-free',
    blocks: 'Research blocks', zeroCases: 'Z baselines', locked: 'Sealed', loadingCases: 'Awaiting public case manifest',
    publicCases: 'public cases', search: 'Search cases', searchHint: 'Search case ID, device, radiation or B0/B1',
    caseFilter: 'Filter by case status', matches: 'Showing', statisticsSnapshotUnknown: 'Qualification snapshot pending',
    node_count: 'Mesh nodes',
    planned: 'Planned', solved: 'Archive verified', archived: 'Archive verified', accepted: 'Science accepted', running: 'Running', remaining: 'Remaining',
    solver_finished: 'Solver finished · awaiting collection', missing_data: 'Missing data', missing_zero_control: 'Missing zero control', under_review: 'Under review', slot_isolated: 'Slot isolated', failedAttempts: 'Failed attempts',
    total: 'Full plan', Z: 'Z Baselines', T: 'T Threshold', S: 'S Stratified', R: 'R Random',
    HR: 'HR Radiation holdout', HP: 'HP Profile holdout', AL: 'AL Active learning',
    statisticsIntent: 'Statistical intent', statisticsSnapshotPending: 'Statistical qualification snapshot not connected', statisticsSnapshotConnected: 'Statistical qualification snapshot connected',
    statisticsEligible: 'Statistically qualified', manifestEligible: 'Manifest eligible', radiation: 'Radiation',
    statisticsPublicCount: 'Public statistical cases', statisticsScopeHint: 'Public blocks (S, R) contain statistical-intent cases; remaining cases are in sealed holdouts.',
    publicCount: 'public', closePanel: 'Close',
    sealed: 'Sealed · block summary only',
    p0: 'P0 diagnostics', p0Badge: 'Tracked separately', p0Note: 'Diagnostics are separate from the formal plan. Formal baselines require a case mapping and acceptance evidence.',
    notesTitle: 'Methodology & definitions',
    recorded: 'Recorded',
    pending: 'Pending', failed: 'Simulation failed', all: 'All', issues: 'In progress', empty: 'No matching records',
    pairs: 'Paired events', parameters: 'Planned parameters', cases: 'Case manifest', more: 'Show more',
    proof: 'Solver completion uses native exit evidence. Archive counts include verified failure archives. Scientific acceptance requires case-level evidence. Statistical eligibility uses its own snapshot.',
    currentActivity: 'Current activity', recentOutcomes: 'Recent outcomes', idle: 'Currently idle', activityStale: 'Awaiting a fresh scheduler sample', noOutcomes: 'No recent outcomes',
    completed: 'Archive verified', collecting: 'Collecting', uncollected: 'Exited, pending collection', healthy: 'Advancing', stalled: 'Stalled',
    fine_step: 'Fine steps', slow_convergence: 'Slow convergence', collection_overdue: 'Collection overdue', verified_success: 'Archive verified', verified_failure: 'Failure archive verified',
    verified_interrupted: 'Interrupted', awaiting_collection: 'Awaiting collection', sealedTask: 'Sealed holdout', unmatchedTask: 'Unmatched task',
    projectionStale: 'Research projection awaiting update (last successful snapshot shown)',
    maintenanceNotes: 'Maintenance notes (manual records)', oldNote: 'Note expired', updateUnknown: 'Update time unknown',
    log: 'Log',
    codex: 'Codex', next: 'Next', evidence: 'Evidence linked',
    preparing: 'Preparation', transport: 'Transport', device: 'Device solve',
    analysis: 'Analysis', validation: 'Validation', none: 'On track', newton_nonconvergence: 'Newton nonconvergence',
    mesh_quality: 'Mesh quality', license_wait: 'License wait', resource_pressure: 'Resource pressure',
    input_validation: 'Input validation', solver_failure: 'Solver issue',
    investigating: 'Investigating', fixing: 'Fixing', prepared: 'Prepared', retesting: 'Retesting',
    monitoring: 'Monitoring', resolved: 'Recorded', attempts: 'Attempts', profile: 'Devices',
    unknown: 'TBD', waiting: 'Awaiting the case manifest', relative: 'Relative scales',
    energy_MeV: 'Energy', theta_deg: 'Incidence θ', phi_deg: 'Incidence φ', temperature_K: 'Temperature',
    source_window_origin: 'Source origin', source_window_x_direction: 'Source X dir', source_window_y_direction: 'Source Y dir',
    source_window_width_coord: 'Source width', source_window_height_coord: 'Source height',
    source_variant: 'Source type', source_window_unit: 'Coordinate unit', particle_injection: 'Injection', transient_final_ns: 'Transient end',
    integrator: 'Integrator', main_max_step_ns: 'Main max step', edge_max_step_ns: 'Edge max step', write_patterns: 'Write patterns',
    read_target: 'Read node', bl_precharge_V: 'BL precharge', device_geometry: 'Geometry', parameterUnavailable: 'N/A',
    input_coordinate_space: 'Input coordinates', particle_free_control: 'Particle-free', not_injected: 'None', mesh_dimensions_unavailable: 'Mesh input',
    Lg_relative: 'Lg', Wfin_relative: 'Wfin', Tox_relative: 'Tox', NA_relative: 'NA', ND_relative: 'ND', Hjc_nm: 'Junction depth',
    Lg_scale: 'Lg', Wfin_scale: 'Wfin', Tox_scale: 'Tox', NA_scale: 'NA', ND_scale: 'ND',
    requested_threads: 'Threads', numerical_threads: 'Threads', grid_points: 'Grid points', research_samples: 'Samples', stored_bit: 'Stored bit',
  },
};
const esc = (value) => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#039;');
const text = (lang, key) => Object.hasOwn(words[lang] || words.en, key) ? (words[lang] || words.en)[key] : key;
export const sealedId = (value) => /^r\d+-(hr|hp)-/i.test(value || '');
const date = (lang, value) => value && Number.isFinite(Date.parse(value))
  ? new Intl.DateTimeFormat(lang === 'zh' ? 'zh-CN' : 'en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value)) : '—';

export function parameterMarkup(parameters, lang = 'zh') {
  return Object.entries(parameters || {}).map(([key, value]) => {
    const unit = key.endsWith('_MeV') ? ' MeV' : key.endsWith('_deg') ? '°' : key.endsWith('_K') ? ' K' : key.endsWith('_nm') ? ' nm'
      : key.endsWith('_ns') ? ' ns' : key.endsWith('_fF') ? ' fF' : key.endsWith('_ohm') ? ' Ω' : key.endsWith('_V') ? ' V'
      : /_(relative|scale)$/.test(key) ? '×' : '';
    const display = value === null || value === undefined ? text(lang, 'parameterUnavailable')
      : typeof value === 'string' ? text(lang, value)
      : Array.isArray(value) ? value.map((item) => typeof item === 'object' ? JSON.stringify(item) : item).join(', ')
      : typeof value === 'object' ? JSON.stringify(value) : String(value);
    return `<span class="parameter-pill"><span>${esc(text(lang, key))}</span><strong>${esc(display)}${value === null || value === undefined ? '' : unit}</strong></span>`;
  }).join('');
}

const NOTE_EXPIRY_HOURS = 24;

function relativeTime(lang, seconds) {
  if (!Number.isFinite(seconds)) return '';
  const [value, unit] = seconds >= 86_400 ? [seconds / 86_400, 'day'] : seconds >= 3600 ? [seconds / 3600, 'hour']
    : seconds >= 60 ? [seconds / 60, 'minute'] : [seconds, 'second'];
  return new Intl.RelativeTimeFormat(lang === 'zh' ? 'zh-CN' : 'en-US').format(-Math.floor(value), unit);
}

function progressCard(entry, lang) {
  const label = (key) => esc(text(lang, key));
  const updated = Date.parse(entry.updated_at);
  const age = Number.isFinite(updated) ? Math.max(0, Math.floor((Date.now() - updated) / 1000)) : null;
  return `<article class="research-update ${entry.issue === 'none' ? '' : 'has-issue'}">
    <div class="update-top"><span class="update-case">${esc(entry.case_id)}</span><span class="badge neutral">${label(entry.action)}</span></div>
    <h3>${label(entry.issue)}</h3>
    <p class="update-note">${esc(entry.note || text(lang, entry.phase))}</p>
    ${entry.next_step ? `<p class="update-next"><span>${label('next')}</span>${esc(entry.next_step)}</p>` : ''}
    <div class="update-footer"><span>${label('codex')} · ${label(entry.phase)}${entry.evidence_recorded ? ` · ✓ ${label('evidence')}` : ''}</span>
      <time title="${esc(date(lang, entry.updated_at))}">${esc(relativeTime(lang, age) || text(lang, 'updateUnknown'))}</time>
      ${age >= NOTE_EXPIRY_HOURS * 3600 ? `<span class="badge warn">${label('oldNote')}</span>` : ''}</div>
  </article>`;
}

export function caseWaitsAreFresh(research) {
  const observed = research?.case_waits_observed_at;
  const maxAge = research?.case_waits_max_age_seconds;
  if (typeof observed !== 'string') return false;
  const age = Date.now() - Date.parse(observed);
  return research?.projection_state !== 'cached_stale' && Number.isFinite(maxAge) && maxAge > 0
    && age >= -60_000 && age <= maxAge * 1000;
}

// The public projection emits fixed sentences and a few variants with public case coordinates.
const publicWaitNotes = new Set([
  '等待 P1 证据审阅和 P2 放行。',
  '等待该结构两种存储状态的数值资格验收。',
  '等待对应存储状态的匹配零源验收记录。',
  '等待该工况的输运输入冻结。',
  '等待该工况的输运完成并核验收集。',
  '等待冻结入选事件并生成对应的粒子源。',
  '等待同结构、同存储状态的匹配零源。',
  '等待真实参考事件、匹配零源和初次阈值试探决定。',
  '等待同工况初次阈值试探的配对读出验收。',
  '等待根据已验收读出确定下一次试探倍率或记录停止决定。',
  '等待确认阈值试探的下一分支及未使用计划位。',
  '等待输入核验和原调度器准入。',
  '等待已审阅输入进入原调度队列。',
  '等待原调度器分配运行资源。',
  '等待原运行的状态回读。',
  '等待原运行完成。',
  '等待核验并收集原运行结果。',
  '等待原运行结果的科学验收。',
  '等待复核已有运行并决定修复或结案。',
  '等待核对该项证据和原任务身份。',
  '等待开发数据快照、候选模型和分批选点决定冻结。',
]);
const publicWaitPatterns = [
  /^等待 LHS0[1-6] 的 b0、b1 数值资格验收。$/,
  /^等待 (?:D[0-3]|LHS0[1-6])\/(?:G0|C1) b[01] ×10 试探的配对读出验收。$/,
  /^LHS02\/(?:G0|C1) b1 ×3 等待同工况 ×30 的配对读出验收和分支决定。$/,
  /^D1\/G0 b1 ×(?:3|30) 等待同一套输入的零源运行完成并核验。$/,
  /^D2\/(?:G0|C1) b1 ×30 仍未翻转，保留 ×3 分支，等待独立的新试探决定。$/,
];
const publicWaitNote = (value) => typeof value === 'string' && value === value.trim() &&
  (publicWaitNotes.has(value) || publicWaitPatterns.some((pattern) => pattern.test(value))) ? value : '';
const caseStates = ['pending', 'running', 'solver_finished', 'solved', 'accepted', 'failed', 'missing_data', 'under_review'];
const caseIssues = ['missing_zero_control', 'under_review', 'slot_isolated'];
const caseStatus = (item) => [caseStates.includes(item.state) ? item.state : 'unknown',
  item.issue !== item.state && caseIssues.includes(item.issue) && item.issue];
const caseArchived = (item) => item.archive_verified === true || (item.archive_verified == null && item.state === 'solved');

function renderCases(research, lang, cohort, updates, sealed) {
  const label = (key) => esc(text(lang, key));
  if (sealed.has(cohort)) return `<p class="empty">${label('sealed')}</p>`;
  if (!research.cases) return `<p class="empty">${label('loadingCases')}</p>`;
  const publicCases = research.cases.filter((item) => !item.sealed && !sealedId(item.case_id) && !sealed.has(item.block || item.cohort));
  const query = view.query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const cases = publicCases.filter((item) => {
    if (cohort !== 'total' && (item.block || item.cohort) !== cohort) return false;
    const entry = updates.get(item.case_id);
    const states = caseStatus(item);
    const matches = view.filter === 'issues' ? entry && entry.action !== 'resolved' :
      view.filter === 'solved' ? caseArchived(item) :
      states.includes(view.filter) || (view.filter === 'under_review' && states.includes('slot_isolated'));
    if (view.filter !== 'all' && !matches) return false;
    const haystack = [item.case_id, item.block, item.cohort, item.profile_id, item.radiation_id, item.condition_id,
      item.pair_id, item.stored_bit == null ? '' : `B${item.stored_bit}`, ...states.filter(Boolean).map((key) => text(lang, key))].join(' ').toLowerCase();
    return query.every((keyword) => haystack.includes(keyword));
  });
  const shown = cases.slice(0, view.limit);
  const showWaits = caseWaitsAreFresh(research);
  return `<details class="plan-details case-manifest" id="case-manifest">
    <summary><strong>${label('cases')}</strong><span>${publicCases.length} ${label('publicCases')}</span></summary>
    <div class="case-tools">
      <div class="case-search-row">
        <input type="search" id="case-search" aria-label="${label('search')}" placeholder="${label('searchHint')}" value="${esc(view.query)}" autocomplete="off">
        <span class="muted" role="status">${label('matches')} ${shown.length} / ${cases.length}</span>
      </div>
      <div class="filters" role="group" aria-label="${label('caseFilter')}">
        ${['all', 'running', 'solver_finished', 'solved', 'accepted', 'failed', 'missing_data', 'missing_zero_control', 'under_review', 'pending', 'issues'].map((key) =>
          `<button type="button" class="filter-chip" data-key="filter-${key}" data-case-filter="${key}" aria-pressed="${view.filter === key}"><md-ripple></md-ripple>${label(key)}</button>`).join('')}
      </div>
    </div>
    <div class="case-grid">${shown.map((item) => {
      const badges = [...caseStatus(item), caseArchived(item) && item.state !== 'solved' && 'archived'];
      const wait = showWaits && publicWaitNote(item.public_wait_zh);
      const condition = item.radiation_id || item.condition_id || text(lang, ['Z', 'control'].includes(item.block || item.cohort) ? 'control' : 'unknown');
      return `<article class="case-row" data-key="case-${esc(item.case_id)}">
        <div><strong>${esc(item.case_id)}</strong><span>${badges.filter(Boolean).map((key) => activityBadge(lang, key)).join(' ')}</span></div>
        <p>${esc(item.profile_id || text(lang, 'unknown'))} · ${esc(condition)}${item.primary_index != null ? ` · P${esc(item.primary_index)}` : ''}${item.stored_bit != null ? ` · B${esc(item.stored_bit)}` : ''}</p>
        <small>${label('attempts')} ${esc(item.attempts ?? '—')}${Number.isSafeInteger(item.failed_attempts) && item.failed_attempts > 0 ? ` · ${label('failedAttempts')} ${item.failed_attempts}` : ''}</small>
        ${wait ? `<p class="case-wait" lang="zh-CN">${esc(wait)}</p>` : ''}
      </article>`;
    }).join('') || `<p class="empty">${label('empty')}</p>`}</div>
    ${cases.length > shown.length ? `<button type="button" id="moreCases" class="more-cases"><md-ripple></md-ripple>${label('more')} (${Math.min(24, cases.length - shown.length)})</button>` : ''}
  </details>`;
}

function renderPaperProgress(paper, lang) {
  if (!paper) return '';
  const label = (key) => esc(text(lang, key));
  const { chapters_done: done, chapters_total: total, build_ok: built, last_sprint_utc: sprint } = paper;
  const validDone = Number.isInteger(done) && done >= 0;
  const validTotal = Number.isInteger(total) && total >= 0;
  const build = built === true ? 'paperBuildOk' : built === false ? 'paperBuildFailed' : 'paperBuildUnknown';
  return `<md-outlined-card class="m3-card" data-key="paper-progress"><div class="card-body">
    <div class="batch-bar"><strong>${label('paperProgress')}</strong>
      <span>${label('paperChapters')} <b>${validDone ? done : '—'} / ${validTotal ? total : '—'}</b></span>
      <span>${label('paperBuild')} · <span class="badge ${built === true ? 'good' : built === false ? 'bad' : 'neutral'}">${label(build)}</span></span>
      <span>${label('paperSprint')} · ${esc(date(lang, sprint))}</span>
    </div>
    ${validDone && validTotal && total > 0 && done <= total ? `<progress value="${done}" max="${total}" aria-label="${label('paperChapters')}"></progress>` : ''}
  </div></md-outlined-card>`;
}

export function renderResearch(research, lang, activity) {
  const label = (key) => esc(text(lang, key));
  const heading = `<div class="section-heading"><h2>${research?.available ? esc(research.revision || '') + ' ' : ''}${label('title')}</h2></div>`;
  const paper = renderPaperProgress(research?.paper_progress, lang);
  const warning = research?.projection_state === 'cached_stale' ? `<p class="health-alert plan-warning">${label('projectionStale')}</p>` : '';
  const blocks = research?.blocks ?? Object.entries(research?.counts || {}).map(([id, counts]) => ({ id, counts }));
  const selected = blocks.find((block) => block.id === view.cohort);
  const cohort = selected?.id ?? 'total';
  const blockCounts = (block) => block.counts ?? (block.planned != null ? block : research.counts?.[block.id]) ?? block;
  const sealed = new Set(blocks.filter((block) => block.sealed).map((block) => block.id));
  const progress = (research?.progress || []).filter((entry) => !entry.sealed && !sealedId(entry.case_id) && !sealed.has(entry.block || entry.cohort));
  const activityMarkup = renderActivity(activity, lang, sealed);
  const maintenance = renderUpdates(progress, lang);
  if (!research?.available) return heading + paper + warning + `<p class="empty">${label('waiting')}</p>` + activityMarkup + maintenance;
  const counts = selected ? blockCounts(selected) : research.totals;
  const archiveKey = (items) => items?.archived != null ? 'archived' : 'solved';
  const overviewKeys = counts?.solver_finished != null ? ['planned', 'solver_finished', 'archived', 'accepted'] :
    ['planned', archiveKey(counts), 'accepted', 'remaining'];
  const updates = new Map(progress.map((entry) => [entry.case_id, entry]));
  const budget = research.budget || {};
  const count = (obj, key) => esc(obj?.[key] ?? '—');
  const stats = (items, keys, plannedLabel = 'planned') => `<div class="plan-stats">${keys.map((key) =>
    `<div><span>${label(key === 'planned' ? plannedLabel : key)}</span><strong>${count(items, key)}</strong></div>`).join('')}</div>`;
  const total = blocks.length ? `<button type="button" class="all-blocks" data-key="block-total" data-cohort="total" aria-pressed="${cohort === 'total'}"><md-ripple></md-ripple>${label('total')} · ${count(research.totals, 'planned')}</button>` : '';
  const matrix = blocks.length ? `<div class="plan-matrix" role="group" aria-label="${label('blocks')}">${blocks.map((block) => {
    const key = block.id;
    const items = blockCounts(block);
    const archive = archiveKey(items);
    const max = items?.planned || 1;
    const portion = (value) => Math.max(0, Math.min(1, (value || 0) / max));
    return `<button type="button" data-key="block-${esc(key)}" data-cohort="${esc(key)}" aria-pressed="${cohort === key}" class="plan-block${block.sealed ? ' sealed' : ''}">
      <md-ripple></md-ripple>
      <span class="plan-block-head"><span>${label(key)}</span>${block.sealed ? `<small>${label('locked')}</small>` : ''}</span>
      <strong>${count(items, archive)}<span> / ${count(items, 'planned')}</span></strong>
      <div class="block-bars">
        <progress class="engineering-progress" value="${portion(items?.[archive])}" aria-label="${label(archive)}"></progress>
        <progress value="${portion(items?.accepted)}" aria-label="${label('accepted')}"></progress>
      </div>
      <span class="plan-block-foot">${label('accepted')} ${count(items, 'accepted')}${items?.pairs != null ? ` · ${count(items, 'pairs')} ${label('pairs')}` : ''}</span>
    </button>`;
  }).join('')}</div>` : '';
  const publicProfiles = (research.profiles || []).filter((item) => !item.sealed && !sealed.has(item.block || item.cohort));
  const publicRadiations = (research.radiations || []).filter((item) => !item.sealed && !sealed.has(item.block || item.cohort));
  const budgetTab = (view.budgetTab === 'profiles' && publicProfiles.length)
    || (view.budgetTab === 'radiations' && publicRadiations.length)
    || (view.budgetTab === 'statistics' && budget.statistics_intent_cases != null) ? view.budgetTab : null;
  const budgetAction = (key) => {
    if (key === 'total_cases' && blocks.length) return { attr: 'cohort', value: 'total' };
    if (key === 'zero_cases' && blocks.some((block) => block.id === 'Z')) return { attr: 'cohort', value: 'Z' };
    if (key === 'profile_count' && publicProfiles.length) return { attr: 'budget-tab', value: 'profiles' };
    if (key === 'radiation_count' && publicRadiations.length) return { attr: 'budget-tab', value: 'radiations' };
    if (key === 'statistics_intent_cases') return { attr: 'budget-tab', value: 'statistics' };
    return null;
  };
  const budgetKeys = [['total_cases', 'planned'], ['zero_cases', 'zeroCases'], ['profile_count', 'profile'],
    ['radiation_count', 'radiation'], ['statistics_intent_cases', 'statisticsIntent']].filter(([key]) => budget[key] != null);
  const snapshotStatus = { connected: 'statisticsSnapshotConnected', not_connected: 'statisticsSnapshotPending' }[research.statistics_snapshot_status] || 'statisticsSnapshotUnknown';
  const diagnostics = Object.entries(research.diagnostics || {});
  return `${heading}${paper}${warning}<md-elevated-card class="m3-card research-panel" data-key="research-panel"><div class="card-body">
    ${budgetKeys.length ? `<div class="budget-chips">${budgetKeys.map(([key, caption]) => {
      const action = budgetAction(key);
      if (!action) return `<span class="budget-chip">${label(caption)} <strong>${count(budget, key)}</strong></span>`;
      const pressed = action.attr === 'cohort' ? !budgetTab && cohort === action.value : budgetTab === action.value;
      return `<button type="button" class="budget-chip is-interactive" data-key="budget-${esc(action.value)}" data-${action.attr}="${esc(action.value)}" aria-pressed="${pressed}"><md-ripple></md-ripple>${label(caption)} <strong>${count(budget, key)}</strong></button>`;
    }).join('')}</div>` : ''}
    ${renderBudgetDetail(research, lang, budgetTab, publicProfiles, publicRadiations, sealed, snapshotStatus)}
    ${matrix}
    <div class="plan-overview">${total}${stats(counts, overviewKeys)}</div>
    ${diagnostics.map(([id, entry]) => {
      const items = entry.counts ?? entry;
      return `<div class="p0-summary"><div class="p0-head"><h3>${label(id === 'P0' ? 'p0' : id)}</h3>${entry.included_in_formal_plan === false ? `<span class="badge neutral">${label('p0Badge')}</span>` : ''}</div>${stats(items, ['planned', archiveKey(items), 'running', 'failed'], 'recorded')}</div>`;
    }).join('')}
    ${activityMarkup}
    <div class="plan-drawers">
      ${renderCases(research, lang, cohort, updates, sealed)}
      ${renderParameters(research, lang, cohort, sealed)}
      ${maintenance}
      <details class="plan-details plan-notes">
        <summary><strong>${label('notesTitle')}</strong></summary>
        <div class="notes-body">
          <p>${[label(snapshotStatus), budget.statistics_intent_cases != null && `${label('statisticsIntent')} ${count(budget, 'statistics_intent_cases')}`,
            budget.manifest_eligible_cases != null && `${label('manifestEligible')} ${count(budget, 'manifest_eligible_cases')}`,
            snapshotStatus === 'statisticsSnapshotConnected' && budget.statistics_eligible_cases != null && `${label('statisticsEligible')} ${count(budget, 'statistics_eligible_cases')}`].filter(Boolean).join(' · ')}</p>
          ${diagnostics.some(([id, entry]) => id === 'P0' && entry.included_in_formal_plan === false) ? `<p>${label('p0Note')}</p>` : ''}
          <p>${label('proof')}</p>
        </div>
      </details>
    </div>
  </div></md-elevated-card>`;
}

function renderBudgetDetail(research, lang, budgetTab, profiles, radiations, sealed, snapshotStatus) {
  if (!budgetTab) return '';
  const label = (key) => esc(text(lang, key));
  const publicCases = (research.cases || []).filter((item) => !item.sealed && !sealedId(item.case_id) && !sealed.has(item.block || item.cohort));
  const header = (title) => `<div class="budget-detail-head"><strong>${title}</strong><button type="button" class="filter-chip" data-budget-tab="close"><md-ripple></md-ripple>${label('closePanel')}</button></div>`;
  if (budgetTab === 'profiles' || budgetTab === 'radiations') {
    const isProfile = budgetTab === 'profiles';
    const items = isProfile ? profiles : radiations;
    const totalCount = research.budget?.[isProfile ? 'profile_count' : 'radiation_count'] ?? items.length;
    const countLabel = items.length < totalCount ? `${items.length} ${label('publicCount')} / ${esc(totalCount)}` : esc(items.length);
    const caseCount = (id) => publicCases.filter((item) => (isProfile ? item.profile_id : (item.radiation_id || item.condition_id)) === id).length;
    return `<div class="budget-detail" data-key="budget-detail-${budgetTab}">${header(`${label(isProfile ? 'profile' : 'radiation')} · ${countLabel}`)}
      <div class="case-grid">${items.map((item) => `<article class="case-row">
        <div><strong>${esc(item.id)}</strong>${publicCases.length ? `<small>${caseCount(item.id)} ${label('publicCases')}</small>` : ''}</div>
        <div class="parameter-line">${parameterMarkup(item.parameters, lang)}</div>
      </article>`).join('')}</div></div>`;
  }
  const budget = research.budget || {};
  const publicStatCount = publicCases.filter((item) => item.statistics_intent).length;
  const eligibleDisplay = snapshotStatus === 'statisticsSnapshotConnected' && budget.statistics_eligible_cases != null
    ? esc(budget.statistics_eligible_cases) : label('unknown');
  return `<div class="budget-detail" data-key="budget-detail-statistics">${header(`${label('statisticsIntent')} · ${esc(budget.statistics_intent_cases ?? '—')}`)}
    <div class="plan-stats">
      <div><span>${label('statisticsIntent')}</span><strong>${esc(budget.statistics_intent_cases ?? '—')}</strong></div>
      <div><span>${label('statisticsPublicCount')}</span><strong>${esc(publicStatCount)}</strong></div>
      <div><span>${label('manifestEligible')}</span><strong>${esc(budget.manifest_eligible_cases ?? '—')}</strong></div>
      <div><span>${label('statisticsEligible')}</span><strong>${eligibleDisplay}</strong></div>
    </div>
    <p class="budget-detail-note">${label(snapshotStatus)} · ${label('statisticsScopeHint')}</p>
  </div>`;
}

function renderParameters(research, lang, cohort, sealed) {
  if (sealed.has(cohort)) return '';
  const entries = [...(research.profiles || []), ...(research.radiations || []),
    ...(research.conditions || []).filter((item) => cohort === 'total' || (item.block || item.cohort) === cohort)]
    .filter((item) => !item.sealed && !sealed.has(item.block || item.cohort));
  if (!entries.length) return '';
  return `<details class="plan-details" id="plan-parameters"><summary><strong>${esc(text(lang, 'parameters'))}</strong>
    <span>${esc(text(lang, 'relative'))}</span></summary>
    <div class="case-grid">${entries.map((item) => `<article class="case-row"><strong>${esc(item.id)}</strong>
      <div class="parameter-line">${parameterMarkup(item.parameters, lang)}</div></article>`).join('')}</div></details>`;
}

const activityTones = {
  solved: 'good', archived: 'good', accepted: 'good',
  solver_finished: 'warn', missing_data: 'warn', missing_zero_control: 'warn', under_review: 'warn', slot_isolated: 'warn',
  running: 'good', healthy: 'good', completed: 'good', verified_success: 'good',
  fine_step: 'warn', slow_convergence: 'warn', collecting: 'warn', uncollected: 'warn', awaiting_collection: 'warn', collection_overdue: 'warn',
  failed: 'bad', stalled: 'bad', verified_failure: 'bad', verified_interrupted: 'warn',
};
const activityBadge = (lang, key) => typeof key === 'string' && Object.hasOwn(words.en, key)
  ? `<span class="badge ${Object.hasOwn(activityTones, key) ? activityTones[key] : 'neutral'}">${esc(text(lang, key))}</span>` : '';
export const executionResult = (value) => ['solver_finished', 'failed', 'missing_data', 'under_review'].includes(value) ? value : null;

function activityTime(seconds) {
  if (!Number.isFinite(seconds)) return '';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor(seconds / 60) % 60;
  return hours ? `${hours}h ${minutes}m` : minutes ? `${minutes}m ${Math.floor(seconds) % 60}s` : `${Math.floor(seconds)}s`;
}

function renderActivity(activity, lang, sealed) {
  if (!activity) return '';
  const label = (key) => esc(text(lang, key));
  const privateTask = (item) => item.sealed || item.kind === 'sealed' || sealedId(item.case_id) || sealed.has(item.block || item.cohort);
  const hiddenTask = (item) => privateTask(item) || item.kind === 'unmatched';
  const name = (item) => privateTask(item) ? text(lang, 'sealedTask') : item.kind === 'unmatched'
    ? text(lang, 'unmatchedTask') : item.label || item.case_id || item.device || text(lang, 'unknown');
  const live = (activity.live_items || []).slice(0, 8).map((item, index) => {
    const hidden = hiddenTask(item);
    const result = (!hidden && executionResult(item.execution_result)) || item.state;
    const key = hidden ? `anonymous-${index}` : item.id || index;
    const progress = item.progress || {};
    const genericCurrent = item.progress_current ?? progress.current;
    const current = genericCurrent ?? item.simulation_time_ns ?? progress.simulation_time_ns;
    const target = item.progress_target ?? progress.target ?? item.goal_time_ns ?? progress.goal_time_ns;
    const unit = item.progress_unit ?? progress.unit ?? (genericCurrent == null ? 'ns' : '');
    const value = (number) => Number.isFinite(number) ? Number(number.toFixed(6)) : '—';
    const stage = item.stage_label || progress.stage_label || '';
    const reading = Number.isFinite(current) || Number.isFinite(target) ? `${value(current)} / ${value(target)} ${unit}`.trim() : '';
    const detail = lang === 'zh' ? item.health_detail_zh || item.health_detail_en : item.health_detail_en || item.health_detail_zh;
    const cpu = item.cpu_set?.length ? `CPU ${item.cpu_set.join(', ')}` : '';
    const engine = item.engine || progress.engine || item.processes?.find((process) => process.engine !== 'post')?.engine;
    const batch = lang === 'zh' ? item.batch_label || item.batch_label_en : item.batch_label_en || item.batch_label;
    const logAge = relativeTime(lang, item.log_age_seconds);
    const timing = [activityTime(item.elapsed_seconds), logAge && `${text(lang, 'log')} ${logAge}`].filter(Boolean);
    return `<article class="case-row" data-key="current-${esc(key)}">
      <div><strong>${esc(name(item))}</strong><span>${activityBadge(lang, result)}${!hidden && item.health !== result ? activityBadge(lang, item.health) : ''}</span></div>
      ${hidden ? '' : `${batch || engine || cpu ? `<p>${[batch, engine, cpu].filter(Boolean).map(esc).join(' · ')}</p>` : ''}
      ${reading || stage ? `<p>${[stage, reading].filter(Boolean).map(esc).join(' · ')}</p>` : ''}
      ${timing.length ? `<small>${timing.map(esc).join(' · ')}</small>` : ''}${detail ? `<small>${esc(detail)}</small>` : ''}`}
    </article>`;
  });
  const outcomes = (activity.recent_outcomes || []).filter((item) => !hiddenTask(item)).slice(0, 8).map((item, index) => {
    const result = executionResult(item.execution_result);
    const archive = result && ['verified_failure', 'verified_interrupted'].includes(item.collection_result);
    const elapsed = activityTime(item.elapsed_seconds);
    return `<article class="case-row" data-key="outcome-${esc(item.id || index)}">
      <div><strong>${esc(name(item))}</strong><span>${activityBadge(lang, result || item.collection_result || item.state)}${archive ? activityBadge(lang, item.collection_result) : ''}</span></div>
      <small>${esc(elapsed ? `${elapsed} · ` : '')}${esc(date(lang, item.finished_at))}</small>
    </article>`;
  });
  return `<div class="research-updates activity-feed"><h3>${label('currentActivity')}</h3>
    ${activity.mode === 'stale' ? `<p class="empty">${label('activityStale')}</p>` : ''}
    ${live.length ? `<div class="update-grid">${live.join('')}</div>` : activity.mode === 'stale' ? '' : `<p class="empty">${label('idle')}</p>`}
    <h3>${label('recentOutcomes')}</h3>
    ${outcomes.length ? `<div class="update-grid">${outcomes.join('')}</div>` : `<p class="empty">${label('noOutcomes')}</p>`}</div>`;
}

function renderUpdates(entries, lang) {
  const recent = [...entries].sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || '')).slice(0, 12);
  if (!recent.length) return '';
  return `<details class="plan-details" id="maintenance-notes"><summary><strong>${esc(text(lang, 'maintenanceNotes'))}</strong></summary>
    <div class="update-grid">${recent.map((entry) => progressCard(entry, lang)).join('')}</div></details>`;
}

export function bindResearch(root, render) {
  root.addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.dataset.cohort) {
      view.cohort = button.dataset.cohort;
      view.budgetTab = null;
    } else if (button.dataset.budgetTab) {
      const next = button.dataset.budgetTab;
      view.budgetTab = next === 'close' || view.budgetTab === next ? null : next;
    } else if (button.dataset.caseFilter) view.filter = button.dataset.caseFilter;
    else if (button.id !== 'moreCases') return;
    view.limit = button.id === 'moreCases' ? view.limit + 24 : 12;
    render();
  });
  root.addEventListener('input', (event) => {
    if (event.target.id !== 'case-search') return;
    view.query = event.target.value;
    view.limit = 12;
    render();
  });
}
