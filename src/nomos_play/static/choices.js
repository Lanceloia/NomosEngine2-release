"use strict";

window.NomosChoices = (() => {
  function render(actions, context, selected, open) {
    const root = document.createDocumentFragment();
    for (const action of actions.filter(a => a.surface === "choices")) {
      const section = document.createElement("section"); section.className = "choice-shelf";
      const heading = document.createElement("h2"); heading.textContent = action.title;
      const description = document.createElement("p"); description.textContent = action.description;
      const grid = document.createElement("div"); grid.className = "choice-tiles";
      for (const option of action.target.options) {
        const button = document.createElement("button"); button.type = "button";
        button.className = "choice-tile";
        button.dataset.choiceId = action.id + ":" + option.id;
        button.setAttribute("aria-pressed", String(selected?.action === action.id && selected?.option === option.id));
        button.append(window.NomosWidgets.render(option.data, option.format, {...context, targets: [], choice: true}));
        button.setAttribute("aria-label", action.title + "：" + button.textContent);
        button.onclick = () => open(action, {[action.target.name]: option.id});
        grid.append(button);
      }
      if (!grid.children.length) {description.textContent = "当前没有可选目标。";}
      section.append(heading, description, grid); root.append(section);
    }
    return root;
  }
  return {render};
})();
