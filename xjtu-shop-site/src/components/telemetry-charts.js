export const escapeHtml = (value) => String(value ?? '')
  .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;').replaceAll("'", '&#39;');

const finite = Number.isFinite;
const limit = (value, min, max) => Math.max(min, Math.min(max, value));
const coordinate = (value) => value.toFixed(2);
const phaseNames = {
  initialization: ['初始化', 'Init'],
  write_sn2: ['写 SN2', 'Write SN2'],
  write_sn1: ['写 SN1', 'Write SN1'],
  hold: ['保持', 'Hold'],
  read: ['读出', 'Read'],
  tail: ['尾段', 'Tail'],
};
const phaseFullNames = {
  initialization: ['初始化', 'Initialization'],
  write_sn2: ['写 SN2', 'Write SN2'],
  write_sn1: ['写 SN1', 'Write SN1'],
  hold: ['保持 / 注入', 'Hold / inject'],
  read: ['读出 SN1', 'Read SN1'],
  tail: ['尾段', 'Tail'],
};
const standardWhr = Object.keys(phaseNames).map((id, index) => ({
  id, start_ns: [0, 2, 10, 18, 30, 32][index], end_ns: [2, 10, 18, 30, 32, 35][index],
}));

export function renderWhr(progress, lang) {
  const { simulation_time_ns: now, goal_time_ns: goal, whr_segments: provided, whr_phase: phase, phase: stage } = progress;
  if (!finite(now) && !finite(goal) && !provided?.length && stage !== 'dc_init' && stage !== 'transient') return '';
  const segments = provided?.length ? provided : standardWhr;
  const start = segments[0].start_ns;
  const end = segments.at(-1).end_ns;
  if (!(end > start)) return '';
  const active = segments.find((segment) => segment.id === phase) || (finite(now) && segments.find((segment, index) =>
    now >= segment.start_ns && (now < segment.end_ns || (index === segments.length - 1 && now === segment.end_ns))));
  const idx = lang === 'zh' ? 0 : 1;
  const shortLabel = (id) => phaseNames[id]?.[idx] || id;
  const fullLabel = (id) => phaseFullNames[id]?.[idx] || id;
  const displayTime = finite(now) ? Number(now.toFixed(6)) : '—';
  const physical = `${displayTime} / ${finite(goal) ? goal : '—'} ns`;
  const percent = finite(now) && goal > 0 ? `${(100 * now / goal).toFixed(1)}%` : '';
  const x = (value) => 4 + 492 * (value - start) / (end - start);
  const cursor = finite(now) ? x(limit(now, start, end)) : null;
  return `<figure class="whr">
    <figcaption class="whr-head">
      <span class="whr-kicker">${provided?.length ? 'DRAM WHR' : lang === 'zh' ? 'DRAM WHR' : 'DRAM WHR'}</span>
      <span class="whr-reading">
        <strong>${physical}</strong>
        ${percent ? `<span class="whr-pct">${percent}</span>` : ''}
        ${active ? `<span class="whr-active-pill phase-${segments.indexOf(active)}">${escapeHtml(fullLabel(active.id))}</span>` : ''}
      </span>
    </figcaption>
    <svg class="whr-bar" viewBox="0 0 500 22" preserveAspectRatio="none" aria-hidden="true">
      ${segments.map(({ id, start_ns, end_ns }, index) => {
        const w = Math.max(0, x(end_ns) - x(start_ns) - 3);
        return `<rect class="whr-segment phase-${index}${id === active?.id ? ' current' : ''}" x="${coordinate(x(start_ns))}" y="6" width="${coordinate(w)}" height="10" rx="5"><title>${escapeHtml(fullLabel(id))} (${start_ns}–${end_ns} ns)</title></rect>`;
      }).join('')}
      ${cursor !== null ? `<line class="whr-cursor" x1="${coordinate(cursor)}" x2="${coordinate(cursor)}" y1="2" y2="20"/><circle class="whr-cursor-dot" cx="${coordinate(cursor)}" cy="11" r="4"/>` : ''}
    </svg>
    <div class="whr-legend">${segments.map(({ id, start_ns, end_ns }, index) => {
      const isCurrent = id === active?.id;
      return `<span class="whr-chip phase-${index}${isCurrent ? ' current' : ''}" title="${escapeHtml(fullLabel(id))} · ${start_ns}–${end_ns} ns"><i aria-hidden="true"></i>${escapeHtml(shortLabel(id))}${isCurrent ? ` <em>${start_ns}–${end_ns} ns</em>` : ''}</span>`;
    }).join('')}</div>
  </figure>`;
}

function decodeRows(fields, rows, keys) {
  if (!fields || !rows) return [];
  const columns = ['ts', ...keys].map((key) => fields.indexOf(key));
  return rows.map((row) => columns.map((column) => finite(row[column]) ? row[column] : null))
    .filter(([timestamp, ...values]) => finite(timestamp) && values.some(finite))
    .sort((a, b) => a[0] - b[0]);
}

function drawSeries(rows, column, x, y, stepped, maxGap) {
  let path = '';
  let previous = null;
  for (const row of rows) {
    const value = row[column];
    if (!finite(value)) {
      previous = null;
      continue;
    }
    const point = `${coordinate(x(row[0]))} ${coordinate(y(value))}`;
    const continues = previous && row[0] - previous[0] <= maxGap;
    if (!continues) path += `M${point}h.01`;
    else if (stepped) path += `H${coordinate(x(row[0]))}V${coordinate(y(value))}`;
    else path += `L${point}`;
    previous = row;
  }
  return path;
}

const taskMetrics = [
  { field: 'simulation_time_ns', labels: ['物理时间', 'Physical time'], unit: ' ns', convert: (value) => value },
  { field: 'stepsize_s', labels: ['步长 log₁₀', 'Step log₁₀'], unit: '', convert: (value) => Math.log10(value) },
  { field: 'rss_bytes', labels: ['内存 RSS', 'Memory RSS'], unit: ' GiB', convert: (value) => value / 1024 ** 3 },
];

export function renderSparkline(history, id, lang, selected) {
  const index = lang === 'zh' ? 0 : 1;
  const metrics = taskMetrics.map((metric) => ({ ...metric,
    rows: decodeRows(history?.task_fields, history?.tasks?.[id], [metric.field])
      .map(([ts, value]) => [ts, metric.convert(value)]).filter((row) => finite(row[1])),
  })).filter((metric) => metric.rows.length);
  const metric = metrics.find((item) => item.field === selected) || metrics[0];
  if (!metric) return '';
  const { rows, unit } = metric;
  const lo = Math.min(...rows.map((row) => row[1]));
  const hi = Math.max(...rows.map((row) => row[1]));
  const first = rows[0][0];
  const range = rows.at(-1)[0] - first || 1;
  const label = lang === 'zh' ? '近 2h 任务趋势' : '2h task trend';
  const rangeText = `${Number(lo.toFixed(4))}${lo === hi ? '' : ` → ${Number(hi.toFixed(4))}`}${unit}`;
  const path = drawSeries(rows, 1, (ts) => 3 + 234 * (ts - first) / range,
    (ns) => hi === lo ? 16 : 26 - 20 * (ns - lo) / (hi - lo), false, 180);
  return `<figure class="sparkline"><figcaption><span>${label}</span><strong>${rangeText}</strong></figcaption>
    <div class="filters sparkline-filters" role="group" aria-label="${label}">${metrics.map(({ field, labels }) =>
      `<button type="button" class="filter-chip" data-key="metric-${field}" data-task-metric="${field}" aria-pressed="${metric.field === field}">${labels[index]}</button>`).join('')}</div>
    <svg viewBox="0 0 240 32" preserveAspectRatio="none" aria-hidden="true"><path class="series series-0" d="${path}"/></svg></figure>`;
}

const metrics = {
  cpu: {
    title: ['CPU 利用率', 'CPU utilization'],
    labels: [['服务器', 'Server'], ['虚拟机', 'Virtual machine']],
    fields: ['server_cpu_percent', 'vm_cpu_percent'], unit: '%', max: 100,
  },
  memory: {
    title: ['可用内存', 'Available memory'],
    labels: [['服务器', 'Server'], ['虚拟机', 'Virtual machine']],
    fields: ['server_available_memory_gib', 'vm_available_memory_gib'], unit: ' GiB',
  },
  parallel: {
    title: ['活跃求解器与核数', 'Active solvers & cores'],
    labels: [['求解进程', 'Solvers'], ['占用核心', 'Cores']],
    fields: ['active_solvers', 'active_cores'], unit: '', stepped: true,
  },
  storage: {
    title: ['三层存储余量', 'Storage headroom'],
    labels: [['服务器剩余空间', 'Server remaining'], ['服务器上虚拟机磁盘文件可增长空间', 'VM disk file growth space on server'], ['虚拟机剩余空间', 'VM remaining']],
    fields: ['server_remaining_gib', 'vm_disk_growth_available_gib', 'vm_remaining_gib'], unit: ' GiB', warning: 5,
  },
};
const plot = { left: 34, right: 310, top: 12, bottom: 88, width: 320 };

export function renderTrends(history, window, lang) {
  const recent = window === '2h';
  const rows = recent ? history?.system_recent : history?.system_5m;
  const locale = lang === 'zh' ? 'zh-CN' : 'en-US';
  const index = lang === 'zh' ? 0 : 1;
  const tickTime = new Intl.DateTimeFormat(locale, {
    ...(recent ? {} : { month: 'numeric', day: 'numeric' }),
    hour: '2-digit', minute: '2-digit',
  });
  return Object.entries(metrics).map(([key, metric]) => {
    const data = decodeRows(history?.system_fields, rows, metric.fields);
    const labels = metric.labels.map((label) => label[index]);
    const title = metric.title[index];
    const legend = `<div class="trend-legend">${labels.map((label, i) => `<span class="legend-${i}">${label}</span>`).join('')}
      ${metric.warning ? `<span class="legend-warning">${metric.warning} GiB ${lang === 'zh' ? '警戒线' : 'warning'}</span><small>${lang === 'zh' ? '各层余量不可相加' : 'Each layer is measured independently'}</small>` : ''}</div>`;
    if (!data.length) return `<md-elevated-card class="m3-card trend-card" id="trend-${key}"><div class="card-body"><h3>${title}</h3>${legend}<p class="empty">${lang === 'zh' ? '等待趋势样本' : 'Awaiting samples'}</p></div></md-elevated-card>`;
    const end = data.at(-1)[0];
    const start = end - (recent ? 7200 : 86400);
    const topValue = metric.max || Math.max(metric.warning ? metric.warning + 4 : metric.stepped ? 2 : 4,
      Math.ceil(Math.max(...data.flatMap((row) => row.slice(1))) / (metric.stepped ? 2 : 4)) * (metric.stepped ? 2 : 4));
    const x = (ts) => plot.left + (plot.right - plot.left) * limit((ts - start) / (end - start), 0, 1);
    const y = (value) => plot.bottom - (plot.bottom - plot.top) * value / topValue;
    return `<md-elevated-card class="m3-card trend-card" id="trend-${key}"><div class="card-body"><div class="trend-head"><h3>${title}</h3>${legend}</div>
      <svg class="trend-svg" viewBox="0 0 320 112" tabindex="0" role="group"
        aria-label="${title} · ${window} · ${lang === 'zh' ? '用左右方向键查看采样' : 'Use arrow keys to inspect samples'}"
        data-points="${escapeHtml(JSON.stringify(data))}" data-start="${start}" data-end="${end}" data-metric="${key}">
        ${[topValue, topValue / 2, 0].map((value) => `<line class="chart-grid" x1="${plot.left}" x2="${plot.right}" y1="${y(value)}" y2="${y(value)}"/><text x="0" y="${y(value) + 3}">${value}${metric.unit === '%' ? '%' : ''}</text>`).join('')}
        ${[start, (start + end) / 2, end].map((ts, i) => `<text x="${x(ts)}" y="106" text-anchor="${['start', 'middle', 'end'][i]}">${escapeHtml(tickTime.format(new Date(ts * 1000)))}</text>`).join('')}
        ${metric.warning ? `<line class="chart-warning" x1="${plot.left}" x2="${plot.right}" y1="${y(metric.warning)}" y2="${y(metric.warning)}"/>` : ''}
        ${labels.map((_, i) => `<path class="series series-${i}" d="${drawSeries(data, i + 1, x, y, metric.stepped, recent ? 120 : 600)}"/>`).join('')}
      </svg><output class="trend-tooltip" aria-live="polite"></output></div></md-elevated-card>`;
  }).join('');
}

export function bindTrendTooltips(root, language) {
  const cache = new WeakMap();
  const inspect = (event) => {
    const svg = event.target.closest('.trend-svg');
    if (!svg || (event.type === 'pointermove' && event.pointerType === 'touch')) return;
    if (event.type === 'keydown' && !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    let view = cache.get(svg);
    if (view?.source !== svg.dataset.points) {
      view = { source: svg.dataset.points, rows: JSON.parse(svg.dataset.points), index: -1 };
      cache.set(svg, view);
    }
    let index;
    if (event.type === 'keydown') {
      event.preventDefault();
      const previous = view.index < 0 ? view.rows.length - 1 : view.index;
      index = event.key === 'Home' ? 0 : event.key === 'End' ? view.rows.length - 1 :
        limit(previous + (event.key === 'ArrowLeft' ? -1 : 1), 0, view.rows.length - 1);
    } else {
      const bounds = svg.getBoundingClientRect();
      const fraction = limit(((event.clientX - bounds.left) / bounds.width * plot.width - plot.left) /
        (plot.right - plot.left), 0, 1);
      const target = Number(svg.dataset.start) + fraction * (Number(svg.dataset.end) - Number(svg.dataset.start));
      index = view.rows.reduce((closest, row, i) => Math.abs(row[0] - target) < Math.abs(view.rows[closest][0] - target) ? i : closest, 0);
    }
    const tooltip = svg.nextElementSibling;
    if (index === view.index && tooltip.textContent) return;
    view.index = index;
    const [ts, ...values] = view.rows[index];
    const lang = language();
    const { labels, unit } = metrics[svg.dataset.metric];
    const time = new Intl.DateTimeFormat(lang === 'zh' ? 'zh-CN' : 'en-US',
      { dateStyle: 'short', timeStyle: 'medium' }).format(new Date(ts * 1000));
    tooltip.textContent = `${time} · ${values.map((value, i) => `${labels[i][lang === 'zh' ? 0 : 1]} ${finite(value) ? value + unit : '—'}`).join(' / ')}`;
  };
  for (const event of ['pointermove', 'click', 'keydown']) root.addEventListener(event, inspect);
}
