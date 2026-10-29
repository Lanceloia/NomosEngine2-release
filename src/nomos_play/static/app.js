"use strict";

const $ = id => document.getElementById(id);
const widgets = window.NomosWidgets;
let session = null, view = null, selected = null, inputs = {}, busy = false;
let currentGame = null, catalog = [];
let subjectGroup = null;
let needsSync = false;
let draftVersion = 0, endingShown = false;
let playing = false, displayState = null;
let replaying = false;
let coordinationTimer = null, lastDraft = null;
let pendingCoordinationDraft = null;
const editingFields = new Set();
const notes = new Map();
const openNotes = new Set();
const inbox = new window.NomosInformation.Inbox();
function showPage(name, focus = false) {
  const buttons = [...document.querySelectorAll('#table-tabs [role="tab"]')];
  const button = buttons.find(button => button.dataset.page === name && !button.hidden);
  if (!button) return;
  window.NomosInformation.selectTab(buttons, [...document.querySelectorAll('#table > [role="tabpanel"]')], name);
  if (focus) button.focus();
}
function openJournal(filters = {}) {
  journal.filter(filters); showPage("records", true);
  $("page-records").scrollIntoView({block:"start"});
}
for (const button of document.querySelectorAll('#table-tabs [role="tab"]')) {
  button.onclick = () => showPage(button.dataset.page);
  button.onkeydown = event => {
    const buttons = [...document.querySelectorAll('#table-tabs [role="tab"]')].filter(button => !button.hidden);
    const index = buttons.indexOf(button);
    const next = {ArrowRight:(index + 1) % buttons.length, ArrowLeft:(index + buttons.length - 1) % buttons.length, Home:0, End:buttons.length - 1}[event.key];
    if (next === undefined) return;
    event.preventDefault(); showPage(buttons[next].dataset.page, true);
  };
}
const messages = {
  StaleChoice: "桌面已经变化，请重新选择。", UnknownChoice: "这个选择已失效，请刷新桌面。",
  InvalidSelection: "请从当前目标中选择。", InvalidChoice: "当前组合不符合规则，请调整选择。",
  IncompleteInputs: "请完成当前选择。",
  ComputerNoChoice: "电脑暂时无法作出选择。", NoCurrentChoice: "目前没有可以继续的选择。",
  ComputerChoiceError: "电脑选择遇到问题，本局已暂停。", NotAdmitted: "本次选择未获当前规则准入，请重新读取后选择。",
  StaleContinuation: "进度已经变化，请刷新桌面。",
  StaleCoordination: "协商局面已经变化，请刷新桌面。",
  InvalidJointDecision: "共同决策窗口不一致，本局已暂停。",
  InvalidSeatDetail: "人物计划与席位不一致，请核对呈现声明。",
  NonSeatTarget: "座位目标与当前桌面不一致，请核对呈现声明。",
  UnknownGame: "这款游戏未登记。", GameLoadFailed: "游戏文件或开局检查失败，请核对服务终端与作者文件。",
  ConnectionLost: "连接中断，请刷新桌面查看当前对局。", InvalidResponse: "未收到完整结果，请刷新桌面查看当前对局。",
  SettlementError: "结算遇到异常，本局已暂停。请刷新桌面核对已完成的行动。",
  UnknownSession: "这局已结束或服务已重新启动，请重新开局。",
};
function node(tag, text, className) {
  const result = document.createElement(tag);
  if (text !== undefined) result.textContent = text;
  if (className) result.className = className;
  return result;
}
function valueNode(value, board = false) {
  if (Array.isArray(value)) {
    if (!value.length) return node("span", "暂无");
    const list = node("div", undefined, "token-list");
    for (const item of value) {
      if (typeof item === "object" && item !== null) list.append(valueNode(item));
      else list.append(node("span", item, "token"));
    }
    return list;
  }
  if (value !== null && typeof value === "object") {
    const record = node("div", undefined, "record");
    for (const [key, item] of Object.entries(value)) {
      const row = node("div", undefined, "record-row");
      row.append(node("span", key, "record-key"), valueNode(item));
      record.append(row);
    }
    return record;
  }
  return node("span", value, board && typeof value === "number" ? "counter" : "");
}
async function api(path, body) {
  let response, data;
  try {response = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});}
  catch {throw new Error("ConnectionLost");}
  try {data = await response.json();}
  catch {throw new Error("InvalidResponse");}
  if (!response.ok) throw new Error(data.code || "RequestFailed");
  return data;
}
async function control(path, body) {
  let opened = false, acknowledged = false;
  try {
    let response;
    try {response = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});}
    catch {throw new Error("ConnectionLost");}
    const next = await window.NomosStream(response, message => {
      if (message.type === "accepted") {
        acknowledged = true;
        cancelChoice();
        feedback(message.action + "已提交，其他参与者正在行动…");
        $("playback-progress").textContent = "已提交 · 等待新的可见变化";
        $("request-status").textContent = "你的行动已提交，正在等待后续变化…";
        updateStatus();
      } else if (message.type === "begin") {
        const savedDraft = pendingCoordinationDraft;
        cancelChoice();
        pendingCoordinationDraft = savedDraft;
        $("event-stage").hidden = false;
        $("current-events").replaceChildren();
        $("playback-progress").textContent = "正在接收桌面变化…";
        playback.open({id: message.id, base: message.base, groups: []});
        opened = true;
        $("table-tabs").scrollIntoView({block:"nearest"});
      } else if (message.type === "group") {
        playback.push(message.group);
      }
    });
    if (opened) await playback.end(next.playback.final);
    await render(next);
    return next;
  } catch (error) {
    if (acknowledged) error.sync = true;
    if (opened) {
      error.sync = true;
      await playback.fail().catch(() => {});
    }
    throw error;
  }
}
function feedback(text, error = false) {
  $("feedback").textContent = text;
  $("feedback").classList.toggle("error", error);
}
function updateStatus() {
  if (view) $("status").textContent = window.NomosTableFeedback.status(view.status, {
    busy, playing, needsSync, pending: $("request-status").textContent,
  });
  $("experience-status").hidden = !view?.experience;
  if (view?.experience) $("experience-status").textContent = `${view.experience.active_players}位长期玩家 · 第${view.experience.visits + (view.status === "closed" ? 0 : 1)}局`;
}
async function run(operation, pending = "正在核对选择…") {
  if (busy) return;
  const focusKey = document.activeElement?.dataset.focusKey;
  busy = true;
  $("request-status").textContent = pending;
  $("library-status").textContent = pending;
  $("setup-status").textContent = pending;
  updateStatus();
  document.querySelectorAll("button,input,textarea,select").forEach(control => {control.disabled = !control.dataset.localControl;});
  const started = performance.now();
  const progress = () => {$("operation-status").textContent = window.NomosTableFeedback.operationStatus(pending, performance.now() - started, playing);};
  progress();
  const progressTimer = setInterval(progress, 1000);
  try {await operation();}
  catch (error) {
    if (session && (error.sync || ["ConnectionLost", "InvalidResponse", "StaleChoice", "UnknownChoice", "StaleContinuation", "StaleCoordination", "SettlementError"].includes(error.message))) needsSync = true;
    const message = (messages[error.message] || "操作暂时未完成。") + " [" + error.message + "]";
    feedback(message, true); $("library-status").textContent = message; $("setup-status").textContent = message;
    if (selected) $("draft-validation").textContent = message;
  }
  finally {
    clearInterval(progressTimer);
    $("operation-status").textContent = "";
    busy = false;
    $("request-status").textContent = "";
    updateStatus();
    if ($("library-status").textContent === pending) $("library-status").textContent = "";
    if ($("setup-status").textContent === pending) $("setup-status").textContent = "";
    document.querySelectorAll("button,input,textarea,select").forEach(control => {control.disabled = !!control.dataset.unavailable;});
    document.querySelectorAll(".action-button,.card-command,.board-action,.choice-tile,.seat-command").forEach(control => {control.disabled = needsSync || playing || !!control.dataset.unavailable;});
    if (needsSync) document.querySelectorAll("#fields button,#fields input,#fields textarea,#fields select").forEach(control => {control.disabled = true;});
    if (selected) $("confirm").disabled = needsSync || playing || !$("choice-form").dataset.complete;
    $("pause-playback").disabled = !playing;
    $("skip-playback").disabled = !playing;
    $("ask-advice").disabled = needsSync || playing || !view?.strategy_available;
    if (needsSync && selected) $("sync-choice").focus();
    else if (focusKey) [...document.querySelectorAll("[data-focus-key]")].find(control => control.dataset.focusKey === focusKey)?.focus();
    scheduleCoordination();
  }
}
function scheduleCoordination() {
  clearTimeout(coordinationTimer);
  coordinationTimer = null;
  if (!session || needsSync || document.hidden || !view?.coordination?.pending) return;
  coordinationTimer = setTimeout(() => {
    if (busy || playing) {scheduleCoordination(); return;}
    run(advanceCoordination, "同伴正在考虑…");
  }, 1200);
}
async function advanceCoordination() {
  pendingCoordinationDraft = selected ? {key:selected.key, window:view.coordination.window, saved:window.NomosCoordination.capture(lastDraft, inputs)} : null;
  await control("/api/coordinate", {session, revision:view.revision});
  await restoreCoordinationDraft();
}
async function restoreCoordinationDraft() {
  const saved = pendingCoordinationDraft;
  if (!saved) return;
  const action = saved.window === view.coordination?.window && view.actions.find(a => a.key === saved.key);
  if (action) {
    const rebound = await window.NomosCoordination.restore(saved.saved, values => api("/api/draft", {session, action:action.id, revision:view.revision, inputs:values}));
    await openAction(action, rebound.choices);
    if (rebound.changed) feedback("局面有变化，请重新选择目标。");
  }
  pendingCoordinationDraft = null;
}
document.addEventListener("visibilitychange", scheduleCoordination);
window.addEventListener("pagehide", () => clearTimeout(coordinationTimer));
function visualContext() {
  const targets = (playing ? [] : view?.actions || []).flatMap(action => (action.target?.options || []).map(option => ({
    title: action.title, action, input: action.target.name, id: option.id, value: option.data,
  })));
  return {
    labels: view?.labels || {}, targets, notes,
    people: new Map((displayState?.seats || view?.seats || []).map(person => [person.reference, person])),
    selection: selected ? {action: selected.id, values: inputs} : null,
    openAction: (action, values) => run(() => openAction(action, values)),
    recordLink: (field, value) => {
      if (value?.reference) return {label:"查看相关记录", open:() => peekRecords({person:value.reference})};
      const event = journal.index.groupReference(field, value);
      return event ? {label:"查看" + window.NomosJournal.groupCaption(event), open:() => peekRecords({group:window.NomosJournal.groupKey(event)})} : null;
    },
  };
}
function peekRecords(filters) {
  const events = journal.index.matching(filters);
  $("record-peek-content").replaceChildren(...events.map(eventNode));
  $("record-peek-title").textContent = `相关记录 · ${events.length} 条`;
  if (!$("record-peek").open) $("record-peek").showModal();
}
$("close-record-peek").onclick = () => $("record-peek").close();
function renderSeats(seats = view.seats) {
  $("player-seats").replaceChildren();
  for (const [index, person] of (seats || []).entries()) {
    const item = node("article", undefined, "player-seat");
    item.dataset.reference = person.reference;
    item.classList.toggle("own-seat", person.self);
    item.append(node("span", "席位 " + (index + 1), "seat-number"));
    const history = node("button", undefined, "secondary icon-button person-history");
    history.type = "button"; history.dataset.localControl = "true";
    history.title = history.ariaLabel = "查看" + person.label + "的相关记录";
    history.append(window.NomosIcon("eye"));
    history.onclick = () => openJournal({person:person.reference});
    item.append(history);
    item.append(widgets.reference(person, {icon: "user"}, visualContext()));
    if (person.badge) item.append(widgets.render(person.badge.data, person.badge.format, visualContext()));
    for (const detail of person.details) {
      const content = node("section", undefined, "seat-detail");
      content.append(node("h3", detail.title), widgets.render(detail.data, detail.format, {...visualContext(), targets: []}));
      item.append(content);
    }
    if (!playing) for (const action of window.NomosSeatChoices.actionsForSeats(view.actions, selected?.id ?? null)) {
      const option = action.target.options.find(o => o.data.reference === person.reference);
      if (!option) continue;
      const active = selected?.id === action.id;
      const value = active ? inputs[action.target.name] : undefined;
      const chosen = active && window.NomosSeatChoices.selection(action.target, value).includes(option.id);
      const button = node("button", active ? (chosen ? "取消选择" : "选择") : action.title, "seat-command");
      if (action.target.kind === "member" && chosen) button.textContent = "已选择";
      button.type = "button"; button.dataset.option = option.id;
      button.dataset.focusKey = "seat:" + action.key + ":" + person.reference;
      button.setAttribute("aria-label", action.title + "：" + person.label);
      button.setAttribute("aria-pressed", String(chosen));
      button.disabled = !window.NomosSeatChoices.enabled(action.target, value, option.id);
      button.dataset.unavailable = button.disabled ? "selection_limit" : "";
      button.onclick = () => run(async () => {
        const value = selected?.id === action.id ? inputs[action.target.name] : undefined;
        const next = window.NomosSeatChoices.toggle(action.target, value, option.id);
        if (selected?.id !== action.id) await openAction(action, {[action.target.name]: next});
        else {inputs = {[action.target.name]: next}; await updateDraft();}
      });
      item.classList.toggle("draft-selected", chosen);
      item.append(button);
    }
    const memo = node("details", undefined, "player-note");
    memo.open = openNotes.has(person.reference);
    memo.ontoggle = () => {
      if (memo.isConnected) memo.open ? openNotes.add(person.reference) : openNotes.delete(person.reference);
    };
    const heading = node("summary", "我的笔记");
    const judgment = node("select");
    judgment.setAttribute("aria-label", person.label + "的个人判断");
    for (const [value, title] of [["unknown", "尚未判断"], ["trust", "我认为可信"], ["suspect", "我认为可疑"]]) {
      const option = node("option", title); option.value = value; judgment.append(option);
    }
    const saved = notes.get(person.reference) || {judgment: "unknown", text: ""};
    judgment.value = saved.judgment;
    judgment.onchange = () => {
      notes.set(person.reference, {...(notes.get(person.reference) || saved), judgment: judgment.value});
      for (const reference of document.querySelectorAll(".person-reference")) {
        if (reference.dataset.reference !== person.reference) continue;
        reference.querySelectorAll(".note-tag").forEach(tag => tag.remove());
        if (judgment.value !== "unknown") reference.append(node("span", judgment.value === "trust" ? "我的判断：可信" : "我的判断：可疑", "note-tag"));
      }
    };
    const entry = node("textarea");
    entry.setAttribute("aria-label", person.label + "的个人笔记");
    entry.placeholder = "记录你的线索与推测"; entry.maxLength = 1000; entry.value = saved.text;
    entry.oninput = () => notes.set(person.reference, {...(notes.get(person.reference) || saved), text: entry.value});
    memo.append(heading, judgment, entry); item.append(memo); $("player-seats").append(item);
  }
}
function eventNode(event) {
  const item = node("div", undefined, "event-item");
  item.dataset.eventId = event.id;
  const heading = node("h3");
  heading.append(window.NomosIcon(event.icon), node("span", event.title));
  if (event.category) heading.append(node("span", event.category, "event-category"));
  if (event.group?.value !== null && event.group) heading.append(node("span", window.NomosJournal.groupCaption(event), "event-group"));
  if (event.scope === "personal") heading.append(node("span", "本人收到", "personal-event"));
  if (event.kind === "replace") heading.append(node("span", "记录更新", "personal-event"));
  item.append(heading, widgets.render(event.data, event.format, {...visualContext(), historical:true, prose:true}));
  if (event.format.sentence) {
    const detail = node("details", undefined, "message-fields");
    detail.append(node("summary", "完整记录"), widgets.render(event.data, event.format, {...visualContext(), historical:true}));
    item.append(detail);
  }
  return item;
}
function currentEventNodes(events) {
  return window.NomosTableFeedback.eventRuns(events).map(run => {
    if (!run.earlier.length) return eventNode(run.latest);
    const group = node("div", undefined, "event-run");
    const earlier = node("details");
    earlier.append(node("summary", `${run.latest.title} · 此前 ${run.earlier.length} 条`));
    for (const event of run.earlier) earlier.append(eventNode(event));
    group.append(earlier, eventNode(run.latest));
    return group;
  });
}
function renderEvents() {
  $("current-events").replaceChildren();
  const latest = view.recent_events;
  $("event-stage").hidden = !latest.length;
  $("current-events").append(...currentEventNodes(latest));
  $("current-events").scrollTop = 0;
}
function renderKeyMessages(events = []) {
  const focused = [...$("key-message-list").children].findIndex(item => item.contains(document.activeElement));
  const focusedId = focused < 0 ? null : $("key-message-list").children[focused].dataset.eventId;
  inbox.ingest(events);
  journal.ingest(events, displayState?.seats || view?.seats || []);
  const unread = inbox.unread();
  $("key-messages").hidden = !unread.length;
  $("unread-count").textContent = `${unread.length} 条未读`;
  $("message-count").hidden = !unread.length;
  $("message-count").textContent = String(unread.length);
  $("key-message-list").replaceChildren();
  for (const event of unread.slice(-3).reverse()) {
    const item = eventNode(event);
    const read = node("button", undefined, "secondary icon-button");
    read.type = "button"; read.dataset.localControl = "true";
    read.title = read.ariaLabel = "标记这条消息已读";
    read.append(window.NomosIcon("check"));
    read.onclick = () => {inbox.acknowledge([event.id]); renderKeyMessages();};
    item.querySelector("h3").append(read);
    $("key-message-list").append(item);
  }
  if (focused >= 0) {
    const items = [...$("key-message-list").children];
    const replacement = items.find(item => item.dataset.eventId === focusedId) || items[Math.min(focused, items.length - 1)];
    (replacement?.querySelector("button") || document.querySelector('#table-tabs [aria-selected="true"]')).focus({preventScroll:true});
  }
  const latest = journal.index.latestGroup();
  $("open-discussion").hidden = !latest;
  if (latest) {
    const key = window.NomosJournal.groupKey(latest);
    const count = journal.index.matching({group:key}).length;
    $("open-discussion").textContent = `${window.NomosJournal.groupCaption(latest)} · ${count} 条记录`;
    $("open-discussion").onclick = () => openJournal({group:key});
  }
}
const journal = new window.NomosJournal.Journal({
  root:$("journal-list"), renderEvent:eventNode, read:() => inbox.read,
  acknowledge:ids => {inbox.acknowledge(ids); renderKeyMessages();},
  controls:{query:$("journal-query"), category:$("journal-category"), person:$("journal-person"),
    speaker:$("journal-speaker"),
    group:$("journal-group"), unread:$("journal-unread"), important:$("journal-important"),
    clear:$("clear-journal"), acknowledge:$("acknowledge-messages"), count:$("journal-count")},
});
$("read-messages").onclick = () => openJournal({important:true});
$("return-desk").onclick = () => showPage("desk", true);
function playbackLock(locked) {
  playing = locked;
  $("table").classList.toggle("is-playing", locked);
  document.querySelector(".history").hidden = locked;
  updateStatus();
  document.querySelectorAll(".action-button,.card-command,.board-action,.choice-tile,.seat-command,#sync-table,#restart").forEach(control => {control.disabled = locked || busy || needsSync || !!control.dataset.unavailable;});
  document.querySelectorAll("#choice-form button,#choice-form input,#choice-form textarea,#choice-form select").forEach(control => {control.disabled = locked || busy || needsSync || !!control.dataset.unavailable;});
  $("confirm").disabled = locked || busy || needsSync || !$("choice-form").dataset.complete;
  for (const id of ["pause-playback", "skip-playback", "playback-speed"]) $(id).disabled = false;
  $("pause-playback").disabled = !locked;
  $("skip-playback").disabled = !locked;
  $("pause-playback").setAttribute("aria-label", "暂停播放");
  $("replay-playback").disabled = locked;
  playbackMode();
}
function playbackMode() {
  $("event-stage-title").textContent = replaying ? "回看本段过程" : "刚刚发生";
  $("playback-mode").textContent = playing ? (replaying ? "回看中" : "结算过程") +
    (playback.paused ? " · 已暂停" : " · 播放中") : "";
  $("action-context").hidden = !playing;
  $("action-context").textContent = (replaying ? "正在回看历史局面" : "正在展示已发生的变化") + "，返回当前局面后继续选择。";
  $("feedback").hidden = playing;
  $("actions").hidden = playing || !!selected;
  $("choice-form").hidden = playing || !selected;
  $("table-summary").setAttribute("aria-label", playing ? "过程局面摘要" : "当前局面摘要");
  $("skip-playback").setAttribute("aria-label", replaying ? "返回当前局面" : "快进至当前局面");
  $("skip-playback").title = replaying ? "返回当前局面" : "快进至当前局面";
}
function frame(state) {
  const before = playing ? (displayState?.panels || []) : (view.playback.base.panels || []);
  displayState = state;
  $("table-summary").replaceChildren();
  for (const panel of window.NomosTableFeedback.summaryPanels(state.panels)) {
    const item = node("div", undefined, "summary-panel");
    item.classList.toggle("summary-people", panel.format.kind === "collection");
    item.append(node("span", panel.title, "summary-label"));
    item.append(panel.format.kind === "track" ? node("strong", `${panel.data} / ${panel.format.steps}`) : widgets.render(panel.data, panel.format, {...visualContext(), compact:true}));
    $("table-summary").append(item);
  }
  renderSeats(state.seats);
  renderPanels([...state.panels, ...view.panels.filter(p => p.zone === "history")], before);
  $("resource-desktop").replaceChildren(window.NomosBoards.render(state.boards, state.seats, playing ? [] : view.actions, action => run(() => openAction(action))));
  renderChoices();
  const focus = window.NomosTableFeedback.summaryPanels(state.panels)
    .filter(panel => panel.format.kind === "collection")
    .map(panel => panel.data.map(person => person.reference));
  window.NomosCognition.render($("cognition-panel"), playing ? null : view.cognition, {...visualContext(), focus, closed:view.status === "closed"});
  $("ask-advice").disabled = needsSync || playing || !view.strategy_available;
  if (playing) window.NomosCognition.renderAdvice($("strategy-advice"), null, visualContext());
}
function renderChoices() {
  const selection = selected?.target ? {action: selected.id, option: inputs[selected.target.name]} : null;
  $("choice-desktop").replaceChildren(window.NomosChoices.render(playing ? [] : view.actions, visualContext(), selection, (action, values) => run(() => openAction(action, values))));
}
const playback = new window.NomosPlayback({
  frame, lock: playbackLock,
  group: async (group, index, total, speed, signal) => {
    const started = performance.now();
    const oldBoards = displayState.boards;
    const positions = window.NomosBoards.positions($("resource-desktop"));
    frame(group.state);
    if (!replaying) renderKeyMessages(group.events);
    window.NomosBoards.markChanges(oldBoards, group.state.boards, $("resource-desktop"));
    $("current-events").replaceChildren(...(group.events.length ? currentEventNodes(group.events) : [node("p", "桌面棋具更新")]));
    $("playback-progress").textContent = total === null ? `已显示 ${index + 1} 次变化 · 结算中` : `${index + 1} / ${total}`;
    const duration = matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 650 / speed;
    await window.NomosBoards.animate(window.NomosBoards.movements(oldBoards, group.state.boards), positions, $("resource-desktop"), duration, signal, animations => {playback.animations = animations;});
    if (duration) await playback.wait(Math.max(0, duration - (performance.now() - started)), signal);
  },
  finish: batch => {
    replaying = false;
    renderKeyMessages(window.NomosTableFeedback.finishedEvents(batch));
    $("current-events").replaceChildren(...currentEventNodes(window.NomosTableFeedback.finishedEvents(batch)));
    $("current-events").scrollTop = 0;
    playbackMode();
    $("playback-progress").textContent = "已到达当前局面";
  },
});
async function openAction(action, values = {}) {
  if (playing) return;
  selected = action; inputs = {...values};
  $("choice-form").dataset.surface = action.surface;
  lastDraft = null;
  editingFields.clear();
  $("fields").replaceChildren(); $("choice-form").dataset.complete = "";
  $("draft-preview").replaceChildren(); $("draft-validation").textContent = "";
  $("confirm").disabled = true;
  $("action-title").textContent = action.title; $("action-description").textContent = action.description;
  $("action-title").hidden = action.surface === "choices";
  $("action-description").hidden = action.surface === "choices";
  $("choice-form").hidden = false; $("actions").hidden = true;
  const onBoard = action.surface !== "dialog";
  $("inline-choice").hidden = !onBoard || action.surface === "seats";
  if (action.surface === "seats") $("seat-desktop").insertBefore($("choice-form"), $("player-seats"));
  else (onBoard ? $("inline-choice") : $("choice-dialog")).append($("choice-form"));
  if (onBoard) $(action.surface === "seats" ? "seat-desktop" : "inline-choice").scrollIntoView({behavior:"smooth", block:"nearest"});
  else if (!$("choice-dialog").open) $("choice-dialog").showModal();
  await updateDraft();
  if (onBoard) $(action.surface === "seats" ? "seat-desktop" : "inline-choice").scrollIntoView({behavior:"instant", block:"start"});
  renderChoices();
}
function renderRules(rules) {
  $("open-rules").hidden = !rules;
  $("rules-index").replaceChildren(); $("rules-sections").replaceChildren(); $("rules-sources").replaceChildren();
  if (!rules) return;
  $("rules-title").textContent = rules.title;
  rules.sections.forEach((section, index) => {
    const part = node("section"); part.id = "rule-section-" + index;
    part.append(node("h3", section.title), node("p", section.text));
    const link = node("a", section.title); link.href = "#" + part.id;
    link.onclick = event => {event.preventDefault(); part.scrollIntoView({block: "start"});};
    $("rules-index").append(link); $("rules-sections").append(part);
  });
  for (const source of rules.sources) {
    const link = node("a", source.title); link.href = source.url;
    link.target = "_blank"; link.rel = "noopener noreferrer";
    $("rules-sources").append(link);
  }
}
function renderPanels(panels, before = []) {
  const changes = new Map(window.NomosTableFeedback.compare({panels: before}, {panels}).map(change => [change.id, change]));
  const openPanels = new Set(view ? [...document.querySelectorAll("details.panel[open]")].map(panel => panel.dataset.panelId) : []);
  for (const zone of ["overview", "board", "private", "history"]) $(zone + "-panels").replaceChildren();
  for (const panel of window.NomosTableFeedback.bodyPanels(panels)) {
    const component = panel.format?.kind === "collection" ? panel.format.element.kind : panel.format?.kind;
    const folded = panel.zone === "history" || panel.fold;
    const container = node(folded ? "details" : "div", undefined, "panel visual-" + component);
    container.dataset.panelId = panel.id;
    if (folded) container.open = openPanels.has(panel.id);
    const caption = panel.title + (view.status === "closed" && panel.zone === "private" ? " · 局中信息" : "");
    const heading = node(folded ? "summary" : "div", caption, "panel-title");
    const change = changes.get(panel.id);
    if (change) {
      container.classList.add("panel-updated");
      heading.append(node("span", change.values.length ? change.values.map(v => v.label + " " + (v.amount > 0 ? "+" : "") + v.amount).join(" · ") : "已更新", "change-note"));
    }
    container.append(heading);
    const content = node("div", undefined, "panel-value");
    content.append(panel.format ? widgets.render(panel.data, panel.format, {...visualContext(), descriptions:panel.zone === "private", historical:panel.zone === "history"}) : valueNode(panel.value, panel.zone === "board"));
    if (change && panel.format?.kind === "resources") {
      for (const key of Object.keys(panel.format.fields)) {
        const delta = change.values.find(v => v.key === key);
        const resource = [...content.querySelectorAll("[data-resource]")].find(el => el.dataset.resource === key);
        if (delta && resource) {
          resource.classList.add("resource-updated");
          resource.append(node("span", (delta.amount > 0 ? "+" : "") + delta.amount, "resource-delta"));
        }
      }
    }
    container.append(content); $(panel.zone + "-panels").append(container);
  }
  document.querySelector(".board").hidden = !$("board-panels").childElementCount;
}
async function render(next) {
  view = next; selected = null; inputs = {}; lastDraft = null; needsSync = false; draftVersion++;
  window.NomosCognition.renderAdvice($("strategy-advice"), null, visualContext());
  $("ask-advice").hidden = !view.strategy_available;
  $("setup").hidden = true; $("table").hidden = false;
  $("choice-form").hidden = true; $("actions").hidden = false;
  if ($("choice-dialog").open) $("choice-dialog").close();
  $("inline-choice").hidden = true; $("choice-dialog").append($("choice-form"));
  $("title").textContent = view.title; $("seat").textContent = "你：" + view.seat;
  document.title = view.title + " · Nomos";
  $("game-description").textContent = view.description;
  renderRules(view.rules);
  renderEvents();
  $("actions").replaceChildren();
  $("actions").append(window.NomosActionControls.render(view.actions, visualContext(),
    action => run(() => openAction(action)),
    (action, values, label) => run(() => submitAction(action, values, label), "正在结算并等待其他参与者…")));
  if (view.status === "budget" || view.coordination?.paused) {
    const button = node("button", "继续其他参与者的行动");
    button.onclick = () => run(() => control("/api/continue", {session, revision: view.revision}));
    $("actions").append(button);
  }
  if (view.code) feedback(messages[view.code] || "对局已暂停。", true);
  $("end-report").hidden = true;
  $("event-stage").hidden = !view.playback.groups.length && !view.recent_events.length;
  if (view.playback.groups.length && !playback.seen.has(view.playback.id)) await playback.play(view.playback);
  else {frame(view.playback.final); playbackLock(false);}
  renderKeyMessages(view.events);
  $("tab-recap").hidden = !view.end_report || view.status !== "closed";
  $("end-report").hidden = !view.end_report || view.status !== "closed";
  $("end-player-choices").replaceChildren();
  if (view.end_report) {
    $("end-report-label").textContent = view.result_label;
    $("end-report-result").replaceChildren(widgets.render(view.end_data, view.end_format, {...visualContext(), historical:true, orderBySeat:true}));
    if (!view.end_report.player_choices.length) {
      $("end-player-choices").append(node("p", "本局未提交个人行动。"));
    }
    view.end_report.player_choices.forEach((decision, index) => {
      const record = node("details", undefined, "record");
      record.append(node("summary", (index + 1) + ". " + decision.action));
      const context = node("div", undefined, "decision-context");
      for (const panel of decision.context) {
        const item = node("span");
        item.append(node("span", panel.title + "：", "record-key"), widgets.render(panel.data, panel.format, {...visualContext(), historical:true}));
        context.append(item);
      }
      record.append(context);
      for (const input of decision.inputs) {
        const row = node("div", undefined, "record-row");
        row.append(node("span", input.label, "record-key"), valueNode(input.value));
        record.append(row);
      }
      const source = node("details");
      source.append(node("summary", "执行来源"), node("code", decision.source));
      record.append(source); $("end-player-choices").append(record);
    });
  }
  if (view.status === "closed" && !endingShown) {
    $("ending-result-label").textContent = view.result_label;
    $("ending-value").replaceChildren(widgets.render(view.end_data, view.end_format, {...visualContext(), historical:true, orderBySeat:true}));
    $("ending-progress").replaceChildren();
    for (const panel of view.panels.filter(panel => panel.zone === "board" && panel.format?.kind === "track")) {
      const row = node("div", undefined, "ending-progress-row");
      row.append(node("span", panel.title), node("strong", `${panel.data} / ${panel.format.steps}`));
      $("ending-progress").append(row);
    }
    $("ending").showModal(); endingShown = true;
  }
  const auditActors = view.end_report?.cognition_audit || [];
  $("mental-audit").hidden = !auditActors.length;
  $("audit-content").replaceChildren();
  $("audit-content").auditState = null;
  $("audit-actor").replaceChildren(...auditActors.map(person => {
    const option = node("option", person.label + (person.self ? " · 你" : " · 电脑"));
    option.value = person.actor; return option;
  }));
}
async function updateDraft() {
  const version = ++draftVersion;
  $("draft-preview").replaceChildren(); $("draft-validation").textContent = "";
  $("confirm").disabled = true; $("choice-form").dataset.complete = "";
  const localField = selected.target?.local_edit ? selected.target
    : lastDraft?.fields.find(field => field.local_edit);
  let draft = window.NomosSeatChoices.localDraft(localField, inputs[localField?.name]);
  if (!draft) draft = await api("/api/draft", {session, action: selected.id, revision: view.revision, inputs});
  if (version !== draftVersion) return;
  let initialized = false;
  for (const field of draft.fields) {
    if (field.kind === "enter" && inputs[field.name] === undefined && widgets.editable(field.format, field.allocation) && !field.error) {
      inputs[field.name] = field.suggested ?? widgets.initial(field.format, field.allocation); initialized = true;
    }
  }
  if (initialized) {
    draft = await api("/api/draft", {session, action: selected.id, revision: view.revision, inputs});
    if (version !== draftVersion) return;
  }
  lastDraft = draft;
  $("draft-preview").replaceChildren();
  for (const preview of draft.preview || []) {
    const part = node("div", undefined, "preview-part");
    part.append(node("span", preview.title, "preview-title"), widgets.render(preview.data, preview.format, {...visualContext(), compact:true}));
    $("draft-preview").append(part);
  }
  $("draft-validation").textContent = draft.fields.find(f => f.error)?.error || "";
  $("fields").replaceChildren();
  $("choice-form").dataset.complete = draft.complete ? "yes" : "";
  $("confirm").disabled = !draft.complete;
  for (let index = 0; index < draft.fields.length; index++) {
    const field = draft.fields[index], fieldset = node("fieldset");
    fieldset.append(node("legend", field.label));
    if (selected.surface === "choices" && field.name === selected.target.name && inputs[field.name] !== undefined) {
      continue;
    }
    if (selected.surface === "seats" && field.name === selected.target.name) {
      const ids = window.NomosSeatChoices.selection(selected.target, inputs[field.name]);
      const chosen = field.fixed ? field.data : field.options.filter(o => ids.includes(o.id)).map(o => o.data);
      const people = Array.isArray(chosen) ? chosen : [chosen];
      fieldset.append(node("p", field.kind === "subset" ? window.NomosTableFeedback.selectionCaption(field.min, field.max, people.length) : "当前选择", "bounds"));
      const summary = node("div", undefined, "seat-selection-summary");
      for (const person of people.filter(Boolean)) summary.append(widgets.render(person, {kind:"reference"}, visualContext()));
      fieldset.append(summary); $("fields").append(fieldset); continue;
    }
    if (field.fixed) {
      fieldset.className = "fixed-input";
      if (field.format.kind === "card" && selected.surface === "inline") {
        fieldset.append(node("p", field.format.label + " " + field.data[field.format.fields.identity], "selected-card-caption"));
      } else if (field.fixed_label) fieldset.append(node("p", field.fixed_label));
      else if (Array.isArray(field.value) && !field.value.length) fieldset.append(node("p", "本项无需选择"));
      else fieldset.append(field.data !== undefined ? widgets.render(field.data, field.format, {...visualContext(), targets: []}) : valueNode(field.value));
      $("fields").append(fieldset);
      continue;
    }
    if (field.kind === "subset") fieldset.append(node("p", window.NomosTableFeedback.selectionCaption(field.min, field.max, inputs[field.name]?.length || 0), "bounds"));
    if (field.options) {
      const isCard = field.options[0]?.format.kind === "card";
      const options = node("div", undefined, isCard ? "options card-grid" : "options");
      const condensed = isCard && field.kind === "member" && inputs[field.name] !== undefined && !editingFields.has(field.name);
      if (condensed && selected.surface === "inline") {
        const option = field.options.find(o => o.id === inputs[field.name]);
        fieldset.append(node("p", option.format.label + " " + option.data[option.format.fields.identity], "selected-card-caption"));
      }
      for (const option of field.options.filter(o => !(condensed && selected.surface === "inline") && (!condensed || o.id === inputs[field.name]))) {
        const label = node("label", undefined, "option" + (isCard ? " card-option" : "")), input = document.createElement("input");
        input.type = field.kind === "member" ? "radio" : "checkbox";
        input.name = field.name; input.value = option.id;
        input.dataset.focusKey = field.name + ":option:" + option.id;
        input.checked = field.kind === "member" ? inputs[field.name] === option.id : (inputs[field.name] || []).includes(option.id);
        if (field.kind === "subset" && !input.checked && (inputs[field.name]?.length || 0) >= field.max) {
          input.disabled = true; input.dataset.unavailable = "selection_limit";
        }
        input.setAttribute("aria-label", typeof option.label === "string" ? option.label : "选择 " + field.label + " " + (option.id + 1));
        input.onchange = async () => {
          if (busy) {input.checked = !input.checked; return;}
          if (field.kind === "member") {inputs[field.name] = option.id; editingFields.delete(field.name);}
          else {
            const values = [...(inputs[field.name] || [])];
            if (input.checked) values.push(option.id); else values.splice(values.indexOf(option.id), 1);
            if (field.kind === "subset" && values.length > field.max) {input.checked = false; return;}
            inputs[field.name] = values;
          }
          // Downstream domains depend on earlier inputs; old values are discarded.
          for (const later of draft.fields.slice(index + 1)) delete inputs[later.name];
          await run(updateDraft);
        };
        const visual = ["card", "resource_choice", "badge", "reference", "record", "table", "variant", "optional"].includes(option.format?.kind);
        const caption = visual ? widgets.render(option.data, option.format, {...visualContext(), targets: [], choice:true, fieldLabels:option.format.kind === "variant"}) : valueNode(option.label);
        if (typeof option.label !== "string" && caption.textContent.trim()) input.setAttribute("aria-label", caption.getAttribute("aria-label") || caption.textContent.trim());
        if (option.icon) caption.prepend(window.NomosIcon(option.icon));
        label.append(input, caption);
        options.append(label);
      }
      fieldset.append(options);
      if (condensed && field.options.length > 1) {
        const revise = node("button", "重选", "secondary"); revise.type = "button";
        revise.onclick = () => run(async () => {editingFields.add(field.name); await updateDraft();});
        fieldset.append(revise);
      }
      if (field.kind !== "member" && (field.kind !== "subset" || field.min === 0)) {
        const empty = node("button", "不选择目标", "secondary"); empty.type = "button";
        empty.onclick = () => run(async () => {
          inputs[field.name] = [];
          for (const later of draft.fields.slice(index + 1)) delete inputs[later.name];
          await updateDraft();
        });
        fieldset.append(empty);
      }
    } else if (widgets.editable(field.format, field.allocation)) {
      fieldset.append(widgets.editor(inputs[field.name], field.format, {
        label: field.label, path: field.name, limit: field.limit, allocation: field.allocation, board: selected.surface === "board",
        unitIcon: view.playback.final.boards.find(b => b.id === selected.board)?.icon,
        change: value => {
          if (busy) return;
          inputs[field.name] = value;
          for (const later of draft.fields.slice(index + 1)) delete inputs[later.name];
          run(updateDraft);
        },
      }));
      if (field.suggested !== undefined) {
        const suggest = node("button", field.suggest_label || "采用建议值", "secondary"); suggest.type = "button";
        suggest.onclick = () => run(async () => {
          inputs[field.name] = field.suggested;
          for (const later of draft.fields.slice(index + 1)) delete inputs[later.name];
          await updateDraft();
        }); fieldset.append(suggest);
      }
    } else if (field.format.kind === "allocation") {
      fieldset.append(node("p", field.error || "暂时无法读取分配目标"));
    } else {
      const entry = node("textarea"); entry.setAttribute("aria-label", field.label);
      entry.value = inputs[field.name] === undefined ? "" : JSON.stringify(inputs[field.name]);
      const apply = node("button", "确定输入", "secondary"); apply.type = "button";
      apply.onclick = () => run(async () => {inputs[field.name] = JSON.parse(entry.value); await updateDraft();});
      fieldset.append(entry, apply);
    }
    $("fields").append(fieldset);
  }
  renderSeats(displayState?.seats || view.seats);
  refreshCardSelection();
}
function refreshCardSelection() {
  for (const button of document.querySelectorAll(".card-command")) {
    const chosen = selected?.id === button.dataset.action && inputs[button.dataset.input] === Number(button.dataset.option);
    button.setAttribute("aria-pressed", String(chosen));
  }
  for (const card of document.querySelectorAll(".game-card")) card.classList.toggle("is-selected", !!card.querySelector('.card-command[aria-pressed="true"]'));
}
async function submitAction(action, values, label) {
  const title = action.title + (label ? " · " + label : "");
  pendingCoordinationDraft = null;
  await control("/api/submit", {session, action: action.id, revision: view.revision, inputs: values});
  if (view.code) feedback(title + "已提交。" + (messages[view.code] || "其他参与者的行动已暂停。") + " [" + view.code + "]", true);
  else feedback(window.NomosTableFeedback.completion(title, view.status, view.actions));
}
$("choice-form").onsubmit = event => {
  event.preventDefault();
  run(() => submitAction(selected, inputs), "正在结算并等待其他参与者…");
};
async function loadMentalAudit(offset = 0) {
  const actor = $("audit-actor").value, currentSession = session;
  $("load-audit").disabled = true;
  try {
    const audit = await api("/api/cognition-audit", {session:currentSession, actor, offset});
    if (session !== currentSession || $("audit-actor").value !== actor) return;
    window.NomosMentalAudit.render($("audit-content"), audit, visualContext(), page => run(() => loadMentalAudit(page)));
  } finally {$("load-audit").disabled = false;}
}
$("load-audit").onclick = () => run(() => loadMentalAudit());
$("audit-actor").onchange = () => {$("audit-content").replaceChildren();};
playback.speed = Number($("playback-speed").value);
$("playback-speed").onchange = event => {playback.speed = Number(event.target.value);};
$("pause-playback").append(window.NomosIcon("pause"));
$("skip-playback").append(window.NomosIcon("skip-forward"));
$("replay-playback").append(window.NomosIcon("restart"));
$("pause-playback").onclick = () => {
  const paused = playback.toggle();
  $("pause-playback").setAttribute("aria-label", paused ? "恢复播放" : "暂停播放");
  $("pause-playback").title = paused ? "恢复播放" : "暂停播放";
  $("pause-playback").replaceChildren(window.NomosIcon(paused ? "play" : "pause"));
  playbackMode();
};
$("skip-playback").onclick = () => playback.skip();
$("replay-playback").onclick = () => {if (!busy && !playing && playback.batch) {replaying = true; playback.play(playback.batch, true);}};
function cancelChoice() {
  pendingCoordinationDraft = null;
  lastDraft = null;
  selected = null; inputs = {}; draftVersion++;
  $("draft-preview").replaceChildren(); $("draft-validation").textContent = "";
  $("choice-form").hidden = true; $("actions").hidden = false;
  if ($("choice-dialog").open) $("choice-dialog").close();
  $("inline-choice").hidden = true; $("choice-dialog").append($("choice-form"));
  renderChoices();
  renderSeats(displayState?.seats || view.seats);
  refreshCardSelection();
}
$("open-rules").onclick = () => $("rules-dialog").showModal();
$("setup-rules").onclick = () => $("rules-dialog").showModal();
$("close-rules").onclick = () => $("rules-dialog").close();
$("cancel").onclick = cancelChoice;
$("choice-dialog").addEventListener("cancel", event => {
  event.preventDefault(); if (!busy) cancelChoice();
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && selected && !busy && !$("choice-dialog").open && !$("rules-dialog").open && !$("record-peek").open) {
    event.preventDefault(); cancelChoice();
  }
});
$("restart").onclick = () => run(async () => {
  try {const closed = await api("/api/close", {session}); subjectGroup = closed.group || null;}
  catch (error) {if (error.message !== "UnknownSession") throw error;}
  session = null; endingShown = false; needsSync = false;
  playback.reset(); displayState = null;
  inbox.reset(); renderKeyMessages(); showPage("desk");
  journal.reset();
  notes.clear(); openNotes.clear();
  view = null; $("table").hidden = true; $("setup").hidden = false; $("seat").textContent = "";
});
function syncTable() {
  return run(async () => {
    await render(await api("/api/view", {session}));
    await restoreCoordinationDraft();
    if (!view.code) feedback("已同步当前桌面。");
  }, "正在读取当前对局…");
}
for (const id of ["sync-table", "sync-choice"]) {
  $(id).append(window.NomosIcon("restart"));
  $(id).onclick = syncTable;
}
$("ask-advice").append(window.NomosIcon("eye"));
$("ask-advice").onclick = () => run(async () => {
  if (playing || needsSync || !view.strategy_available) return;
  const result = await api("/api/advice", {session, revision: view.revision});
  if (result.revision === view.revision) window.NomosCognition.renderAdvice($("strategy-advice"), result, visualContext());
}, "正在分析当前选择…");
$("dismiss-ending").onclick = () => $("ending").close();
$("show-end-report").onclick = () => {
  $("ending").close();
  showPage("recap");
  requestAnimationFrame(() => {
    $("end-report-title").focus({preventScroll:true});
    $("end-report").scrollIntoView({behavior:"instant", block:"start"});
  });
};
async function selectGame(game) {
  const setup = await api("/api/select", {game:game.id});
  if (currentGame !== game.id) subjectGroup = null;
  currentGame = game.id; view = null; endingShown = false; needsSync = false;
  pendingCoordinationDraft = null;
  playback.reset(); displayState = null;
  inbox.reset(); renderKeyMessages(); showPage("desk");
  journal.reset();
  notes.clear(); openNotes.clear();
  $("library").hidden = true; $("setup").hidden = false; $("seats").replaceChildren();
  $("title").textContent = setup.title; $("intro").textContent = setup.description;
  renderRules(setup.rules);
  $("setup-rules").hidden = !setup.rules;
  for (const seat of setup.seats) {
    const button = node("button", seat.label, "seat-button");
    button.dataset.seat = seat.id;
    button.onclick = () => run(async () => {
      const started = await api("/api/start", {game:currentGame, seat:seat.id, ...(subjectGroup ? {group:subjectGroup} : {})});
      subjectGroup = started.group || null;
      session = started.session; await render(started.view);
      if (!view.code) feedback(window.NomosTableFeedback.nextChoice(view.status, view.actions));
    });
    $("seats").append(button);
  }
}
$("back-library").onclick = () => {
  $("setup").hidden = true; $("library").hidden = false;
  $("title").textContent = "Nomos 桌游"; $("library-status").textContent = "";
};
fetch("/api/setup").then(response => {
  if (!response.ok) throw new Error("SetupFailed");
  return response.json();
}).then(async setup => {
  catalog = setup.games;
  $("title").textContent = "Nomos 桌游";
  $("back-library").hidden = catalog.length < 2;
  for (const game of catalog) {
    const button = node("button", undefined, "game-choice secondary");
    button.dataset.game = game.id;
    button.append(node("strong", game.title), node("span", game.description));
    button.onclick = () => run(() => selectGame(game), "正在检查规则并准备席位…");
    $("game-list").append(button);
  }
  $("library").hidden = false;
  if (catalog.length === 1) await run(() => selectGame(catalog[0]), "正在检查规则并准备席位…");
}).catch(() => {
  $("library").hidden = false; $("library-status").textContent = "桌面暂时无法连接，请确认本地服务正在运行。";
});
