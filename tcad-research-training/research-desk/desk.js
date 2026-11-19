(() => {
  'use strict';

  const byId = id => document.getElementById(id);
  const views = ['query', 'wave', 'audit', 'plan'];
  const viewTabs = byId('view-tabs');
  const motion = matchMedia('(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)');

  function activate(view) {
    viewTabs.activeTabIndex = views.indexOf(view);
    for (const name of views) byId(`${name}-pane`).hidden = name !== view;
  }

  const fields = {
    device: {D0:['D0', '结构零'], D1:['D1', '结构一'], D2:['D2', '结构二'], D3:['D3', '结构三']},
    state: {b0:['b0', '存零', '写零', '状态零', '状态0'], b1:['b1', '存一', '写一', '状态一', '状态1']},
    source: {zero:['无粒子', '零源'], particle:['有粒子', '质子', '中子', '重离子']},
    intent: {point:['归档读点', '读点', '读出裕量', '读出电压', '裕量', '位线电压'], protocol:['协议时刻', '协议核对', '读写协议', '协议'], predict:['模型预测'], holdout:['留出评估']}
  };
  const tokens = Object.entries(fields).flatMap(([key, options]) =>
    Object.entries(options).flatMap(([value, words]) => words.map(word => ({key, value, word: word.toLowerCase()})))
  ).sort((left, right) => right.word.length - left.word.length);

  function parse(text) {
    let rest = text.normalize('NFKC').toLowerCase().trim();
    if (/留出|hold\s*-?\s*out|解封/.test(rest)) return {intent: 'holdout'};
    if (/预测|推断|估算|模型|截面|错误率|\bser\b/.test(rest)) return {intent: 'predict'};
    rest = rest.replace(/^(?:请\s*)?(?:查询|查看|核对|查一下|查)\s*/, '').replace(/[?？。]\s*$/, '');
    const values = {};
    while (rest) {
      const clock = /^(\d+(?:\.\d+)?)\s*(?:ns|纳秒)/.exec(rest);
      const token = clock ? {key:'time', value:Number(clock[1]), word:clock[0]} : tokens.find(item => rest.startsWith(item.word));
      if (!token || Object.hasOwn(values, token.key)) return {};
      values[token.key] = token.value;
      rest = rest.slice(token.word.length).trimStart();
      if (rest.startsWith('的')) {
        rest = rest.slice(1).trimStart();
        if (!tokens.some(item => item.key === 'intent' && rest.startsWith(item.word))) return {};
      } else if (/^[,、]/.test(rest)) {
        rest = rest.slice(1).trimStart();
        if (!rest) return {};
      }
    }
    return values;
  }

  function show(title, reason, tone = 'idle', intent = '') {
    byId('verdict').textContent = title;
    byId('reason').textContent = reason;
    byId('status-icon').textContent = {idle:'i', ok:'✓', stop:'!'}[tone];
    byId('notice').dataset.tone = tone;
    byId('archive-id').hidden = !intent;
    byId('record').hidden = !intent;
    byId('point').hidden = intent !== 'point';
    byId('protocol').open = intent === 'protocol';
    byId('evidence').open = false;
  }

  function evaluate(values) {
    if (values.intent === 'holdout') return show('留出集封存中', '', 'stop');
    if (values.intent === 'predict') return show('模型待训练', '', 'stop');
    if (Object.keys(fields).some(key => !values[key])) return show('请补全查询条件', '', 'stop');
    if ((Object.hasOwn(values, 'time') && (values.time !== 31.9 || values.intent !== 'point')) ||
        values.device !== 'D2' || values.state !== 'b0' || values.source !== 'zero') {
      return show('待归档', '现有归档：D2 · b0 · 无粒子 · 31.9 ns', 'stop');
    }
    show('已找到归档', values.intent === 'point' ? '原始保存点' : '协议时刻', 'ok', values.intent);
  }

  function makeChip(label, onClick) {
    const chip = document.createElement('md-filter-chip');
    chip.label = label;
    chip.addEventListener('click', onClick);
    return chip;
  }

  function initQuery() {
    const phrase = byId('phrase');
    const chips = new Map();
    let current = {};
    let pendingText = false;
    function select(values) {
      current = values;
      for (const [key, options] of chips) {
        for (const [value, chip] of options) chip.selected = current[key] === value;
      }
    }
    function query() {
      pendingText = false;
      select(parse(phrase.value));
      evaluate(current);
    }
    for (const group of document.querySelectorAll('[data-field]')) {
      const key = group.dataset.field;
      const options = new Map();
      chips.set(key, options);
      for (const [value, [label]] of Object.entries(fields[key])) {
        const chip = makeChip(label, () => {
          const values = {...(pendingText ? parse(phrase.value) : current), [key]:value};
          pendingText = false;
          delete values.time;
          select(values);
          phrase.value = ['device','source','state','intent'].filter(field => values[field]).map(field => fields[field][values[field]][0]).join(' ');
          evaluate(current);
        });
        options.set(value, chip);
        group.append(chip);
      }
    }
    byId('parse').addEventListener('click', query);
    phrase.addEventListener('keydown', event => {
      if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return;
      event.preventDefault();
      query();
    });
    phrase.addEventListener('input', () => {
      pendingText = true;
      select({});
      show('待查询', '');
    });
    for (const [id, intent] of [['quick-point','读出裕量'], ['quick-protocol','协议时刻']]) {
      byId(id).addEventListener('click', () => {
        phrase.value = `查询 D2 无粒子 b0 的${intent}`;
        query();
      });
    }
    byId('show-wave').addEventListener('click', () => {
      activate('wave');
      byId('tab-wave').focus();
    });
    const modeButton = byId('mode-button'), modeMenu = byId('mode-menu');
    modeButton.addEventListener('click', () => { modeMenu.open = !modeMenu.open; });
    modeButton.addEventListener('keydown', event => {
      if (event.key === 'Escape' && modeMenu.open) modeMenu.close();
    });
    modeMenu.addEventListener('opening', () => modeButton.setAttribute('aria-expanded', 'true'));
    modeMenu.addEventListener('closing', () => modeButton.setAttribute('aria-expanded', 'false'));
    byId('archive-mode').addEventListener('click', () => { modeMenu.open = false; });
    query();
  }

  function initWave() {
    const trace = window.WHR_TRACE, samples = trace?.samples;
    if (trace?.alias !== 'WHR-01' || !Array.isArray(samples) || samples.length !== 620 ||
        !samples.every((row, index) => Array.isArray(row) && row.length === 4 && row.every(Number.isFinite) &&
          (!index || samples[index-1][0] < row[0]))) return;
    const readIndex = samples.findIndex(row => row[0] === 31.9 && row[1] === Number(byId('read-voltage').textContent));
    if (readIndex < 0 || samples[0][0] !== 0 || samples.at(-1)[0] !== 35) return;
    byId('sample-count').textContent = samples.length;
    const plot = byId('plot'), slider = byId('sample');
    const series = [{col:1,color:'#005cbb',dash:''},{col:2,color:'#006874',dash:'7 3'},{col:3,color:'#943c75',dash:'2 3'}];
    const voltages = samples.flatMap(row => row.slice(1));
    const low = Math.floor(Math.min(...voltages)*10)/10, high = Math.ceil(Math.max(...voltages)*10)/10;
    const times = [[10,'SN2 写低'],[18,'SN1 写低'],[18.1,'写释放'],[18.2,'保持起点候选'],[30,'隔离驱动'],[31.9,'SN1 读出'],[35,'结束']];
    const eventChips = new Map();
    for (const [time, label] of times) {
      const index = samples.findIndex(row => row[0] === time);
      if (index < 0) continue;
      const chip = makeChip(`${time} ns · ${label}`, () => {
        slider.value = index;
        readSample();
      });
      eventChips.set(index, chip);
      byId('event-times').append(chip);
    }
    slider.max = samples.length - 1;
    slider.value = readIndex;
    function svgNode(tag, attributes, text) {
      const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
      for (const [key,value] of Object.entries(attributes)) element.setAttribute(key,value);
      if (text !== undefined) element.textContent = text;
      return element;
    }
    let cursor, dots, horizontal, vertical;
    const readings = [...byId('readings').querySelectorAll('dd')];
    function readSample() {
      const index = Number(slider.value), row = samples[index];
      byId('index-label').textContent = `${index+1} / ${samples.length}`;
      slider.ariaValueTextStart = `第 ${index+1} 个保存点，${row[0]} ns`;
      for (const [eventIndex, chip] of eventChips) chip.selected = eventIndex === index;
      readings.forEach((field,col) => { field.textContent = row[col]; });
      if (!cursor) return;
      const position = horizontal(row[0]);
      cursor.setAttribute('x1',position); cursor.setAttribute('x2',position);
      dots.forEach((dot,seriesIndex) => { dot.setAttribute('cx',position); dot.setAttribute('cy',vertical(row[seriesIndex+1])); });
    }
    function draw() {
      const width = plot.clientWidth, height = plot.clientHeight;
      if (!width || !height) return;
      const left = 43, right = width-16, top = 20, bottom = height-34;
      horizontal = time => left + time/35*(right-left);
      vertical = voltage => bottom - (voltage-low)/(high-low)*(bottom-top);
      plot.setAttribute('viewBox',`0 0 ${width} ${height}`);
      const layer = document.createDocumentFragment();
      for (let tick = 0; tick <= 4; tick++) {
        const voltage = low+(high-low)*tick/4, position = vertical(voltage);
        layer.append(svgNode('line',{x1:left,x2:right,y1:position,y2:position,stroke:'#d9dce5'}),
          svgNode('text',{x:left-4,y:position+4,'text-anchor':'end'},voltage.toFixed(2)));
      }
      for (const time of [0,5,10,15,20,25,30,35]) layer.append(svgNode('text',{x:horizontal(time),y:bottom+16,'text-anchor':'middle'},time));
      layer.append(svgNode('text',{x:8,y:14},'V'),svgNode('text',{x:right,y:height-3,'text-anchor':'end'},'ns'));
      for (const {col,color,dash} of series) layer.append(svgNode('polyline',{points:samples.map(row => `${horizontal(row[0])},${vertical(row[col])}`).join(' '),fill:'none',stroke:color,'stroke-width':2,'stroke-dasharray':dash || 'none'}));
      cursor = svgNode('line',{y1:top,y2:bottom,stroke:'#45474f','stroke-dasharray':'3 4'});
      dots = series.map(({color}) => svgNode('circle',{r:4,fill:color,stroke:'white','stroke-width':1.5}));
      layer.append(cursor,...dots);
      plot.replaceChildren(layer);
      readSample();
    }
    slider.addEventListener('input', readSample);
    plot.addEventListener('click', event => {
      if (!horizontal) return;
      const relative = event.clientX - plot.getBoundingClientRect().left - plot.clientLeft;
      slider.value = samples.reduce((best,row,index) => Math.abs(horizontal(row[0])-relative) < Math.abs(horizontal(samples[best][0])-relative) ? index : best,0);
      readSample();
    });
    readSample();
    byId('scope').hidden = false;
    byId('trace-error').hidden = true;
    new ResizeObserver(draw).observe(plot);
  }

  function initGlass() {
    for (const card of document.querySelectorAll('[data-glass], .filter-group, .parameter-pill')) {
      let frame = 0, lightX, lightY, spring;
      function reset() {
        cancelAnimationFrame(frame);
        frame = 0;
        card.style.removeProperty('--shine');
        spring?.cancel();
      }
      card.addEventListener('pointerenter', event => {
        if (!motion.matches || event.pointerType !== 'mouse') return;
        spring?.cancel();
        spring = card.animate([{transform:'scale(1)'}, {transform:'scale(1.023,.992)'},
          {transform:'scale(.996,1.009)'}, {transform:'scale(1)'}], {duration:350, easing:'ease-out'});
        card.style.setProperty('--shine', '1');
      });
      card.addEventListener('pointermove', event => {
        if (!motion.matches || event.pointerType !== 'mouse') return;
        const rect = card.getBoundingClientRect();
        lightX = event.clientX - rect.left;
        lightY = event.clientY - rect.top;
        if (frame) return;
        frame = requestAnimationFrame(() => {
          frame = 0;
          card.style.setProperty('--light-x', `${lightX}px`);
          card.style.setProperty('--light-y', `${lightY}px`);
        });
      }, {passive:true});
      card.addEventListener('pointerleave', reset);
      motion.addEventListener('change', reset);
    }
  }

  const margin = (0.6 - Number(byId('read-voltage').textContent)) * 1000;
  const sign = margin >= 0 ? '+' : '';
  byId('summary-margin').textContent = `${sign}${margin.toFixed(2)}`;
  byId('margin').append(`${sign}${margin.toFixed(6)} `, Object.assign(document.createElement('small'), {textContent:'mV'}));
  const components = [...new Set([...document.querySelectorAll('*')].map(element => element.localName).filter(name => name.startsWith('md-')))];
  const waiting = setTimeout(() => show('请检查本地组件文件', '', 'stop'), 3000);
  Promise.all(components.map(name => customElements.whenDefined(name))).then(async () => {
    await Promise.all([...document.querySelectorAll(components.join(','))].map(component => component.updateComplete));
    clearTimeout(waiting);
    viewTabs.addEventListener('change', () => activate(views[viewTabs.activeTabIndex]));
    initQuery();
    initWave();
    initGlass();
  });
})();
