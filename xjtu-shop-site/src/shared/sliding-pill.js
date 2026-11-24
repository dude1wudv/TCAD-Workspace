export function syncSlidingThumb(track, { activeSelector = '.is-active', scrollIntoView = false } = {}) {
  if (!track) return;
  const thumb = track.querySelector('.pill-thumb, .stage-thumb');
  const active = track.querySelector(activeSelector);
  if (!thumb || !active) return;

  const measure = () => {
    if (!track.isConnected || !active.isConnected) return;
    const width = active.offsetWidth;
    const left = active.offsetLeft;
    if (width <= 0) return;
    track.style.setProperty('--thumb-x', `${left}px`);
    track.style.setProperty('--thumb-w', `${width}px`);
    track.classList.add('is-ready');

    if (scrollIntoView && track.scrollWidth > track.clientWidth + 4) {
      const targetLeft = Math.max(0, left - (track.clientWidth - width) / 2);
      track.scrollTo({ left: targetLeft, behavior: 'smooth' });
    }
  };

  requestAnimationFrame(measure);
}

export function bindSlidingPill(track, onSelect, { buttonSelector = '[data-pill-value]', scrollActiveOnSelect = true } = {}) {
  if (!track) return null;

  const update = (scroll = false) => syncSlidingThumb(track, { activeSelector: `${buttonSelector}.is-active`, scrollIntoView: scroll });

  track.addEventListener('click', event => {
    const btn = event.target instanceof Element ? event.target.closest(buttonSelector) : null;
    if (!btn || !track.contains(btn)) return;
    const value = btn.dataset.pillValue ?? btn.dataset.viewId ?? btn.dataset.stageId ?? btn.dataset.chartKey ?? btn.dataset.scenarioId ?? btn.dataset.tabKey;
    track.querySelectorAll(buttonSelector).forEach(el => {
      const isMatch = el === btn;
      el.classList.toggle('is-active', isMatch);
      el.setAttribute('aria-selected', String(isMatch));
      el.setAttribute('aria-pressed', String(isMatch));
    });
    update(scrollActiveOnSelect);
    if (onSelect) onSelect(value, btn);
  });

  if (typeof ResizeObserver !== 'undefined') {
    const ro = new ResizeObserver(() => update(false));
    ro.observe(track);
    track.querySelectorAll(buttonSelector).forEach(btn => ro.observe(btn));
  } else {
    window.addEventListener('resize', () => update(false));
  }

  document.fonts?.ready?.then(() => update(false));
  update(false);
  return update;
}
