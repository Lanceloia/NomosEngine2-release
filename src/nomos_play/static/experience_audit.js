"use strict";

window.NomosExperienceAudit = (() => {
  const palette = ['#216e59', '#b04c43', '#326da8', '#8858a0', '#92720b', '#1b7e89', '#75513b', '#565c66'];
  const number = value => Number(value.toFixed(2));
  const signed = value => `${value > 0 ? '+' : ''}${number(value)}`;
  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  function svgNode(tag, attributes, text) {
    const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, String(value));
    if (text !== undefined) element.textContent = text;
    return element;
  }
  function iconButton(title, icon, action, disabled = false) {
    const button = node('button', undefined, 'secondary icon-button');
    button.type = 'button'; button.title = title; button.setAttribute('aria-label', title);
    button.append(window.NomosIcon(icon)); button.onclick = action; button.disabled = disabled;
    return button;
  }
  function render(root, audit, context, navigate) {
    if (root.auditState?.actor !== audit.actor) root.auditState = {actor:audit.actor};
    const state = root.auditState;
    if (state.point === undefined || !audit.entries.some(entry => entry.index === state.point)) state.point = audit.offset;
    const typed = item => window.NomosWidgets.render(item.data, item.format, {...context, historical:true, fieldLabels:true});
    const parameters = items => {
      const part = node('div', undefined, 'experience-parameters');
      for (const item of items) part.append(node('span', item.label + '：'), typed(item));
      return part;
    };
    function go(index) {
      state.point = index; state.option = null; state.family = null; state.expanded = false;
      const point = audit.timeline.points[index];
      if (point.page !== audit.offset) navigate(point.page);
      else paint();
    }
    function chart() {
      const section = node('section', undefined, 'experience-timeline');
      section.append(node('h4', '心理评分时间图'));
      const controls = node('div', undefined, 'audit-chart-controls');
      const label = node('label', '查看维度'), select = node('select');
      for (const track of [{id:'',title:'行动评分 · 全部'},
        ...audit.timeline.tracks.map(track=>({...track,title:'行动评分 · '+track.title})),
        ...audit.timeline.judgments.map(track=>({...track,title:'局势判断 · '+track.title}))]) {
        const option = node('option', track.title); option.value = track.id; select.append(option);
      }
      select.value = state.track || '';
      select.onchange = () => {state.track = select.value; paint();};
      label.append(select); controls.append(label); section.append(controls);
      const judgment = state.track?.startsWith('judgment:');
      const available = judgment ? audit.timeline.judgments : audit.timeline.tracks;
      const tracks = available.filter(track => !state.track || track.id === state.track);
      const points = audit.timeline.points;
      const at = (point, track) => (judgment ? point.judgments : point.values)[track.id];
      const values = points.flatMap(point => tracks.map(track => at(point, track)).filter(value => value !== undefined));
      if (!judgment) values.push(...points.filter(point => tracks.some(track => track.id === point.selected)).map(point => point.selected_value));
      const low = Math.min(0, ...values), high = Math.max(1, ...values), span = high - low;
      const width = Math.max(680, root.clientWidth || 0, 70 + points.length * 30), height = 270;
      const x = index => 60 + index * (width - 85) / Math.max(1, points.length - 1);
      const y = value => 20 + (high - value) * 205 / span;
      const scroll = node('div', undefined, 'experience-plot-scroll');
      scroll.dataset.pointX = String(x(state.point));
      const svg = svgNode('svg', {viewBox:`0 0 ${width} ${height}`, width, height, role:'img', 'aria-label':judgment ? '局势判断随本人决策次数的变化' : '各类行动最高评分随本人决策次数的变化'});
      for (const value of [...new Set([low, 0, high])]) {
        svg.append(svgNode('line', {x1:55, x2:width-15, y1:y(value), y2:y(value), stroke:'#cbd4d8', 'stroke-dasharray':value === 0 ? '0' : '4 4'}));
        svg.append(svgNode('text', {x:48, y:y(value)+5, 'text-anchor':'end'}, String(number(value))));
      }
      svg.append(svgNode('line', {x1:x(state.point), x2:x(state.point), y1:15, y2:230, stroke:'#253c37', 'stroke-dasharray':'3 4'}));
      const legend = node('div', undefined, 'experience-legend');
      for (const track of tracks) {
        const color = palette[available.indexOf(track) % palette.length];
        const key = node('span', track.title); key.style.setProperty('--track-color', color); legend.append(key);
        let segment = [];
        const flush = () => {
          if (segment.length > 1) svg.append(svgNode('polyline', {points:segment.join(' '), fill:'none', stroke:color, 'stroke-width':2}));
          segment = [];
        };
        for (const point of points) {
          const value = at(point, track);
          if (value === undefined) {flush(); continue;}
          segment.push(`${x(point.index)},${y(value)}`);
        }
        flush();
        for (const point of points) {
          const value = at(point, track);
          if (value === undefined) continue;
          const selected = judgment || point.selected === track.id && point.selected_value === value;
          const marker = svgNode('circle', {cx:x(point.index), cy:y(value), r:selected ? 5 : 3, fill:selected ? color : '#fff', stroke:color, 'stroke-width':2});
          marker.append(svgNode('title', {}, `第${point.index+1}次 · #${point.occurrence} · ${track.title} ${signed(value)}${!judgment && selected ? ' · 已选择' : ''}`));
          marker.onclick = () => go(point.index); svg.append(marker);
          if (!judgment && point.selected === track.id && point.selected_value !== value) {
            const chosen = svgNode('circle', {cx:x(point.index), cy:y(point.selected_value), r:5, fill:color, stroke:color, 'stroke-width':2});
            chosen.append(svgNode('title', {}, `第${point.index+1}次 · #${point.occurrence} · ${track.title} ${signed(point.selected_value)} · 已选择`));
            chosen.onclick = () => go(point.index); svg.append(chosen);
          }
        }
      }
      const interval = Math.max(1, Math.ceil(points.length / 12));
      points.forEach(point => {
        if (point.index % interval === 0 || point.index === points.length - 1) svg.append(svgNode('text', {x:x(point.index), y:250, 'text-anchor':'middle'}, String(point.index+1)));
      });
      scroll.append(svg); section.append(scroll, legend);
      section.append(node('p', judgment ? '横轴：本人第几次决策 · 纵轴：当时记录的局势判断值' : '横轴：本人第几次决策 · 折线：每类行动当时的最高评分 · 实心点：实际选择分', 'cognition-status'));
      section.append(node('small', judgment ? '每个点对应当时的具体方案；没有记录该项判断时留空。' : '每个点保留当时的目标与理由；空缺表示该类行动未进入当次候选。'));
      const navigation = node('div', undefined, 'experience-scrubber');
      const slider = node('input'); slider.type = 'range'; slider.min = 0; slider.max = Math.max(0, audit.total - 1); slider.step = 1; slider.value = state.point;
      slider.setAttribute('aria-label', '查看第几次决策');
      slider.onchange = () => go(Number(slider.value));
      navigation.append(iconButton('上一次决策', 'back', () => go(state.point-1), state.point === 0), slider,
        iconButton('下一次决策', 'skip-forward', () => go(state.point+1), state.point === audit.total-1),
        node('strong', `${state.point+1} / ${audit.total}`));
      section.append(navigation);
      return section;
    }
    function summary(entry) {
      const chosen = entry.alternatives.find(item => item.selected);
      const section = node('section', undefined, 'experience-summary');
      section.append(node('strong', `这一次，选择了「${chosen.title}」`), parameters(chosen.inputs));
      const delta = chosen.total - chosen.prior;
      section.append(node('p', `当前判断 ${signed(chosen.prior)} 分，参考经历后 ${signed(chosen.total)} 分。`));
      section.append(node('small', delta ? `经历使这个方案的评分${delta > 0 ? '增加' : '减少'} ${number(Math.abs(delta))} 分。` : '适用经历未改变这个方案的总评分。'));
      section.append(node('small', entry.resolution === 'planning' ? '本次按有界规划形成行动意向。' : entry.resolution === 'canonical' ? '多个方案并列最高，本次按声明顺序选中。' : '这是本次评分最高的方案。'));
      const changes = chosen.parts.filter(part => part.weight && part.weighted !== part.baseline);
      if (changes.length) section.append(node('p', '变化主要来自：' + changes.map(part => `${part.label} ${signed(part.weighted-part.baseline)}`).join('，')));
      for (const contribution of entry.contributions.filter(item => item.adjustment).slice(0, 3)) {
        section.append(node('small', `${contribution.past ? '过去' : '本局'}的「${contribution.action}」#${contribution.occurrence}，本次分数调整 ${signed(contribution.adjustment)}。`));
      }
      return section;
    }
    function messages(entry) {
      const section = node('section', undefined, 'experience-received');
      section.append(node('h4', '这次决策前，新收到什么'));
      if (!entry.received.length) section.append(node('p', '与上次决策之间没有新的收件。', 'cognition-status'));
      const earlier = node('details'); earlier.append(node('summary', `更早收到的 ${Math.max(0, entry.received.length-3)} 条信息`));
      entry.received.forEach((receipt, index) => {
        const part = node('div', undefined, 'experience-message');
        part.append(node('strong', `${receipt.occurrence === null ? '开局' : '#'+receipt.occurrence} · ${receipt.label}`), typed(receipt));
        (index < entry.received.length-3 ? earlier : section).append(part);
      });
      if (entry.received.length > 3) section.append(earlier);
      return section;
    }
    function judgments(option) {
      const section = node('section', undefined, 'experience-judgments');
      const motives = option.judgments.filter(item => item.category === 'motive');
      if (motives.length) section.append(node('h4', '想促成什么'));
      for (const item of motives) {
        const row = node('div', undefined, 'experience-judgment');
        row.append(node('span', item.label), typed(item)); section.append(row);
      }
      section.append(node('h4', option.selected ? '当时怎样看局面' : '怎样评价这个方案'));
      const extra = node('details'); extra.append(node('summary', '其他局势判断'));
      const assessments = option.judgments.filter(item => item.category === 'judgment');
      if (!assessments.length) section.append(node('p', option.detailed ? '这项选择没有另行声明局势判断。' : '该备选的详细局势判断未留档。', 'cognition-status'));
      assessments.forEach((item, index) => {
        const row = node('div', undefined, 'experience-judgment');
        row.append(node('span', item.label), typed(item));
        (index < 4 ? section : extra).append(row);
      });
      if (assessments.length > 4) section.append(extra);
      return section;
    }
    function comparison(entry) {
      const section = node('section', undefined, 'experience-competition');
      section.append(node('h4', '下一步的取舍'));
      const selected = entry.alternatives.find(item => item.selected);
      const families = [...new Map(entry.alternatives.map(item => [item.ability, item.title]))];
      if (state.family == null || state.family && !families.some(([id]) => id === state.family)) state.family = selected.ability;
      const controls = node('label', '比较方案 ', 'experience-option-controls'), filter = node('select');
      filter.setAttribute('aria-label', '比较哪类行动');
      for (const [id, title] of [['', '全部行动'], ...families]) {
        const option = node('option', title); option.value = id; filter.append(option);
      }
      filter.value = state.family;
      filter.onchange = () => {state.family = filter.value; state.expanded = false; paint();};
      controls.append(filter); section.append(controls);
      const options = entry.alternatives.filter(item => !state.family || item.ability === state.family);
      const visible = state.expanded ? options : options.filter((item, index) => index < 6 || item.id === state.option);
      const table = node('table'), head = node('thead'), headings = node('tr');
      for (const title of ['行动 / 具体方案', '当前判断', '参考经历后', '']) headings.append(node('th', title));
      head.append(headings); table.append(head);
      const body = node('tbody');
      for (const option of visible) {
        const row = node('tr');
        if (option.id === state.option) row.className = 'focused';
        const title = node('td'); title.append(node('strong', option.title + (option.selected ? ' · 已执行' : '')), parameters(option.inputs));
        if (option.count > 1) title.append(node('small', `本类第${option.rank}方案 · 共${option.count}个候选`));
        const inspect = node('td'); inspect.append(iconButton(`查看${option.title}第${option.rank}方案的评分依据`, 'eye', () => {state.option = option.id; paint();}));
        row.append(title, node('td', signed(option.prior)), node('td', signed(option.total)), inspect); body.append(row);
      }
      table.append(body); section.append(table);
      if (options.length > 6) {
        const more = node('button', state.expanded ? '收起方案' : `展开全部 ${options.length} 个方案`, 'secondary');
        more.type = 'button'; more.onclick = () => {state.expanded = !state.expanded; paint();}; section.append(more);
      }
      return section;
    }
    function dimensions(option) {
      const section = node('section', undefined, 'experience-dimensions');
      section.append(node('h4', `${option.title} · 评分从哪里来`));
      const scale = Math.max(1, ...option.parts.flatMap(part => [Math.abs(part.baseline), Math.abs(part.weighted)]));
      const legend = node('p', '浅色：当前判断　实色：参考经历后的分数', 'cognition-status');
      section.append(legend);
      for (const part of option.parts) {
        if (part.weight === 0) {
          const observation = node('p', `${part.label} · 估计值 ${signed(part.prior)} → ${signed(part.expected)} · 权重 0`, 'cognition-status');
          section.append(observation); continue;
        }
        const row = node('div', undefined, 'experience-dimension');
        const bars = node('div', undefined, 'experience-bars');
        for (const [value, tone] of [[part.baseline,'baseline'],[part.weighted,'expected']]) {
          const bar = node('span', undefined, tone + (value < 0 ? ' negative' : ''));
          bar.style.setProperty('left', `${50 + Math.min(0,value) / scale * 50}%`);
          bar.style.setProperty('width', `${Math.abs(value) / scale * 50}%`);
          bars.append(bar);
        }
        row.append(node('span', part.label), bars, node('strong', `${signed(part.baseline)} → ${signed(part.weighted)}`));
        row.title = `预测值 ${number(part.expected)} × 权重 ${part.weight}`; section.append(row);
      }
      section.append(node('p', `总分 ${signed(option.prior)} → ${signed(option.total)} · 经验净影响 ${signed(option.total-option.prior)}`, 'experience-total'));
      return section;
    }
    function provenance(entry) {
      const section = node('details', undefined, 'experience-provenance');
      section.append(node('summary', '实际选择的完整依据与经验出处'));
      const motives = node('p', entry.goals.map(item => `${item.label} × ${item.weight}`).join('，'));
      section.append(node('h4', '本局目标'), motives);
      if (entry.personality.length) section.append(node('p', '行事倾向：' + entry.personality.map(item => `${item.label} × ${item.weight}`).join('，')));
      for (const item of entry.explanations) {
        const detail = node('details'); detail.append(node('summary', item.label), typed(item)); section.append(detail);
      }
      section.append(node('h4', '实际参考的经验'));
      if (!entry.contributions.length) section.append(node('p', '这次选择依据当前判断。'));
      for (const contribution of entry.contributions) {
        const part = node('details');
        part.append(node('summary', `${contribution.past ? '过去' : '本局'}第${contribution.game}局 · ${contribution.action} #${contribution.occurrence}`));
        part.append(node('p', '那次经历的实际反馈：' + contribution.results.map(item => `${item.label} ${signed(item.value)}`).join('，')));
        part.append(node('p', '对本次方案的评分调整：' + signed(contribution.adjustment)));
        part.append(node('p', `相似度 ${Math.round(contribution.similarity*100)}% · 独立权重 ` + contribution.independence.map(item => `${item.label} ${item.value}`).join('，')));
        part.append(node('small', '实际反馈：' + contribution.evidence.map(item => `${context.labels?.[item.channel] || item.channel} #${item.occurrence}`).join('，')));
        section.append(part);
      }
      section.append(node('p', entry.resolution === 'planning' ? '按有界规划选中，比较范围为本次实际考虑的方案。' : entry.resolution === 'canonical' ? '最高分相同，按声明顺序决议。' : '选择当时唯一最高分。'));
      section.append(node('small', '行动来源：' + entry.source));
      return section;
    }
    function paint() {
      root.replaceChildren();
      root.append(node('h4', '从信息到选择'));
      root.append(node('p', `参与${audit.participations}局 · 累计${audit.samples}项回顾 · 本局${audit.total}次选择`, 'cognition-status'));
      if (!audit.total) {root.append(node('p', '本局还没有自主决策记录。')); return;}
      const entry = audit.entries.find(item => item.index === state.point);
      const option = entry.alternatives.find(item => item.id === state.option) || entry.alternatives.find(item => item.selected);
      state.option = option.id;
      if (state.track === undefined) state.track = entry.alternatives.find(item => item.selected).ability;
      root.append(summary(entry), chart());
      const focused = node('section', undefined, 'experience-decision');
      focused.append(node('h4', `第${entry.index+1}次决策 · #${entry.occurrence} · ${entry.title}`), parameters(entry.inputs));
      const layout = node('div', undefined, 'experience-decision-layout');
      const basis = node('div'); basis.append(messages(entry), judgments(option));
      const choice = node('div'); choice.append(comparison(entry), dimensions(option));
      layout.append(basis, choice); focused.append(layout, provenance(entry)); root.append(focused);
      const scroll = root.querySelector('.experience-plot-scroll');
      scroll.scrollLeft = Math.max(0, Number(scroll.dataset.pointX) - scroll.clientWidth/2);
      if (audit.pending_feedback) root.append(node('p', `${audit.pending_feedback}项选择仍待对应反馈。`, 'cognition-status'));
    }
    paint();
  }
  return {render};
})();
