const icons = {
  simulation: '<rect x="6" y="6" width="12" height="12" rx="3"/><path d="M9 1v5m6-5v5M9 18v5m6-5v5M1 9h5m-5 6h5m12-6h5m-5 6h5M9 12h6m-3-3v6"/>',
  radiation: '<circle cx="12" cy="12" r="2.2"/><path d="M12 4.5a7.5 7.5 0 0 1 6.5 3.75l-3.2 1.85A3.8 3.8 0 0 0 12 8.2V4.5Zm0 15a7.5 7.5 0 0 1-6.5-3.75l3.2-1.85A3.8 3.8 0 0 0 12 15.8v3.7Zm7.5-7.5a7.5 7.5 0 0 1-3.75 6.5l-1.85-3.2A3.8 3.8 0 0 0 15.8 12h3.7Z"/>',
  server: '<rect x="3" y="4" width="18" height="6" rx="2"/><rect x="3" y="14" width="18" height="6" rx="2"/><path d="M7 7h.01M7 17h.01M11 7h6M11 17h6"/>',
  agent: '<rect x="5" y="7" width="14" height="11" rx="3"/><path d="M12 3v4M9 12h.01M15 12h.01M9 15.5h6M2 12h3m14 0h3"/>',
  shield: '<path d="M12 3 4.5 6v5.5c0 4.9 3.2 8.9 7.5 10.2 4.3-1.3 7.5-5.3 7.5-10.2V6L12 3Z"/><path d="m9 12 2 2 4-4"/>',
  archive: '<path d="M4 8h16v12H4zM3 4h18v4H3zM9 12h6m-4 4h2"/>',
  model: '<circle cx="5" cy="12" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><circle cx="12" cy="12" r="2"/><path d="M7 12h3m4-1.5 3-4.2M14 13.5l3 4.2"/>',
  ledger: '<path d="M6 3h10l3 3v15H6V3Z"/><path d="M10 9h5m-5 4h5m-5 4h3"/>',
  boundary: '<path d="M12 4 3 19h18L12 4Z"/><path d="M12 10v4m0 3h.01"/>',
  docs: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H19v16H6.5A2.5 2.5 0 0 0 4 21V5.5Z"/><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H19M8 7h7m-7 4h7"/>',
  code: '<path d="m8 8-4 4 4 4m8-8 4 4-4 4M13.5 5l-3 14"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2.2M12 19.8V22M4.9 4.9l1.6 1.6m11 11 1.6 1.6M2 12h2.2M19.8 12H22M4.9 19.1l1.6-1.6m11-11 1.6-1.6"/>',
  moon: '<path d="M20.2 14.4A8.5 8.5 0 0 1 9.6 3.8a8.5 8.5 0 1 0 10.6 10.6Z"/>',
  arrow: '<path d="M5 12h14m-6-6 6 6-6 6"/>',
  external: '<path d="M14 4h6v6M10 14 20 4M19 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h5"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  refresh: '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1"/>',
  chevron: '<path d="m8 10 4 4 4-4"/>',
  up: '<path d="m12 19V5m-6 6 6-6 6 6"/>',
  telemetry: '<path d="M3 12h4l2.5-6 4 12 2.5-6h5"/>'
};

export function icon(name, extra = '') {
  const hasClass = /\bclass\s*=/.test(extra);
  const attrs = hasClass
    ? extra.replace(/\bclass\s*=\s*"([^"]*)"/, 'class="ui-icon $1"')
    : `class="ui-icon" ${extra}`.trim();
  return `<svg ${attrs} width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.arrow}</svg>`;
}
