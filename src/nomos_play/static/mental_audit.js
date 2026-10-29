"use strict";

window.NomosMentalAudit = (() => {
  function node(tag, text, className) {
    const result = document.createElement(tag);
    if (text !== undefined) result.textContent = text;
    if (className) result.className = className;
    return result;
  }
  const position = point => point.occurrence === null ? "开局" : `#${point.occurrence}`;
  function boundCell(value, point, track) {
    if (!value) return {text:({pending:"待续",conflict:"冲突"}[point.status] || "未形成"), tone:"unknown"};
    if (track.members.length === 1) {
      if (value[0] === 1) return {text:"确定", tone:"certain"};
      if (value[1] === 0) return {text:"排除", tone:"excluded"};
      return {text:"待定", tone:"possible"};
    }
    return {text:(value[0] === value[1] ? value[0] : `${value[0]}–${value[1]}`) + "人", tone:"range"};
  }
  function renderTrend(root, trend, kind, state, typed, label, navigate) {
    if (!trend.points.length) return;
    const isBound = kind === "bounds", tracks = trend.tracks, points = trend.points;
    const section = node("section", undefined, "audit-trend");
    root.append(section);
    const options = isBound ? [...new Map(tracks.map(track=>[
      JSON.stringify(track.category.data), track.category
    ])).entries()] : [];
    const choices = state[kind] ||= {category:options[0]?.[0], scope:tracks.some(track=>track.members?.length===1) ? "individuals" : "groups", point:points.length-1};
    choices.point = Math.min(choices.point, points.length-1);
    function paint(focus) {
      section.replaceChildren();
      section.append(node("h4", isBound ? "身份线索的变化" : "评价的变化"));
      section.append(node("p", isBound ? "确定、排除或仍待定 · 按当时已取得的线索显示" : "正分偏好，负分顾虑 · 保留当时的评价尺度", "cognition-status"));
      const controls = node("div", undefined, "audit-chart-controls");
      function select(caption, name, items) {
        const field = node("label", caption), input = node("select");
        input.className = `audit-${name}`;
        for (const [id, text] of items) {
          const option = node("option", text); option.value = id; input.append(option);
        }
        input.value = choices[name];
        input.onchange = () => {choices[name] = input.value; choices.track = null; paint(name);};
        field.append(input); controls.append(field);
        if (focus === name) queueMicrotask(()=>input.focus());
      }
      if (isBound) {
        select("判断维度", "category", options.map(([id, value])=>[id, typed(value).textContent]));
        select("查看对象", "scope", [["individuals","各位玩家"],["groups","玩家组合"]]);
      }
      section.append(controls);
      const visible = tracks.filter(track=>!isBound || JSON.stringify(track.category.data) === choices.category &&
        (choices.scope === "individuals" ? track.members.length === 1 : track.members.length > 1));
      if (!visible.length) {section.append(node("p", "这一维度尚无对应记录。")); return;}
      let track = visible.find(item=>item.id === choices.track) || visible[0];
      choices.track = track.id;
      const point = points[choices.point];
      const scroll = node("div", undefined, "audit-chart-scroll"), table = node("table", undefined, "audit-heatmap");
      scroll.tabIndex = 0; scroll.setAttribute("aria-label", isBound ? "身份线索时间图" : "评价时间图");
      const caption = node("caption", "横轴：判断发生变化的检查点　纵轴：判断对象");
      table.append(caption);
      const head = node("thead"), headings = node("tr");
      headings.append(node("th", isBound ? "对象 / 历程" : "评价对象 / 历程"));
      for (const p of points) {const th=node("th",position(p)); th.scope="col"; headings.append(th);}
      head.append(headings); table.append(head);
      const body = node("tbody");
      const magnitude = Math.max(1, ...points.flatMap(p=>Object.values(p.values).filter(v=>typeof v === "number").map(Math.abs)));
      for (const item of visible) {
        const row = node("tr"), title = node("th"); title.scope = "row";
        if (isBound) title.append(...item.members.map(typed));
        else title.append(typed(item.subject), node("small", `${label(item.rule)} · ${position(item)}`));
        row.append(title);
        points.forEach((p,index)=>{
          const value = p.values[item.id];
          const cell = isBound ? boundCell(value,p,item) : value === undefined ? {text:"未形成",tone:"unknown"} :
            {text:`${value>0 ? '+' : ''}${value}`,tone:value>0 ? "positive" : value<0 ? "negative" : "neutral"};
          const td=node("td"), button=node("button",cell.text,`audit-cell audit-${cell.tone}`);
          button.type="button"; button.dataset.track=item.id; button.dataset.point=index;
          button.setAttribute("aria-pressed",String(item.id===choices.track && index===choices.point));
          button.setAttribute("aria-label",`${title.textContent} · ${position(p)} · ${cell.text}`);
          if (!isBound && value !== undefined) button.style.setProperty("--audit-strength",String(0.1+0.55*Math.abs(value)/magnitude));
          button.onclick=()=>{choices.track=item.id; choices.point=index; paint("cell");};
          if (focus==="cell" && item.id===choices.track && index===choices.point) queueMicrotask(()=>button.focus());
          td.append(button); row.append(td);
        });
        body.append(row);
      }
      table.append(body); scroll.append(table); section.append(scroll);
      scroll.scrollLeft=choices.scrollLeft ?? scroll.scrollWidth;
      scroll.scrollTop=choices.scrollTop || 0;
      scroll.onscroll=()=>{choices.scrollLeft=scroll.scrollLeft; choices.scrollTop=scroll.scrollTop;};
      const legend=node("div",undefined,"audit-legend");
      for (const [tone,text] of (isBound ? [["certain","确定"],["possible","待定"],["excluded","排除"],["unknown","尚无判断 / 待续"]] : [["positive","正面评价"],["negative","负面评价"],["unknown","尚无评价"]])) {
        legend.append(node("span",text,`audit-key audit-${tone}`));
      }
      section.append(legend);
      const detail=node("div",undefined,"audit-point");
      detail.append(node("strong",`${position(point)} · `));
      if (isBound) detail.append(...track.members.map(typed), typed(track.category));
      else detail.append(typed(track.subject));
      const now=point.values[track.id], before=points[choices.point-1]?.values[track.id];
      const text=(value,p)=>isBound ? boundCell(value,p,track).text : value === undefined ? "未形成" : `${value>0 ? '+' : ''}${value}`;
      detail.append(node("strong",choices.point>0 ? `${text(before,points[choices.point-1])} → ${text(now,point)}` : text(now,point)));
      const evidence=node("button","查看当时记录","secondary"); evidence.type="button";
      evidence.onclick=()=>{state.logOpen=true; state.entry=point.entry; navigate(point.page);};
      detail.append(evidence); section.append(detail);
    }
    paint();
  }
  function render(root, audit, context, navigate) {
    root.replaceChildren();
    if (audit.kind === 'experience') return window.NomosExperienceAudit.render(root, audit, context, navigate);
    if (root.auditState?.actor !== audit.actor) root.auditState = {actor:audit.actor};
    const state = root.auditState;
    const typed = value => window.NomosWidgets.render(value.data, value.format, {...context, historical:true, fieldLabels:true});
    const label = text => context.labels?.[text] || text;
    if (audit.predictions.length) {
      const section=node("section",undefined,"audit-trend audit-predictions");
      section.append(node("h4","决策当时的身份概率"));
      section.append(node("p","在实际行动前预测，随这次行动保存。","cognition-status"));
      for (const prediction of audit.predictions) {
        const checkpoint=node("div",undefined,"audit-point");
        checkpoint.append(node("strong",`#${prediction.occurrence} · ${prediction.label}`));
        checkpoint.append(node("small",`依据至 #${prediction.basis} · 模型 ${prediction.model.slice(0,12)}`));
        const list=node("div",undefined,"audit-probability-list");
        for (const item of prediction.subjects) {
          const row=node("div",undefined,"audit-probability");
          const meter=node("meter"); meter.min=0; meter.max=1; meter.value=item.probability;
          meter.setAttribute("aria-label",`${typed(item.subject).textContent} · ${prediction.label}`);
          const p=item.probability;
          const percentage=p===0 ? "0%" : p===1 ? "100%" : p<0.001 ? "<0.1%" : p>0.999 ? ">99.9%" : `${(p*100).toFixed(1)}%`;
          row.append(typed(item.subject),meter,node("strong",percentage));
          list.append(row);
        }
        const evidence=node("button","查看这次行动","secondary"); evidence.type="button";
        evidence.onclick=()=>{state.logOpen=true; state.entry=prediction.entry; navigate(prediction.page);};
        checkpoint.append(list,evidence); section.append(checkpoint);
      }
      root.append(section);
    }
    renderTrend(root,audit.trends.bounds,"bounds",state,typed,label,navigate);
    renderTrend(root,audit.trends.appraisals,"appraisals",state,typed,label,navigate);
    if (!audit.trends.bounds.points.length && !audit.trends.appraisals.points.length) root.append(node("p","本局尚未形成可绘制的判断变化。"));
    const log=node("details",undefined,"audit-log"), entries=node("div",undefined,"audit-log-entries");
    log.open=!!state.logOpen;
    log.ontoggle=()=>{state.logOpen=log.open;};
    log.append(node("summary",`记录明细 · ${audit.total}项`),entries); root.append(log);
    function judgment(value) {
      const body = node("div");
      if (!value) {body.append(node("p", "尚未形成这一项判断")); return body;}
      if (value.proposition) body.append(typed(value.proposition), node("p", `支持 ${value.support} · 反对 ${value.opposition}`));
      if (value.appraisal) body.append(typed(value.appraisal), node("p", `评价 ${value.score > 0 ? "+" : ""}${value.score}`));
      return body;
    }
    for (const [index,entry] of audit.entries.entries()) {
      const details = node("details",undefined,"audit-entry"), body = node("div");
      const checkpoint = !['message','action'].includes(entry.kind);
      const position = entry.occurrence === null ? (checkpoint ? "开局依据" : "开局") :
        (checkpoint ? "依据至发生 " : "发生 ") + entry.occurrence;
      let title;
      if (entry.kind === "action") {
        title = "采取行动：" + entry.title;
        for (const input of entry.inputs) {
          const row = node("div", undefined, "audit-change");
          row.append(node("strong", input.label), typed(input)); body.append(row);
        }
        if (entry.decision) {
          const snapshot = node("section", undefined, "audit-change");
          snapshot.append(node("h4", "当时的决策依据"));
          const categories = {information:"当时掌握的信息", judgment:"局势判断", motive:"行为取舍"};
          for (const category of Object.keys(categories)) {
            const items = entry.decision.explanations.filter(item=>item.category===category);
            if (!items.length) continue;
            snapshot.append(node("strong",categories[category]));
            for (const item of items) {
              const row=node("div", undefined, "audit-change");
              row.append(node("span",item.label),typed(item)); snapshot.append(row);
            }
          }
          const scores=node("details"); scores.append(node("summary",`当时评分 ${entry.decision.score}`));
          for (const part of entry.decision.parts) scores.append(node("p",`${part.label}：${part.value>0 ? '+' : ''}${part.value}`));
          snapshot.append(scores); body.append(snapshot);
        }
        body.append(node("small", "行动来源：" + entry.source));
      } else if (entry.kind === "message") {
        title = "收到：" + label(entry.channel);
        body.append(typed(entry.message));
        for (const change of entry.changes) {
          const block = node("section", undefined, "audit-change");
          block.append(node("h4", label(change.rule)));
          const pair = node("div", undefined, "audit-judgments");
          for (const [caption, value] of [["此前", change.before], ["收到后", change.after]]) {
            const column = node("div"); column.append(node("strong", caption), judgment(value)); pair.append(column);
          }
          block.append(pair); body.append(block);
        }
        if (!entry.changes.length) body.append(node("p", entry.processed ? "这条消息未新增软判断。" : "这条消息未触发软判断修订；可靠约束的变化见检查点。"));
        body.append(node("small", "消息来源：" + entry.source));
      } else if (entry.kind === "bounds") {
        title = `人数范围检查点 · ${entry.changes.length}项变化`;
        body.append(node("p", {complete:"计算完成", conflict:"线索冲突", pending:"计算待续"}[entry.status] || entry.status));
        const range = value => value ? value[0] === value[1] ? String(value[0]) : `${value[0]} 至 ${value[1]}` : "未给出范围";
        for (const change of entry.changes) {
          const row = node("div", undefined, "audit-change");
          row.append(...change.members.map(typed), typed(change.category), node("strong", `${range(change.before)} → ${range(change.after)}`));
          body.append(row);
        }
      } else if (entry.kind === "reasoning") {
        title = "推导检查点";
        for (const change of entry.changes) {
          const row = node("div", undefined, "audit-change");
          row.append(node("strong", change.active ? "新增推导" : "撤回推导"), typed(change.proposition), node("span", change.polarity === "opposition" ? "反对" : "支持"));
          body.append(row);
        }
      } else {
        title = "有限分析检查点";
        body.append(node("p", entry.model_count === null ? "分析尚未完成" : `${label(entry.status)} · ${entry.model_count} 种相容配置`));
      }
      const summary=node("summary", `${position} · ${title}`);
      details.append(summary, body); entries.append(details);
      if (state.entry===audit.offset+index) {
        details.open=true; summary.tabIndex=-1;
        queueMicrotask(()=>summary.focus());
      }
    }
    if (!audit.entries.length) entries.append(node("p", "这一页没有更多记录。"));
    const navigation = node("div", undefined, "audit-pages");
    const previous = node("button", "上一页", "secondary"), next = node("button", "下一页", "secondary");
    previous.type = next.type = "button";
    previous.disabled = audit.previous === null; next.disabled = audit.next === null;
    previous.onclick = () => navigate(audit.previous); next.onclick = () => navigate(audit.next);
    navigation.append(previous, node("span", `${audit.total ? audit.offset + 1 : 0}–${Math.min(audit.offset + audit.entries.length, audit.total)} / ${audit.total}`), next);
    log.append(navigation);
    if (audit.pending) root.append(node("p", "终局时仍有判断等待处理。"));
  }
  return {render};
})();
