const state = { workspaces: [], currentWorkspace: null, task: null, currentPanel: "chat", sessions: new Map(), user: null, models: [], usage: null, market: null, authMode: "login", settingsTab: "account", accountEpoch: 0 };
const $ = (id) => document.getElementById(id);

// One modal at a time. Each response belongs to the account that opened it.
const dialogQueue = [];
let activeDialog = null;
function requestDialog(options) {
  return new Promise(resolve => {
    dialogQueue.push({options, resolve, epoch: state.accountEpoch, opener: document.activeElement});
    showNextDialog();
  });
}
function showNextDialog() {
  if (activeDialog || !dialogQueue.length) return;
  const entry = dialogQueue.shift(), options = entry.options;
  if (entry.epoch !== state.accountEpoch || (options.isCurrent && !options.isCurrent())) {
    entry.resolve(null); showNextDialog(); return;
  }
  activeDialog = entry;
  const dialog = $("app-dialog"), input = $("app-dialog-input");
  dialog.classList.toggle("dialog-danger", Boolean(options.danger));
  $("app-dialog-title").textContent = options.title || "确认操作";
  $("app-dialog-message").textContent = options.message || "";
  $("app-dialog-context").textContent = options.context || "";
  $("app-dialog-context").hidden = !options.context;
  $("app-dialog-detail").textContent = options.detail || "";
  $("app-dialog-detail").hidden = !options.detail;
  $("app-dialog-input-group").hidden = !options.input;
  $("app-dialog-input-label").textContent = options.inputLabel || "请输入";
  input.value = options.value || "";
  input.placeholder = options.placeholder || "";
  input.required = Boolean(options.input);
  $("app-dialog-error").textContent = "";
  $("app-dialog-confirm").textContent = options.confirmText || "确认";
  dialog.showModal();
  (options.input ? input : $("app-dialog-cancel")).focus();
  if (options.input) input.select();
}
function finishDialog(value) {
  const entry = activeDialog;
  if (!entry) return;
  activeDialog = null;
  $("app-dialog").close();
  const valid = entry.epoch === state.accountEpoch && (!entry.options.isCurrent || entry.options.isCurrent());
  entry.resolve(valid ? value : null);
  if (entry.opener?.isConnected) entry.opener.focus();
  Promise.resolve().then(showNextDialog);
}
function dismissDialogs() {
  for (const entry of dialogQueue.splice(0)) entry.resolve(null);
  finishDialog(null);
}
function setupDialogs() {
  const dialog = $("app-dialog");
  $("app-dialog-form").onsubmit = event => {
    event.preventDefault();
    if (!activeDialog) return;
    const options = activeDialog.options, value = options.input ? $("app-dialog-input").value.trim() : true;
    const error = options.input && !value ? "请填写此项后继续。" : options.validate?.(value);
    if (error) { $("app-dialog-error").textContent = error; $("app-dialog-input").focus(); return; }
    finishDialog(value);
  };
  $("app-dialog-cancel").onclick = $("app-dialog-close").onclick = () => finishDialog(null);
  dialog.addEventListener("cancel", event => { event.preventDefault(); finishDialog(null); });
  dialog.addEventListener("keydown", event => {
    if (event.key !== "Tab") return;
    const controls = [...dialog.querySelectorAll("button, input")].filter(control => !control.disabled && control.getClientRects().length);
    const first = controls[0], last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  let backdrop = false;
  dialog.addEventListener("pointerdown", event => { backdrop = event.target === dialog; });
  dialog.addEventListener("click", event => { if (backdrop && event.target === dialog) finishDialog(null); backdrop = false; });
}

// Session DOM nodes stay bound to their original task even while detached.
const welcomeMarkup = $("project-messages").innerHTML;
const freeWelcomeMarkup = $("free-messages").innerHTML;
function projectSession(workspaceId) {
  if (!state.sessions.has(workspaceId)) state.sessions.set(workspaceId, { messages: [], task: null, draft: "", command: "", serviceCommand: "", generation: 0, historyLoaded: false, historyLoading: null, turnViews: new Map(), completedTasks: new Map(), treeWidth: 320, previewGeneration: 0, documentGeneration: 0, treeRoot: "", folderOpen: new Map(), selectedFile: "" });
  return state.sessions.get(workspaceId);
}
function renderConversation(workspaceId) {
  if (workspaceId !== "" && workspaceId !== state.currentWorkspace?.id) return;
  const container = $(workspaceId === "" ? "free-messages" : "project-messages"), session = projectSession(workspaceId);
  const displayed = [], grouped = new Set();
  for (const message of session.messages) {
    const taskId = message.dataset?.taskId, completed = session.completedTasks.get(taskId);
    if (!completed) { displayed.push(message); continue; }
    if (grouped.has(taskId)) continue;
    grouped.add(taskId);
    completed.body.replaceChildren(...session.messages.filter(node => node.dataset?.taskId === taskId));
    displayed.push(completed.message);
  }
  // A task may finish before any displayable event arrives.
  for (const [taskId, completed] of session.completedTasks) if (!grouped.has(taskId)) displayed.push(completed.message);
  container.replaceChildren(...displayed);
  if (!displayed.length) {
    container.innerHTML = workspaceId === "" ? freeWelcomeMarkup : welcomeMarkup;
    document.querySelectorAll("[data-suggest]").forEach((item) => item.onclick = () => { $("project-input").value = item.dataset.suggest; sendProjectMessage(); });
  }
  container.scrollTop = container.scrollHeight;
}
function addProjectMessage(workspaceId, message) {
  projectSession(workspaceId).messages.push(message);
  renderConversation(workspaceId);
}
function resetConversations() {
  dismissDialogs();
  resetLivePreview();
  state.accountEpoch++;
  state.sessions.clear(); state.currentWorkspace = null; state.task = null; state.workspaces = []; state.market = null;
  $("project-messages").replaceChildren(); $("free-messages").replaceChildren();
  $("document-preview").textContent = ""; $("document-preview").classList.add("hidden");
  for (const id of ["project-input", "free-input", "quick-chat"]) $(id).value = "";
}
async function loadConversation(workspaceId, refresh = false) {
  const session = projectSession(workspaceId), epoch = state.accountEpoch;
  if (session.historyLoading) return session.historyLoading;
  if (session.historyLoaded && !refresh) return;
  session.historyLoading = (async () => {
    try {
      const data = await api(`/api/conversations?workspace_id=${encodeURIComponent(workspaceId)}`);
      if (epoch !== state.accountEpoch) return;
      const previous = session.historyLoaded ? [] : session.messages.splice(0);
      for (const turn of data.items || []) {
        let view = session.turnViews.get(turn.id);
        if (!view && turn.generation_id && session.generationViews?.has(turn.generation_id)) {
          view={message:session.generationViews.get(turn.generation_id)};
          session.turnViews.set(turn.id,view);
        }
        if (!view) {
          appendMessage("user", turn.goal, workspaceId, "", turn.created_at || "");
          view = {message: appendMessage("agent", turn.error || turn.reply || "正在生成回复…", workspaceId, "", turn.created_at || "")};
          session.turnViews.set(turn.id, view);
        }
        if (turn.task && !view.taskId) {
          const task = turn.task;
          const controls = appendAgentTurn(task, view.message);
          view.taskId = task.id;
          session.task = task;
          if (state.currentWorkspace?.id === workspaceId) state.task = task;
          const run = {taskId: task.id, workspaceId, task, after: 0, ...controls, epoch};
          for (const event of turn.events || []) { renderTaskEvent(event, run); run.after = Math.max(run.after, event.sequence); }
          if (["succeeded", "failed", "cancelled"].includes(task.status)) finishTaskView(run, task.status);
          else if (["executing", "cancelling"].includes(task.status)) pollTask(run);
        } else if (!turn.task) {
          const timing = turn.timing || {started_at:turn.created_at, finished_at:turn.finished_at};
          if (turn.status === "generating") {
            if (!view.message.querySelector('.thinking-indicator')) showThinking(view.message, timing);
            renderIntent(view.message, turn.intent);
          }
          else {
            view.message.innerHTML = `${intentMarkup(turn.intent, true)}<div class="message-bubble">${escapeHtml(turn.error || turn.reply || "本轮对话已结束。")}</div>`;
            setMessageTiming(view.message, timing);
          }
        }
      }
      for (const job of data.generations || []) {
        session.generationViews ||= new Map();
        let message=session.generationViews.get(job.id) || session.turnViews.get(job.turn_id)?.message;
        if (!message) {
          appendMessage("user",job.goal,workspaceId,"",job.created_at);
          message=appendMessage("agent","",workspaceId,"",job.created_at);
        }
        watchGeneration(job,message,workspaceId,epoch);
      }
      session.messages.push(...previous);
      session.historyLoaded = true;
      renderConversation(workspaceId);
      if ((data.items || []).some(turn => turn.status === "generating")) {
        setTimeout(() => { if (epoch === state.accountEpoch) loadConversation(workspaceId, true); }, 1500);
      }
    } catch (error) { if (epoch === state.accountEpoch) showError(new Error(`历史记录加载失败：${error.message}，重新打开工程可重试`)); }
    finally { session.historyLoading = null; }
  })();
  return session.historyLoading;
}
function updateSessionTask(workspaceId, task) {
  const session = projectSession(workspaceId);
  if (session.task?.id === task.id) session.task = task;
  if (state.currentWorkspace?.id === workspaceId && state.task?.id === task.id) state.task = task;
}

async function api(path, options = {}) {
  const epoch = state.accountEpoch;
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await response.json();
  if (epoch !== state.accountEpoch) { const error = new Error("账户已切换，忽略旧请求"); error.staleAccount = true; throw error; }
  if (!response.ok) { const payload = data.error && typeof data.error === "object" ? data.error : data; const error = new Error(payload.message || payload.error || "请求失败"); error.httpStatus = response.status; error.approvalRequired = Boolean(payload.approval_required); error.authRequired = response.status === 401; error.payload = payload; if (error.authRequired && epoch === state.accountEpoch && !path.startsWith("/api/auth/")) showAuth("login"); throw error; }
  return data;
}
async function callTool(tool, action, workspaceId, argumentsValue = {}, approved = false) { const response = await api("/api/tools/call", { method: "POST", body: JSON.stringify({ api_version: "1.0", tool, action, workspace_id: workspaceId || "", arguments: argumentsValue, approval: approved === true ? { approved: true, source: "user_confirmation" } : {} }) }); return response.data; }

function showAuth(mode = "login") { dismissDialogs(); state.authMode = mode; $("auth-screen").classList.remove("hidden"); $("app-shell").classList.add("auth-locked"); $("auth-title").textContent = mode === "register" ? "注册 CodeSpider" : "登录 CodeSpider"; $("auth-subtitle").textContent = mode === "register" ? "首个注册用户自动成为管理员。" : "登录后管理工程、模型和积分用量。"; $("auth-submit").textContent = mode === "register" ? "注册并登录" : "登录"; $("auth-switch").textContent = mode === "register" ? "已有账号？登录" : "没有账号？注册"; $("auth-error").textContent = ""; $("auth-form").reset(); }
function hideAuth() { $("auth-screen").classList.add("hidden"); $("app-shell").classList.remove("auth-locked"); }
async function submitAuth(event) { event.preventDefault(); try { const endpoint = state.authMode === "register" ? "/api/auth/register" : "/api/auth/login"; await api(endpoint, { method: "POST", body: JSON.stringify({ username: $("auth-username").value.trim(), password: $("auth-password").value }) }); await loadAccount(); hideAuth(); await loadWorkspaces(); setView("home"); } catch (error) { $("auth-error").textContent = error.message || "认证失败"; } }
async function loadAccount() { const account = await api("/api/auth/me"); if (state.user?.id !== account.user?.id) resetConversations(); state.user = account.user; state.models = account.models || []; state.usage = account.usage || { total_calls: 0, total_cost: 0 }; updateAccountUi(account); loadCheckin(); if (state.user.role === "ADMIN") await loadAdminData(); }
async function loadCheckin() { try { const status = await api("/api/auth/checkin"); updateCheckinUi(status); } catch (_) {} }
function updateCheckinUi(status) { const button = $("checkin-button"), label = $("checkin-status"); if (!button || !label || !status) return; button.disabled = Boolean(status.claimed); button.textContent = status.claimed ? "今日已签到" : `签到领 ${status.reward || 10} 积分`; label.textContent = status.claimed ? `已领取 · ${status.date}` : "今天还没有签到"; }
async function claimCheckin() { try { const status = await api("/api/auth/checkin", { method: "POST", body: "{}" }); updateCheckinUi(status); await loadAccount(); showToast(status.already_claimed ? "今天已经签到过了" : `签到成功，获得 ${status.reward} 积分`); } catch (error) { showError(error); } }
function switchSettingsTab(tab = "account") {
  if (!["account", "models", "users", "defaults", "market"].includes(tab) || (["models", "users", "defaults"].includes(tab) && state.user?.role !== "ADMIN")) tab = "account";
  state.settingsTab = tab;
  document.querySelectorAll("[data-settings-tab]").forEach((button) => {
    const active = button.dataset.settingsTab === tab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll("[data-settings-section]").forEach((panel) => panel.classList.toggle("hidden", panel.dataset.settingsSection !== tab));
  if (tab === "market") loadMarket();
}
function updateSelectedModel(model = state.models.find((item) => item.id === state.user?.selected_model_id)) {
  $("global-model-summary").textContent = model?.name || "未选择模型";
  $("global-provider-summary").textContent = model ? `${model.provider} · ${model.model}` : "先选择一个可用模型";
}
function updateAccountUi(account) {
  const user = account.user, admin = user.role === "ADMIN";
  $("user-name").textContent = user.username;
  $("user-meta").textContent = admin ? `管理员 · ${user.balance} 积分` : `${user.balance} 积分`;
  $("user-avatar").textContent = (user.username || "A").slice(0, 1).toUpperCase();
  $("account-username").textContent = user.username;
  $("account-balance").textContent = `${user.balance} 积分`;
  $("account-calls").textContent = `${account.usage?.total_calls || 0} 次`;
  $("settings-role").textContent = admin ? "管理员" : "个人账户";
  const select = $("account-model");
  select.innerHTML = state.models.length ? state.models.map((model) => `<option value="${escapeHtml(model.id)}">${escapeHtml(model.name)} · ${escapeHtml(model.model)}</option>`).join("") : `<option value="">暂无可用模型</option>`;
  if (account.selected_model) select.value = account.selected_model.id;
  $("save-account-model").disabled = !state.models.length;
  document.querySelectorAll("[data-settings-admin]").forEach((button) => button.classList.toggle("hidden", !admin));
  $("admin-model-panel").classList.toggle("hidden", !admin);
  $("legacy-global-settings").classList.toggle("hidden", !admin);
  switchSettingsTab(state.settingsTab);
  updateSelectedModel(account.selected_model);
}
function marketItemCard(item) {
  const kind = {plugin:"插件",skill:"Skill",function:"Function"}[item.kind];
  const example = Object.fromEntries(Object.keys(item.input_schema?.properties || {}).map(key=>[key, ""]));
  return `<article class="market-item"><div class="market-item-main"><span class="market-kind">${kind}</span><div><h3>${escapeHtml(item.name)}</h3><p>${escapeHtml(item.description)}</p><small>${escapeHtml(item.id)} · v${escapeHtml(item.version)}${item.personal ? " · 仅自己可见" : " · 内置"}</small><details><summary>使用说明</summary><pre>${escapeHtml(item.instructions || JSON.stringify(item.input_schema, null, 2))}</pre></details>${item.kind === "function" && item.enabled ? `<details><summary>在当前项目调用</summary><p>当前项目：${escapeHtml(state.currentWorkspace?.name || "请先打开一个项目")}</p><textarea data-function-input="${escapeHtml(item.id)}" rows="4" aria-label="Function 参数">${escapeHtml(JSON.stringify(example, null, 2))}</textarea><button class="outline-btn" data-function-call="${escapeHtml(item.id)}">调用</button><pre data-function-output="${escapeHtml(item.id)}"></pre></details>` : ""}</div></div><div class="market-controls">${item.installed ? `<label class="market-toggle"><input type="checkbox" data-market-id="${escapeHtml(item.id)}" ${item.enabled ? "checked" : ""}><span>${item.enabled ? "已启用" : "已停用"}</span></label>` : ""}<button class="outline-btn" data-market-install="${escapeHtml(item.id)}" data-installed="${item.installed}">${item.installed ? "卸载" : "安装"}</button></div></article>`;
}
function renderMarket() {
  const list = $("market-list");
  const query = ($("market-search")?.value || "").toLowerCase(), kind = $("market-kind")?.value || "";
  const items = (state.market?.items || []).filter(item=>(!kind || item.kind===kind) && `${item.name} ${item.description} ${item.id}`.toLowerCase().includes(query));
  list.innerHTML = items.map(marketItemCard).join("") || `<div class="settings-empty">没有匹配的能力</div>`;
  list.querySelectorAll?.("[data-market-id]").forEach(input=>input.onchange=()=>changeMarket(input.dataset.marketId, input.checked));
  list.querySelectorAll?.("[data-market-install]").forEach(button=>button.onclick=()=>changeMarket(button.dataset.marketInstall, button.dataset.installed!=="true", button.dataset.installed!=="true"));
  list.querySelectorAll?.("[data-function-call]").forEach(button=>button.onclick=()=>invokeMarketFunction(button.dataset.functionCall));
}
async function loadMarket() {
  try { state.market = await api("/api/market"); renderMarket(); }
  catch (error) { if (!error.authRequired) showError(error); }
}
async function changeMarket(itemId, enabled, installed) {
  try {
    await api("/api/market/preferences", {method:"POST",body:JSON.stringify({item_id:itemId,enabled,installed})});
    await loadMarket();
  } catch (error) { showError(error); if (!error.staleAccount) renderMarket(); }
}
async function invokeMarketFunction(itemId, approved = false, captured = null) {
  const epoch = state.accountEpoch, workspace = captured?.workspace || state.currentWorkspace;
  if (!workspace) return showError(new Error("请先打开要操作的项目"));
  let input;
  try {
    input = captured?.input || JSON.parse(document.querySelector(`[data-function-input="${itemId}"]`).value);
    const result = await callTool("function", "call", workspace.id, {function_id:itemId,input}, approved);
    if (state.currentWorkspace !== workspace || epoch !== state.accountEpoch) return;
    const output = document.querySelector(`[data-function-output="${itemId}"]`);
    if (output) output.textContent = JSON.stringify(result, null, 2);
  } catch (error) {
    if (state.currentWorkspace !== workspace || epoch !== state.accountEpoch) return;
    if (error.approvalRequired) {
      const confirmed = await requestDialog({title:"允许调用此功能？", message:error.message,
        context:workspace.name, detail:JSON.stringify(input, null, 2), confirmText:"允许调用",
        isCurrent:() => state.currentWorkspace === workspace && epoch === state.accountEpoch});
      if (confirmed && state.currentWorkspace === workspace && epoch === state.accountEpoch) return invokeMarketFunction(itemId, true, {workspace,input});
      return;
    }
    showError(error);
  }
}
async function saveMarketSkill() {
  try {
    const item = await api("/api/market/skills", {method: "POST", body: JSON.stringify({name: $("market-skill-name").value, keywords: $("market-skill-keywords").value.split(",").map(x => x.trim()).filter(Boolean), description: $("market-skill-description").value, instructions: $("market-skill-instructions").value})});
    $("market-skill-name").value = $("market-skill-keywords").value = $("market-skill-description").value = $("market-skill-instructions").value = "";
    $("market-skill-saved").textContent = "已保存";
    await loadMarket();
    setTimeout(() => { $("market-skill-saved").textContent = ""; }, 1800);
  } catch (error) { showError(error); }
}
async function loadAdminData() {
  const models = await api("/api/admin/models");
  const users = await api("/api/admin/users");
  $("admin-model-list").innerHTML = models.items.map((model) => `<div class="admin-row"><div class="settings-row-main"><span class="settings-row-symbol" aria-hidden="true">✦</span><div class="settings-row-copy"><b>${escapeHtml(model.name)}</b><small>${escapeHtml(model.provider)} / ${escapeHtml(model.model)} · ${model.api_key_set ? "密钥已配置" : "未配置密钥"}</small></div></div><div class="admin-row-actions"><button class="outline-btn" data-assign-model="${escapeHtml(model.id)}">分配给用户</button></div></div>`).join("") || `<div class="settings-empty">还没有模型，展开上方「添加模型」开始配置。</div>`;
  $("admin-user-list").innerHTML = users.items.map((user) => `<div class="admin-row"><div class="settings-row-main"><span class="settings-row-symbol" aria-hidden="true">${escapeHtml(user.username.slice(0, 1).toUpperCase())}</span><div class="settings-row-copy"><b>${escapeHtml(user.username)}</b><small>${user.role === "ADMIN" ? "管理员" : "成员"} · 余额 ${escapeHtml(user.balance)} 积分</small></div></div><div class="admin-row-actions"><input type="number" min="1" value="10" aria-label="为 ${escapeHtml(user.username)} 增加的积分" data-credit-value="${escapeHtml(user.id)}" /><button class="outline-btn" data-credit-user="${escapeHtml(user.id)}">充值</button></div></div>`).join("") || `<div class="settings-empty">暂无团队成员。</div>`;
  document.querySelectorAll("[data-credit-user]").forEach((button) => button.onclick = () => creditUser(button.dataset.creditUser));
  document.querySelectorAll("[data-assign-model]").forEach((button) => button.onclick = () => assignModel(button.dataset.assignModel, users.items));
}
async function saveAccountModel() { const modelId = $("account-model").value; if (!modelId) return; try { await api("/api/models/select", { method: "POST", body: JSON.stringify({ model_id: modelId }) }); state.user.selected_model_id = modelId; updateSelectedModel(); showToast("模型选择已保存"); } catch (error) { showError(error); } }
async function addAdminModel() { try { await api("/api/admin/models", { method: "POST", body: JSON.stringify({ name: $("admin-model-name").value, provider: $("admin-model-provider").value, model: $("admin-model-id").value, base_url: $("admin-model-base-url").value, api_key: $("admin-model-key").value }) }); ["admin-model-name", "admin-model-id", "admin-model-base-url", "admin-model-key"].forEach((id) => $(id).value = ""); await loadAccount(); $("admin-model-saved").textContent = "已添加"; setTimeout(() => $("admin-model-saved").textContent = "", 1800); } catch (error) { showError(error); } }
async function creditUser(userId) { const input = document.querySelector(`[data-credit-value="${userId}"]`); try { await api(`/api/admin/users/${userId}/credit`, { method: "POST", body: JSON.stringify({ amount: Number(input.value) }) }); await loadAccount(); showToast("积分已充值"); } catch (error) { showError(error); } }
async function assignModel(modelId, users) {
  const epoch = state.accountEpoch;
  const username = await requestDialog({title:"分配模型", message:"选择可使用此模型的用户。", context:modelId,
    input:true, inputLabel:"用户名", value:users.find(user => user.role === "USER")?.username || "",
    placeholder:"输入用户名", confirmText:"确认分配", validate:value => users.some(user => user.username === value) ? "" : "未找到该用户，请检查用户名。"});
  if (username === null || epoch !== state.accountEpoch) return;
  const user = users.find(item => item.username === username);
  if (!user) return;
  try { await api(`/api/admin/models/${modelId}/assign`, {method:"POST",body:JSON.stringify({user_id:user.id})}); showToast("模型已分配"); }
  catch (error) { showError(error); }
}

function escapeHtml(value) { return String(value ?? "").replace(/[&<>\"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '\"': "&quot;" }[char])); }
function showToast(message) { const toast = $("toast"); toast.textContent = message; toast.classList.add("show"); setTimeout(() => toast.classList.remove("show"), 2300); }
function showError(error) { if (!error.staleAccount) showToast(error.message || "请求失败"); }
function setView(view) { dismissDialogs(); if (view === "free-chat") loadConversation(""); document.querySelectorAll(".view").forEach((item) => item.classList.remove("active-view")); const target = $(`${view}-view`); if (target) target.classList.add("active-view"); document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === view)); updateProjectSwitcher(); }

async function loadWorkspaces() { const data = await api("/api/workspaces"); state.workspaces = data.items; renderWorkspaceLists(); }
function projectIcon(type) { return type === "html-prototype" ? "H5" : type === "python" ? "Py" : type === "vue" ? "V" : type === "java-springboot" ? "J" : "⌘"; }
function modeLabel(mode) { return mode === "divergent" ? "发散模式" : "安全执行模式"; }
function updateProjectSwitcher() {
  const workspace = state.currentWorkspace, inProject = Boolean(workspace && $("project-view")?.classList.contains("active-view"));
  $("switcher-project-name").textContent = inProject ? workspace.name : "CodeSpider 工作台";
  $("switcher-project-meta").textContent = inProject ? `${workspace.project_type} · ${modeLabel(workspace.execution_mode)}` : "首页 / 随意对话";
  $("switcher-project-icon").textContent = inProject ? projectIcon(workspace.project_type) : "⌘";
}
function renderProjectSwitcher() {
  const menu = $("project-switcher-menu");
  if (!menu) return;
  const projects = state.workspaces.map((workspace) => `<button class="project-menu-item ${state.currentWorkspace?.id === workspace.id ? "active" : ""}" data-workspace="${escapeHtml(workspace.id)}" role="menuitem"><span class="project-symbol">${projectIcon(workspace.project_type)}</span><span><b>${escapeHtml(workspace.name)}</b><small>${escapeHtml(workspace.project_type)}</small></span></button>`).join("");
  menu.innerHTML = `<button class="project-menu-item" data-view="free-chat" role="menuitem"><span class="project-symbol">✦</span><span><b>随意对话</b><small>不绑定工程</small></span></button><div class="project-menu-divider"></div>${projects || `<div class="project-menu-empty">还没有工程</div>`}<button class="project-menu-add" data-new-project type="button">＋ 添加工程</button>`;
  menu.querySelectorAll?.("[data-workspace]").forEach((item) => item.onclick = () => { closeProjectSwitcher(); openWorkspace(item.dataset.workspace); });
  menu.querySelectorAll?.("[data-view]").forEach((item) => item.onclick = () => { closeProjectSwitcher(); setView(item.dataset.view); });
  menu.querySelector?.("[data-new-project]") && (menu.querySelector("[data-new-project]").onclick = () => { closeProjectSwitcher(); setView("home"); openNewProject(); });
  updateProjectSwitcher();
}
function closeProjectSwitcher() { $("project-switcher-menu")?.classList.add("hidden"); $("project-switcher-toggle")?.setAttribute("aria-expanded", "false"); }
function renderWorkspaceLists() { renderProjectSwitcher(); $("project-cards").innerHTML = state.workspaces.map((workspace) => `<article class="project-card" data-workspace="${workspace.id}"><div class="project-card-top"><div class="project-card-icon">${projectIcon(workspace.project_type)}</div><span class="project-card-menu">···</span></div><h3>${escapeHtml(workspace.name)}</h3><p>${escapeHtml(workspace.root)}</p><div class="project-card-footer"><span>${escapeHtml(workspace.project_type)}</span><span>打开项目 ›</span></div></article>`).join(""); document.querySelectorAll(".project-card[data-workspace]").forEach((item) => item.onclick = () => openWorkspace(item.dataset.workspace)); $("empty-projects").classList.toggle("hidden", state.workspaces.length > 0); }

async function openWorkspace(id) {
  const workspace = state.workspaces.find((item) => item.id === id);
  if (!workspace) return;
  if (state.currentWorkspace?.id !== id) {
    if (state.currentWorkspace) Object.assign(projectSession(state.currentWorkspace.id), {
      draft: $("project-input").value, command: $("command").value, serviceCommand: $("service-command").value,
    });
    state.currentWorkspace = workspace;
    resetLivePreview();
    const session = projectSession(id);
    state.task = session.task;
    $("project-input").value = session.draft;
    $("command").value = session.command;
    $("service-command").value = session.serviceCommand;
    for (const target of ["file-tree", "preview-path", "preview-content", "preview-path-label", "document-preview", "settings-saved", "design-review-result"]) $(target).textContent = "";
    clearPreview(session);
    applyExplorerWidth(workspace);
    $("document-preview").classList.add("hidden");
    $("symbol-count").textContent = "—";
    $("doc-status").textContent = "待读取";
    $("command-output").textContent = "等待执行命令…";
    $("processes").textContent = "暂无运行中的服务";
    renderConversation(id);
    switchPanel("chat");
  }
  setView("project");
  renderWorkspaceLists();
  updateProjectHeader();
  fillSettings();
  await Promise.all([loadExplorer(), loadConversation(id)]);
}
function updateProjectHeader() { const workspace = state.currentWorkspace; $("project-name-title").textContent = workspace.name; $("project-meta").textContent = `${workspace.project_type} · ${modeLabel(workspace.execution_mode)} · ${workspace.root}`; $("project-avatar").textContent = projectIcon(workspace.project_type); $("context-project").textContent = workspace.name; $("context-path").textContent = workspace.root; $("context-mode").textContent = modeLabel(workspace.execution_mode); $("context-description").textContent = workspace.description || "还没有添加说明"; }
function openNewProject() { $("new-project-form").classList.remove("hidden"); $("project-name").focus(); }
$("project-name").oninput = () => { $("project-root").placeholder = `~/.codespider/project/${state.user?.id || "{用户ID}"}/${$("project-name").value.trim() || "{项目名称}"}`; };
function closeNewProject() { $("new-project-form").classList.add("hidden"); }
async function createWorkspace() { try { const workspace = await api("/api/workspaces", { method: "POST", body: JSON.stringify({ root: $("project-root").value, name: $("project-name").value }) }); closeNewProject(); await loadWorkspaces(); await openWorkspace(workspace.id); showToast("工程已添加"); } catch (error) { showError(error); } }

function switchPanel(panel) { state.currentPanel = panel; document.querySelectorAll(".project-nav-item").forEach((item) => item.classList.toggle("active", item.dataset.panel === panel)); document.querySelectorAll(".panel-view").forEach((item) => item.classList.remove("active-panel")); const target = $(`${panel}-panel`); if (target) target.classList.add("active-panel"); if (panel === "explorer") loadExplorer(); if (panel === "artifacts") loadArtifacts(); if (panel === "terminal") listProcesses(); if (panel === "settings") fillSettings(); if (panel === "live-preview") loadLivePreview(); }

let livePreviewGeneration = 0, livePreviewTimer = null, livePreviewData = null;
function resetLivePreview() {
  livePreviewGeneration++; clearTimeout(livePreviewTimer); livePreviewData = null;
  const frame = $("live-preview-frame");
  if (frame) { frame.removeAttribute("src"); frame.classList.add("hidden"); }
  if ($("live-preview-log")) $("live-preview-log").textContent = "";
  if ($("live-preview-details")) $("live-preview-details").open = false;
  if ($("live-preview-status")) { $("live-preview-status").textContent = "正在读取预览状态…"; $("live-preview-status").classList.remove("is-building"); }
  if ($("live-preview-empty")) $("live-preview-empty").classList.remove("hidden");
  if ($("preview-build")) $("preview-build").disabled = true;
  if ($("preview-reload")) $("preview-reload").disabled = true;
  if ($("preview-cancel")) $("preview-cancel").classList.add("hidden");
}
async function loadLivePreview(forceReload = false) {
  const workspace = state.currentWorkspace, epoch = state.accountEpoch, generation = ++livePreviewGeneration;
  if (!workspace) return;
  clearTimeout(livePreviewTimer);
  const current = () => state.currentWorkspace === workspace && epoch === state.accountEpoch && generation === livePreviewGeneration;
  try {
    const data = await callTool("preview", "status", workspace.id);
    if (!current()) return;
    livePreviewData = data;
    const job = data.job || {}, busy = ["queued", "installing", "building"].includes(job.status);
    const labels = {queued:"等待构建…", installing:"正在安装依赖…", building:"正在编译前端…", ready:"编译成功，等待任务发布…", published:"最新预览已发布", failed:"构建失败", cancelled:"构建已取消"};
    const status = $("live-preview-status");
    status.textContent = !data.supported ? "当前支持 HTML / JS / CSS 前端原型和 Vue / Vite 静态应用预览。" : (labels[job.status] || "尚未构建，点击「构建并预览」开始。") + (job.error ? ` ${job.error}` : "") + (data.current ? ` · 更新于 ${new Date(data.current.published_at).toLocaleString()}` : "");
    status.classList.toggle("is-building", busy);
    $("preview-build").disabled = !data.supported || busy;
    $("preview-cancel").classList.toggle("hidden", !busy || Boolean(job.task_id));
    $("preview-reload").disabled = !data.current;
    $("live-preview-log").textContent = job.log || "暂无构建日志";
    if (["failed", "cancelled", "published"].includes(job.status) && $("live-preview-details").dataset.jobState !== `${job.id}:${job.status}`) $("live-preview-details").open = false;
    $("live-preview-details").dataset.jobState = `${job.id}:${job.status}`;
    const frame = $("live-preview-frame"), url = data.current?.url;
    const validUrl = typeof url === "string" && /^\/preview\/[a-f0-9]{48}\/$/.test(url);
    $("live-preview-empty").classList.toggle("hidden", validUrl);
    frame.classList.toggle("hidden", !validUrl);
    if (validUrl && (forceReload || frame.getAttribute("src") !== url)) frame.src = url;
    else if (!validUrl) frame.removeAttribute("src");
  } catch (error) {
    if (!current()) return;
    $("live-preview-status").textContent = `读取预览状态失败：${error.message}，正在重试…`;
  }
  if (current() && state.currentPanel === "live-preview") livePreviewTimer = setTimeout(() => loadLivePreview(), 2500);
}
async function buildLivePreview(approved = false, workspace = state.currentWorkspace) {
  if (!workspace) return;
  const epoch = state.accountEpoch, current = () => workspace === state.currentWorkspace && epoch === state.accountEpoch;
  $("preview-build").disabled = true;
  try {
    await callTool("preview", "build", workspace.id, {}, approved);
    if (current()) await loadLivePreview();
  } catch (error) {
    if (!current()) return;
    if (error.approvalRequired) {
      const confirmed = await requestDialog({title:"构建并发布预览？", message:"将执行当前插件的检查和构建，准备所需依赖，并在成功后更新预览。", context:workspace.name, confirmText:"开始构建", isCurrent:current});
      if (confirmed && current()) return buildLivePreview(true, workspace);
    } else showError(error);
  } finally { if (current()) $("preview-build").disabled = ["queued", "installing", "building"].includes(livePreviewData?.job?.status); }
}
async function cancelLivePreview() {
  const workspace = state.currentWorkspace, buildId = livePreviewData?.job?.id, epoch = state.accountEpoch;
  if (!workspace || !buildId) return;
  try {
    await callTool("preview", "cancel", workspace.id, {build_id:buildId});
    if (workspace === state.currentWorkspace && epoch === state.accountEpoch) await loadLivePreview();
  } catch (error) { if (workspace === state.currentWorkspace && epoch === state.accountEpoch) showError(error); }
}
$("preview-build").onclick = () => buildLivePreview();
$("preview-reload").onclick = () => loadLivePreview(true);
$("preview-cancel").onclick = cancelLivePreview;
function applyExplorerWidth(workspace = state.currentWorkspace) {
  const grid = $("explorer-panel")?.querySelector(".explorer-grid");
  if (!grid || !workspace) return;
  grid.style.setProperty("--explorer-tree-width", `${projectSession(workspace.id).treeWidth || 320}px`);
}
function clearPreview(session = state.currentWorkspace ? projectSession(state.currentWorkspace.id) : null) {
  if (session) { session.selectedFile = ""; session.previewGeneration++; }
  for (const file of $("file-tree").querySelectorAll?.("[data-file]") || []) {
    file.classList.remove("selected");
    file.setAttribute("aria-current", "false");
  }
  const preview = $("file-preview");
  if (!preview) return;
  preview.classList.remove("hidden");
  $("preview-path").textContent = "选择文件";
  $("preview-path-label").textContent = "选择文件后显示内容";
  $("preview-content").textContent = "";
}
function setupExplorerResizer() {
  const resizer = $("explorer-resizer");
  if (!resizer || resizer.dataset.bound === "true" || typeof window.addEventListener !== "function") return;
  resizer.dataset.bound = "true";
  let drag = null;
  const finish = () => {
    if (!drag) return;
    drag = null;
    resizer.classList.remove("dragging");
    document.body.classList.remove("resizing-explorer");
  };
  resizer.addEventListener("pointerdown", (event) => {
    if (!state.currentWorkspace) return;
    event.preventDefault();
    const grid = $("explorer-panel")?.querySelector(".explorer-grid");
    if (!grid) return;
    const session = projectSession(state.currentWorkspace.id);
    if (event.button !== 0) return;
    drag = { startX: event.clientX, startWidth: grid.querySelector(".explorer-tree-pane").getBoundingClientRect().width, grid, session, workspace: state.currentWorkspace, pointerId: event.pointerId };
    resizer.classList.add("dragging");
    document.body.classList.add("resizing-explorer");
    resizer.setPointerCapture?.(event.pointerId);
  });
  window.addEventListener("pointermove", (event) => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    if (state.currentWorkspace !== drag.workspace) return finish();
    const style = getComputedStyle(drag.grid);
    const available = drag.grid.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    const width = Math.max(160, Math.min(available - 252, drag.startWidth + event.clientX - drag.startX));
    drag.session.treeWidth = width;
    drag.grid.style.setProperty("--explorer-tree-width", `${width}px`);
  });
  window.addEventListener("pointerup", finish);
  window.addEventListener("pointercancel", finish);
  window.addEventListener("blur", finish);
  resizer.addEventListener("lostpointercapture", finish);
  resizer.addEventListener("dblclick", () => {
    if (!state.currentWorkspace) return;
    const session = projectSession(state.currentWorkspace.id);
    session.treeWidth = 320;
    applyExplorerWidth(state.currentWorkspace);
  });
  resizer.addEventListener("keydown", (event) => {
    if (!state.currentWorkspace || !["ArrowLeft", "ArrowRight", "Home"].includes(event.key)) return;
    event.preventDefault();
    const session = projectSession(state.currentWorkspace.id);
    session.treeWidth = event.key === "Home" ? 320 : Math.max(160, Math.min(700, (session.treeWidth || 320) + (event.key === "ArrowRight" ? 20 : -20)));
    applyExplorerWidth(state.currentWorkspace);
  });
}
function renderFileTree(items, workspace) {
  const session = projectSession(workspace.id), container = $("file-tree");
  applyExplorerWidth(workspace);
  if (session.treeRoot !== workspace.root) {
    session.treeRoot = workspace.root;
    session.folderOpen = new Map();
    clearPreview(session);
  }
  const root = new Map();
  for (const item of items) {
    const parts = item.path.split("/").filter(Boolean);
    let children = root;
    parts.forEach((name, index) => {
      const folder = index < parts.length - 1 || item.kind === "directory";
      if (!children.has(name)) children.set(name, {name, path: parts.slice(0, index + 1).join("/"), folder, children: new Map()});
      children = children.get(name).children;
    });
  }
  const folderIcon = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M1.5 4V2.5h5l1.5 2h6.5v9h-13Z"/></svg>';
  const fileIcon = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 1.5h5l4 4v9h-9Z"/><path d="M8.5 1.5v4h4"/></svg>';
  function branch(nodes, depth = 0) {
    return [...nodes.values()].sort((a, b) => Number(b.folder) - Number(a.folder) || a.name.localeCompare(b.name, undefined, {numeric: true, sensitivity: "base"})).map(node => {
      if (node.folder) {
        const open = session.folderOpen.get(node.path) ?? depth === 0;
        return `<li><details class="file-folder" data-folder="${escapeHtml(node.path)}" ${open ? "open" : ""}><summary title="${escapeHtml(node.path)}">${folderIcon}<span class="tree-name">${escapeHtml(node.name)}</span></summary><ul class="tree-children">${branch(node.children, depth + 1)}</ul></details></li>`;
      }
      return `<li><button class="file-row tree-file${session.selectedFile === node.path ? " selected" : ""}" data-file="${escapeHtml(node.path)}" title="${escapeHtml(node.path)}" aria-current="${session.selectedFile === node.path}">${fileIcon}<span class="tree-name">${escapeHtml(node.name)}</span></button></li>`;
    }).join("");
  }
  container.innerHTML = `<div class="tree-toolbar"><span class="tree-root" title="${escapeHtml(workspace.root)}">${folderIcon}<b>${escapeHtml(workspace.name)}</b></span><span class="tree-actions"><button type="button" data-tree-action="expand" title="展开所有目录">展开</button><button type="button" data-tree-action="collapse" title="折叠所有目录">折叠</button></span></div><ul class="tree-branches">${branch(root)}</ul>${root.size ? "" : '<p class="tree-empty">工程中暂无可展示的文件</p>'}`;
  const folders = [...(container.querySelectorAll?.("[data-folder]") || [])];
  for (const folder of folders) folder.ontoggle = () => session.folderOpen.set(folder.dataset.folder, folder.open);
  for (const action of container.querySelectorAll?.("[data-tree-action]") || []) action.onclick = () => {
    for (const folder of folders) {
      folder.open = action.dataset.treeAction === "expand";
      session.folderOpen.set(folder.dataset.folder, folder.open);
    }
  };
  for (const button of container.querySelectorAll?.("[data-file]") || []) button.onclick = () => {
    if (state.currentWorkspace !== workspace) return;
    session.selectedFile = button.dataset.file;
    for (const file of container.querySelectorAll("[data-file]")) {
      const selected = file === button;
      file.classList.toggle("selected", selected);
      file.setAttribute("aria-current", String(selected));
    }
    return previewFile(button.dataset.file, false, workspace);
  };
}
async function loadExplorer() {
  const workspace = state.currentWorkspace;
  if (!workspace) return;
  try {
    const tree = await callTool("workspace", "list_tree", workspace.id, { limit: 1000 });
    if (state.currentWorkspace !== workspace) return;
    renderFileTree(tree.items, workspace);
    const symbols = await callTool("code", "symbols", workspace.id);
    if (state.currentWorkspace !== workspace) return;
    $("symbol-count").textContent = `${symbols.items.length} 个符号`;
  } catch (error) { if (state.currentWorkspace === workspace) showError(error); }
}
async function previewFile(path, approved = false, workspace = state.currentWorkspace) {
  if (!workspace) return;
  const session = projectSession(workspace.id), generation = ++session.previewGeneration, epoch = state.accountEpoch;
  const current = () => state.currentWorkspace === workspace && state.accountEpoch === epoch && session.previewGeneration === generation;
  session.selectedFile = path;
  $("preview-path").textContent = path;
  $("preview-path-label").textContent = "正在读取…";
  $("preview-content").textContent = "";
  try {
    const data = await callTool("workspace", "read_file", workspace.id, { path }, approved);
    if (!current()) return;
    $("file-preview").classList.remove("hidden");
    $("preview-path").textContent = path;
    $("preview-path-label").textContent = "已加载文件内容";
    $("preview-content").textContent = data.content;
  } catch (error) {
    if (!current()) return;
    $("preview-path-label").textContent = "读取失败，请重新选择文件重试";
    showError(error);
  }
}

async function createTask(goal) {
  const workspace = state.currentWorkspace;
  if (!workspace) return showError(new Error("请先选择工程"));
  const session = projectSession(workspace.id), generation = ++session.generation, epoch = state.accountEpoch;
  const pending = appendMessage("agent", "", workspace.id);
  pending.dataset.generation = String(generation);
  showThinking(pending);
  try {
    if (session.historyLoading) await session.historyLoading;
    if (epoch !== state.accountEpoch) return;
    const recommendation = await api(`/api/workspaces/${workspace.id}/recommendation`, {method:"POST", body:JSON.stringify({goal})});
    if (epoch !== state.accountEpoch) return;
    let pluginId = recommendation.plugin?.id || "";
    if (recommendation.requires_choice) {
      const choices = (recommendation.alternatives || []).filter(item=>item.enabled);
      const selected = await requestDialog({title:"确认本项目的技术栈", message:recommendation.recommendation,
        context:workspace.name, detail:choices.map(item=>`${item.name}（${item.id}）`).join("\n"), input:true,
        inputLabel:"工程插件名称或 ID", value:recommendation.plugin?.name || "", confirmText:"使用此技术栈",
        isCurrent:()=>epoch===state.accountEpoch && state.currentWorkspace?.id===workspace.id,
        validate:value=>choices.some(item=>[item.name,item.id].includes(value)) ? "" : "请选择上方已启用的工程插件。"});
      if (!selected || epoch!==state.accountEpoch) {
        pending.innerHTML='<div class="message-bubble">已取消生成，可调整需求后重新发送。</div>';
        setMessageTiming(pending,{started_at:pending.dataset.startedAt,finished_at:new Date().toISOString()}); return;
      }
      pluginId=choices.find(item=>[item.name,item.id].includes(selected)).id;
    }
    if (recommendation.recommendation && pending.querySelector('.thinking-hint')) pending.querySelector('.thinking-hint').textContent=recommendation.recommendation;
    const task = await api("/api/tasks", { method: "POST", body: JSON.stringify({ workspace_id: workspace.id, goal, plugin_id:pluginId, async_generation:true, intent_preview:true }) });
    if (epoch !== state.accountEpoch) return;
    if (task.id?.startsWith("gen_") || ["queued","running","interrupted"].includes(task.status) || task.request === undefined && task.progress && !task.plan) {
      watchGeneration(task,pending,workspace.id,epoch); return;
    }
    if (session.generation === generation) {
      session.task = task;
      if (state.currentWorkspace?.id === workspace.id) state.task = task;
    }
    appendAgentTurn(task, pending);
    if (task.conversation_turn_id) session.turnViews.set(task.conversation_turn_id, {message: pending, taskId: task.id});
    if (state.currentWorkspace?.id === workspace.id) switchPanel("chat");
  } catch (error) {
    if (epoch !== state.accountEpoch) return;
    pending.innerHTML = `<div class="message-bubble" role="alert">${escapeHtml(`生成未完成：${error.message}`)}</div>`;
    setMessageTiming(pending, {started_at:pending.dataset.startedAt, finished_at:new Date().toISOString()});
    if (state.currentWorkspace?.id === workspace.id) showError(error);
  }
}
function watchGeneration(job, message, workspaceId, epoch = state.accountEpoch) {
  if (epoch!==state.accountEpoch) return;
  const session=projectSession(workspaceId);
  session.generationViews ||= new Map();
  session.generationViews.set(job.id,message);
  if (job.turn_id) {
    for (const [turnId, view] of session.turnViews) if (view.message===message && turnId!==job.turn_id) session.turnViews.delete(turnId);
    session.turnViews.set(job.turn_id,{message});
  }
  const timing={started_at:job.created_at,finished_at:job.finished_at};
  const intent=job.intent || job.progress?.intent;
  if (job.status==='completed' && job.kind==='chat') {
    message.dataset.pollingGeneration='';
    message.innerHTML=`${intentMarkup(intent,true)}<div class="message-bubble">${escapeHtml(job.reply || '')}</div>`;
    setMessageTiming(message,job.timing || timing);
    loadAccount().catch(()=>{}); return;
  }
  if (job.status==='completed' && job.task) {
    message.dataset.pollingGeneration='';
    appendAgentTurn(job.task,message);
    if (message.dataset.generation ? Number(message.dataset.generation)===session.generation :
        !session.task || Date.parse(job.task.created_at)>=Date.parse(session.task.created_at)) {
      session.task=job.task;
      if (state.currentWorkspace?.id===workspaceId) state.task=job.task;
    }
    if (job.task.conversation_turn_id) session.turnViews.set(job.task.conversation_turn_id,{message,taskId:job.task.id});
    loadAccount().catch(()=>{}); return;
  }
  if (['failed','interrupted'].includes(job.status)) {
    message.dataset.pollingGeneration='';
    const repairing=job.draft?.repair_pending;
    const saved=job.draft?.files ? ` 已保留 ${job.draft.files} 个文件的草稿。` : '';
    const error=job.error || '本次生成未完成，已保存进度。';
    message.innerHTML=`${intentMarkup(intent,true)}<div class="message-bubble" role="alert">${escapeHtml((repairing?error.replaceAll('继续生成','继续修复'):error)+saved)}</div><button class="resume-generation outline-btn">${repairing?'继续修复':'继续生成'}</button>`;
    setMessageTiming(message,timing);
    const button=message.querySelector('.resume-generation');
    button.onclick=async()=>{
      if (epoch!==state.accountEpoch || button.disabled) return;
      button.disabled=true;
      try {
        const resumed=await api(`/api/generations/${job.id}/resume`,{method:'POST',body:'{}'});
        watchGeneration(resumed,message,workspaceId,epoch);
      } catch(error) { if(epoch===state.accountEpoch){button.disabled=false;showError(error);} }
    };
    return;
  }
  if (!message.querySelector('.thinking-indicator')) showThinking(message,timing);
  renderIntent(message,intent);
  const hint=message.querySelector('.thinking-hint');
  if (hint) hint.textContent=(job.progress?.stage || '正在排队') + (job.progress?.total ? ` · ${job.progress.completed || 0}/${job.progress.total} 个文件` : '');
  if (message.dataset.pollingGeneration===job.id) return;
  message.dataset.pollingGeneration=job.id;
  const poll=async()=>{
    if(epoch!==state.accountEpoch) return;
    try {
      const next=await api(`/api/generations/${job.id}`);
      if(epoch!==state.accountEpoch) return;
      message.dataset.pollingGeneration='';
      watchGeneration(next,message,workspaceId,epoch);
    } catch(error) {
      if(epoch!==state.accountEpoch) return;
      if(error.authRequired) return;
      if([403,404].includes(error.httpStatus)) {
        message.dataset.pollingGeneration='';
        message.innerHTML='<div class="message-bubble">该生成任务已不再可访问。</div>'; return;
      }
      if(hint)hint.textContent='连接中断，正在重连；后台生成仍会继续。';
      setTimeout(poll,3000);
    }
  };
  setTimeout(poll,1200);
}

function intentMarkup(intent, collapsed = false) {
  if (!intent?.summary) return '';
  const detail=[['目标',intent.goals],['约束',intent.constraints],['接下来',intent.steps]]
    .filter(([,items])=>items?.length)
    .map(([label,items])=>`<div class="intent-items"><b>${label}</b><ul>${items.map(item=>`<li>${escapeHtml(item)}</li>`).join('')}</ul></div>`).join('');
  const body=`<p class="intent-summary">${escapeHtml(intent.summary)}</p>${detail ? `<div class="intent-details">${detail}</div>` : ''}`;
  const label=intent.status==='unavailable' ? '需求理解提示' : '需求理解';
  return collapsed ? `<details class="intent-brief intent-collapsed"><summary>${label}</summary>${body}</details>` :
    `<section class="intent-brief"><div class="intent-label">${label}</div><p class="intent-summary">${escapeHtml(intent.summary)}</p>${detail ? `<details class="intent-expand"><summary>目标与处理步骤</summary>${detail}</details>` : ''}</section>`;
}
function renderIntent(message,intent) {
  if (!intent?.summary) return;
  let container=message.querySelector('.intent-container');
  const markup=intentMarkup(intent);
  if (!container) { container=document.createElement('div'); container.className='intent-container'; message.prepend(container); }
  if (container._intentMarkup!==markup) { container.innerHTML=markup; container._intentMarkup=markup; }
}

function patchPreview(task) {
  return (task.patches || []).map((patch) => `<details class="thinking-card"><summary>${escapeHtml(patch.operation || "write_file")} · ${escapeHtml(patch.path)}</summary><div class="thinking-body">${patch.expected !== undefined ? `<b>原内容</b><pre>${escapeHtml(patch.expected)}</pre>` : ""}<b>新内容</b><pre>${escapeHtml(patch.replacement ?? patch.content ?? "")}</pre></div></details>`).join("");
}
function designText(value) { return typeof value === "string" ? value : JSON.stringify(value); }
function designPreview(task) {
  const design = task.design || {}, report = task.design_review;
  if (!design.modules?.length && !report) return "";
  const modules = (design.modules || []).map(m => `<div class="thinking-line"><b>${escapeHtml(m.path)}</b><span>${escapeHtml(m.responsibility)} · ${escapeHtml((m.depends_on || []).join(", "))}</span></div>`).join("");
  const contracts = (design.interfaces || []).map(i => `<div class="thinking-line"><b>${escapeHtml(i.path)} · ${escapeHtml(i.symbol)}</b><span>${escapeHtml(designText(i.inputs))} → ${escapeHtml(designText(i.outputs))} / ${escapeHtml(designText(i.errors))}</span></div>`).join("");
  const patterns = (design.patterns || []).map(p => `<div class="thinking-line"><b>${escapeHtml(p.name)}</b><span>${escapeHtml(p.reason)}</span></div>`).join("");
  const findings = (report?.findings || []).map(f => `<li>${escapeHtml(f.severity)} · ${escapeHtml(f.path)} ${escapeHtml(f.message)}</li>`).join("");
  const structure = (report?.modules || []).map(m => `<details><summary>${escapeHtml(m.path)} · ${escapeHtml(m.layer || "未分层")} · ${escapeHtml(m.parser)}</summary><ul>${m.symbols.map(s => `<li>${escapeHtml(s.kind)} ${escapeHtml(s.qualified_name || s.name)}${s.parameter_names ? `(${escapeHtml(s.parameter_names.join(", "))})` : ""} · L${s.line}</li>`).join("")}</ul><p>${(m.calls || []).map(c => `${escapeHtml(c.caller)} → ${escapeHtml(c.callee)}`).join("<br>")}</p></details>`).join("");
  const dependencies = (report?.dependencies || []).map(d => `${escapeHtml(d.from)} → ${escapeHtml(d.to)}`).join("<br>");
  const metrics = report?.metrics;
  return `<details class="thinking-card"><summary>设计与结构审查${metrics ? ` · ${metrics.modules} 模块 / ${metrics.classes} 类 / ${metrics.functions} 函数` : ""}</summary><div class="thinking-body">${modules}${contracts}${patterns}${structure}<p>${dependencies}</p>${report ? `<p>${report.blocking ? "未满足强制契约" : report.passed ? "已检查规则通过" : "存在结构建议或未完成检查"} · ${report.mode === "enforce" ? "强制" : "建议"}</p><ul>${findings}</ul><p>${(report.limitations || []).map(escapeHtml).join(" ")}</p>` : ""}</div></details>`;
}
function appendDesignReview(event, workspaceId, taskId = "") {
  const message = document.createElement("div"); message.className = "message agent";
  message.dataset.taskId = taskId;
  message.innerHTML = designPreview({design_review:event.payload}); addProjectMessage(workspaceId,message);
}
function capabilityPreview(task) {
  const selected = task.capabilities;
  if (!selected) return "";
  return `<div class="thinking-line"><b>工程插件</b><span>${escapeHtml(selected.plugin?.name || "通用分析")} ${escapeHtml(selected.plugin?.version || "")}</span></div><div class="thinking-line"><b>Skill / Function</b><span>${[...(selected.skills || []), ...(selected.functions || [])].map(item=>escapeHtml(item.name)).join(" · ") || "无额外能力"}</span></div>`;
}
function appendAgentTurn(task, existingMessage = null) {
  const message = existingMessage || document.createElement("div");
  message.className = "message agent";
  message.dataset.taskId = task.id;
  const thinking = (task.thinking || []).map((item) => `<div class="thinking-line"><b>${escapeHtml(item.title)}</b><span>${escapeHtml(item.summary)}</span></div>`).join("");
  const steps = (task.plan || []).map((step) => `<div class="thinking-line"><b>${escapeHtml(step.step)}. ${escapeHtml(step.title)}</b><span>${escapeHtml(step.detail)}</span></div>`).join("");
  const count = task.patches?.length || 0;
  message.innerHTML = `${intentMarkup(task.intent,true)}<div class="message-bubble">${escapeHtml(task.summary || "方案已准备好，请查看下方详情。")}</div>
    <p class="task-status" role="status">${count ? `待确认：将修改 ${count} 个文件，批准后写入并运行验证。` : "当前方案没有代码变更；批准后仅分析和验证工程。生成代码请在设置中选择已配置的大模型。"}</p>
    <details class="thinking-card"><summary><span class="thinking-label">方案详情</span><span class="thinking-meta">${task.plan?.length || 0} 个步骤 · ${count} 个文件</span></summary><div class="thinking-body">${thinking}${steps}<div class="thinking-line"><b>执行目录</b><span>${escapeHtml(task.workspace_snapshot?.root || state.workspaces.find((item) => item.id === task.workspace_id)?.root || "")}</span></div>${capabilityPreview(task)}${designPreview(task)}${patchPreview(task)}<p>批准后使用已选择插件的验证流程；必要时安装工程依赖。</p></div></details>
    <button class="approve-inline">批准执行</button>`;
  const button = message.querySelector(".approve-inline"), statusNode = message.querySelector(".task-status");
  button.onclick = () => approveTask(task, button, statusNode, message);
  const timing = task.timing || {started_at:message.dataset.startedAt || task.created_at, response_finished_at:task.created_at};
  const running = ["executing", "cancelling"].includes(task.status);
  setMessageTiming(message, running ? timing : {...timing, finished_at:timing.response_finished_at, duration_ms:timing.generation_duration_ms}, {live:running, label:running ? "本轮已用时" : "生成耗时"});
  if (!existingMessage) addProjectMessage(task.workspace_id, message);
  if (["executing", "cancelling", "succeeded", "failed", "cancelled"].includes(task.status)) {
    button.disabled = true;
    button.textContent = ({succeeded:"已完成", failed:"执行失败", cancelled:"已取消"})[task.status] || "执行中…";
    if (statusNode) { statusNode.textContent = task.error || button.textContent; if (running) statusNode.innerHTML = activityDots + escapeHtml(button.textContent); }
  }
  return {button, statusNode, message};
}
function formatElapsed(milliseconds) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  if (seconds < 60) return `${seconds} 秒`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
  return `${Math.floor(seconds / 3600)} 小时 ${Math.floor(seconds % 3600 / 60)} 分 ${seconds % 60} 秒`;
}
function setMessageTiming(message, timing = {}, {live = false, label = "耗时", timestamp = timing.finished_at || timing.started_at} = {}) {
  const started = Date.parse(timing.started_at), ended = Date.parse(timing.finished_at), stamp = Date.parse(timestamp);
  if (Number.isFinite(started)) message.dataset.startedAt = timing.started_at;
  let meta = message.querySelector(".message-meta");
  if (!meta) { meta = document.createElement("div"); meta.className = "message-meta"; message.appendChild(meta); }
  const date = new Date(stamp), today = new Date();
  const clock = Number.isFinite(stamp) ? date.toLocaleTimeString("zh-CN", {hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit"}) : "";
  const display = Number.isFinite(stamp) && date.toDateString() !== today.toDateString() ? `${date.toLocaleDateString("zh-CN")} ${clock}` : clock;
  const duration = Number.isFinite(timing.duration_ms) ? timing.duration_ms : Number.isFinite(started) && Number.isFinite(ended) ? ended - started : null;
  const elapsed = live && Number.isFinite(started) ? `${label} ${formatElapsed(Date.now() - started)}` : label ? duration === null ? "耗时未记录" : `${label} ${formatElapsed(duration)}` : "";
  meta.innerHTML = `${clock ? `<time datetime="${escapeHtml(date.toISOString())}" title="${escapeHtml(date.toLocaleString('zh-CN', {hour12:false}))}">${escapeHtml(display)}</time>` : ""}${elapsed ? `<span class="message-duration" title="${label.startsWith('本轮') ? '从本轮开始到结束，包含等待用户确认的时间' : '本轮回复处理耗时'}">${escapeHtml(elapsed)}</span>` : ""}`;
  meta.dataset.liveStart = live && Number.isFinite(started) ? timing.started_at : "";
  meta.dataset.elapsedLabel = label;
}
function refreshMessageClocks() {
  for (const meta of document.querySelectorAll('.message-meta[data-live-start]')) {
    const started = Date.parse(meta.dataset.liveStart), duration = meta.querySelector('.message-duration');
    if (Number.isFinite(started) && duration) duration.textContent = `${meta.dataset.elapsedLabel} ${formatElapsed(Date.now() - started)}`;
  }
  setTimeout(refreshMessageClocks, 1000);
}
const activityDots = '<span class="activity-dots" aria-hidden="true"><i></i><i></i><i></i></span>';
function showThinking(message, timing = {started_at: new Date().toISOString()}) {
  message.innerHTML = `<div class="message-bubble thinking-indicator" role="status">${activityDots}<span>思考中</span><span class="thinking-hint">正在生成回复，请稍候…</span></div>`;
  setMessageTiming(message, timing, {live:true, label:"已等待", timestamp:timing.started_at});
}
function appendMessage(role, text, workspaceId = state.currentWorkspace?.id, taskId = "", timestamp = new Date().toISOString()) {
  const message = document.createElement("div"); message.className = `message ${role}`; message.dataset.taskId = taskId;
  message.innerHTML = `<div class="message-bubble">${escapeHtml(text)}</div>`;
  setMessageTiming(message, {started_at: timestamp}, {label:"", timestamp});
  addProjectMessage(workspaceId, message); return message;
}
refreshMessageClocks();
async function sendProjectMessage() { const input = $("project-input"); const goal = input.value.trim(); if (!goal) return; input.value = ""; appendMessage("user", goal); await createTask(goal); }
async function sendFreeMessage() {
  const input = $("free-input"), text = input.value.trim(), epoch = state.accountEpoch;
  if (!text) return;
  input.value = "";
  appendMessage("user", text, "");
  const pending = appendMessage("agent", "", "");
  showThinking(pending);
  try {
    await loadConversation("");
    if (epoch !== state.accountEpoch) return;
    const result = await api("/api/conversations/free", {method: "POST", body: JSON.stringify({text,async_generation:true,intent_preview:true})});
    if (epoch !== state.accountEpoch) return;
    if (result.id?.startsWith('gen_')) { watchGeneration(result,pending,'',epoch); return; }
    pending.innerHTML = `<div class="message-bubble">${escapeHtml(result.reply)}</div>`;
    setMessageTiming(pending, result.timing || {started_at:pending.dataset.startedAt, finished_at:new Date().toISOString()});
    projectSession("").turnViews.set(result.id, {message: pending});
    loadAccount().catch(() => {});
  } catch (error) {
    if (epoch !== state.accountEpoch) return;
    pending.innerHTML = `<div class="message-bubble" role="alert">${escapeHtml(`对话未完成：${error.message}，请重新发送。`)}</div>`;
    setMessageTiming(pending, {started_at:pending.dataset.startedAt, finished_at:new Date().toISOString()});
  }
}

async function approveTask(task, button, statusNode = null, message = null) {
  if (!task || button.disabled) return;
  if (task.workspace_id !== state.currentWorkspace?.id) return showError(new Error("请先打开这个任务所属的工程"));
  const epoch = state.accountEpoch;
  button.disabled = true;
  button.textContent = "提交中…";
  try {
    const approved = await api(`/api/tasks/${task.id}/approve`, { method: "POST", body: "{}" });
    if (epoch !== state.accountEpoch) return;
    updateSessionTask(task.workspace_id, approved);
    button.textContent = "执行中…";
    if (statusNode) statusNode.innerHTML = activityDots + (task.patches?.length ? "已批准，正在写入文件并执行验证。" : "已批准，正在分析和验证工程。");
    if (message) setMessageTiming(message, approved.timing || task.timing || {started_at:message.dataset.startedAt}, {live:true, label:"本轮已用时"});
    appendMessage("agent", "任务已批准，Agent 正在执行工程分析和验证命令。", task.workspace_id, task.id);
    pollTask({ taskId: task.id, workspaceId: task.workspace_id, task:{...task,...approved}, after: 0, button, statusNode, message, epoch });
  } catch (error) {
    if (epoch !== state.accountEpoch) return;
    button.disabled = false;
    button.textContent = "批准执行";
    appendMessage("agent", `批准失败：${error.message}。可以重试。`, task.workspace_id, task.id);
    showError(error);
  }
}
function appendToolEvent(event, workspaceId, taskId = "") { const request = event.payload?.request || {}; const attempt = event.payload?.attempt ? ` · 第 ${event.payload.attempt}/${event.payload.max_attempts || event.payload.attempt} 次` : ""; const message = document.createElement("div"); message.className = "message agent"; message.dataset.taskId = taskId; message.innerHTML = `<details class="thinking-card tool-card"><summary><span class="thinking-label">工具调用</span><span class="thinking-meta">调用 ${escapeHtml(request.tool || "tool")}.${escapeHtml(request.action || "call")}${escapeHtml(attempt)}</span></summary><div class="thinking-body"><div class="thinking-line"><b>工具请求</b><span>${escapeHtml(JSON.stringify(request.arguments || {}))}</span></div></div></details>`; addProjectMessage(workspaceId, message); }
function appendToolRetryEvent(event, workspaceId, taskId = "") { const payload = event.payload || {}; const message = document.createElement("div"); message.className = "message agent"; message.dataset.taskId = taskId; message.innerHTML = `<details class="thinking-card tool-card"><summary><span class="thinking-label">正在重试</span><span class="thinking-meta">${escapeHtml(payload.message || "工具调用失败，正在重试")}</span></summary><div class="thinking-body"><div class="thinking-line"><b>失败原因</b><span>${escapeHtml(payload.details || "请稍候")}</span></div></div></details>`; addProjectMessage(workspaceId, message); }
function appendProcessOutput(event, workspaceId, taskId = "") { const payload = event.payload || {}, failed = Number(payload.exit_code) !== 0, label = failed ? "执行失败（详情已折叠）" : "验证输出（已折叠）"; const message = document.createElement("div"); message.className = "message agent"; message.dataset.taskId = taskId; message.innerHTML = `<details class="thinking-card execution-card"><summary><span class="thinking-label">${label}</span><span class="thinking-meta">${escapeHtml(payload.command || "验证命令")} · exit ${escapeHtml(payload.exit_code)}</span></summary><div class="thinking-body"><pre class="execution-output">${escapeHtml((payload.output || "").slice(-12000) || "（命令没有输出）")}</pre></div></details>`; addProjectMessage(workspaceId, message); }
function appendTaskFailure(event, workspaceId, taskId = "") { const payload = event.payload || {}, message = appendMessage("agent", payload.error || payload.message || "执行失败，请检查工程配置后重试。", workspaceId, taskId, event.created_at || ""); if (payload.details) { const details = document.createElement("div"); details.className = "message agent"; details.dataset.taskId = taskId; details.innerHTML = `<details class="thinking-card execution-card"><summary><span class="thinking-label">失败详情（已折叠）</span><span class="thinking-meta">展开查看原始错误</span></summary><div class="thinking-body"><pre class="execution-output">${escapeHtml(payload.details)}</pre></div></details>`; addProjectMessage(workspaceId, details); } return message; }
function collapseTaskDetails(workspaceId, taskId) {
  for (const node of projectSession(workspaceId).messages) {
    if (node.dataset?.taskId === taskId) for (const detail of node.querySelectorAll?.("details") || []) detail.open = false;
  }
}
function summarizeTaskTurn(run, status) {
  const session = projectSession(run.workspaceId);
  let completed = session.completedTasks.get(run.taskId);
  if (!completed) {
    const message = document.createElement("div"), details = document.createElement("details");
    message.className = "message agent completed-turn";
    message.dataset.taskId = run.taskId;
    details.className = "turn-process";
    const heading = document.createElement("summary"), label = document.createElement("span"), stateLabel = document.createElement("span");
    label.className = "turn-process-label"; label.textContent = "执行过程";
    stateLabel.className = "turn-process-state";
    heading.appendChild(label); heading.appendChild(stateLabel);
    const body = document.createElement("div"); body.className = "turn-process-body";
    details.appendChild(heading); details.appendChild(body);
    const conclusion = document.createElement("p"); conclusion.className = "message-bubble turn-conclusion";
    conclusion.setAttribute("role", "status");
    message.appendChild(details); message.appendChild(conclusion);
    completed = {message, details, body, conclusion, stateLabel};
    session.completedTasks.set(run.taskId, completed);
    collapseTaskDetails(run.workspaceId, run.taskId);
    details.open = false;
  }
  const labels = {succeeded:"已完成", failed:"执行失败", cancelled:"已取消"};
  completed.stateLabel.textContent = labels[status];
  completed.message.dataset.status = status;
  const result = run.result || run.task?.error || ({succeeded:"本轮任务已完成。", failed:"本轮执行失败，请展开执行过程查看原因后重试。", cancelled:"本轮任务已取消。"})[status];
  const paragraph = String(result).replace(/\s+/g, " ").trim();
  completed.conclusion.textContent = paragraph.length > 600 ? paragraph.slice(0, 600) + "…展开执行过程查看完整信息。" : paragraph;
  if (run.hasPreview) {
    const link = document.createElement("button"); link.className = "outline-btn turn-preview-link"; link.textContent = "查看预览";
    link.onclick = () => { if (state.currentWorkspace?.id === run.workspaceId) switchPanel("live-preview"); };
    completed.conclusion.appendChild(link);
  }
  const timing = {...(run.task?.timing || {started_at:run.task?.created_at})};
  timing.finished_at = run.finishedAt || timing.finished_at || (["succeeded", "failed", "cancelled"].includes(run.task?.status) ? run.task?.updated_at : "");
  if (run.message) setMessageTiming(run.message, timing, {label:"本轮耗时"});
  setMessageTiming(completed.message, timing, {label:"本轮耗时"});
  renderConversation(run.workspaceId);
}
function finishTaskView(run, status) {
  run.finished = true; run.button.disabled = true;
  run.button.textContent = ({succeeded: "已完成", failed: "执行失败", cancelled: "已取消"})[status];
  summarizeTaskTurn(run, status);
}
function renderTaskEvent(event, run) {
  if (event.type === "preview.published") {
    run.hasPreview = true;
    if (state.currentWorkspace?.id === run.workspaceId && state.currentPanel === "live-preview") loadLivePreview();
  }
  if (event.type === "preview.built") appendProcessOutput(event, run.workspaceId, run.taskId);
  if (event.type === "tool.call") appendToolEvent(event, run.workspaceId, run.taskId);
  if (event.type === "tool.retry") appendToolRetryEvent(event, run.workspaceId, run.taskId);
  if (event.type === "file.changed") appendMessage("agent", `已写入文件：${event.payload.path || event.payload.relative_path || "工程文件"}`, run.workspaceId, run.taskId, event.created_at || "");
  if (event.type === "process.output") appendProcessOutput(event, run.workspaceId, run.taskId);
  if (event.type === "agent.notice") appendMessage("agent", event.payload.message, run.workspaceId, run.taskId, event.created_at || "");
  if (event.type === "design.reviewed") appendDesignReview(event, run.workspaceId, run.taskId);
  if (["task.succeeded", "task.failed", "task.cancelled"].includes(event.type) && !run.terminalSeen) {
    const result = event.payload.message || event.payload.error || ({"task.succeeded": "执行完成", "task.failed": "执行失败", "task.cancelled": "任务已取消"})[event.type];
    if (event.type === "task.failed") appendTaskFailure(event, run.workspaceId, run.taskId);
    if (run.statusNode) run.statusNode.textContent = result;
    run.finishedAt = event.created_at || run.finishedAt;
    run.result = result;
    run.terminalSeen = true;
    summarizeTaskTurn(run, event.type.slice(5));
  }
}
async function pollTask(run) {
  if (!run || run.finished || (run.epoch !== undefined && run.epoch !== state.accountEpoch)) return;
  try {
    const data = await api(`/api/tasks/${run.taskId}/events?after=${run.after}`);
    if (run.epoch !== undefined && run.epoch !== state.accountEpoch) return;
    for (const event of data.items) {
      if (event.sequence <= run.after) continue;
      renderTaskEvent(event, run);
      run.after = event.sequence;
    }
    const latest = await api(`/api/tasks/${run.taskId}`);
    if (run.epoch !== undefined && run.epoch !== state.accountEpoch) return;
    updateSessionTask(run.workspaceId, latest);
    run.task = {...run.task, ...latest};
    if (run.message && !run.terminalSeen) setMessageTiming(run.message, run.task.timing || {started_at:run.message.dataset.startedAt}, {live:!["succeeded", "failed", "cancelled"].includes(latest.status), label:"本轮已用时"});
    run.failures = 0;
    const terminal = ["succeeded", "failed", "cancelled"].includes(latest.status);
    if (terminal && run.terminalSeen) {
      finishTaskView(run, latest.status);
      return;
    }
    // State and events are separate reads: completion can happen between them.
    run.button.textContent = terminal ? "同步最终结果…" : "执行中…";
    setTimeout(() => pollTask(run), 900);
  } catch (error) {
    if (run.epoch !== undefined && run.epoch !== state.accountEpoch) return;
    run.failures = (run.failures || 0) + 1;
    run.button.textContent = "连接中断，正在重试…";
    if (run.failures === 1 && state.currentWorkspace?.id === run.workspaceId) showError(error);
    setTimeout(() => pollTask(run), Math.min(900 * 2 ** Math.min(run.failures, 5), 15000));
  }
}
async function runCommand(approved = false, workspace = state.currentWorkspace, command = $("command").value.trim()) {
  if (!workspace) return showError(new Error("请先选择工程"));
  if (!command) return showError(new Error("请输入命令"));
  const epoch = state.accountEpoch;
  try {
    const result = await callTool("process", "run", workspace.id, { command }, approved);
    if (state.currentWorkspace === workspace) $("command-output").textContent = `risk=${result.risk} exit=${result.exit_code}\n${result.output}`;
  } catch (error) {
    if (state.currentWorkspace !== workspace) return;
    if (error.approvalRequired) {
      const confirmed = await requestDialog({title:"执行这条命令？", message:error.message, context:workspace.name,
        detail:command, confirmText:"允许执行", danger:error.payload?.risk === "high",
        isCurrent:() => state.currentWorkspace === workspace && epoch === state.accountEpoch});
      if (confirmed && state.currentWorkspace === workspace && epoch === state.accountEpoch) return runCommand(true, workspace, command);
      return;
    }
    showError(error);
  }
}
async function startService(approved = false, workspace = state.currentWorkspace, command = $("service-command").value.trim()) {
  if (!workspace) return showError(new Error("请先选择工程"));
  if (!command) return showError(new Error("请输入启动命令"));
  const epoch = state.accountEpoch;
  try {
    await callTool("process", "start", workspace.id, { command }, approved);
    await listProcesses(workspace);
  } catch (error) {
    if (state.currentWorkspace !== workspace) return;
    if (error.approvalRequired) {
      const confirmed = await requestDialog({title:"启动项目服务？", message:error.message, context:workspace.name,
        detail:command, confirmText:"允许启动", danger:error.payload?.risk === "high",
        isCurrent:() => state.currentWorkspace === workspace && epoch === state.accountEpoch});
      if (confirmed && state.currentWorkspace === workspace && epoch === state.accountEpoch) return startService(true, workspace, command);
      return;
    }
    showError(error);
  }
}
async function listProcesses(workspace = state.currentWorkspace) {
  if (!workspace) return;
  try {
    const result = await callTool("process", "list", workspace.id);
    if (state.currentWorkspace !== workspace) return;
    $("processes").textContent = result.items.length ? result.items.map((item) => `pid=${item.pid} ${item.status} ${item.command}`).join("\n") : "暂无运行中的服务";
  } catch (error) { if (state.currentWorkspace === workspace) showError(error); }
}
async function stopServices() {
  const workspace = state.currentWorkspace;
  if (!workspace) return;
  try {
    const result = await callTool("process", "list", workspace.id);
    for (const item of result.items.filter((process) => process.status === "running")) await callTool("process", "stop", workspace.id, { pid: item.pid }, true);
    await listProcesses(workspace);
  } catch (error) { if (state.currentWorkspace === workspace) showError(error); }
}
async function loadArtifacts(approved = false, workspace = state.currentWorkspace) {
  if (!workspace) return;
  const session = projectSession(workspace.id), generation = ++session.documentGeneration, epoch = state.accountEpoch;
  const current = () => state.currentWorkspace === workspace && epoch === state.accountEpoch && generation === session.documentGeneration;
  $("doc-status").textContent = "读取中…";
  $("document-preview").textContent = "";
  $("document-preview").classList.add("hidden");
  try {
    const result = await callTool("document", "read", workspace.id, {}, approved);
    if (!current()) return;
    $("doc-status").textContent = result.exists ? "已保存" : "未生成";
    if (result.exists) {
      $("document-preview").textContent = result.content;
      $("document-preview").classList.remove("hidden");
    }
  } catch (error) {
    if (!current()) return;
    $("doc-status").textContent = "读取失败";
    showError(error);
  }
}
async function generateDocument(approved = false, workspace = state.currentWorkspace) {
  if (!workspace) return showError(new Error("请先选择工程"));
  const session = projectSession(workspace.id), generation = ++session.documentGeneration, epoch = state.accountEpoch;
  const current = () => state.currentWorkspace === workspace && epoch === state.accountEpoch && generation === session.documentGeneration;
  try {
    const result = await callTool("document", "generate", workspace.id, {}, approved);
    if (!current()) return;
    $("document-preview").classList.remove("hidden");
    $("document-preview").textContent = result.content;
    $("doc-status").textContent = "已生成";
    showToast("文档已生成");
  } catch (error) {
    if (!current()) return;
    if (error.approvalRequired) {
      const confirmed = await requestDialog({title:"生成工程文档？", message:"将根据当前工程生成文档，并写入或覆盖已有文件。",
        context:workspace.name, detail:"CODESPIDER.md", confirmText:"生成并保存", isCurrent:current});
      if (confirmed && current()) return generateDocument(true, workspace);
      return;
    }
    showError(error);
  }
}

async function deleteWorkspace() {
  const workspace = state.currentWorkspace, epoch = state.accountEpoch;
  if (!workspace) return;
  const id = workspace.id, name = workspace.name;
  const isCurrent = () => epoch === state.accountEpoch && state.currentWorkspace?.id === id && state.currentWorkspace?.name === name;
  const button = $("delete-project");
  if (button.disabled) return;
  button.disabled = true;
  try {
    const confirmed = await requestDialog({title: "删除这个项目？", message: "项目将从列表中移除，无法继续通过原项目访问对话和产物。磁盘源码、对话及产物存档仍保留。", context: name, detail: workspace.root, confirmText: "继续删除", danger: true, isCurrent});
    if (!confirmed || !isCurrent()) return;
    const typed = await requestDialog({title: "再次确认删除", message: "请输入完整项目名称确认删除。运行中的任务或服务必须先停止。", context: name, input: true, inputLabel: "项目名称", placeholder: name, confirmText: "确认删除项目", danger: true, isCurrent,
      validate: value => value === name ? "" : "项目名称不一致，请输入完整名称。"});
    if (typed !== name || !isCurrent()) return;
    await api(`/api/workspaces/${encodeURIComponent(id)}/delete`, {method: "POST", body: JSON.stringify({confirmed: true, confirm_name: typed})});
    if (epoch !== state.accountEpoch) return;
    state.sessions.delete(id);
    state.workspaces = state.workspaces.filter(item => item.id !== id);
    if (state.currentWorkspace?.id === id) {
      state.currentWorkspace = null; state.task = null;
      $("project-messages").replaceChildren();
      setView("home");
    }
    renderWorkspaceLists();
    showToast("项目已删除，磁盘源码与历史存档已保留");
  } catch (error) { if (epoch === state.accountEpoch) showError(error); }
  finally { button.disabled = false; }
}

function fillSettings() { if (!state.currentWorkspace) return; $("settings-name").value = state.currentWorkspace.name || ""; $("settings-root").value = state.currentWorkspace.root || ""; $("settings-execution-mode").value = state.currentWorkspace.execution_mode || "safe"; $("settings-command-allowlist").value = (state.currentWorkspace.command_allowlist || []).join("\n"); $("settings-start-command").value = state.currentWorkspace.start_command || ""; $("settings-description").value = state.currentWorkspace.description || ""; }
async function saveSettings() { const workspace = state.currentWorkspace; if (!workspace) return; try { const updated = await api(`/api/workspaces/${workspace.id}/settings`, { method: "POST", body: JSON.stringify({ name: $("settings-name").value, root: $("settings-root").value, execution_mode: $("settings-execution-mode").value, command_allowlist: $("settings-command-allowlist").value.split("\n").map((item) => item.trim()).filter(Boolean), start_command: $("settings-start-command").value, description: $("settings-description").value }) }); state.workspaces = state.workspaces.map((item) => item.id === updated.id ? updated : item); renderWorkspaceLists(); if (state.currentWorkspace !== workspace) return; state.currentWorkspace = updated; updateProjectHeader(); $("settings-saved").textContent = "已保存"; setTimeout(() => { if (state.currentWorkspace === updated) $("settings-saved").textContent = ""; }, 1800); } catch (error) { showError(error); } }
async function reviewProjectDesign(approved = false, workspace = state.currentWorkspace) {
  if (!workspace) return;
  try {
    const report = await callTool("code", "design_review", workspace.id, {}, approved);
    if (state.currentWorkspace !== workspace) return;
    $("design-review-result").innerHTML = designPreview({design_review:report});
  } catch (error) {
    if (state.currentWorkspace !== workspace) return;
    showError(error);
  }
}
async function reindexProject() { if (!state.currentWorkspace) return; try { await loadExplorer(); showToast("工程索引已刷新"); } catch (error) { showError(error); } }

async function loadGlobalSettings() { try { await loadAccount(); if (state.user.role !== "ADMIN") { $("legacy-global-settings").classList.add("hidden"); return; } const settings = await api("/api/settings"); $("global-provider").value = settings.provider; $("global-model").value = settings.model; $("global-base-url").value = settings.base_url || ""; $("global-temperature").value = settings.temperature; $("global-max-tokens").value = settings.max_tokens; $("global-api-key").value = ""; $("global-key-status").textContent = settings.api_key_set ? `已设置：${settings.api_key_preview}（留空则保留）` : "未设置 API Key";  } catch (error) { showError(error); } }
async function saveGlobalSettings(clearApiKey = false) { try { const payload = { provider: $("global-provider").value, model: $("global-model").value, base_url: $("global-base-url").value, api_key: $("global-api-key").value, temperature: Number($("global-temperature").value), max_tokens: Number($("global-max-tokens").value), clear_api_key: clearApiKey }; const settings = await api("/api/settings", { method: "POST", body: JSON.stringify(payload) }); $("global-api-key").value = ""; $("global-key-status").textContent = settings.api_key_set ? `已设置：${settings.api_key_preview}（留空则保留）` : "未设置 API Key";  $("global-settings-saved").textContent = "已保存"; setTimeout(() => $("global-settings-saved").textContent = "", 1800); showToast("全局模型设置已保存"); } catch (error) { showError(error); } }

document.querySelectorAll("[data-settings-tab]").forEach((button) => {
  button.onclick = () => switchSettingsTab(button.dataset.settingsTab);
  button.onkeydown = (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    const tabs = [...document.querySelectorAll("[data-settings-tab]")].filter((item) => !item.classList.contains("hidden"));
    let index = tabs.indexOf(button);
    index = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    event.preventDefault();
    switchSettingsTab(tabs[index].dataset.settingsTab);
    tabs[index].focus();
  };
});
document.querySelectorAll("[data-view]").forEach((item) => item.onclick = () => setView(item.dataset.view)); document.querySelectorAll("[data-panel]").forEach((item) => item.onclick = () => { if (item.dataset.panel) switchPanel(item.dataset.panel); }); document.querySelectorAll("[data-quick]").forEach((item) => item.onclick = () => { $("quick-chat").value = item.dataset.quick; $("quick-chat").focus(); }); document.querySelectorAll("[data-suggest]").forEach((item) => item.onclick = () => { $("project-input").value = item.dataset.suggest; sendProjectMessage(); });
setupDialogs();
setupExplorerResizer();
$("focus-toggle").onclick = () => $("app-shell").classList.toggle("context-hidden"); $("toggle-context").onclick = () => $("app-shell").classList.toggle("context-hidden"); $("context-close").onclick = () => $("app-shell").classList.add("context-hidden"); $("home-add-project").onclick = openNewProject; $("empty-add-project").onclick = openNewProject; $("close-new-project").onclick = closeNewProject; $("create-project").onclick = createWorkspace; $("project-send").onclick = sendProjectMessage; $("free-send").onclick = sendFreeMessage; $("refresh-explorer").onclick = loadExplorer; $("review-design").onclick = () => reviewProjectDesign(); $("close-preview").onclick = () => clearPreview(); $("download-project").onclick = () => { if (state.currentWorkspace) window.location.href = `/api/workspaces/${encodeURIComponent(state.currentWorkspace.id)}/download`; }; $("run-command").onclick = () => runCommand(); $("start-service").onclick = () => startService(); $("stop-services").onclick = stopServices; $("generate-doc").onclick = () => generateDocument(); $("save-settings").onclick = saveSettings; $("delete-project").onclick = deleteWorkspace; $("reindex-project").onclick = reindexProject; $("project-settings-btn").onclick = () => switchPanel("settings"); $("quick-send").onclick = () => { setView("free-chat"); $("free-input").value = $("quick-chat").value; sendFreeMessage(); };
$("project-switcher-toggle").onclick = () => { const menu = $("project-switcher-menu"), open = menu.classList.toggle("hidden"); $("project-switcher-toggle").setAttribute("aria-expanded", String(!open)); }; document.addEventListener?.("click", (event) => { if (!event.target.closest?.(".project-switcher")) closeProjectSwitcher(); });
$("global-settings").onclick = () => { setView("global-settings"); loadGlobalSettings(); }; $("save-global-settings").onclick = () => saveGlobalSettings(false); $("clear-api-key").onclick = async () => {
  const epoch = state.accountEpoch;
  const confirmed = await requestDialog({title:"清除 API Key？", message:"清除后，此模型需要重新配置密钥才能使用。", danger:true, confirmText:"清除密钥"});
  if (confirmed && epoch === state.accountEpoch) await saveGlobalSettings(true);
};
$("auth-form").onsubmit = submitAuth; $("auth-switch").onclick = () => showAuth(state.authMode === "login" ? "register" : "login"); $("logout-btn").onclick = async () => { try { await api("/api/auth/logout", { method: "POST", body: "{}" }); } finally { resetConversations(); state.user = null; showAuth("login"); } }; $("save-account-model").onclick = saveAccountModel; $("add-admin-model").onclick = addAdminModel; $("checkin-button").onclick = claimCheckin; $("market-save-skill").onclick = saveMarketSkill; $("market-search").oninput = renderMarket; $("market-kind").onchange = renderMarket;
$("project-input").addEventListener("keydown", (event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") sendProjectMessage(); }); $("free-input").addEventListener("keydown", (event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") sendFreeMessage(); });

api("/api/health").then(async () => { $("health").innerHTML = "<i></i>在线"; try { await loadAccount(); hideAuth(); await loadWorkspaces(); } catch (error) { if (!error.authRequired) showError(error); } }).catch(() => { $("health").innerHTML = "<i style='background:#c86f62'></i>离线"; });
