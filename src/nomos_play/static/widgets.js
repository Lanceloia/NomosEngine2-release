"use strict";

window.NomosWidgets = (() => {
  function el(tag, text, className) {
    const result = document.createElement(tag);
    if (text !== undefined) result.textContent = text;
    if (className) result.className = className;
    return result;
  }
  function label(value, context) {return context.labels?.[String(value)] ?? value;}
  function token(style, amount, compact = false) {
    const item = el("span", undefined, "gem-token" + (compact ? " compact" : ""));
    const gem = el("span", undefined, "gem-shape " + style.symbol);
    gem.style.setProperty("--gem-color", style.color);
    gem.setAttribute("aria-hidden", "true");
    item.append(gem);
    if (amount !== undefined) item.append(el("strong", amount));
    item.title = style.label;
    item.setAttribute("aria-label", style.label + (amount === undefined ? "" : " " + amount));
    return item;
  }
  function resources(data, fields, compact = false) {
    const row = el("div", undefined, "resource-row" + (compact ? " compact" : ""));
    for (const [key, style] of Object.entries(fields)) {
      if (compact && !data[key]) continue;
      const part = el("div", undefined, "resource-item");
      part.dataset.resource = key;
      part.append(token(style, data[key] ?? 0, compact));
      if (!compact) part.append(el("span", style.label, "resource-name"));
      row.append(part);
    }
    if (!row.children.length) row.append(el("span", "0", "free-cost"));
    return row;
  }
  function equal(a, b) {
    if (a === b) return true;
    if (a === null || b === null || typeof a !== "object" || typeof b !== "object") return false;
    const keys = Object.keys(a);
    return keys.length === Object.keys(b).length && keys.every(k => Object.hasOwn(b, k) && equal(a[k], b[k]));
  }
  function card(data, format, context) {
    const body = el("div", undefined, "game-card");
    const fields = format.fields, palette = format.palette || {};
    const bonus = palette[data[fields.bonus]];
    body.style.setProperty("--card-color", bonus?.color || "#d7bd70");
    const top = el("div", undefined, "card-top");
    const points = el("span", undefined, "card-points");
    points.append(window.NomosIcon("star"), el("strong", data[fields.score]));
    points.title = context.labels?.[fields.score] || "得分";
    top.append(points);
    if (bonus) top.append(token(bonus));
    body.append(top);
    const mark = el("div", undefined, "card-emblem");
    if (bonus) mark.append(token(bonus));
    else mark.append(window.NomosIcon("star"));
    body.append(mark);
    const identity = format.label + " " + String(data[fields.identity]).padStart(2, "0");
    body.append(el("span", identity, "card-name"));
    if (fields.cost) body.append(resources(data[fields.cost], palette, true));
    if (context.targets) {
      const links = context.targets.filter(t => equal(t.value, data));
      if (links.length) {
        const commands = el("div", undefined, "card-commands");
        for (const link of links) {
          const button = el("button", link.title, "card-command");
          button.type = "button";
          button.dataset.action = link.action.id; button.dataset.input = link.input; button.dataset.option = link.id;
          button.setAttribute("aria-pressed", String(context.selection?.action === link.action.id && context.selection.values[link.input] === link.id));
          button.onclick = () => context.openAction(link.action, {[link.input]: link.id});
          commands.append(button);
        }
        body.append(commands);
      }
    }
    return body;
  }
  function table(data, format, context) {
    const wrapper = el("div", undefined, "table-scroll"), grid = el("table", undefined, "score-table");
    wrapper.tabIndex = 0;
    wrapper.setAttribute("aria-label", "数据表");
    const head = el("thead"), header = el("tr");
    for (const title of Object.values(format.columns)) header.append(el("th", title));
    head.append(header); grid.append(head);
    const body = el("tbody");
    const key = context.orderBySeat && Object.keys(format.columns).find(name => {
      const cell = format.cells[name];
      return cell.kind === "reference" || cell.kind === "badge" && cell.reference;
    });
    const order = new Map([...(context.people?.keys() || [])].map((ref, index) => [ref, index]));
    const rows = key ? [...data].sort((a, b) => (order.get(a[key]?.reference) ?? Infinity) - (order.get(b[key]?.reference) ?? Infinity)) : data;
    for (const item of rows) {
      const row = el("tr");
      for (const key of Object.keys(format.columns)) {
        const cell = el("td", undefined, "cell-" + format.cells[key].kind); cell.append(render(item[key], format.cells[key], {...context, compact:true})); row.append(cell);
      }
      body.append(row);
    }
    grid.append(body); wrapper.append(grid); return wrapper;
  }
  function reference(data, format, context) {
    const person = context.historical ? null : context.people?.get(data.reference);
    const root = el("span", undefined, "person-reference");
    root.dataset.reference = data.reference;
    root.classList.toggle("has-known-danger", !!person?.marks.some(mark => mark.tone === "danger"));
    const identity = el("span", undefined, "identity-badge");
    identity.append(window.NomosIcon(format.icon || "user"), el("span", data.label));
    root.append(identity);
    if (person?.self) root.append(el("span", "你", "self-tag"));
    for (const mark of person?.marks || []) {
      const tag = el("span", undefined, "person-mark tone-" + mark.tone);
      tag.append(window.NomosIcon(mark.icon), el("span", mark.label));
      tag.title = mark.label;
      root.append(tag);
    }
    const note = context.historical ? null : context.notes?.get(data.reference);
    if (note?.judgment && note.judgment !== "unknown") {
      root.append(el("span", note.judgment === "trust" ? "我的判断：可信" : "我的判断：可疑", "note-tag"));
    }
    return root;
  }
  function render(data, format = {}, context = {}) {
    if (format.kind === "indicator") {
      const style = format.items[String(data)], item = el("span", undefined, "value-indicator tone-" + style.tone);
      item.append(window.NomosIcon(style.icon), el("span", style.label)); return item;
    }
    if (format.kind === "track") {
      const root = el("div", undefined, "value-track tone-" + format.tone);
      root.setAttribute("aria-label", `${data} / ${format.steps}`);
      for (let step = 0; step < format.steps; step++) {
        const slot = el("span", undefined, "track-slot" + (step < data ? " filled" : ""));
        slot.append(window.NomosIcon(format.icon)); root.append(slot);
      }
      root.append(el("strong", `${data} / ${format.steps}`)); return root;
    }
    if (format.kind === "optional") return data === null ? el("span", "暂无", "empty-value") : render(data, format.value, context);
    if (format.kind === "variant") {
      const variant = format.cases[data.tag], root = el("span", undefined, "variant-value");
      if (variant.sentence) {
        for (const part of variant.sentence) root.append(typeof part === 'string' ? el('span',part) : render(data.fields[part.field], variant.fields[part.field], {...context,prose:true,fieldLabels:false}));
        for (const field of Object.keys(variant.fields)) {
          const link = context.recordLink?.(field, data.fields[field]);
          if (link) {
            const button = el('button',link.label,'secondary record-link'); button.type = 'button';
            button.onclick = event => {event.preventDefault(); event.stopPropagation(); link.open();}; root.append(button);
          }
        }
        root.setAttribute('aria-label', root.textContent);
        return root;
      }
      const accessible = [variant.label];
      root.append(el("span", variant.label, "variant-label"));
      for (const [field, fieldFormat] of Object.entries(variant.fields)) {
        if (context.fieldLabels) {
          const item = el("span", undefined, "variant-field");
          item.append(el("span", variant.field_labels?.[field] || context.labels?.[field] || field, "record-key"), render(data.fields[field], fieldFormat, context));
          accessible.push(item.textContent);
          root.append(item);
        } else {
          const item = render(data.fields[field], fieldFormat, context);
          accessible.push(item.textContent); root.append(item);
        }
        const link = context.recordLink?.(field, data.fields[field]);
        if (link) {
          const button = el("button", link.label, "secondary record-link"); button.type = "button";
          button.onclick = event => {event.preventDefault(); event.stopPropagation(); link.open();};
          root.append(button);
        }
      }
      root.setAttribute("aria-label", accessible.join(" "));
      if (context.choice && variant.description) root.append(el("span", variant.description, "reason-description"));
      return root;
    }
    if (format.kind === "reference" || format.kind === "badge" && format.reference) return reference(data, format, context);
    if ((!format.kind || format.kind === "scalar") && data && typeof data === "object" && Object.keys(data).length === 2 && typeof data.reference === "string" && typeof data.label === "string") return reference(data, {}, context);
    if (format.kind === "collection") {
      if (!data?.length) return el("span", "暂无", "empty-value");
      if (format.element.kind === "table") return table(data, format.element, context);
      if (format.element.kind === "card") {
        const groupKey = format.element.fields.group;
        const groups = groupKey ? [...new Set(data.map(x => x[groupKey]))].sort((a,b) => b - a) : [null];
        const root = el("div", undefined, "card-collection");
        for (const group of groups) {
          const band = el("div", undefined, "card-band");
          if (group !== null) band.append(el("div", "等级 " + label(group, context), "tier-label"));
          const grid = el("div", undefined, "card-grid");
          for (const value of data.filter(x => group === null || x[groupKey] === group)) grid.append(card(value, format.element, context));
          band.append(grid); root.append(band);
        }
        return root;
      }
      const list = el("div", undefined, "token-list");
      for (const item of data) list.append(render(item, format.element, context));
      return list;
    }
    if (format.kind === "resources") return resources(data, format.fields, context.compact);
    if (format.kind === "card") return card(data, format, context);
    if (format.kind === "allocation") {
      const root = el("div", undefined, "allocation-result"), f = format.fields;
      for (const row of data[f.rows]) {
        const item = el("div", undefined, "record-row");
        item.append(render(row[f.target], format.target_format, context), el("strong", row[f.quantity]));
        root.append(item);
      }
      root.append(el("div", "保留 " + data[f.reserve], "quantity-total")); return root;
    }
    if (format.kind === "badge") {
      const style = format.items?.[data] || format;
      const badge = el("span", undefined, "identity-badge");
      const icon = window.NomosIcon(style.icon);
      if (style.color) icon.style.color = style.color;
      badge.append(icon, el("span", format.value_labels?.[String(data)] ?? (style.label || label(data, context))));
      if ((context.choice || context.descriptions) && style.description) {
        const body = el("div", undefined, "badge-description");
        body.append(badge, el("p", style.description)); return body;
      }
      return badge;
    }
    if (format.kind === "table") return table([data], format, context);
    if (format.kind === "resource_choice") {
      const row = el("span", undefined, "resource-choice");
      row.append(token(format.palette[data]), el("span", format.palette[data].label)); return row;
    }
    if (format.kind === "record" && data !== null) {
      if (context.prose && format.sentence) {
        const sentence = el("p", undefined, "message-sentence");
        for (const part of format.sentence) sentence.append(typeof part === "string" ? el("span",part) : render(
          data[part.field], {...format.fields[part.field].format,
            ...(format.fields[part.field].value_labels ? {value_labels:format.fields[part.field].value_labels} : {})},
          {...context,prose:false,fieldLabels:true}));
        return sentence;
      }
      const record = el("div", undefined, "record");
      for (const [key, field] of Object.entries(format.fields)) {
        if (field.omit_empty && (data[key] === null || Array.isArray(data[key]) && !data[key].length)) continue;
        const row = el("div", undefined, "record-row");
        row.append(el("span", field.label, "record-key"), render(data[key], {...field.format,
          ...(field.value_labels ? {value_labels:field.value_labels} : {})}, {...context, fieldLabels:true}));
        record.append(row);
      }
      return record;
    }
    if (Array.isArray(data)) return render(data, {kind: "collection", element: {}}, context);
    if (data !== null && typeof data === "object") {
      return render(data, {kind: "record", fields: Object.fromEntries(Object.keys(data).map(k => [k, {label: label(k, context), format: {}}]))}, context);
    }
    const shown = format.value_labels?.[String(data)] ?? (typeof data === "boolean" ? (context.labels?.[String(data)] || (data ? "是" : "否")) : label(data === null ? "null" : data, context));
    return el("span", shown ?? "暂无", format.kind === "number" ? "numeric-value" : "");
  }
  function initial(format, allocation) {
    if (format.kind === "allocation") {
      if (!allocation) return null;
      const f = format.fields;
      return {[f.rows]: allocation.targets.map(t => ({[f.target]: t.key, [f.quantity]: 0})), [f.reserve]: allocation.total};
    }
    if (format.kind === "resources") return Object.fromEntries(Object.keys(format.fields).map(k => [k, 0]));
    if (format.kind === "record") return Object.fromEntries(Object.entries(format.fields).map(([k,f]) => [k, initial(f.format)]));
    if (format.kind === "number") return Math.max(0, format.min ?? 0);
    if (format.kind === "boolean") return false;
    if (format.kind === "enum") return format.options[0]?.value;
    return null;
  }
  function editable(format, allocation) {
    if (format.kind === "allocation") return !!allocation;
    return ["resources", "number", "boolean", "enum"].includes(format.kind) ||
      format.kind === "record" && Object.values(format.fields).every(f => editable(f.format));
  }
  function editor(value, format, options) {
    const root = el("div", undefined, format.kind === "resources" ? "resource-editor" : "typed-editor");
    if (format.kind === "allocation") {
      root.className = "allocation-editor";
      if (options.board) root.classList.add("board-allocation-editor");
      const domain = options.allocation, f = format.fields;
      if (!domain || !value) {root.append(el("p", "暂时无法读取分配目标")); return root;}
      const rows = value[f.rows], assigned = rows.reduce((sum, row) => sum + row[f.quantity], 0);
      const reserve = domain.total - assigned;
      const summary = el("div", undefined, "allocation-summary");
      summary.setAttribute("aria-live", "polite");
      for (const [caption, amount] of [["总额", domain.total], ["已分配", assigned], ["保留", reserve], ["至少分配", domain.minimum]]) {
        const item = el("span"); item.append(el("span", caption), el("strong", amount)); summary.append(item);
      }
      root.append(summary);
      const messages = [];
      if (reserve < 0) messages.push("超出总额 " + (-reserve) + "，请减少分配。");
      if (assigned < domain.minimum) messages.push("还需分配 " + (domain.minimum - assigned) + "。");
      for (const target of domain.targets) {
        const index = rows.findIndex(row => equal(row[f.target], target.key));
        if (index < 0) {messages.push("分配目标已变化，请重新打开行动。"); continue;}
        const quantity = rows[index][f.quantity], row = el("div", undefined, "quantity-row allocation-row");
        row.append(el("span", target.label, "quantity-label"));
        if (options.board) {
          const slots = el("div", undefined, "allocation-slots");
          for (let slot = 0; slot < Math.min(target.capacity, 12); slot++) {
            const unit = el("span", undefined, "allocation-slot" + (slot < quantity ? " occupied" : ""));
            unit.append(window.NomosIcon(options.unitIcon)); slots.append(unit);
          }
          slots.setAttribute("aria-label", `已安排 ${quantity} / ${target.capacity}`);
          row.append(slots);
        }
        row.append(editor(quantity, {kind: "number", min: 0, max: target.capacity}, {
          ...options, label: target.label, path: options.path + ".target:" + JSON.stringify(target.key),
          change: next => {
            const updated = rows.map((r, i) => i === index ? {...r, [f.quantity]: next} : r);
            options.change({...value, [f.rows]: updated, [f.reserve]: domain.total - updated.reduce((sum, r) => sum + r[f.quantity], 0)});
          },
        }));
        if (quantity > target.capacity) {row.classList.add("invalid-quantity"); messages.push(target.label + "超出容量 " + (quantity - target.capacity) + "。");}
        root.append(row);
      }
      if (!domain.targets.length) root.append(el("p", "暂无分配目标，全部保留。"));
      if (messages.length) root.append(el("p", messages.join(" "), "allocation-validation"));
    } else if (format.kind === "resources" || format.kind === "record") {
      const fields = format.fields;
      for (const [key, style] of Object.entries(fields)) {
        const row = el("div", undefined, "quantity-row");
        if (format.kind === "resources") row.append(token(style), el("span", style.label, "quantity-label"));
        else row.append(el("span", style.label, "quantity-label"));
        const childFormat = format.kind === "resources" ? {kind:"number", min:0, max: options.limit?.[key] ?? null} : style.format;
        row.append(editor(value[key], childFormat, {
          ...options, label: style.label, path: options.path + "." + key, limit: options.limit?.[key],
          change: next => options.change({...value, [key]: next}),
        })); root.append(row);
      }
      if (format.kind === "resources") root.append(el("div", "合计 " + Object.values(value).reduce((a,b) => a+b, 0) + " 枚", "quantity-total"));
    } else if (format.kind === "number") {
      root.classList.add("stepper");
      const input = el("input"); input.type = "number"; input.step = "1";
      input.min = format.min ?? ""; input.max = format.max ?? ""; input.value = value;
      input.setAttribute("aria-label", options.label); input.dataset.focusKey = options.path;
      input.onchange = () => {
        const next = Number(input.value);
        if (Number.isSafeInteger(next)) options.change(next);
      };
      const change = (name, direction) => {
        const button = el("button", undefined, "step-button"); button.type = "button";
        button.append(window.NomosIcon(name)); button.title = (direction > 0 ? "增加" : "减少") + options.label;
        button.setAttribute("aria-label", button.title);
        button.dataset.focusKey = options.path + "." + name;
        button.disabled = direction < 0 ? value <= (format.min ?? -Infinity) : value >= (format.max ?? Infinity);
        button.dataset.unavailable = button.disabled ? "yes" : "";
        button.onclick = () => options.change(value + direction); return button;
      };
      root.append(change("minus", -1), input, change("plus", 1));
      if (format.max !== null && format.max !== undefined) root.append(el("span", "可用 " + format.max, "quantity-limit"));
    } else if (format.kind === "boolean") {
      const input = el("input"); input.type = "checkbox"; input.checked = value;
      input.setAttribute("aria-label", options.label); input.onchange = () => options.change(input.checked); root.append(input);
    } else if (format.kind === "enum") {
      const input = el("select"); input.setAttribute("aria-label", options.label);
      for (const option of format.options) {const item = el("option", option.label); item.value = option.value; input.append(item);}
      input.value = value; input.onchange = () => options.change(input.value); root.append(input);
    }
    return root;
  }
  return {render, reference, editor, initial, editable, equal};
})();
