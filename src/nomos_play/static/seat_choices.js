"use strict";

const NomosSeatChoices = (() => {
  function actionsForSeats(actions, selectedId = null) {
    return actions.filter(action => action.surface === "seats"
      && (selectedId === null ? !action.group : action.id === selectedId));
  }
  function selection(target, value) {
    return target.kind === "member" ? (value === undefined ? [] : [value]) : (value || []);
  }
  function enabled(target, value, id) {
    if (target.fixed) return false;
    const chosen = selection(target, value);
    return target.kind === "member" || chosen.includes(id) || target.max === 1 || chosen.length < target.max;
  }
  function toggle(target, value, id) {
    if (!target.options.some(option => option.id === id)) throw new Error("InvalidSelection");
    if (!enabled(target, value, id)) return value;
    if (target.kind === "member") return id;
    const chosen = selection(target, value);
    if (chosen.includes(id)) return chosen.filter(index => index !== id);
    return target.max === 1 ? [id] : [...chosen, id];
  }
  function localDraft(target, value) {
    if (!target?.local_edit || target.fixed || target.kind !== "subset") return null;
    const ids = value === undefined ? [] : value;
    const complete = value !== undefined && Array.isArray(ids)
      && ids.length >= target.min && ids.length <= target.max
      && new Set(ids).size === ids.length
      && ids.every(id => target.options.some(option => option.id === id));
    return {fields: [target], complete, preview: []};
  }
  return {actionsForSeats, selection, enabled, toggle, localDraft};
})();
if (typeof module !== "undefined") module.exports = NomosSeatChoices;
else window.NomosSeatChoices = NomosSeatChoices;
