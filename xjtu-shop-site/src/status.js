import '@material/web/labs/card/elevated-card.js';
import '@material/web/labs/card/outlined-card.js';
import '@material/web/button/filled-tonal-button.js';
import '@material/web/iconbutton/icon-button.js';
import '@material/web/ripple/ripple.js';
import './status-dashboard.css';
import { escapeHtml as esc, renderWhr, renderSparkline, renderTrends, bindTrendTooltips } from './components/telemetry-charts.js';
import { renderResearch, bindResearch, parameterMarkup, sealedId } from './research-dashboard.js';

const app = document.getElementById('app');
const state = {
  lang: 'zh', window: '24h', runFilter: 'all', selectedTask: null,
  activeSection: 'overview', navDrawerOpen: false,
  live: null, full: null, fullHash: null, lastFullRequest: -Infinity,
  liveMode: 'loading', fullFailed: false, refreshing: false,
  taskMetrics: new Map(),
};
try { if (localStorage.getItem('xjtu-lang') === 'en') state.lang = 'en'; } catch {}

const labels = {
  running: ['运行中', 'Running'], collecting: ['待收集', 'Collecting'],
  completed: ['已完成', 'Completed'], failed: ['异常', 'Failed'],
  pending: ['待运行', 'Pending'], idle: ['空闲', 'Idle'], unknown: ['待观测', 'Unknown'],
  healthy: ['正常推进', 'Advancing'], fine_step: ['微步收敛', 'Fine steps'], stalled: ['停滞预警', 'Stalled'],
  operational: ['在线', 'Online'], maintenance: ['维护暂停', 'Maintenance pause'],
  offline: ['离线', 'Offline'], degraded: ['降级', 'Degraded'],
  ready: ['就绪', 'Ready'], fresh: ['最新', 'Fresh'], stale: ['过期', 'Stale'],
  cached_stale: ['缓存待更新', 'Cached snapshot'], unavailable: ['暂不可用', 'Unavailable'],
  progressing: ['正常推进', 'Progressing'], active: ['运行中', 'Active'],
  paused: ['维护暂停', 'Maintenance pause'], delayed: ['更新延迟', 'Delayed'],
  slow_convergence: ['慢收敛', 'Slow convergence'], uncollected: ['已退出待收集', 'Exited, pending collection'],
  collection_overdue: ['收集超时', 'Collection overdue'],
  probe_error: ['探针异常', 'Probe error'], probe_failed: ['探针异常', 'Probe error'],
  awaiting_collection: ['待收集', 'Collecting'], verified_success: ['已核验', 'Verified'],
  verified_failure: ['核验失败', 'Failed'], verified_interrupted: ['已中断', 'Interrupted'],
  dc_init: ['直流初始化', 'DC init'], transient: ['瞬态求解', 'Transient'],
  mesh: ['网格生成', 'Meshing'], post: ['后处理', 'Post-processing'],
  setup: ['准备', 'Setup'], process: ['工艺仿真', 'Process simulation'],
  transport: ['粒子输运', 'Particle transport'], events: ['粒子输运', 'Particle transport'],
  run: ['运行', 'Running'], complete: ['完成', 'Complete'],
  sealed: ['封存留出任务', 'Sealed holdout'], unmatched: ['未关联任务', 'Unmatched task'],
};
const tone = {
  healthy: 'good', running: 'good', operational: 'good', completed: 'good', ready: 'good', fresh: 'good', progressing: 'good', active: 'good',
  collecting: 'warn', fine_step: 'warn', maintenance: 'warn', degraded: 'warn', pending: 'warn',
  cached_stale: 'warn', stale: 'warn', probe_error: 'warn', probe_failed: 'warn',
  paused: 'warn', delayed: 'warn', slow_convergence: 'warn', uncollected: 'warn', awaiting_collection: 'warn', collection_overdue: 'warn',
  stalled: 'bad', failed: 'bad', offline: 'bad', unavailable: 'bad',
};
const b = (zh, en) => state.lang === 'zh' ? zh : en;
const label = (key) => b(...(labels[key] || labels.unknown));
const localized = (zh, en) => b(zh || en, en || zh);
const finite = Number.isFinite;
const number = (value, digits = 0) => finite(value) ? Number(value.toFixed(digits)).toString() : '—';
const unit = (value, suffix, digits = 0) => finite(value) ? number(value, digits) + suffix : '—';
const gib = (bytes, digits = 1) => number(finite(bytes) ? bytes / 1024 ** 3 : null, digits);
const date = (time) => finite(Date.parse(time))
  ? new Intl.DateTimeFormat(b('zh-CN', 'en-US'), { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(time)) : '—';
const sampleThreshold = (payload) => payload?.health?.freshness?.scheduler_threshold_seconds ?? 180;
function validSample(value, thresholdSeconds = 180) {
  const elapsed = Date.now() - Date.parse(value);
  return elapsed >= -60_000 && elapsed <= thresholdSeconds * 1000;
}
const redacted = (task) => ['sealed', 'unmatched'].includes(task.kind) || sealedId(task.case_id);
const category = (task) => sealedId(task.case_id) ? 'sealed' : task.kind;

function duration(seconds) {
  if (!finite(seconds) || seconds < 0) return '—';
  const value = Math.floor(seconds);
  return `${Math.floor(value / 3600)}h ${Math.floor(value / 60) % 60}m ${value % 60}s`;
}

function pill(key, caption = label(key)) {
  return `<span class="badge ${tone[key] || 'neutral'}"><i aria-hidden="true"></i>${esc(caption)}</span>`;
}

function meter(value, total, title) {
  if (!finite(value) || !finite(total) || total <= 0) return '<div class="meter-empty" aria-hidden="true"></div>';
  return `<progress aria-label="${esc(title)}" value="${Math.max(0, Math.min(value, total))}" max="${total}"></progress>`;
}

function cpuName(cpus) {
  return Array.isArray(cpus) && cpus.length ? `CPU ${cpus.join(', ')}` : b('CPU 待观测', 'CPU unknown');
}

function taskName(task) {
  if (redacted(task)) return label(category(task));
  const name = task.label || task.case_id || task.id;
  if (state.lang === 'zh') return name;
  return (name || '').replace('P0 无粒子基线', 'P0 particle-free baseline').replace('无粒子基线', 'Particle-free baseline')
    .replace('性能对照', 'Performance comparison').replace('P0 诊断', 'P0 diagnostics')
    .replace('研究仿真', 'Research simulation').replace(/写 ([01])/g, 'Write $1');
}

function schedulerFor(simulation, threshold) {
  const source = simulation.scheduler || simulation.benchmark || {};
  const vm = source.virtual_machine || {};
  const observedAt = source.observed_at || vm.observed_at;
  const hasObservation = Boolean(observedAt);
  const stale = source.observation_stale === true || !validSample(observedAt, threshold);
  const observedSlots = source.slots || [];
  const declaredCount = source.slot_count ?? vm.cpu?.cores ?? observedSlots.length;
  const count = source.reserved_cpus ? declaredCount : Math.max(declaredCount, vm.cpu?.cores ?? 0, observedSlots.length);
  const tasks = source.tasks || (source.id ? [source] : []);
  const slotsByCpu = new Map(observedSlots.map((slot, index) => [slot.cpu ?? slot.index ?? index, slot]));
  const slots = Array.from({ length: count }, (_, cpu) => {
    const slot = slotsByCpu.get(cpu);
    return {
      cpu, state: stale ? 'unknown' : slot?.state || 'unknown', cluster: stale ? null : slot?.cluster,
      owners: stale ? [] : slot?.task_ids ?? (slot?.task_id ? [slot.task_id] : []),
      usage: slot?.usage_percent ?? vm.cpu?.per_core_percent?.[`cpu${cpu}`],
    };
  });
  // Earlier snapshots used slot_count for the compute pool and exposed all cores via the VM sample.
  const reserved_cpus = source.reserved_cpus ?? slots.slice(declaredCount).map((slot) => slot.cpu);
  return { ...source, vm, observedAt, hasObservation, stale, tasks, slots, count, reserved_cpus };
}

function progressReading(progress) {
  return {
    current: progress?.current ?? progress?.simulation_time_ns,
    target: progress?.target ?? progress?.goal_time_ns,
    unit: progress?.unit ?? (progress?.current == null ? 'ns' : ''),
  };
}

function topology(scheduler) {
  const widths = scheduler.layout_widths;
  if (!scheduler.stale && widths?.length) {
    const groups = new Map();
    for (const width of widths) groups.set(width, (groups.get(width) || 0) + 1);
    return [...groups].sort(([a], [c]) => a - c).map(([width, count]) => `${count}×${width}`).join('+');
  }
  return localized(scheduler.label, scheduler.label_en) || label('unknown');
}

function licensesFor(scheduler, batch) {
  const health = scheduler.vm.daemon_health ?? batch.daemon_health;
  return ['lmgrd', 'snpslmd'].map((name) => {
    const alive = scheduler.stale ? null : health?.[name]?.alive;
    return [name, alive === true ? 'operational' : alive === false ? 'offline' : 'unknown',
      alive === true ? health[name].elapsed_seconds : null];
  });
}

const serviceNames = {
  'research-site': ['研究展示站', 'Research site'],
  'tcad-controller': ['TCAD 调度器', 'TCAD scheduler'],
  'simulation-runtime': ['仿真虚拟机', 'Simulation VM'],
};
const licenseService = (service) => ['lmgrd', 'snpslmd'].includes(service.id) || service.id?.startsWith('license-') || ['daemon', 'license'].includes(service.kind);

function servicesFor(payload, scheduler, batch) {
  if (Array.isArray(payload.health?.services?.items)) return payload.health.services.items;
  const services = Object.keys(serviceNames).map((id) => {
    const service = payload.services?.find((item) => item.id === id);
    const paused = id === 'tcad-controller' && (batch.pause?.active === true || service?.state === 'maintenance' ||
      (!payload.simulation?.active_batch && (scheduler.controller?.dispatch_paused === true ||
        payload.simulation?.controller_mode === 'maintenance')));
    return { ...service, id, state: paused ? 'maintenance' : service?.state || 'unknown',
      detail: paused ? localized(batch.pause?.reason_zh, batch.pause?.reason_en) : service?.detail };
  });
  return services.concat(licensesFor(scheduler, batch).map(([id, state, elapsed_seconds]) => ({ id, state, elapsed_seconds, kind: 'license' })));
}

function serviceName(service) {
  const names = serviceNames[service.id] || {
    web: serviceNames['research-site'], controller: serviceNames['tcad-controller'], vm: serviceNames['simulation-runtime'],
  }[service.kind];
  return names ? b(...names) : service.id?.replace(/^license-/, '') || service.kind;
}

function serviceDetail(service) {
  const detail = typeof service.detail === 'string' ? service.detail : localized(service.detail?.zh, service.detail?.en);
  return detail || (finite(service.elapsed_seconds) ? `${licenseService(service) ? b('许可进程', 'License') : b('运行时长', 'Uptime')} · ${duration(service.elapsed_seconds)}` : '');
}

function renderHealth(payload, scheduler, batch, research, services) {
  const health = payload.health || {};
  const freshness = health.freshness || {};
  const simulation = health.simulation || {};
  const projection = freshness.research_projection_state ?? research?.projection_state ??
    (research?.available ? (research.observation_stale ? 'stale' : 'fresh') : 'unavailable');
  const states = services.filter((service) => !licenseService(service)).map((service) => service.state);
  const fallbackServiceState = states.every((state) => state === 'operational') ? 'operational'
    : states.every((state) => state === 'offline') ? 'offline'
    : states.some((state) => ['offline', 'degraded'].includes(state)) ? 'degraded'
    : states.includes('maintenance') ? 'maintenance' : 'unknown';
  const serviceState = health.services?.state ?? payload.overall ?? (states.length ? fallbackServiceState : 'unknown');
  const schedulerAge = freshness.scheduler_age_seconds ?? age(scheduler.observedAt);
  const freshnessState = freshness.state ?? (scheduler.stale ? (scheduler.hasObservation ? 'stale' : 'unknown') : 'fresh');
  const running = scheduler.tasks.filter((task) => task.state === 'running');
  const observed = !scheduler.stale;
  const legacy = !scheduler.hasObservation && payload.simulation?.observed && !payload.simulation.observation_stale ? payload.simulation : null;
  const active = simulation.active_tasks ?? (observed ? scheduler.active_groups ?? running.length : legacy?.running_groups);
  const stalled = simulation.stalled_tasks ?? (observed ? running.filter((task) => task.health === 'stalled').length : null);
  const fine = simulation.fine_step_tasks ?? (observed ? running.filter((task) => ['fine_step', 'slow_convergence'].includes(task.health)).length : null);
  const uncollected = simulation.uncollected_tasks ?? (observed ? batch.collecting ?? scheduler.tasks.filter((task) => ['collecting', 'uncollected'].includes(task.state)).length : null);
  const paused = batch.pause?.active || serviceState === 'maintenance' || services.some((service) => service.state === 'maintenance');
  const simulationState = simulation.state ?? (paused ? 'paused' : !observed && !legacy ? 'unknown' : stalled ? 'stalled' : fine ? 'fine_step' : active ? 'healthy' : uncollected ? 'collecting' : 'idle');
  const findings = [
    [b('服务就绪', 'Services'), serviceState, services.map((service) => `${serviceName(service)} · ${label(service.state)}`)],
    [b('数据新鲜', 'Data freshness'), freshnessState, [
      `${b('调度采样', 'Scheduler sample')} ${unit(schedulerAge, ' s')} / ${sampleThreshold(payload)} s`,
      ...(typeof freshness.scheduler_probe_ok === 'boolean' ? [b('调度探针', 'Scheduler probe') + ' · ' + label(freshness.scheduler_probe_ok ? 'operational' : 'probe_error')] : []),
      `${b('科研投影', 'Research projection')} · ${label(projection)}${finite(freshness.research_age_seconds) ? ` · ${unit(freshness.research_age_seconds, ' s')}` : ''}`,
    ]],
    [b('仿真推进', 'Simulation'), simulationState, [
      localized(simulation.summary_zh, simulation.summary_en),
      `${label('running')} ${number(active)} · ${label('stalled')} ${number(stalled)}`,
      `${label('fine_step')} ${number(fine)} · ${label('collecting')} ${number(uncollected)}`,
    ]],
  ];
  const warnings = [
    paused && (localized(batch.pause?.reason_zh, batch.pause?.reason_en) || label('maintenance')),
    (freshness.scheduler_probe_ok === false || ['probe_error', 'probe_failed'].includes(freshnessState)) && b('调度探针异常', 'Scheduler probe error'),
    projection === 'cached_stale' && b('科研投影待更新（展示上一份成功快照）', 'Research projection awaiting update (last successful snapshot shown)'),
  ].filter(Boolean);
  return `<div class="overview-health"><div class="health-chips">${findings.map(([name, key, details], i) => `<details class="health-chip" data-key="health-${i}">
    <summary title="${esc(details.join(' · '))}">${pill(key, `${name} · ${label(key)}`)}</summary>
    <ul>${details.filter(Boolean).map((detail) => `<li>${esc(detail)}</li>`).join('')}</ul>
  </details>`).join('')}</div>${warnings.length ? `<p class="health-alert">${warnings.map(esc).join(' · ')}</p>` : ''}</div>`;
}

function resourceRow(title, resource, alert = false, hint = '') {
  const { available_bytes: available, total_bytes: total } = resource || {};
  return `<div class="resource-row${alert ? ' low-space' : ''}"${hint ? ` title="${esc(hint)}"` : ''}>
    <span class="resource-label">${title}</span>
    <strong>${gib(available)}<span> / ${gib(total)} GiB</span>${alert ? ` <small>${b('警戒', 'Low')}</small>` : ''}</strong>
    ${meter(available, total, title)}
  </div>`;
}

function renderKpis(payload, scheduler, batch, research, services) {
  const vm = scheduler.vm;
  const system = payload.system || {};
  const totals = research?.totals;
  const runningGroups = scheduler.stale ? null : scheduler.active_groups ?? scheduler.tasks.filter((task) => task.state === 'running').length;
  const bound = scheduler.stale ? null : scheduler.active_slots;
  const root = system.storage?.server_root;
  const swap = vm.swap || {};
  const swapUsed = swap.used_bytes ?? (finite(swap.total_bytes) && finite(swap.available_bytes) ? swap.total_bytes - swap.available_bytes : null);
  const belowThreshold = root?.low_space === true || (finite(root?.available_bytes) &&
    root.available_bytes < (root.warning_below_bytes ?? 20 * 1024 ** 3));
  const plan = (key) => number(totals?.[key]);
  const independentTip = b('各层资源独立采样，余量不可相加', 'Each layer is sampled independently and cannot be summed');
  return `<md-elevated-card class="m3-card"><article class="panel kpi">
    <div class="kpi-head"><h2>${b('活动求解器', 'Active solvers')}</h2><span class="topology-badge">${esc(topology(scheduler))}</span></div>
    <div class="kpi-lead"><strong>${number(runningGroups)}</strong><span>${b('项运行中', 'running')}</span></div>
    <div class="kpi-meta">
      <span>${b('占用核心', 'Cores')} <b>${number(bound)} / ${number(scheduler.count || null)}</b></span>
      <span>${b('服务器 CPU / Load 1m', 'Server CPU / Load 1m')} <b>${unit(system.cpu?.usage_percent, '%', 1)} / ${number(system.cpu?.load_1m, 2)}</b></span>
      <span>${b('虚拟机 CPU', 'VM CPU')} <b>${unit(vm.cpu?.usage_percent, '%', 1)}</b></span>
      <span>${b('虚拟机 Load 1m / 5m / 15m', 'VM Load 1m / 5m / 15m')} <b>${['load_1m', 'load_5m', 'load_15m'].map((key) => number(vm.cpu?.[key], 2)).join(' / ')}</b></span>
      <span>${b('求解进程', 'Solvers')} <b>${number(scheduler.stale ? null : scheduler.active_solvers)}</b></span>
    </div>
    <div class="license-line">${services.filter(licenseService).map((service) => pill(service.state, serviceName(service))).join('')}</div>
  </article></md-elevated-card>
  <md-elevated-card class="m3-card"><article class="panel kpi">
    <div class="kpi-head"><h2>${b('仿真吞吐', 'Throughput')}</h2>${research?.revision ? `<span class="kpi-tag">${esc(research.revision)}</span>` : ''}</div>
    <div class="kpi-lead"><strong>${number(batch.collected)}<small> / ${number(batch.total)}</small></strong><span>${b('本批已收集', 'collected')}</span></div>
    ${meter(batch.collected, batch.total, b('本批已收集', 'Batch collected'))}
    <div class="kpi-meta">
      <span title="${b('工程完成 / 科学验收 / 计划', 'Engineering / Science / Planned')}">${b('正式进度', 'Formal plan')} <b>${plan('solved')} / ${plan('accepted')} / ${plan('planned')}</b></span>
      <span class="kpi-sub">${b('工程完成 / 科学验收 / 计划', 'Engineering / Science / Planned')}</span>
      <span>${b('近 24h 完成', '24h verified')} <b>${number(batch.completed_24h)}</b></span>
    </div>
  </article></md-elevated-card>
  <md-elevated-card class="m3-card"><article class="panel kpi">
    <div class="kpi-head"><h2>${b('双层内存', 'Memory')}</h2><span class="kpi-tag" title="${esc(independentTip)}">${b('独立计量', 'Independent')}</span></div>
    <div class="resource-stack">
      ${resourceRow(b('服务器可用内存', 'Server available'), system.memory)}
      ${resourceRow(b('虚拟机可用 / 分配内存', 'VM available / allocated'), vm.memory)}
      <div class="kpi-meta"><span>${b('虚拟机 Swap 已用 / 分配', 'VM swap used / allocated')} <b>${gib(swapUsed)} / ${gib(swap.total_bytes)} GiB</b></span></div>
    </div>
  </article></md-elevated-card>
  <md-elevated-card class="m3-card"><article class="panel kpi">
    <div class="kpi-head"><h2>${b('三层存储', 'Storage')}</h2><span class="kpi-tag" title="${esc(independentTip)}">${b('独立计量', 'Independent')}</span></div>
    <div class="resource-stack">
      ${resourceRow(b('服务器剩余空间', 'Server remaining'), root, belowThreshold)}
      ${resourceRow(b('虚拟机磁盘可增长空间', 'VM disk growth'), system.storage?.vm_disk_growth, false, b('服务器上虚拟机磁盘文件可增长空间', 'VM disk file growth space on server'))}
      ${resourceRow(b('虚拟机剩余 / 分配空间', 'VM remaining / allocated'), vm.storage, false, b('虚拟机剩余空间 / 虚拟机分配空间（逻辑容量）', 'VM remaining / allocated logical capacity'))}
    </div>
  </article></md-elevated-card>`;
}

function renderSlots(scheduler) {
  const byId = new Map(scheduler.tasks.map((task) => [task.id, task]));
  const reserved = new Set(scheduler.reserved_cpus || []);
  const background = scheduler.slots.filter((slot) => reserved.has(slot.cpu));
  const compute = scheduler.slots.filter((slot) => !reserved.has(slot.cpu));
  const range = (slots) => {
    const groups = [];
    for (const { cpu } of slots) {
      const previous = groups.at(-1);
      if (previous && previous[1] + 1 === cpu) previous[1] = cpu;
      else groups.push([cpu, cpu]);
    }
    return `CPU ${groups.map(([start, end]) => start === end ? start : `${start}–${end}`).join(', ')}`;
  };
  const cell = (slot) => {
    const task = byId.get(slot.owners[0]);
    const health = slot.owners.length > 1 ? 'running' : task?.health || slot.state;
    const name = slot.owners.length > 1 ? b('多任务共享', 'Shared') :
      task ? redacted(task) ? label(category(task)) : task.case_id || task.device || taskName(task) : label(slot.state);
    const { current, target } = progressReading(task && !redacted(task) && slot.owners.length === 1 ? task.progress : undefined);
    const selected = slot.owners.includes(state.selectedTask);
    const tag = task ? 'button' : 'div';
    return `<${tag} class="cpu-cell ${tone[health] || 'neutral'}${selected ? ' selected' : ''}${task ? ' interactive' : ''}"
        data-key="cpu-${slot.cpu}" ${task ? `type="button" data-slot-task="${esc(task.id)}" aria-pressed="${selected}"` : ''}>
      ${task ? '<md-ripple></md-ripple>' : ''}
      <span class="cpu-head"><span>CPU ${slot.cpu}</span><i aria-hidden="true"></i></span>
      <strong>${unit(slot.usage, '%', 1)}</strong>
      <span class="cpu-task" title="${esc(name)}">${esc(name)}</span>
      ${meter(current, target, b('任务进度', 'Task progress'))}
    </${tag}>`;
  };
  if (!scheduler.slots.length) return `<p class="empty">${b('等待虚拟机核心观测', 'Awaiting VM core samples')}</p>`;
  const groups = [];
  for (const slot of compute) {
    const previous = groups.at(-1);
    const last = previous?.at(-1);
    if (slot.cluster && slot.cluster === last?.cluster && slot.cpu === last.cpu + 1) previous.push(slot);
    else groups.push([slot]);
  }
  return `<div class="cpu-layout">${compute.length ? `<div><p class="matrix-caption">${b('计算核心', 'Compute')} · ${range(compute)}</p>
    <div class="compute-cores" style="--compute-columns:${Math.min(compute.length, 10)}">${groups.map((group) => {
      if (group.length === 1) return cell(group[0]);
      const width = group.length;
      const health = byId.get(group[0].owners[0])?.health || group[0].state;
      return `<div class="cpu-cluster ${tone[health] || 'neutral'}" data-key="cluster-${group[0].cpu}"
        style="--wide-span:${Math.min(width, 10)};--narrow-span:${Math.min(width, 5)}">${group.map(cell).join('')}</div>`;
    }).join('')}</div></div>` : ''}
    ${background.length ? `<div class="background-core"><p class="matrix-caption" title="${range(background)}">${b('后台余量', 'Reserve')}</p><div class="reserve-cores">${background.map(cell).join('')}</div></div>` : ''}
  </div>`;
}

const commonParameters = ['profile', 'stored_bit', 'temperature_K', 'node_count', 'integrator'];

function taskParameters(task) {
  const data = { ...task.parameters };
  if (!Object.hasOwn(data, 'profile') && task.device != null) data.profile = task.device;
  if (!Object.hasOwn(data, 'stored_bit') && task.stored_bit != null) data.stored_bit = task.stored_bit;
  return [Object.fromEntries(commonParameters.filter((key) => Object.hasOwn(data, key)).map((key) => [key, data[key]])),
    Object.fromEntries(Object.entries(data).filter(([key]) => !commonParameters.includes(key)))];
}

function stepSize(step) {
  if (!finite(step)) return '—';
  if (step >= 1e-9) return `${number(step * 1e9, 3)} ns`;
  if (step >= 1e-12) return `${number(step * 1e12, 3)} ps`;
  return `${number(step * 1e15, 3)} fs`;
}

const healthReasons = {
  log_silent_low_cpu: ['日志停更，求解进程 CPU 使用率低', 'Log updates stopped and solver CPU usage is low'],
  log_silent_high_cpu: ['日志已超过允许静默时间', 'The solver log exceeded its quiet window'],
  sim_time_frozen_30m: ['仿真时间连续 30 分钟未推进', 'Simulation time has not advanced for 30 minutes'],
  stepsize_below_1ps: ['求解步长小于 1 皮秒', 'Step size below 1 picosecond'],
  slow_step_over_30s: ['最近一次求解步超过 30 秒', 'The last confirmed step took over 30 seconds'],
  collection_overdue: ['求解已退出，超过收集宽限时间', 'The solver exited and the collection grace period elapsed'],
};

function taskHealthDetail(task) {
  const reason = task.health_reason;
  return localized(task.health_detail_zh, task.health_detail_en) || (reason ?
    (healthReasons[reason] ? b(...healthReasons[reason]) : labels[reason] ? label(reason) : reason.replaceAll('_', ' ')) : '');
}

function renderProcesses(processes) {
  if (!processes?.length) return '';
  return `<details class="task-details" data-key="task-processes"><summary>${b('子进程明细', 'Child processes')} (${processes.length})</summary>
    <div class="process-list">${processes.map((process) => `<div class="process-row">
      <strong>${esc(process.engine || '—')}</strong><span>${esc(cpuName(process.cpu_set))}</span>
      <span>CPU ${unit(process.cpu_percent, '%', 1)}</span><span>RSS ${unit(finite(process.rss_bytes) ? process.rss_bytes / 1024 ** 3 : null, ' GiB', 2)}</span>
      <span>${number(process.threads)} ${b('线程', 'threads')}</span></div>`).join('')}</div></details>`;
}

function taskCard(task, scheduler, history) {
  const selected = state.selectedTask === task.id;
  const taskState = scheduler.stale ? 'unknown' : task.state;
  const tags = [`<span class="badge neutral">${esc(cpuName(task.cpu_set))}</span>`, pill(scheduler.stale ? 'unknown' : task.health || taskState)];
  const id = esc(task.id);
  const clearBtn = selected ? `<button type="button" class="clear-selection" data-clear-selection="1" title="${b('取消选中 (Esc)', 'Clear selection (Esc)')}">${b('取消聚焦', 'Unfocus')} ×</button>` : '';
  const title = `<h3 tabindex="-1">${esc(taskName(task))}</h3>`;
  if (redacted(task)) return `<md-elevated-card class="m3-card task-card-shell${selected ? ' selected' : ''}" data-key="task-${id}" data-task="${id}"><article class="panel task-card anonymous${selected ? ' selected' : ''}"><div class="task-heading"><div>${title}<div class="tag-line">${tags.join('')}</div></div>${clearBtn}</div></article></md-elevated-card>`;
  const batch = localized(task.batch_label, task.batch_label_en);
  if (batch) tags.unshift(`<span class="badge accent">${esc(batch)}</span>`);
  const progress = task.progress || {};
  const reading = progressReading(progress);
  const phase = progress.stage || progress.phase;
  const stage = state.lang === 'zh' && labels[phase] ? label(phase) : progress.stage_label || (phase ? label(phase) : '');
  const whr = !progress.mode || progress.mode === 'whr' ? renderWhr(progress, state.lang) : '';
  const taskProgress = whr || (finite(reading.current) || finite(reading.target) ? `<div class="task-progress">
    <p>${esc(stage || b('任务进度', 'Task progress'))} · <strong>${number(reading.current, 6)} / ${number(reading.target, 6)} ${esc(reading.unit)}</strong></p>
    ${meter(reading.current, reading.target, b('任务进度', 'Task progress'))}</div>` : '');
  const reason = taskHealthDetail(task);
  const { simulation_time_ns: current, goal_time_ns: goal, rate_ns_per_hour: rate } = progress;
  const rateAvailable = !scheduler.stale && finite(rate);
  const eta = rateAvailable && rate > 0 && task.health === 'healthy' && finite(current) && goal > current
    ? (goal - current) / rate : null;
  const rateNote = eta != null ? `${b('约剩', 'ETA')} ${number(eta, 1)} h`
    : !scheduler.stale && task.health === 'fine_step'
      ? b('微步瞬态', 'Fine-step transient')
      : b('速率采样中', 'Sampling rate');
  const rateTip = eta != null ? '' : b('当前步长收缩或样本不足，暂不外推剩余时间', 'Reduced steps or insufficient samples; ETA withheld');
  const observed = scheduler.observedAt || '';
  const runtime = duration(task.elapsed_seconds);
  const running = taskState === 'running';
  const [keyParameters, otherParameters] = taskParameters(task);
  const details = parameterMarkup(otherParameters, state.lang);
  const solveTiming = [['assembly_s', b('组装', 'Assembly')], ['solve_s', b('求解', 'Solve')]]
    .filter(([key]) => finite(progress[key]))
    .map(([key, caption]) => `<span class="parameter-pill"><span>${caption}</span><strong>${unit(progress[key], ' s', 3)}</strong></span>`).join('');
  return `<md-elevated-card class="m3-card task-card-shell${selected ? ' selected' : ''}" data-key="task-${id}" data-task="${id}"><article class="panel task-card${selected ? ' selected' : ''}">
    <div class="task-heading"><div>${title}<div class="tag-line">${tags.join('')}</div></div>${clearBtn}</div>
    ${reason ? `<p class="task-health-reason">${esc(reason)}</p>` : ''}
    ${taskProgress}
    <dl class="diagnostics">
      <div title="${esc(rateTip)}"><dt>${b('推进速率', 'Rate')}</dt><dd><strong>${unit(rateAvailable ? rate : null, ' ns/h', 4)}</strong><small>${rateNote}</small></dd></div>
      <div><dt>${b('步长 · 牛顿迭代', 'Step · Newton')}</dt><dd><strong>${stepSize(progress.stepsize_s)}</strong>
        <small>${number(progress.newton_iterations)} ${b('次', 'iter')} · ${unit(progress.step_wall_s, ' s', 2)} · ${b('误差', 'err')} ${finite(progress.error) ? Number(progress.error.toPrecision(3)) : '—'}</small></dd></div>
      <div><dt>${b('进程资源', 'Resources')}</dt><dd><strong>CPU ${unit(task.cpu_percent, '%', 1)}</strong>
        <small>RSS ${gib(task.rss_bytes, 2)} GiB · ${b('峰', 'Peak')} ${gib(task.hwm_bytes, 2)} GiB</small></dd></div>
      <div><dt>${b('运行与心跳', 'Runtime')}</dt><dd><strong><span data-runtime="${finite(task.elapsed_seconds) ? task.elapsed_seconds : ''}" data-sample="${running ? esc(observed) : ''}">${runtime}</span></strong>
        <small><span data-log-time="${esc(progress.log_updated_at || '')}"></span>${stage ? ` · ${esc(stage)}` : ''}</small></dd></div>
    </dl>
    ${renderSparkline(history, task.id, state.lang, state.taskMetrics.get(task.id))}
    <div class="parameter-line">${parameterMarkup(keyParameters, state.lang)}</div>
    <details class="task-details" data-key="task-details"><summary>${b('更多参数', 'More parameters')}</summary><div class="parameter-line">${details}${solveTiming}
      ${!details && !solveTiming ? `<span class="muted">${b('暂无其他参数', 'No additional parameters')}</span>` : ''}</div></details>
    ${renderProcesses(task.processes)}
  </article></md-elevated-card>`;
}

function renderServices(services) {
  return services.map((service) => {
    const detail = serviceDetail(service);
    return `<md-elevated-card class="m3-card" data-key="service-${esc(service.id)}"><article class="panel service"><h3>${esc(serviceName(service))}</h3>${pill(service.state)}
      ${detail ? `<p>${esc(detail)}</p>` : ''}</article></md-elevated-card>`;
  }).join('');
}

function renderRuns(simulation, batch) {
  const title = localized(batch.label, batch.label_en) || b('等待批次观测', 'Awaiting batch samples');
  const totals = [['collected', b('已收集', 'Collected')], ...['running', 'collecting', 'failed', 'pending', 'unknown'].map((key) => [key, label(key)])];
  const headers = [b('任务', 'Task'), b('批次', 'Batch'), b('核数', 'Cores'), b('时长', 'Runtime'),
    b('物理时间', 'Time'), b('状态', 'Status'), b('完成时间', 'Finished')];
  const rows = (simulation.recent_runs || []).filter((run) => !redacted(run)).slice(0, 20).filter((run) =>
    state.runFilter === 'all' || run.state === state.runFilter || (state.runFilter === 'running' && run.state === 'collecting'));
  const cells = rows.map((run) => {
    const data = [`<strong>${esc(taskName(run))}</strong>`, esc(localized(run.batch_label, run.batch_label_en) || '—'),
      number(run.requested_threads), duration(run.elapsed_seconds), unit(run.final_time_ns ?? run.simulation_time_ns, ' ns', 4),
      `${pill(run.state, run.collection_result ? label(run.collection_result) : label(run.state))}${run.health ? ` ${pill(run.health)}` : ''}`, date(run.finished_at)];
    return `<tr data-key="run-${esc(run.id)}">${data.map((value, i) =>
      `<td><span class="cell-label" aria-hidden="true">${headers[i]}</span><span>${value}</span></td>`).join('')}</tr>`;
  }).join('');
  return `<div class="batch-bar"><strong>${esc(title)}</strong>
    <span>${totals.map(([key, caption]) => `${caption} <b>${number(batch[key])}</b>`).join(' · ')}</span></div>
    <div class="filters" role="group" aria-label="${b('筛选任务', 'Filter runs')}">
      ${['all', 'running', 'completed', 'failed'].map((key) => `<button type="button" class="filter-chip" data-run-filter="${key}"
        aria-pressed="${key === state.runFilter}"><md-ripple></md-ripple>${key === 'all' ? b('全部', 'All') : label(key)}</button>`).join('')}
    </div>
    ${rows.length ? `<table class="run-table" aria-label="${b('近期执行流水', 'Recent runs')}"><thead><tr>${headers.map((caption) => `<th scope="col">${caption}</th>`).join('')}</tr></thead>
      <tbody>${cells}</tbody></table>` : `<p class="empty">${b('当前筛选下暂无流水', 'No matching runs')}</p>`}`;
}

// Keep keyed cards and controls alive across samples. Native details own their open state.
const markupCache = new WeakMap();
const nodeKey = (node) => node?.nodeType === 1 ? node.id || node.getAttribute('data-key') : null;

function patchChildren(parent, incoming) {
  const keyed = new Map([...parent.childNodes].filter(nodeKey).map((node) => [nodeKey(node), node]));
  let cursor = parent.firstChild;
  for (const next of incoming.childNodes) {
    const key = nodeKey(next);
    let current = key ? keyed.get(key) : nodeKey(cursor) ? null : cursor;
    if (current?.nodeName !== next.nodeName) current = next.cloneNode(true);
    if (current !== cursor) parent.insertBefore(current, cursor);
    if (next.nodeType === 3 && current.nodeValue !== next.nodeValue) current.nodeValue = next.nodeValue;
    if (next.nodeType === 1) {
      for (const attr of [...current.attributes]) {
        if (attr.name !== 'open' && !next.hasAttribute(attr.name)) current.removeAttribute(attr.name);
      }
      for (const attr of next.attributes) {
        if (attr.name !== 'open' && current.getAttribute(attr.name) !== attr.value) current.setAttribute(attr.name, attr.value);
      }
      patchChildren(current, next);
    }
    cursor = current.nextSibling;
  }
  while (cursor) {
    const next = cursor.nextSibling;
    cursor.remove();
    cursor = next;
  }
}

function update(id, markup) {
  const element = document.getElementById(id);
  if (markupCache.get(element) === markup) return;
  const template = document.createElement('template');
  template.innerHTML = markup;
  const focused = document.activeElement;
  patchChildren(element, template.content);
  if (focused?.isConnected && document.activeElement === document.body && element.contains(focused)) {
    focused.focus({ preventScroll: true });
  }
  markupCache.set(element, markup);
}

const sections = [
  { id: 'overview', num: '00', zh: '总览', en: 'Overview' },
  { id: 'schedule', num: '01', zh: '调度矩阵', en: 'Matrix' },
  { id: 'tasks', num: '02', zh: '活动任务', en: 'Tasks' },
  { id: 'trends', num: '03', zh: '系统趋势', en: 'Trends' },
  { id: 'services', num: '04', zh: '服务健康', en: 'Services' },
  { id: 'runs', num: '05', zh: '执行流水', en: 'Runs' },
  { id: 'research', num: '06', zh: '科研计划', en: 'Research' },
];
const regions = ['overview', 'kpis', 'schedule', 'tasks', 'trends', 'services', 'runs', 'research'];
app.innerHTML = `<header class="topbar">
  <div class="topbar-inner">
    <a class="brand" href="https://tcad.xjtu.shop/" aria-label="xjtu.shop"><span class="brand-mark" aria-hidden="true">X</span>xjtu.shop</a>
    <div class="heartbeat neutral" id="heartbeat"><i aria-hidden="true"></i><span id="heartbeat-text" role="status"></span><span id="heartbeat-age"></span></div>
    <nav id="top-nav" class="top-nav" aria-label="Section navigation"></nav>
    <nav id="controls" class="topbar-controls" aria-label="Dashboard controls"></nav>
  </div>
  <nav id="mobile-nav" class="mobile-nav" aria-label="Quick section navigation"></nav>
</header>
<div class="page-frame">
  <aside id="side-nav" class="side-nav" aria-label="Directory"></aside>
  <div class="page-main">
    <main class="dashboard">
      <section id="overview" class="dashboard-anchor"></section>
      <section id="kpis" class="kpi-grid"></section>
      ${regions.slice(2).map((id) => `<section class="dashboard-section dashboard-anchor" id="${id}"></section>`).join('')}
    </main>
    <footer class="dashboard" id="footer"></footer>
  </div>
</div>
<div id="mobile-toc" class="mobile-toc"></div>`;

function renderNavs() {
  const navItems = (compact = false) => sections.map((sec) => {
    const active = state.activeSection === sec.id;
    const text = b(sec.zh, sec.en);
    return `<button type="button" class="nav-pill${active ? ' active' : ''}" data-nav-target="${sec.id}" aria-current="${active ? 'location' : 'false'}">
      <md-ripple></md-ripple>${compact ? '' : `<span class="nav-num">${sec.num}</span>`}<span>${text}</span>
    </button>`;
  }).join('');
  update('top-nav', navItems(true));
  update('mobile-nav', `<div class="mobile-nav-track">${navItems(true)}</div>`);
  update('side-nav', `<div class="side-nav-card">
    <p class="side-nav-title">${b('页面目录', 'Contents')}</p>
    <div class="side-nav-list">${navItems(false)}</div>
  </div>`);
  const menuIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 7h16M4 12h12M4 17h8"/></svg>';
  const closeIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>';
  update('mobile-toc', `${state.navDrawerOpen ? `<div class="toc-sheet" role="dialog" aria-label="${b('快速导航', 'Quick jump')}">
    <div class="toc-sheet-head"><strong>${b('快速跳转', 'Jump to section')}</strong>
      <button type="button" class="toc-close" data-toc-toggle="1" aria-label="${b('关闭目录', 'Close')}">${closeIcon}</button></div>
    <div class="toc-sheet-grid">${navItems(false)}</div>
  </div>` : ''}
  <button type="button" class="toc-fab${state.navDrawerOpen ? ' open' : ''}" data-toc-toggle="1" aria-expanded="${state.navDrawerOpen}" aria-label="${b('章节目录', 'Sections')}">
    <md-ripple></md-ripple>${state.navDrawerOpen ? closeIcon : menuIcon}<span>${b('目录', 'Menu')}</span>
  </button>`);
}

function renderControls() {
  const dark = document.documentElement.dataset.theme === 'dark';
  const icon = (path) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">${path}</svg>`;
  const refresh = icon('<path d="M20 7v5h-5M4 17v-5h5"/><path d="M5 8a8 8 0 0 1 14-2l1 2M4 16l1 2a8 8 0 0 0 14-2"/>');
  const theme = dark ? icon('<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M19 5l-1.5 1.5m-11 11L5 19"/>')
    : icon('<path d="M20 15a8.5 8.5 0 0 1-11-11A8.5 8.5 0 1 0 20 15Z"/>');
  const control = (id, title, content, attributes = '') => `<button id="${id}" class="icon-btn" type="button" aria-label="${title}" title="${title}" ${attributes}><md-ripple></md-ripple>${content}</button>`;
  update('controls', control('refresh', b('立即刷新', 'Refresh now'), refresh, `aria-busy="${state.refreshing}"`)
    + control('theme', dark ? b('切换浅色', 'Light mode') : b('切换深色', 'Dark mode'), theme)
    + control('language', b('Switch to English', '切换中文'), b('EN', '中'))
    + `<a class="home-link" href="https://tcad.xjtu.shop/" aria-label="${b('返回研究首页', 'Back to research home')}"><md-ripple></md-ripple>${b('研究首页', 'Home')} <span aria-hidden="true">↗</span></a>`);
}

const sectionDivider = (num, tag) => `<div class="section-divider" aria-hidden="true"><span class="divider-line"></span><span class="divider-badge"><i class="divider-gem"></i>${num} · ${tag}</span><span class="divider-line"></span></div>`;
const heading = (title, subtitle = '', num = '', tag = '') => `${num ? sectionDivider(num, tag) : ''}<div class="section-heading"><h2>${title}</h2>${subtitle ? `<p>${subtitle}</p>` : ''}</div>`;
const newestPayload = () => !state.live || Date.parse(state.full?.generated_at) > Date.parse(state.live.generated_at) ? state.full : state.live;
const currentResearch = () => {
  const summary = state.live?.research_summary;
  const full = state.full?.research;
  if (!summary || Date.parse(state.full?.generated_at) > Date.parse(state.live.generated_at)) return full ?? summary;
  return { ...(full?.revision === summary.revision ? full : {}), ...summary };
};

function researchActivity(payload, scheduler) {
  const feed = payload.activity_feed;
  if (feed?.mode && feed.live_items && feed.recent_outcomes) return feed;
  const simulation = payload.simulation || {};
  const legacy = !scheduler.hasObservation && simulation.observed && !simulation.observation_stale;
  const live = legacy ? (simulation.current_runs || []).map((item) => ({ ...item, label: item.group, state: 'running' }))
    : scheduler.tasks.filter((task) => ['running', 'collecting', 'uncollected'].includes(task.state));
  const recent = simulation.recent_runs || [];
  const finished = recent.filter((task) => task.finished_at && ['completed', 'failed', 'uncollected'].includes(task.state));
  const recentOutcomes = finished.length ? finished : (simulation.recent_activity || []).map((item) => ({ ...item, label: item.group }));
  return { mode: feed?.mode ?? (scheduler.stale && !legacy ? 'stale' : live.length ? 'active' : 'idle'),
    live_items: feed?.live_items ?? live, recent_outcomes: feed?.recent_outcomes ?? recentOutcomes };
}

function updateResearch(payload, scheduler, research) {
  const projectionState = research?.projection_state ?? payload.health?.freshness?.research_projection_state;
  update('research', sectionDivider('06', b('科研计划', 'Research')) + renderResearch({ ...research, projection_state: projectionState }, state.lang, researchActivity(payload, scheduler)));
}

function render() {
  document.documentElement.lang = b('zh-CN', 'en');
  document.title = b('仿真状态看板 · xjtu.shop', 'Simulation status · xjtu.shop');
  renderControls();
  renderNavs();
  const payload = newestPayload() || {};
  const simulation = payload.simulation || {};
  const scheduler = schedulerFor(simulation, sampleThreshold(payload));
  const batch = simulation.active_batch || {};
  const research = currentResearch();
  const history = state.live?.history;
  const services = servicesFor(payload, scheduler, batch);
  const summary = localized(batch.summary_zh, batch.summary_en) ||
    localized(payload.health?.simulation?.summary_zh, payload.health?.simulation?.summary_en) ||
    (payload.generated_at ? b('等待调度态势摘要', 'Awaiting a scheduler summary') :
      state.fullFailed ? b('状态数据暂时不可用', 'Status data unavailable') : b('正在读取状态数据…', 'Loading status…'));
  update('overview', `<md-elevated-card class="m3-card overview-shell"><div class="overview"><div><h1>${b('仿真状态看板', 'Simulation status')}</h1>
    <p>${esc(summary)}</p></div>${pill(payload.overall)}</div>${renderHealth(payload, scheduler, batch, research, services)}</md-elevated-card>`);
  update('kpis', renderKpis(payload, scheduler, batch, research, services));
  const sample = scheduler.hasObservation ? `${scheduler.stale ? b('观测快照', 'Snapshot') : b('采样', 'Sampled')} · ${date(scheduler.observedAt)}` : '';
  const matrixHint = state.selectedTask ? b('点击空白处或 Esc 取消选中', 'Click outside or press Esc to clear') : sample;
  update('schedule', heading(b('虚拟机调度矩阵', 'VM scheduling matrix'), matrixHint, '01', b('调度矩阵', 'Matrix'))
    + `<md-elevated-card class="m3-card"><div class="panel matrix">${renderSlots(scheduler)}</div></md-elevated-card>`);
  const tasks = scheduler.tasks.filter((task) => ['running', 'collecting', 'uncollected', 'unknown'].includes(task.state));
  const taskTitle = scheduler.stale && scheduler.hasObservation ? b('活动任务 · 快照', 'Active tasks · snapshot') : b('活动任务遥测', 'Active task telemetry');
  update('tasks', heading(taskTitle, '', '02', b('活动任务', 'Tasks')) + `<div class="task-grid">${tasks.map((task) => taskCard(task, scheduler, history)).join('') ||
    `<p class="empty">${scheduler.stale ? b('等待任务观测', 'Awaiting task samples') : b('当前无活动任务', 'No active tasks')}</p>`}</div>`);
  update('trends', `${sectionDivider('03', b('系统趋势', 'Trends'))}<div class="section-heading"><h2>${b('系统趋势', 'System trends')}</h2><div class="filters" role="group" aria-label="${b('采样时段', 'Sample window')}">
    ${['2h', '24h'].map((window) => `<button type="button" class="filter-chip" data-window="${window}" aria-pressed="${window === state.window}"><md-ripple></md-ripple>${window}</button>`).join('')}
    </div></div><div class="trend-grid">${renderTrends(history, state.window, state.lang)}</div>`);
  update('services', heading(b('服务健康', 'Service health'), '', '04', b('服务健康', 'Services')) + `<div class="service-grid">${renderServices(services)}</div>`);
  update('runs', heading(b('近期执行流水', 'Recent runs'), '', '05', b('执行流水', 'Runs')) + `<md-elevated-card class="m3-card"><div class="panel runs-panel">${renderRuns(simulation, batch)}</div></md-elevated-card>`);
  updateResearch(payload, scheduler, research);
  update('footer', `<div class="scope"><details class="scope-details"><summary>${b('公开范围与数据口径', 'Public scope & definitions')}</summary>
    <p>${b('公开服务健康、资源摘要和已脱敏的仿真进度。服务器与虚拟机内存及三层存储空间独立采样、余量不相加；工程完成以原任务核验收集为准，科学验收另需逐例证据。',
      'Shows service health, resource summaries and sanitized simulation progress. Server and VM memory and storage layers are independent. Engineering completion uses verified collection; scientific acceptance requires case-level evidence.')}</p>
    </details></div>`);
  tick();
}

function age(time) {
  const timestamp = Date.parse(time);
  return finite(timestamp) ? Math.max(0, Math.floor((Date.now() - timestamp) / 1000)) : null;
}

function writeText(element, value) {
  if (element.textContent !== value) element.textContent = value;
}

function tick() {
  if (document.hidden) return;
  const payload = newestPayload();
  const threshold = sampleThreshold(payload);
  const scheduler = payload?.simulation?.scheduler || payload?.simulation?.benchmark;
  const sample = scheduler?.observed_at || scheduler?.virtual_machine?.observed_at || payload?.generated_at;
  const seconds = age(sample);
  const heartbeat = document.getElementById('heartbeat');
  const live = state.liveMode === 'online' && payload === state.live;
  const expired = payload && (!validSample(sample, threshold) || payload.stale || scheduler?.observation_stale);
  const errored = state.liveMode === 'error' && (payload !== state.full || state.fullFailed) || !payload && state.fullFailed;
  const delayed = seconds != null && seconds > (live ? 45 : 90);
  const [status, color] = expired ? [b('采样过期', 'Sample stale'), 'bad'] :
    errored || delayed ? [b('更新延迟', 'Delayed'), 'warn'] :
    !payload ? [b('等待采样', 'Waiting'), 'neutral'] :
    live ? [b('实时在线', 'Live'), 'good'] : [b('定时更新', 'Periodic'), 'good'];
  const heartbeatClass = `heartbeat ${color}${live && color === 'good' ? ' pulsing' : ''}`;
  if (heartbeat.className !== heartbeatClass) heartbeat.className = heartbeatClass;
  writeText(document.getElementById('heartbeat-text'), status);
  writeText(document.getElementById('heartbeat-age'), seconds == null ? '' : `· ${b(`${seconds}s 前`, `${seconds}s ago`)}`);
  for (const element of app.querySelectorAll('[data-runtime]')) {
    const sampled = age(element.dataset.sample);
    const offset = sampled != null && validSample(element.dataset.sample, threshold) ? sampled : 0;
    writeText(element, element.dataset.runtime ? duration(Number(element.dataset.runtime) + offset) : '—');
  }
  for (const element of app.querySelectorAll('[data-log-time]')) {
    const secs = age(element.dataset.logTime);
    writeText(element, secs == null ? b('心跳未知', 'Heartbeat unknown') : b(`日志 ${secs}s 前`, `Log ${secs}s ago`));
  }
}

const LIVE_INTERVAL = 15000;
const FULL_INTERVAL = 60000;

async function fetchStatus(path) {
  const response = await fetch(path, { cache: 'no-store', signal: AbortSignal.timeout(12000) });
  if (response.status === 404 && path === './live.json') return null;
  if (!response.ok) throw new Error(`${path} returned HTTP ${response.status}`);
  const payload = await response.json();
  if (!payload || (!Array.isArray(payload.services) && !Array.isArray(payload.health?.services?.items)) || !finite(Date.parse(payload.generated_at))) {
    throw new Error(`Invalid status payload from ${path}`);
  }
  return payload;
}

async function loadFull() {
  state.lastFullRequest = Date.now();
  try {
    state.full = await fetchStatus('./status.json');
    state.fullFailed = false;
  } catch (error) {
    state.fullFailed = true;
    console.warn('Status snapshot refresh failed', error);
  }
  render();
  return !state.fullFailed;
}

function recordResearchHash() {
  if (state.full?.research && state.live?.research_hash &&
      Date.parse(state.full.generated_at) === Date.parse(state.live.generated_at)) {
    state.fullHash = state.live.research_hash;
  }
}

async function loadLive() {
  try {
    const payload = await fetchStatus('./live.json');
    state.liveMode = payload ? 'online' : 'fallback';
    if (payload) {
      state.live = payload;
    } else {
      state.live = null;
      state.fullHash = null;
    }
  } catch (error) {
    state.liveMode = 'error';
    console.warn('Live status refresh failed', error);
  }
  render();
}

async function refresh(immediate = false) {
  if (state.refreshing) return;
  state.refreshing = true;
  renderControls();
  try {
    const needsFull = Date.now() - state.lastFullRequest >= FULL_INTERVAL ||
      (immediate && ['fallback', 'error'].includes(state.liveMode));
    const [, receivedFull] = await Promise.all([loadLive(), needsFull ? loadFull() : null]);
    if (receivedFull) recordResearchHash();
    const researchChanged = state.live?.research_hash && state.live.research_hash !== state.fullHash;
    const manualFallback = immediate && state.liveMode === 'fallback';
    if (!needsFull && (researchChanged || manualFallback)) {
      if (await loadFull()) recordResearchHash();
    }
  } finally {
    state.refreshing = false;
    renderControls();
  }
}

function clearSelection() {
  if (!state.selectedTask) return;
  state.selectedTask = null;
  render();
}

app.addEventListener('click', (event) => {
  const button = event.target.closest('button');
  if (button) {
    if (button.id === 'refresh') {
      refresh(true);
      return;
    }
    if (button.id === 'theme') {
      statusTheme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem('xjtu-status-theme', statusTheme); } catch {}
      applyStatusTheme(statusTheme);
      renderControls();
      return;
    }
    if (button.id === 'language') {
      state.lang = b('en', 'zh');
      try { localStorage.setItem('xjtu-lang', state.lang); } catch {}
      render();
      return;
    }
    if (button.dataset.tocToggle) {
      state.navDrawerOpen = !state.navDrawerOpen;
      renderNavs();
      return;
    }
    if (button.dataset.navTarget) {
      const targetId = button.dataset.navTarget;
      state.activeSection = targetId;
      state.navDrawerOpen = false;
      renderNavs();
      const target = document.getElementById(targetId);
      target?.scrollIntoView({ block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
      return;
    }
    if (button.dataset.clearSelection) {
      clearSelection();
      return;
    }
    if (button.dataset.slotTask) {
      const next = button.dataset.slotTask;
      if (state.selectedTask === next) {
        clearSelection();
        return;
      }
      state.selectedTask = next;
      render();
      const target = [...app.querySelectorAll('[data-task]')].find((task) => task.dataset.task === state.selectedTask);
      target?.scrollIntoView({ block: 'nearest', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
      target?.querySelector('h3')?.focus({ preventScroll: true });
      return;
    }
    if (button.dataset.window) {
      state.window = button.dataset.window;
      render();
      return;
    }
    if (button.dataset.runFilter) {
      state.runFilter = button.dataset.runFilter;
      render();
      return;
    }
    if (button.dataset.taskMetric) {
      state.taskMetrics.set(button.closest('[data-task]').dataset.task, button.dataset.taskMetric);
      render();
      return;
    }
    return;
  }
  if (state.navDrawerOpen && !event.target.closest?.('#mobile-toc')) {
    state.navDrawerOpen = false;
    renderNavs();
  }
  // Clicking outside the selected task card or on blank page space clears CPU selection.
  const clickedTask = event.target.closest?.('[data-task]');
  if (state.selectedTask && clickedTask?.dataset?.task !== state.selectedTask && !event.target.closest?.('[data-slot-task]')) {
    clearSelection();
  }
});

// Clicking blank margins outside #app (e.g. body sides) also clears selection.
document.addEventListener('click', (event) => {
  if (state.navDrawerOpen && !app.contains(event.target)) {
    state.navDrawerOpen = false;
    renderNavs();
  }
  if (!state.selectedTask) return;
  if (app.contains(event.target)) return;
  clearSelection();
});

document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  if (state.navDrawerOpen) {
    state.navDrawerOpen = false;
    renderNavs();
  }
  if (state.selectedTask) clearSelection();
});

// Scroll Spy: highlight the active section in top, side, and mobile navigation bars.
if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
  let scrollFrame = 0;
  const syncActiveSection = () => {
    scrollFrame = 0;
    const offset = 132;
    let current = sections[0].id;
    for (const sec of sections) {
      const el = document.getElementById(sec.id);
      if (!el || typeof el.getBoundingClientRect !== 'function') continue;
      if (el.getBoundingClientRect().top <= offset) current = sec.id;
    }
    if (current !== state.activeSection) {
      state.activeSection = current;
      renderNavs();
      const activeMobile = document.querySelector('#mobile-nav .nav-pill.active');
      activeMobile?.scrollIntoView?.({ inline: 'center', block: 'nearest', behavior: 'smooth' });
    }
  };
  window.addEventListener('scroll', () => {
    if (!scrollFrame && typeof requestAnimationFrame === 'function') {
      scrollFrame = requestAnimationFrame(syncActiveSection);
    }
  }, { passive: true });
}

// Hovering a CPU slot softly highlights the matching task card.
const scheduleSection = document.getElementById('schedule');
scheduleSection.addEventListener('pointerover', (event) => {
  const slot = event.target.closest?.('[data-slot-task]');
  if (!slot) return;
  const id = slot.dataset.slotTask;
  for (const el of app.querySelectorAll('[data-task]')) {
    el.classList.toggle('hovered', el.dataset.task === id);
  }
});
scheduleSection.addEventListener('pointerout', (event) => {
  const slot = event.target.closest?.('[data-slot-task]');
  if (!slot) return;
  if (event.relatedTarget && slot.contains(event.relatedTarget)) return;
  for (const el of app.querySelectorAll('[data-task].hovered')) {
    el.classList.remove('hovered');
  }
});

systemTheme.addEventListener('change', () => {
  if (statusTheme !== 'light' && statusTheme !== 'dark') {
    applyStatusTheme(systemTheme.matches ? 'dark' : 'light');
    renderControls();
  }
});
bindResearch(document.getElementById('research'), () => {
  const payload = newestPayload() || {};
  updateResearch(payload, schedulerFor(payload.simulation || {}, sampleThreshold(payload)), currentResearch());
});
bindTrendTooltips(document.getElementById('trends'), () => state.lang);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) {
    tick();
    refresh(true);
  }
});
render();
refresh();
setInterval(() => { if (!document.hidden) refresh(); }, LIVE_INTERVAL);
setInterval(tick, 1000);
