"use strict";

window.NomosInformation = (() => {
  class Inbox {
    constructor() {this.reset();}
    reset() {this.events = new Map(); this.read = new Set();}
    ingest(events) {
      for (const event of events) this.events.set(event.id, event);
    }
    unread() {return [...this.events.values()].filter(event => event.emphasis && !this.read.has(event.id));}
    acknowledge(ids) {for (const id of ids) if (this.events.has(id)) this.read.add(id);}
  }
  function selectTab(buttons, panels, name) {
    if (!panels.some(panel => panel.dataset.page === name)) return;
    for (const panel of panels) panel.hidden = panel.dataset.page !== name;
    for (const button of buttons) {
      const active = button.dataset.page === name;
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
    }
  }
  return Object.freeze({Inbox, selectTab});
})();
