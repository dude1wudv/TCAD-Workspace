import '@material/web/labs/card/outlined-card.js';
import '@material/web/labs/card/filled-card.js';
import '@material/web/switch/switch.js';
import { escapeHtml } from '../shared/site-shell.js';
import { bindSlidingPill, syncSlidingThumb } from '../shared/sliding-pill.js';
import { icon } from '../shared/icons.js';

let scenarioTimer = 0;

export function mountAgentArchitecture(root, copy, state, onRedraw) {
  clearTimeout(scenarioTimer);

  const arch = copy.arch;
  const activeTabIndex = state.archTab ?? 0;
  const activeNodeId = state.archNode ?? 'controller';
  const showGuardrails = Boolean(state.showGuardrails);
  const currentTab = arch.tabs[activeTabIndex] || arch.tabs[0];
  const nodes = arch.topology.nodes;
  const scenarios = arch.topology.scenarios || [];
  const activeScenarioId = state.archScenario || scenarios[0]?.id || 'admission';
  const scenario = scenarios.find(s => s.id === activeScenarioId) || scenarios[0];
  const steps = scenario?.steps || [];
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let activeStepIdx = Number.isInteger(state.archStep)
    ? Math.min(Math.max(0, state.archStep), Math.max(0, steps.length - 1))
    : (reducedMotion ? Math.max(0, steps.length - 1) : 0);

  const selectedNode = nodes.find(n => n.id === activeNodeId) || nodes[1];

  const toneColor = tone => ({
    primary: 'var(--primary)',
    violet: 'var(--violet)',
    teal: 'var(--teal)',
    good: 'var(--good)',
    warn: 'var(--warn)'
  }[tone] || 'var(--primary)');

  const toneBg = tone => ({
    primary: 'var(--primary-container)',
    violet: 'var(--violet-bg)',
    teal: 'var(--teal-bg)',
    good: 'var(--good-bg)',
    warn: 'var(--warn-bg)'
  }[tone] || 'var(--primary-container)');

  function applyStepHighlight(stepIdx) {
    activeStepIdx = stepIdx;
    state.archStep = stepIdx;
    const step = steps[stepIdx];
    if (!step || !root.isConnected) return;

    root.querySelectorAll('.topo-node').forEach(nodeEl => {
      const hit = step.nodes.includes(nodeEl.dataset.topoNode);
      nodeEl.classList.toggle('is-sim-active', hit);
    });

    root.querySelectorAll('.topo-edge-flow').forEach(edgeEl => {
      const hit = edgeEl.dataset.edgeId === step.edge;
      edgeEl.classList.toggle('is-flow-active', hit);
    });

    root.querySelectorAll('.trace-step-btn').forEach((btn, idx) => {
      btn.classList.toggle('is-current', idx === stepIdx);
      btn.classList.toggle('is-done', idx < stepIdx);
      btn.setAttribute('aria-current', idx === stepIdx ? 'step' : 'false');
    });
  }

  function playScenario(fromIdx = 0) {
    clearTimeout(scenarioTimer);
    if (reducedMotion || !steps.length) {
      applyStepHighlight(Math.max(0, steps.length - 1));
      return;
    }
    applyStepHighlight(fromIdx);
    if (fromIdx < steps.length - 1) {
      scenarioTimer = window.setTimeout(() => {
        if (!root.isConnected) return;
        playScenario(fromIdx + 1);
      }, 960);
    }
  }

  root.innerHTML = `
    <div class="section-head">
      <p class="eyebrow">${icon('agent')} ${escapeHtml(arch.eyebrow)}</p>
      <h2>${escapeHtml(arch.title)}</h2>
      <p class="lead">${escapeHtml(arch.lead)}</p>
    </div>

    <div class="arch-layout">
      <md-outlined-card class="arch-topology-card">
        <div class="arch-topology-head">
          <div>
            <h3>${escapeHtml(arch.topology.title)}</h3>
            <p>${escapeHtml(arch.topology.scenarioTitle || arch.topology.subtitle)}</p>
          </div>
          <label class="guardrail-toggle">
            <span>${escapeHtml(arch.guardrailSwitch)}</span>
            <md-switch id="archGuardrailSwitch" ${showGuardrails ? 'selected' : ''} aria-label="${escapeHtml(arch.guardrailSwitch)}"></md-switch>
          </label>
        </div>

        <div class="arch-scenario-bar">
          <div class="pill-track arch-scenario-track" id="archScenarioTrack" role="tablist" aria-label="${escapeHtml(arch.topology.title)}">
            <span class="pill-thumb" aria-hidden="true"></span>
            ${scenarios.map(s => `
              <button
                type="button"
                role="tab"
                class="pill-tab ${s.id === activeScenarioId ? 'is-active' : ''}"
                aria-selected="${String(s.id === activeScenarioId)}"
                data-pill-value="${s.id}">
                ${escapeHtml(s.label)}
              </button>
            `).join('')}
          </div>
          <button type="button" class="arch-replay-btn" id="archReplayBtn" aria-label="${escapeHtml(arch.topology.replayLabel || 'Replay')}">
            ${icon('refresh')}
            <span>${escapeHtml(arch.topology.replayLabel || 'Replay')}</span>
          </button>
        </div>

        <div class="arch-svg-wrap">
          <svg class="arch-topology-svg" viewBox="0 0 820 304" role="img" aria-label="${escapeHtml(arch.topology.title)}">
            <defs>
              <marker id="arrowHead" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 1 L 10 5 L 0 9 z" fill="var(--outline-strong)" />
              </marker>
            </defs>

            <!-- Server Zone -->
            <rect x="16" y="10" width="788" height="134" rx="16" class="zone-box zone-server" />
            <text x="32" y="30" class="zone-caption">ROCKY LINUX 9 · 20-CORE CONTROL PLANE</text>

            <!-- Isolated VM Zone -->
            <rect x="110" y="168" width="600" height="126" rx="16" class="zone-box zone-vm" />
            <text x="128" y="188" class="zone-caption">LOOPBACK-ONLY BOUNDARY · ZERO PUBLIC EXPOSURE</text>

            <!-- Orthogonal Connectors + Directional Scenario Flow -->
            <path d="M 260 85 H 296" class="topo-edge" marker-end="url(#arrowHead)" />
            <path d="M 524 85 H 560" class="topo-edge" marker-end="url(#arrowHead)" />
            <path d="M 410 126 V 154 H 259 V 202" class="topo-edge" marker-end="url(#arrowHead)" />
            <path d="M 674 126 V 154 H 561 V 202" class="topo-edge dashed" marker-end="url(#arrowHead)" />
            <path d="M 390 241 H 430" class="topo-edge" marker-end="url(#arrowHead)" />

            <path d="M 260 85 H 296" data-edge-id="ctrl-pub" class="topo-edge-flow" />
            <path d="M 524 85 H 560" data-edge-id="ctrl-ledger" class="topo-edge-flow" />
            <path d="M 410 126 V 154 H 259 V 202" data-edge-id="ctrl-pool" class="topo-edge-flow" />
            <path d="M 674 126 V 154 H 561 V 202" data-edge-id="vm-ledger" class="topo-edge-flow" />
            <path d="M 390 241 H 430" data-edge-id="pool-vm" class="topo-edge-flow" />

            ${nodes.map(node => {
              const isSelected = node.id === selectedNode.id;
              return `
                <g class="topo-node ${isSelected ? 'is-selected' : ''}" data-topo-node="${node.id}" tabindex="0" role="button" aria-pressed="${isSelected}" aria-label="${escapeHtml(node.label)}">
                  <rect class="topo-card-rect" x="${node.x}" y="${node.y}" width="${node.w}" height="${node.h}" rx="12"
                    fill="${isSelected ? toneBg(node.tone) : 'var(--surface-low)'}"
                    stroke="${isSelected ? toneColor(node.tone) : 'var(--outline-strong)'}"
                    stroke-width="${isSelected ? '2.2' : '1.2'}" />
                  <text x="${node.x + 14}" y="${node.y + 22}" class="topo-kicker" fill="${toneColor(node.tone)}">${escapeHtml(node.kicker)}</text>
                  <text x="${node.x + 14}" y="${node.y + 45}" class="topo-label">${escapeHtml(node.label)}</text>
                  <text x="${node.x + 14}" y="${node.y + 65}" class="topo-sub">${escapeHtml(node.sub)}</text>
                </g>
              `;
            }).join('')}
          </svg>
        </div>

        <div class="arch-trace-grid" id="archTraceStrip" aria-live="polite">
          ${steps.map((st, idx) => `
            <button type="button" class="trace-step-btn ${idx === activeStepIdx ? 'is-current' : idx < activeStepIdx ? 'is-done' : ''}" data-trace-step="${idx}">
              <div class="trace-step-top">
                <span class="trace-step-dot" aria-hidden="true">${icon('check')}</span>
                <strong class="mono">${escapeHtml(st.tag)}</strong>
              </div>
              <p>${escapeHtml(st.text)}</p>
            </button>
          `).join('')}
        </div>

        <div class="topo-detail-bar" aria-live="polite">
          <span class="pill ${selectedNode.tone}">${escapeHtml(selectedNode.kicker)}</span>
          <div>
            <strong>${escapeHtml(selectedNode.label)}</strong>
            <p>${escapeHtml(selectedNode.detail)}</p>
          </div>
        </div>
      </md-outlined-card>

      <div class="arch-tabs-panel">
        <div class="pill-track arch-spec-track" id="archSpecTrack" role="tablist" aria-label="${escapeHtml(arch.title)}">
          <span class="pill-thumb" aria-hidden="true"></span>
          ${arch.tabs.map((tab, idx) => `
            <button
              type="button"
              role="tab"
              class="pill-tab ${idx === activeTabIndex ? 'is-active' : ''}"
              aria-selected="${String(idx === activeTabIndex)}"
              data-pill-value="${idx}">
              ${escapeHtml(tab.label)}
            </button>
          `).join('')}
        </div>
        <p class="arch-tab-summary">${escapeHtml(currentTab.summary)}</p>
        <div class="arch-cards-grid">
          ${currentTab.cards.map(card => `
            <md-filled-card class="arch-detail-card reveal-item ${showGuardrails ? 'show-guardrails' : ''}">
              <div class="arch-card-inner">
                <div class="arch-card-head">
                  <h3>${escapeHtml(card.title)}</h3>
                  <span class="pill ${card.tone}">${escapeHtml(card.badge)}</span>
                </div>
                <ul class="arch-points">
                  ${card.points.map(pt => `<li>${escapeHtml(pt)}</li>`).join('')}
                </ul>
                <div class="arch-guardrail">
                  ${icon('shield')}
                  <span>${escapeHtml(card.guardrail)}</span>
                </div>
              </div>
            </md-filled-card>
          `).join('')}
        </div>
      </div>
    </div>
  `;

  const scenarioTrack = root.querySelector('#archScenarioTrack');
  bindSlidingPill(scenarioTrack, id => {
    state.archScenario = id;
    state.archStep = 0;
    onRedraw();
  });
  syncSlidingThumb(scenarioTrack, { activeSelector: '.pill-tab.is-active' });

  const specTrack = root.querySelector('#archSpecTrack');
  bindSlidingPill(specTrack, idxStr => {
    state.archTab = Number(idxStr) || 0;
    onRedraw();
  });
  syncSlidingThumb(specTrack, { activeSelector: '.pill-tab.is-active' });

  root.querySelector('#archReplayBtn')?.addEventListener('click', () => {
    playScenario(0);
  });

  root.querySelectorAll('[data-trace-step]').forEach(btn => {
    btn.addEventListener('click', () => {
      clearTimeout(scenarioTimer);
      applyStepHighlight(Number(btn.dataset.traceStep) || 0);
    });
  });

  root.querySelector('#archGuardrailSwitch')?.addEventListener('change', event => {
    state.showGuardrails = event.currentTarget.selected;
    root.querySelectorAll('.arch-detail-card').forEach(card => {
      card.classList.toggle('show-guardrails', state.showGuardrails);
    });
  });

  root.querySelectorAll('[data-topo-node]').forEach(el => {
    const activate = () => {
      clearTimeout(scenarioTimer);
      state.archNode = el.dataset.topoNode;
      onRedraw();
    };
    el.addEventListener('click', activate);
    el.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        activate();
      }
    });
  });

  playScenario(activeStepIdx);
}
