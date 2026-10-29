"use strict";

const NomosBoards = (() => {
  const locationKey = (...parts) => JSON.stringify(parts);
  function locations(boards) {
    const result = new Map();
    for (const board of boards) {
      for (const pool of board.pools) result.set(locationKey(board.id, "pool", pool.id), pool.quantity);
      for (const person of board.people) {
        result.set(locationKey(board.id, person.reference, "reserve"), person.reserve);
        for (const group of person.groups) for (const site of group.sites) {
          result.set(locationKey(board.id, person.reference, group.id, site.key), site.quantity);
        }
      }
    }
    return result;
  }
  function movements(before, after) {
    const old = locations(before), next = locations(after), result = [];
    for (const board of after) {
      if (board.motion !== "conserved") continue;
      const negative = [], positive = [];
      const keys = [...next.keys()].filter(key => JSON.parse(key)[0] === board.id);
      if (keys.some(key => !Number.isSafeInteger(next.get(key)) || old.has(key) && !Number.isSafeInteger(old.get(key)))) continue;
      for (const [key, amount] of next) {
        if (JSON.parse(key)[0] !== board.id || !old.has(key)) continue;
        const delta = amount - old.get(key);
        if (delta) (delta < 0 ? negative : positive).push({key, amount: Math.abs(delta)});
      }
      const lost = negative.reduce((n, p) => n + p.amount, 0), gained = positive.reduce((n, p) => n + p.amount, 0);
      if (!Number.isSafeInteger(lost) || lost !== gained) continue;
      // A single endpoint determines aggregate transfers without inventing individual identities.
      if (negative.length === 1) for (const target of positive) result.push({from: negative[0].key, to: target.key, quantity: target.amount, icon: board.icon});
      else if (positive.length === 1) for (const source of negative) result.push({from: source.key, to: positive[0].key, quantity: source.amount, icon: board.icon});
    }
    return result;
  }
  function el(tag, text, className) {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    if (className) item.className = className;
    return item;
  }
  function counter(key, amount, label, icon) {
    const item = el("div", undefined, "resource-location"); item.dataset.location = key;
    item.append(el("span", label, "location-label"));
    const tokens = el("div", undefined, "worker-tokens");
    for (let index = 0; index < Math.min(amount, 8); index++) tokens.append(window.NomosIcon(icon));
    tokens.append(el("strong", amount)); item.append(tokens); return item;
  }
  function render(boards, people, actions, openAction) {
    const root = el("div", undefined, "resource-boards");
    for (const board of boards) {
      const section = el("section", undefined, "resource-board");
      section.append(el("h2", board.title));
      const pools = el("div", undefined, "resource-pools");
      for (const pool of board.pools) pools.append(counter(locationKey(board.id, "pool", pool.id), pool.quantity, pool.title, board.icon));
      section.append(pools);
      for (const person of board.people) {
        const player = el("section", undefined, "resource-player"); player.dataset.owner = person.reference;
        const self = people.find(p => p.reference === person.reference)?.self;
        player.classList.toggle("own-board", !!self);
        const heading = el("div", undefined, "resource-player-heading");
        heading.append(window.NomosIcon("user"), el("h3", person.label + (self ? " · 你" : "")));
        if (self) for (const action of actions.filter(a => a.board === board.id)) {
          const button = el("button", action.title, "board-action"); button.type = "button";
          button.onclick = () => openAction(action); heading.append(button);
        }
        player.append(heading, counter(locationKey(board.id, person.reference, "reserve"), person.reserve, "待命 · " + board.unit, board.icon));
        const groups = el("div", undefined, "resource-groups");
        for (const group of person.groups) {
          const part = el("section", undefined, "resource-group"); part.append(el("h4", group.title));
          const sites = el("div", undefined, "resource-sites");
          for (const site of group.sites) sites.append(counter(locationKey(board.id, person.reference, group.id, site.key), site.quantity, site.label, board.icon));
          if (!group.sites.length) sites.append(el("span", "暂无", "empty-sites"));
          part.append(sites); groups.append(part);
        }
        player.append(groups); section.append(player);
      }
      root.append(section);
    }
    return root;
  }
  function positions(root) {
    return new Map([...root.querySelectorAll("[data-location]")].map(item => [item.dataset.location, item.getBoundingClientRect()]));
  }
  function markChanges(before, after, root) {
    const old = locations(before), next = locations(after);
    for (const item of root.querySelectorAll('[data-location]')) {
      const key = item.dataset.location;
      if (!old.has(key) || old.get(key) === next.get(key)) continue;
      const prior = old.get(key), current = next.get(key);
      const numeric = Number.isSafeInteger(prior) && Number.isSafeInteger(current);
      const delta = numeric ? current - prior : null;
      const mark = el('span', numeric ? (delta > 0 ? '+' : '') + delta : '已更新', 'resource-change');
      mark.classList.add(numeric && delta < 0 ? 'decrease' : 'increase'); item.append(mark);
    }
  }
  async function animate(moves, before, root, duration, signal, register) {
    const after = positions(root), animations = [], tokens = [];
    for (const move of moves) {
      const from = before.get(move.from), to = after.get(move.to);
      if (!from || !to || signal.aborted) continue;
      const count = Math.min(move.quantity, 6);
      for (let i = 0; i < count && tokens.length < 36; i++) {
        const token = el("span", undefined, "flying-unit"); token.append(window.NomosIcon(move.icon));
        if (i === 0 && move.quantity > 6) token.append(el("strong", move.quantity));
        token.setAttribute("aria-hidden", "true"); document.body.append(token); tokens.push(token);
        const x = from.left + from.width / 2, y = from.top + from.height / 2;
        animations.push(token.animate([
          {transform: `translate(${x}px, ${y}px)`, opacity: 0},
          {opacity: 1, offset: 0.15},
          {transform: `translate(${to.left + to.width / 2}px, ${to.top + to.height / 2}px)`, opacity: 1},
        ], {duration, delay: i * 25, easing: "ease-in-out", fill: "forwards"}));
      }
    }
    const cancel = () => animations.forEach(a => a.cancel());
    register(animations);
    signal.addEventListener("abort", cancel, {once: true});
    try {await Promise.all(animations.map(a => a.finished.catch(() => {})));}
    finally {signal.removeEventListener("abort", cancel); cancel(); tokens.forEach(t => t.remove()); register([]);}
  }
  return {locationKey, locations, movements, render, positions, markChanges, animate};
})();
if (typeof module !== "undefined") module.exports = NomosBoards;
else window.NomosBoards = NomosBoards;
