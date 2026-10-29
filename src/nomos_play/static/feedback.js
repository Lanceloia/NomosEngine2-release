"use strict";

globalThis.NomosTableFeedback = (() => {
  function stable(value) {
    if (Array.isArray(value)) return value.map(stable);
    if (value !== null && typeof value === "object") {
      return Object.fromEntries(Object.keys(value).sort().map(key => [key, stable(value[key])]));
    }
    return value;
  }
  function content(panel) {
    const data = stable(panel.data);
    if (panel.format?.kind === "collection" && panel.format.element.kind === "table") {
      return JSON.stringify([...data].sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b))));
    }
    return JSON.stringify(data);
  }
  function delta(previous, current) {
    return Number.isSafeInteger(previous) && Number.isSafeInteger(current) &&
      Number.isSafeInteger(current - previous) ? current - previous : null;
  }
  function status(state, {busy = false, playing = false, needsSync = false, pending = ""} = {}) {
    if (needsSync) return "等待同步当前对局";
    if (playing) return "正在展示结算过程";
    if (busy) return pending || "正在处理当前选择";
    return {ready:"等待你的选择", waiting:"等待同伴确认", closed:"对局结束",
      budget:"等待继续", blocked:"对局暂停", rejected:"对局暂停"}[state] || "正在读取对局";
  }
  function nextChoice(state, actions = []) {
    if (state !== "ready") return status(state);
    const primary = actions.filter(action => !action.group);
    const titles = (primary.length ? primary : actions).map(action => action.title);
    return titles.length && titles.length <= 3 ? "接下来：" + titles.join("、") + "。" : "请选择下一项行动。";
  }
  function completion(title, state, actions = []) {
    if (state === "closed") return title + "已完成，对局结束。可以查看最终局面与本局复盘。";
    if (state === "waiting") return title + "已完成，等待同伴确认。";
    if (state !== "ready") return title + "已完成。" + status(state);
    return "上一项「" + title + "」已记录。" + nextChoice(state, actions);
  }
  function eventRuns(events) {
    const runs = [];
    for (const event of events) {
      const last = runs.at(-1);
      if (last && last.latest.title === event.title && last.latest.scope === event.scope && last.latest.kind === event.kind) {
        last.earlier.push(last.latest);
        last.latest = event;
      } else runs.push({latest:event, earlier:[]});
    }
    return runs;
  }
  function summaryPanels(panels) {
    return panels.filter(panel => {
      if (panel.zone !== "board" || panel.fold) return false;
      const kind = panel.format?.kind;
      if (["scalar", "number", "enum", "boolean", "track", "indicator", "reference", "badge"].includes(kind)) return true;
      const element = panel.format?.element;
      return kind === "collection" && (element?.kind === "reference" || element?.kind === "badge" && element.reference);
    });
  }
  function bodyPanels(panels) {
    const summary = new Set(summaryPanels(panels));
    return panels.filter(panel => !summary.has(panel) && !(panel.zone === "private" &&
      (panel.data === null || Array.isArray(panel.data) && !panel.data.length)));
  }
  function finishedEvents(batch) {
    return batch.groups.flatMap(group => group.events || []);
  }
  function selectionCaption(minimum, maximum, selected) {
    const required = minimum === maximum ? `需选 ${minimum} 项` : `可选 ${minimum} 至 ${maximum} 项`;
    return `${required}，已选 ${selected} 项`;
  }
  function operationStatus(pending, elapsed, playing) {
    return `${playing ? "正在展示结算过程" : pending} · ${Math.floor(Math.max(0, elapsed) / 1000)} 秒`;
  }
  function compare(previous, current) {
    if (!previous || previous.revision !== undefined && previous.revision === current.revision) return [];
    const before = new Map(previous.panels.map(panel => [panel.id, panel]));
    const changes = [];
    for (const panel of current.panels) {
      const prior = before.get(panel.id);
      if (prior && content(prior) === content(panel)) continue;
      const values = [];
      const amount = prior ? delta(prior.data, panel.data) : null;
      if (amount !== null && amount !== 0) values.push({label:panel.title, amount});
      else if (prior && panel.format?.kind === "resources") {
        for (const [key, style] of Object.entries(panel.format.fields)) {
          const amount = delta(prior.data[key], panel.data[key]);
          if (amount !== null && amount !== 0) values.push({key, label:style.label, amount});
        }
      }
      changes.push({id:panel.id, title:panel.title, fresh:!prior, values});
    }
    return changes;
  }
  return Object.freeze({compare, status, nextChoice, completion, eventRuns, summaryPanels, bodyPanels, finishedEvents, selectionCaption, operationStatus});
})();
