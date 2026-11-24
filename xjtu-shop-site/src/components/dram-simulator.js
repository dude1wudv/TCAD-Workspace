import { escapeHtml } from '../shared/site-shell.js';
import { bindSlidingPill, syncSlidingThumb } from '../shared/sliding-pill.js';
import { icon } from '../shared/icons.js';

const PRESET_IDS = ['v4', 'v3', 'd1'];

export function createDramSimulator({ lang = 'zh', onNavigateView, copy }) {
  let currentLang = lang;
  let activePreset = 'v4';
  let activeStageIdx = 0;
  let strikeCount = 0;
  let rafId = 0;
  let destroyed = false;
  let containerEl = null;
  let canvasEl = null;
  let resizeObserver = null;
  let autoDemoTimer = 0;

  // Live animation state for physics particles & waveforms
  const simState = {
    t: 0,
    progress: 1,
    impactX: 0.46,
    impactY: 0.42,
    vertex: null,
    primaryPath: [],
    secondaries: [],
    charges: [],
    pulseRings: [],
    waveform: [],
    diffWave: [],
    metrics: { peakLet: '36.76 MeV', dvSn: '-0.28 V', readout: 'protonInelastic' }
  };

  function getPresetCopy(presetId) {
    return copy[currentLang].hero.simPresets.find(p => p.id === presetId) || copy[currentLang].hero.simPresets[0];
  }

  function seededRand(seed) {
    let s = Math.sin(seed * 9301 + 49297) * 233280;
    return s - Math.floor(s);
  }

  function triggerStrike(normX = 0.46, normY = 0.44, presetOverride = null) {
    if (presetOverride) activePreset = presetOverride;
    strikeCount += 1;
    simState.t = 0;
    simState.progress = matchMedia('(prefers-reduced-motion: reduce)').matches ? 1 : 0;
    simState.impactX = Math.max(0.18, Math.min(0.82, normX));
    simState.impactY = Math.max(0.28, Math.min(0.78, normY));
    simState.secondaries = [];
    simState.charges = [];
    simState.pulseRings = [{ x: simState.impactX, y: simState.impactY, r: 0, alpha: 1 }];

    const entryX = Math.max(0.16, Math.min(0.84, simState.impactX - 0.08));
    simState.primaryPath = [
      { x: entryX, y: 0.04 },
      { x: simState.impactX, y: simState.impactY },
      { x: Math.min(0.92, simState.impactX + 0.14), y: 0.94 }
    ];
    simState.vertex = { x: simState.impactX, y: simState.impactY };

    const baseSeed = strikeCount * 17 + PRESET_IDS.indexOf(activePreset) * 31;

    if (activePreset === 'v4') {
      const branches = [
        { angle: 0.42, len: 0.34, color: '#6ee0b4', width: 2.3, label: 'p / α' },
        { angle: 1.08, len: 0.28, color: '#ff8f70', width: 2.6, label: 'Si*' },
        { angle: -0.58, len: 0.25, color: '#7eb7ff', width: 1.9, label: 'Li7' },
        { angle: 2.35, len: 0.21, color: '#ffc57a', width: 1.8, label: 'n' },
        { angle: -1.35, len: 0.19, color: '#cfbaff', width: 1.7, label: 'γ' }
      ];
      branches.forEach((b, i) => {
        const jitter = (seededRand(baseSeed + i) - 0.5) * 0.26;
        const a = b.angle + jitter;
        const dx = Math.cos(a) * b.len;
        const dy = Math.sin(a) * b.len;
        simState.secondaries.push({
          x0: simState.impactX,
          y0: simState.impactY,
          x1: Math.max(0.08, Math.min(0.92, simState.impactX + dx)),
          y1: Math.max(0.18, Math.min(0.92, simState.impactY + dy)),
          color: b.color,
          width: b.width,
          label: b.label
        });
      });
      // Funnel charges drifting toward Storage Node (~0.36, 0.33)
      for (let i = 0; i < 16; i += 1) {
        const rx = simState.impactX + (seededRand(baseSeed + 20 + i) - 0.5) * 0.14;
        const ry = simState.impactY + (seededRand(baseSeed + 40 + i) - 0.5) * 0.14;
        simState.charges.push({ sx: rx, sy: ry, tx: 0.36, ty: 0.32, delay: i * 0.03 });
      }
      simState.metrics = {
        peakLet: '36.76 MeV',
        dvSn: '-0.31 V',
        readout: 'protonInelastic'
      };
    } else if (activePreset === 'v3') {
      simState.primaryPath = [
        { x: simState.impactX - 0.04, y: 0.04 },
        { x: simState.impactX + 0.07, y: 0.94 }
      ];
      for (let i = 0; i < 24; i += 1) {
        const p = 0.16 + (i / 24) * 0.72;
        const px = simState.primaryPath[0].x + (simState.primaryPath[1].x - simState.primaryPath[0].x) * p;
        const py = simState.primaryPath[0].y + (simState.primaryPath[1].y - simState.primaryPath[0].y) * p;
        simState.charges.push({ sx: px, sy: py, tx: 0.36, ty: 0.31, delay: i * 0.02 });
      }
      simState.metrics = {
        peakLet: 'LET 40 MeV·cm²/mg',
        dvSn: '-0.49 V',
        readout: 'MAE 0.53 / 0.40 mV'
      };
    } else {
      // D1 differential offset cancellation
      for (let i = 0; i < 12; i += 1) {
        simState.charges.push({
          sx: 0.50,
          sy: 0.25,
          tx: i % 2 === 0 ? 0.26 : 0.74,
          ty: 0.25,
          delay: i * 0.025
        });
      }
      simState.metrics = {
        peakLet: '+12.5 mV → -0.26 mV',
        dvSn: '98% CM Cancel',
        readout: '4.69 mV Net'
      };
    }

    syncHud();
    syncPipelineTicker();
    ensureAnimationLoop();
  }

  function syncHud() {
    if (!containerEl) return;
    const presetInfo = getPresetCopy(activePreset);
    const countEl = containerEl.querySelector('#simEventCounter');
    const statALabel = containerEl.querySelector('#simStatALabel');
    const statAVal = containerEl.querySelector('#simStatAVal');
    const statBVal = containerEl.querySelector('#simStatBVal');
    const statCVal = containerEl.querySelector('#simStatCVal');
    const captionEl = containerEl.querySelector('#simPresetCaption');

    if (countEl) countEl.textContent = `#${String(strikeCount).padStart(2, '0')}`;
    if (statALabel) statALabel.textContent = presetInfo.statLabel;
    if (statAVal) statAVal.textContent = simState.metrics.peakLet;
    if (statBVal) statBVal.textContent = simState.metrics.dvSn;
    if (statCVal) statCVal.textContent = simState.metrics.readout;
    if (captionEl) captionEl.textContent = presetInfo.caption;
  }

  function syncPipelineTicker() {
    if (!containerEl) return;
    const nodes = copy[currentLang].hero.nodes;
    const pills = containerEl.querySelectorAll('.sim-pipe-btn');
    pills.forEach((btn, idx) => {
      btn.classList.toggle('is-active', idx === activeStageIdx);
      btn.setAttribute('aria-pressed', String(idx === activeStageIdx));
    });
    const detailEl = containerEl.querySelector('#simPipeDetail');
    const node = nodes[activeStageIdx] || nodes[0];
    if (detailEl && node) {
      detailEl.innerHTML = `
        <div class="sim-pipe-head">
          <strong>${escapeHtml(node.step)} · ${escapeHtml(node.name)}</strong>
          <span class="pill primary">${escapeHtml(node.badge)}</span>
        </div>
        <p>${escapeHtml(node.detail)}</p>
      `;
    }
  }

  function drawScene(ctx, w, h) {
    const isDark = document.documentElement.dataset.theme === 'dark';
    const bgTop = isDark ? '#080e19' : '#0f1829';
    const bgBot = isDark ? '#0d1626' : '#16233b';
    const grd = ctx.createLinearGradient(0, 0, 0, h);
    grd.addColorStop(0, bgTop);
    grd.addColorStop(1, bgBot);
    ctx.fillStyle = grd;
    ctx.fillRect(0, 0, w, h);

    // Subtle scientific grid
    ctx.strokeStyle = 'rgba(138, 186, 255, 0.065)';
    ctx.lineWidth = 1;
    const step = 28;
    for (let x = step; x < w; x += step) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
    for (let y = step; y < h; y += step) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    // 1T1C Schematic Cross-Section Layers
    const siTop = h * 0.31;
    const subFill = ctx.createLinearGradient(0, siTop, 0, h);
    subFill.addColorStop(0, 'rgba(34, 58, 96, 0.42)');
    subFill.addColorStop(1, 'rgba(16, 28, 50, 0.72)');
    ctx.fillStyle = subFill;
    ctx.fillRect(w * 0.06, siTop, w * 0.88, h * 0.62);
    ctx.strokeStyle = 'rgba(138, 186, 255, 0.24)';
    ctx.strokeRect(w * 0.06, siTop, w * 0.88, h * 0.62);

    // Deep Trench Storage Node (SN)
    const snX = w * 0.30;
    const snY = h * 0.24;
    const snW = w * 0.13;
    const snH = h * 0.36;
    ctx.fillStyle = 'rgba(0, 145, 234, 0.22)';
    ctx.fillRect(snX, snY, snW, snH);
    ctx.strokeStyle = 'rgba(126, 183, 255, 0.65)';
    ctx.lineWidth = 1.4;
    ctx.strokeRect(snX, snY, snW, snH);

    // Wordline Gate (WL)
    const wlX = w * 0.46;
    const wlY = h * 0.20;
    const wlW = w * 0.11;
    const wlH = h * 0.11;
    ctx.fillStyle = 'rgba(110, 224, 180, 0.22)';
    ctx.fillRect(wlX, wlY, wlW, wlH);
    ctx.strokeStyle = 'rgba(110, 224, 180, 0.7)';
    ctx.strokeRect(wlX, wlY, wlW, wlH);

    // Bitline BL & Neutral Reference Cell (D1 highlighted)
    const blX = w * 0.62;
    const blY = h * 0.24;
    const blW = w * 0.14;
    const blH = h * 0.12;
    ctx.fillStyle = activePreset === 'd1' ? 'rgba(207, 186, 255, 0.26)' : 'rgba(255, 197, 122, 0.16)';
    ctx.fillRect(blX, blY, blW, blH);
    ctx.strokeStyle = activePreset === 'd1' ? 'rgba(207, 186, 255, 0.85)' : 'rgba(255, 197, 122, 0.55)';
    ctx.strokeRect(blX, blY, blW, blH);

    // Architectural labels
    ctx.font = '600 10.5px "Cascadia Mono", Consolas, monospace';
    ctx.fillStyle = 'rgba(216, 230, 255, 0.85)';
    ctx.fillText('SN Capacitor', snX + 4, snY - 6);
    ctx.fillStyle = 'rgba(110, 224, 180, 0.9)';
    ctx.fillText('WL', wlX + wlW * 0.32, wlY - 6);
    ctx.fillStyle = activePreset === 'd1' ? 'rgba(207, 186, 255, 0.95)' : 'rgba(255, 197, 122, 0.88)';
    ctx.fillText(activePreset === 'd1' ? 'BL / Neutral Ref' : 'Bitline BL', blX + 4, blY - 6);
    ctx.fillStyle = 'rgba(158, 176, 200, 0.72)';
    ctx.fillText('Si P-Well Substrate', w * 0.08, h * 0.89);

    const prog = Math.min(1, simState.progress);

    // Draw D1 common-mode / differential waves when in d1 mode
    if (activePreset === 'd1') {
      const waveY = h * 0.66;
      ctx.save();
      ctx.beginPath();
      for (let i = 0; i <= 48; i += 1) {
        const u = i / 48;
        const px = w * 0.12 + u * (w * 0.44);
        const pulse = Math.exp(-Math.pow((u - 0.42) * 5.2, 2)) * 22 * Math.sin(prog * Math.PI * 0.65);
        const py = waveY - pulse;
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.strokeStyle = 'rgba(255, 143, 112, 0.78)';
      ctx.lineWidth = 1.8;
      ctx.stroke();

      ctx.beginPath();
      for (let i = 0; i <= 48; i += 1) {
        const u = i / 48;
        const px = w * 0.12 + u * (w * 0.44);
        const net = Math.exp(-Math.pow((u - 0.55) * 6.5, 2)) * 9 * prog;
        const py = waveY + 18 - net;
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.strokeStyle = '#6ee0b4';
      ctx.lineWidth = 2.2;
      ctx.stroke();

      ctx.font = '600 10px "Cascadia Mono", Consolas, monospace';
      ctx.fillStyle = 'rgba(255, 143, 112, 0.9)';
      ctx.fillText('Fixed Ref: +12.5 mV', w * 0.12, waveY - 26);
      ctx.fillStyle = '#6ee0b4';
      ctx.fillText('Matched Net: -0.26 mV CM · 4.69 mV Signal', w * 0.12, waveY + 34);
      ctx.restore();
    }

    // Draw primary particle track
    if (simState.primaryPath.length >= 2) {
      const p0 = simState.primaryPath[0];
      const pv = simState.primaryPath[1];
      const p2 = simState.primaryPath[2];

      const primarySeg = Math.min(1, prog * 2.2);
      const cx = (p0.x + (pv.x - p0.x) * primarySeg) * w;
      const cy = (p0.y + (pv.y - p0.y) * primarySeg) * h;

      ctx.save();
      ctx.shadowColor = activePreset === 'v3' ? '#6ee0b4' : '#7eb7ff';
      ctx.shadowBlur = 10;
      ctx.strokeStyle = activePreset === 'v3' ? '#6ee0b4' : '#7eb7ff';
      ctx.lineWidth = activePreset === 'v3' ? 2.8 : 2.1;
      ctx.beginPath();
      ctx.moveTo(p0.x * w, p0.y * h);
      ctx.lineTo(cx, cy);
      ctx.stroke();

      if (p2 && prog > 0.42) {
        const tailSeg = Math.min(1, (prog - 0.42) * 1.9);
        ctx.globalAlpha = 0.65;
        ctx.beginPath();
        ctx.moveTo(pv.x * w, pv.y * h);
        ctx.lineTo((pv.x + (p2.x - pv.x) * tailSeg) * w, (pv.y + (p2.y - pv.y) * tailSeg) * h);
        ctx.stroke();
      }
      ctx.restore();
    }

    // Nuclear reaction vertex & secondary tracks (v4)
    if (simState.vertex && prog > 0.35) {
      const secProg = Math.min(1, (prog - 0.35) * 1.55);
      const vx = simState.vertex.x * w;
      const vy = simState.vertex.y * h;

      simState.pulseRings.forEach(ring => {
        const radius = 6 + secProg * 36;
        ctx.beginPath();
        ctx.arc(vx, vy, radius, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(138, 186, 255, ${(1 - secProg * 0.72).toFixed(2)})`;
        ctx.lineWidth = 1.4;
        ctx.stroke();
      });

      simState.secondaries.forEach(s => {
        const sx = s.x0 * w;
        const sy = s.y0 * h;
        const ex = (s.x0 + (s.x1 - s.x0) * secProg) * w;
        const ey = (s.y0 + (s.y1 - s.y0) * secProg) * h;
        ctx.save();
        ctx.strokeStyle = s.color;
        ctx.lineWidth = s.width;
        ctx.shadowColor = s.color;
        ctx.shadowBlur = 8;
        ctx.beginPath();
        ctx.moveTo(sx, sy);
        ctx.lineTo(ex, ey);
        ctx.stroke();
        if (secProg > 0.65) {
          ctx.shadowBlur = 0;
          ctx.font = '700 10px "Cascadia Mono", Consolas, monospace';
          ctx.fillStyle = s.color;
          ctx.fillText(s.label, ex + 4, ey - 2);
        }
        ctx.restore();
      });

      // Glowing vertex core
      ctx.beginPath();
      ctx.arc(vx, vy, 4.2, 0, Math.PI * 2);
      ctx.fillStyle = '#ffffff';
      ctx.fill();
    }

    // Charge funneling packets drifting into SN
    if (prog > 0.25) {
      simState.charges.forEach(c => {
        const local = Math.max(0, Math.min(1, (prog - 0.22 - c.delay) * 1.65));
        if (local <= 0 || local >= 1) return;
        const eased = 1 - Math.pow(1 - local, 2.2);
        const cx = (c.sx + (c.tx - c.sx) * eased) * w;
        const cy = (c.sy + (c.ty - c.sy) * eased) * h;
        ctx.beginPath();
        ctx.arc(cx, cy, 2.3, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(110, 224, 180, ${(1 - local * 0.35).toFixed(2)})`;
        ctx.fill();
      });
    }

    // Bottom-right mini oscilloscope waveform overlay
    const scopeW = Math.min(154, w * 0.34);
    const scopeH = 44;
    const scopeX = w - scopeW - 12;
    const scopeY = h - scopeH - 12;
    ctx.fillStyle = 'rgba(7, 13, 24, 0.78)';
    ctx.fillRect(scopeX, scopeY, scopeW, scopeH);
    ctx.strokeStyle = 'rgba(138, 186, 255, 0.28)';
    ctx.lineWidth = 1;
    ctx.strokeRect(scopeX, scopeY, scopeW, scopeH);

    ctx.beginPath();
    const samples = 36;
    for (let i = 0; i <= samples; i += 1) {
      const u = i / samples;
      const sx = scopeX + 6 + u * (scopeW - 12);
      const amp = activePreset === 'd1' ? 5 : activePreset === 'v3' ? 20 : 15;
      const envelope = u < 0.22 ? 0 : Math.exp(-(u - 0.22) * 3.8) * (1 - Math.exp(-(u - 0.22) * 18));
      const sy = scopeY + 12 + envelope * amp * prog;
      if (i === 0) ctx.moveTo(sx, sy);
      else ctx.lineTo(sx, sy);
    }
    ctx.strokeStyle = '#7eb7ff';
    ctx.lineWidth = 1.7;
    ctx.stroke();

    ctx.font = '600 9.5px "Cascadia Mono", Consolas, monospace';
    ctx.fillStyle = 'rgba(216, 230, 255, 0.76)';
    ctx.fillText('ΔV_SN Transient', scopeX + 6, scopeY + scopeH - 5);
  }

  function renderCanvasFrame() {
    if (!canvasEl || destroyed) return;
    const rect = canvasEl.getBoundingClientRect();
    if (rect.width < 10 || rect.height < 10) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const targetW = Math.round(rect.width * dpr);
    const targetH = Math.round(rect.height * dpr);
    if (canvasEl.width !== targetW || canvasEl.height !== targetH) {
      canvasEl.width = targetW;
      canvasEl.height = targetH;
    }
    const ctx = canvasEl.getContext('2d');
    if (!ctx) return;
    ctx.save();
    ctx.scale(dpr, dpr);
    drawScene(ctx, rect.width, rect.height);
    ctx.restore();
  }

  function ensureAnimationLoop() {
    cancelAnimationFrame(rafId);
    const tick = () => {
      if (destroyed) return;
      if (simState.progress < 1) {
        simState.progress = Math.min(1, simState.progress + 0.022);
      }
      renderCanvasFrame();
      if (simState.progress < 1) {
        rafId = requestAnimationFrame(tick);
      }
    };
    rafId = requestAnimationFrame(tick);
  }

  function renderHtml() {
    const h = copy[currentLang].hero;
    return `
      <div class="sim-stage-card">
        <div class="sim-stage-head">
          <div class="sim-title-wrap">
            <strong>${escapeHtml(h.blueprintTitle)}</strong>
            <span class="sim-demo-badge">${escapeHtml(h.simDemoBadge)}</span>
          </div>
          <div class="sim-head-actions">
            <span class="sim-hud-counter mono" id="simEventCounter">#01</span>
            <button type="button" class="sim-fire-btn" id="simFireBtn">
              ${icon('radiation')}
              <span>${escapeHtml(h.simFireBtn)}</span>
            </button>
          </div>
        </div>

        <div class="pill-track sim-preset-track" id="simPresetTrack" role="tablist" aria-label="${escapeHtml(h.blueprintTitle)}">
          <span class="pill-thumb" aria-hidden="true"></span>
          ${h.simPresets.map(p => `
            <button
              type="button"
              role="tab"
              class="pill-tab ${p.id === activePreset ? 'is-active' : ''}"
              aria-selected="${String(p.id === activePreset)}"
              data-pill-value="${p.id}">
              ${escapeHtml(p.label)}
            </button>
          `).join('')}
        </div>

        <div class="sim-canvas-wrap">
          <canvas id="dramSimCanvas" aria-label="${escapeHtml(h.blueprintTitle)}"></canvas>
          <span class="sim-canvas-hint">${escapeHtml(h.simClickHint)}</span>
        </div>

        <div class="sim-telemetry-bar">
          <div>
            <span id="simStatALabel">${escapeHtml(getPresetCopy(activePreset).statLabel)}</span>
            <strong class="sim-hud-val mono" id="simStatAVal">--</strong>
          </div>
          <div>
            <span>${escapeHtml(h.simNodeDropLabel)}</span>
            <strong class="sim-hud-val mono" id="simStatBVal">--</strong>
          </div>
          <div>
            <span>${escapeHtml(h.simReadoutLabel)}</span>
            <strong class="sim-hud-val mono" id="simStatCVal">--</strong>
          </div>
        </div>

        <p class="sim-preset-caption" id="simPresetCaption">${escapeHtml(getPresetCopy(activePreset).caption)}</p>

        <div class="sim-pipeline-row" role="group" aria-label="${escapeHtml(h.blueprintHint)}">
          ${h.nodes.map((n, idx) => `
            <button
              type="button"
              class="sim-pipe-btn ${idx === activeStageIdx ? 'is-active' : ''}"
              aria-pressed="${String(idx === activeStageIdx)}"
              data-pipe-idx="${idx}">
              <span class="mono">${escapeHtml(n.step)}</span>
              <strong>${escapeHtml(n.name)}</strong>
            </button>
          `).join('')}
        </div>

        <div class="sim-pipe-detail" id="simPipeDetail"></div>
      </div>
    `;
  }

  function mount(slot, nextLang = currentLang) {
    currentLang = nextLang;
    containerEl = slot;
    if (!containerEl) return;
    containerEl.innerHTML = renderHtml();
    canvasEl = containerEl.querySelector('#dramSimCanvas');

    const track = containerEl.querySelector('#simPresetTrack');
    bindSlidingPill(track, val => {
      activePreset = val;
      activeStageIdx = val === 'v4' ? 0 : val === 'v3' ? 1 : 2;
      triggerStrike(0.46, 0.44, val);
    });
    syncSlidingThumb(track, { activeSelector: '.pill-tab.is-active' });

    containerEl.querySelector('#simFireBtn')?.addEventListener('click', () => {
      const jitterX = 0.34 + Math.random() * 0.32;
      const jitterY = 0.34 + Math.random() * 0.32;
      triggerStrike(jitterX, jitterY);
    });

    canvasEl?.addEventListener('click', event => {
      const rect = canvasEl.getBoundingClientRect();
      const nx = (event.clientX - rect.left) / Math.max(1, rect.width);
      const ny = (event.clientY - rect.top) / Math.max(1, rect.height);
      triggerStrike(nx, ny);
    });

    containerEl.querySelectorAll('.sim-pipe-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        activeStageIdx = Number(btn.dataset.pipeIdx) || 0;
        syncPipelineTicker();
      });
    });

    resizeObserver?.disconnect();
    if (typeof ResizeObserver !== 'undefined' && canvasEl) {
      resizeObserver = new ResizeObserver(() => renderCanvasFrame());
      resizeObserver.observe(canvasEl);
    }

    syncHud();
    syncPipelineTicker();
    if (strikeCount === 0) {
      clearTimeout(autoDemoTimer);
      autoDemoTimer = setTimeout(() => triggerStrike(0.46, 0.44, activePreset), 220);
    } else {
      renderCanvasFrame();
    }
  }

  function redrawTheme() {
    renderCanvasFrame();
  }

  function destroy() {
    destroyed = true;
    clearTimeout(autoDemoTimer);
    cancelAnimationFrame(rafId);
    resizeObserver?.disconnect();
  }

  return { mount, redrawTheme, destroy };
}
