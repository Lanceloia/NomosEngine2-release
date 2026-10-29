"use strict";

window.NomosJournal = (() => {
  const groupKey = event => event.group && event.group.value !== null
    ? JSON.stringify([event.group.label, event.group.value]) : "";
  const groupCaption = event => groupKey(event) ? `${event.group.label} ${event.group.value}` : "其他记录";
  function references(value, found = new Set()) {
    if (Array.isArray(value)) value.forEach(item => references(item, found));
    else if (value && typeof value === "object") {
      if (typeof value.reference === "string" && typeof value.label === "string") found.add(value.reference);
      else Object.values(value).forEach(item => references(item, found));
    }
    return found;
  }
  class Index {
    constructor() {this.reset();}
    reset() {this.entries = new Map();}
    ingest(events, text) {
      for (const event of events) if (!this.entries.has(event.id)) this.entries.set(event.id, {
        event, text:text(event).toLocaleLowerCase(), people:references(event.data),
      });
    }
    matching({query = "", category = "", person = "", speaker = "", group = "", unread = false, important = false} = {}, read = new Set()) {
      const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
      return [...this.entries.values()].filter(row =>
        (!category || row.event.category === category) && (!person || row.people.has(person)) &&
        (!speaker || row.event.actor?.reference === speaker) &&
        (!group || groupKey(row.event) === group) && (!unread || !read.has(row.event.id)) &&
        (!important || row.event.emphasis) &&
        terms.every(term => row.text.includes(term))).map(row => row.event);
    }
    threads(events) {
      const groups = new Map();
      for (const event of events) {
        const key = groupKey(event);
        if (!groups.has(key)) groups.set(key, {key, label:groupCaption(event), events:[]});
        const thread = groups.get(key); thread.events.push(event);
        groups.delete(key); groups.set(key, thread);
      }
      return [...groups.values()].reverse();
    }
    latestGroup() {
      return [...this.entries.values()].reverse().find(row => groupKey(row.event))?.event;
    }
    groupReference(field, value) {
      const groups = new Map([...this.entries.values()].filter(row => row.event.group?.field === field &&
        row.event.group.value === value).map(row => [groupKey(row.event),row.event]));
      return groups.size === 1 ? groups.values().next().value : undefined;
    }
  }
  class Journal {
    constructor({root, controls, renderEvent, read, acknowledge}) {
      Object.assign(this, {root, controls, renderEvent, read, acknowledge});
      this.index = new Index(); this.expanded = new Map();
      controls.query.oninput = () => this.render();
      for (const name of ["category", "person", "speaker", "group", "unread", "important"]) controls[name].onchange = () => this.render();
      controls.clear.onclick = () => this.filter({});
      controls.acknowledge.onclick = () => acknowledge(this.matching().map(event => event.id));
    }
    reset() {this.index.reset(); this.expanded.clear(); this.filter({});}
    values() {
      const c = this.controls;
      return {query:c.query.value, category:c.category.value, person:c.person.value,
        speaker:c.speaker.value, group:c.group.value, unread:c.unread.checked, important:c.important.checked};
    }
    matching() {return this.index.matching(this.values(), this.read());}
    filter(values) {
      for (const name of ["query", "category", "person", "speaker", "group"]) this.controls[name].value = values[name] || "";
      this.controls.unread.checked = !!values.unread;
      this.controls.important.checked = !!values.important;
      this.render();
    }
    ingest(events, people) {
      this.index.ingest(events, event => {
        const item = this.renderEvent(event);
        return `${event.title} ${event.category} ${groupCaption(event)} ${item.textContent}`;
      });
      this.options(this.controls.category, [...new Set([...this.index.entries.values()].map(row => row.event.category))].map(value => [value,value]));
      const groups = new Map([...this.index.entries.values()].filter(row => groupKey(row.event)).map(row => [groupKey(row.event),groupCaption(row.event)]));
      this.options(this.controls.group,[...groups].reverse());
      this.options(this.controls.person,(people || []).map(person => [person.reference,person.label]));
      this.options(this.controls.speaker,(people || []).map(person => [person.reference,person.label]));
      this.render();
    }
    options(select, options) {
      const selected = select.value;
      const first = select.options[0];
      select.replaceChildren(first, ...options.map(([value,label]) => {
        const option = document.createElement("option"); option.value = value; option.textContent = label; return option;
      }));
      select.value = options.some(([value]) => value === selected) ? selected : "";
    }
    render() {
      const events = this.matching(), filters = this.values();
      const signature = JSON.stringify(filters);
      const anchor = signature === this.signature ? [...this.root.querySelectorAll('[data-event-id]')].find(item => {
        const box = item.getBoundingClientRect(); return box.top >= 0 && box.top < innerHeight && box.height > 0;
      }) : null;
      const anchorTop = anchor?.getBoundingClientRect().top;
      this.signature = signature;
      this.root.replaceChildren();
      this.controls.count.textContent = `${events.length} / ${this.index.entries.size} 条`;
      this.controls.acknowledge.disabled = !events.some(event => !this.read().has(event.id));
      this.controls.acknowledge.dataset.unavailable = this.controls.acknowledge.disabled ? "no_unread" : "";
      if (!events.length) {
        const empty = document.createElement("p"); empty.textContent = "没有符合条件的消息。"; this.root.append(empty); return;
      }
      const filtered = !!(filters.query || filters.category || filters.person || filters.speaker || filters.group || filters.unread || filters.important);
      for (const [index, thread] of this.index.threads(events).entries()) {
        const section = document.createElement("details"); section.className = "journal-thread";
        section.open = filtered || (this.expanded.has(thread.key) ? this.expanded.get(thread.key) : index === 0);
        section.ontoggle = () => {if (section.isConnected) this.expanded.set(thread.key, section.open);};
        const heading = document.createElement("summary");
        heading.textContent = `${thread.label} · ${thread.events.length} 条`;
        section.append(heading);
        for (const event of thread.events) {
          const item = this.renderEvent(event);
          item.classList.toggle("unread-event", !this.read().has(event.id));
          section.append(item);
        }
        this.root.append(section);
      }
      if (anchor) {
        const replacement = [...this.root.querySelectorAll('[data-event-id]')].find(item => item.dataset.eventId === anchor.dataset.eventId);
        if (replacement) scrollBy(0, replacement.getBoundingClientRect().top - anchorTop);
      }
    }
  }
  return Object.freeze({Index, Journal, groupKey, groupCaption, references});
})();
