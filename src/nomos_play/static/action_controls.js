"use strict";

window.NomosActionControls = (() => {
  function node(tag, text, className) {
    const result = document.createElement(tag);
    if (text !== undefined) result.textContent = text;
    if (className) result.className = className;
    return result;
  }
  function render(actions, context, open, submit) {
    const root = document.createDocumentFragment(), groups = new Map();
    for (const action of actions) {
      if (action.surface === "choices") continue;
      let parent = root;
      if (action.group) {
        if (!groups.has(action.group)) groups.set(action.group, []);
        parent = {append: child => groups.get(action.group).push(child)};
      }
      if (action.surface === "buttons") {
        const section = node("section", undefined, "direct-action");
        section.append(node("h3", action.title), node("p", action.description, "direct-description"));
        for (const preview of action.preview) {
          const row = node("div", undefined, "direct-preview");
          row.append(node("span", preview.title), window.NomosWidgets.render(preview.data, preview.format, context));
          section.append(row);
        }
        const buttons = node("div", undefined, "direct-buttons");
        for (const option of action.direct.options) {
          const button = node("button", option.label, "action-button direct-command");
          button.type = "button";
          button.setAttribute("aria-label", action.title + "：" + option.label);
          if (option.icon) button.prepend(window.NomosIcon(option.icon));
          button.onclick = () => submit(action, {[action.direct.name]: option.id}, option.label);
          buttons.append(button);
        }
        section.append(buttons); parent.append(section);
      } else {
        const button = node("button", action.title, "action-button");
        button.type = "button";
        if (action.icon) button.prepend(window.NomosIcon(action.icon));
        button.onclick = () => action.immediate ? submit(action, {}, action.title) : open(action); parent.append(button);
      }
    }
    for (const [title, buttons] of groups) {
      const group = node("details", undefined, "action-group");
      group.append(node("summary", title), ...buttons); root.append(group);
    }
    return root;
  }
  return {render};
})();
