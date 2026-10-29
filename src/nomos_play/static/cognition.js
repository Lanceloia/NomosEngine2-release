"use strict";

window.NomosCognition = (() => {
  function node(tag, text, className) {
    const result = document.createElement(tag);
    if (text !== undefined) result.textContent = text;
    if (className) result.className = className;
    return result;
  }
  function details(title, content) {
    const root = node("details");
    root.append(node("summary", title), content);
    return root;
  }
  function renderAdvice(root, advice, context) {
    root.replaceChildren();
    root.hidden = !advice;
    if (!advice) return;
    root.append(node("h3", "当前行动建议"));
    if (advice.status !== "proposed") {
      const statuses = {tie:"几项选择得分相同", no_positive_score:"当前没有倾向的选择", no_candidate:"当前没有可评分的选择", closed:"本局已结束", no_opportunity:"等待行动机会"};
      root.append(node("p", statuses[advice.status] || advice.status));
      return;
    }
    root.append(node("strong", advice.action));
    root.append(node("p", "同一行动机会内，参考总分越高，策略越倾向选择。", "cognition-status"));
    for (const input of advice.inputs) {
      const row = node("div", undefined, "advice-input");
      row.append(node("span", input.label), window.NomosWidgets.render(input.data, input.format, context));
      root.append(row);
    }
    for (const [category, title] of [['information','信息依据'],['judgment','局势判断']]) {
      const items = advice.explanations.filter(item => item.category === category);
      if (!items.length) continue;
      const section = node('section', undefined, 'advice-explanation');
      section.append(node('h4', title));
      for (const item of items) {
        const row = node('div', undefined, 'advice-basis');
        row.append(node('span', item.label), window.NomosWidgets.render(item.data, item.format, {...context,fieldLabels:true}));
        section.append(row);
      }
      root.append(section);
    }
    root.append(node('h4', '行为取舍'));
    for (const item of advice.explanations.filter(item => item.category === 'motive')) {
      root.append(details(item.label, window.NomosWidgets.render(item.data,item.format,{...context,fieldLabels:true})));
    }
    const list = node("dl", undefined, "score-parts");
    for (const part of advice.parts) list.append(node("dt", part.label), node("dd", `${part.value > 0 ? "+" : ""}${part.value}`));
    list.append(node("dt", "参考总分"), node("dd", advice.score, "score-total"));
    root.append(list);
  }
  function renderReasoning(root, cognition, context) {
    const graph = cognition.reasoning;
    if (!graph?.active || !graph.current_graph_complete || !graph.arguments.length) return;
    const nodes = new Map([...graph.arguments, ...graph.base_arguments].map(argument => [argument.id, argument]));
    const positions = new Map(graph.arguments.map((argument, index) => [argument.id, index]));
    const list = node("div", undefined, "cognition-reasoning");
    const value = proposition => window.NomosWidgets.render(proposition, cognition.proposition_format, {...context, fieldLabels:true});
    const polarity = name => name === "opposition" ? "反对" : "支持";
    const pageSize = 32, edgeLimit = 256;
    function page(start, focus) {
      list.replaceChildren();
      const entries = [];
      for (const argument of graph.arguments.slice(start, start + pageSize)) {
        const body = node("div");
        const entry = details("", body);
        entry.className = "inference-entry";
        entry.children[0].append(node("span", polarity(argument.polarity)), value(argument.proposition));
        entry.ontoggle = () => {
          body.replaceChildren();
          if (!entry.open) return;
          for (const other of entries) if (other !== entry) {
            other.open = false;
            other.children[1].replaceChildren();
          }
          let remaining = edgeLimit;
          for (const premise of argument.premises) {
            if (remaining-- <= 0) break;
            const item = node("div", undefined, "inference-premise");
            item.append(node("span", polarity(premise.polarity)), value(premise.proposition));
            for (const identity of premise.alternatives) {
              if (remaining-- <= 0) break;
              const parent = nodes.get(identity);
              if (!parent) continue;
              if (parent.occurrence !== undefined) {
                item.append(node("small", `${parent.source}/${parent.slot} · ${parent.occurrence === null ? "开局" : "发生 " + parent.occurrence}`));
              } else {
                const link = node("button", `上游推导：${context.labels?.[parent.relation] || parent.relation}`, "secondary");
                link.type = "button";
                link.onclick = () => page(Math.floor(positions.get(identity) / pageSize) * pageSize, identity);
                item.append(link);
              }
            }
            body.append(item);
          }
          if (remaining < 0) body.append(node("p", "本项依据超过显示预算"));
        };
        entries.push(entry);
        list.append(entry);
        if (argument.id === focus) entry.open = true;
      }
      if (graph.arguments.length > pageSize) {
        const navigation = node("div", undefined, "reasoning-pages");
        const previous = node("button", "上一页", "secondary"), next = node("button", "下一页", "secondary");
        previous.type = next.type = "button";
        previous.disabled = start === 0;
        next.disabled = start + pageSize >= graph.arguments.length;
        previous.onclick = () => page(start - pageSize);
        next.onclick = () => page(start + pageSize);
        navigation.append(previous, node("span", `${start + 1}–${Math.min(start + pageSize, graph.arguments.length)} / ${graph.arguments.length}`), next);
        list.append(navigation);
      }
    }
    page(0);
    root.append(details(`推导依据 · ${graph.arguments.length}`, list));
  }
  function renderLocalBounds(root, cognition, context) {
    if (cognition.local?.status !== "complete" || !cognition.local.complete) return;
    const format = cognition.format.fields?.local?.format?.fields?.bounds?.format?.element;
    if (!format?.fields) return;
    const bounds = cognition.view.local.bounds.filter(bound => bound.members.length &&
      (bound.minimum > 0 || bound.maximum < bound.members.length));
    if (!bounds.length) return;
    const people = context.people || new Map();
    const basic = bound => people.size > 0 && (bound.members.length === people.size &&
      bound.members.every(person => people.has(person.reference)) ||
      bound.members.length === 1 && people.get(bound.members[0].reference)?.self);
    const relevant = bound => (context.focus || []).some(group => group.length === bound.members.length &&
      bound.members.every(person => group.includes(person.reference)));
    const ordered = bounds.filter(bound => !basic(bound)).sort((a, b) => Number(relevant(b)) - Number(relevant(a)));
    const list = node("div", undefined, "cognition-bounds");
    const more = node("div"), basics = node("div");
    function row(bound) {
      const row = node("div", undefined, "bound-summary");
      row.append(window.NomosWidgets.render(bound.members, format.fields.members.format, {...context, historical:true}));
      row.append(window.NomosWidgets.render(bound.category, format.fields.category.format, context));
      row.append(node("strong", bound.minimum === bound.maximum ? `${bound.minimum}` : `${bound.minimum} 至 ${bound.maximum}`));
      return row;
    }
    ordered.forEach((bound, index) => {
      (index < 4 ? list : more).append(row(bound));
    });
    root.append(node("h3", "当前线索下的人数范围"), node("p", "范围表示现有线索允许的最少与最多人数。", "cognition-status"));
    if (ordered.length) root.append(list);
    if (more.childNodes.length) root.append(details(`其余人数范围 · ${ordered.length - 4}`, more));
    for (const bound of bounds.filter(basic)) basics.append(row(bound));
    if (basics.childNodes.length) root.append(details(`身份与全桌基础事实 · ${basics.childNodes.length}`, basics));
  }
  function render(root, cognition, context) {
    root.replaceChildren();
    root.hidden = !cognition;
    if (!cognition) return;
    const heading = node("h2", context.closed ? "终局前的判断" : "我的判断");
    heading.prepend(window.NomosIcon("eye"));
    root.append(heading);
    if (context.closed) root.append(node("p", "下面保留本局结算时形成的判断；完整身份见终局揭晓。", "cognition-status"));
    if (cognition.explanation_complete === false) {
      root.append(node("p", "判断已更新，部分依据待展示", "cognition-status"));
    }
    const finite = cognition.finite;
    const local = cognition.local;
    if (local) {
      const captions = {complete: "局部判断已更新", conflict: "当前线索存在冲突", pending: "判断尚未完成"};
      root.append(node("p", captions[local.status] || local.status, "cognition-status"));
      renderLocalBounds(root, cognition, context);
      const grounds = node("ol", undefined, "cognition-grounds");
      for (const ground of local.grounds) {
        grounds.append(node("li", `${context.labels?.[ground.definition] || ground.definition} · ${ground.occurrence === null ? "开局" : `发生 ${ground.occurrence}`}`));
      }
      root.append(details(`实际依据 · ${local.grounds.length}`, grounds));
      const assumptions = node("ul");
      for (const assumption of local.assumptions || []) assumptions.append(node("li", assumption.description));
      if (assumptions.childNodes.length) root.append(details("分析前提", assumptions));
    }
    if (finite) {
      const captions = {consistent: "相容", inconsistent: "输入与假设不相容", pending: "尚未完成"};
      const status = node("p", captions[finite.status] || finite.status, "cognition-status");
      if (finite.model_count !== null && finite.model_count !== undefined) {
        status.append(node("span", `${finite.model_count} 种相容配置`));
      }
      root.append(status);
      if (finite.reason) {
        const reasons = {missing_inputs: "尚缺实际取得的输入", not_initialized: "等待初始化", preparation_budget: "本轮准备预算已用尽", ValueBudget: "本轮值预算已用尽", explanation_budget: "依据说明超出本次显示预算"};
        root.append(node("p", reasons[finite.reason] || `状态原因：${finite.reason}`));
      }
      const answers = finite.status === "consistent" && finite.complete ? cognition.view.analysis?.answers || [] : [];
      const format = cognition.format.fields?.analysis?.format?.fields?.answers?.format?.element?.fields?.key?.format || {};
      const list = node("ul", undefined, "cognition-answers");
      for (const answer of answers) {
        const item = node("li");
        item.append(window.NomosWidgets.render(answer.key, format, context));
        item.append(node("strong", answer.entailed ? "必然" : answer.possible ? "可能" : "排除"));
        list.append(item);
      }
      if (answers.length) root.append(list);
      const grounds = node("ol", undefined, "cognition-grounds");
      for (const ground of finite.grounds) {
        const occurrence = ground.occurrence === null ? "开局" : `发生 ${ground.occurrence}`;
        grounds.append(node("li", `${context.labels?.[ground.definition] || ground.definition} · ${ground.source}/${ground.slot} · ${occurrence} · ${ground.sample}`));
      }
      root.append(details(`实际依据 · ${finite.grounds.length}`, grounds));
      const assumptions = node("ul");
      for (const assumption of finite.assumptions) assumptions.append(node("li", assumption.description));
      root.append(details("分析假设", assumptions));
    }
    renderReasoning(root, cognition, context);
    root.append(details("高级判断详情", window.NomosWidgets.render(cognition.view, cognition.format, context)));
  }
  return {render, renderAdvice};
})();
