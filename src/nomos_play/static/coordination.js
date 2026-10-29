"use strict";

const NomosCoordination = (() => {
  function canonical(value) {
    if (Array.isArray(value)) return value.map(canonical);
    if (value !== null && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
    return value;
  }
  const signature = value => JSON.stringify(canonical(value));
  function capture(draft, choices) {
    if (!draft) return [];
    return draft.fields.filter(field => !field.fixed && choices[field.name] !== undefined).map(field => {
      const chosen = choices[field.name];
      if (!field.options) return {name:field.name, kind:field.kind, raw:JSON.parse(JSON.stringify(chosen))};
      const ids = field.kind === "member" ? [chosen] : chosen;
      return {name:field.name, kind:field.kind, values:ids.map(id => field.options.find(o => o.id === id).data)};
    });
  }
  async function restore(saved, construct) {
    const choices = {};
    let changed = false;
    for (const item of saved) {
      const draft = await construct(choices);
      const field = draft.fields.find(f => f.name === item.name);
      if (!field || field.fixed || field.kind !== item.kind) {changed = true; break;}
      if (item.values) {
        const options = item.values.map(value => field.options.find(o => signature(o.data) === signature(value)));
        if (options.some(o => !o)) {changed = true; break;}
        choices[item.name] = item.kind === "member" ? options[0].id : options.map(o => o.id);
      } else choices[item.name] = item.raw;
    }
    return {choices, changed};
  }
  return {capture, restore};
})();
if (typeof module !== "undefined") module.exports = NomosCoordination;
else window.NomosCoordination = NomosCoordination;
