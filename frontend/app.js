const state = { workspaces: [], currentWorkspace: null, task: null, currentPanel: "chat", sessions: new Map(), user: null, models: [], usage: null, authMode: "login", settingsTab: "account" };
const $ = (id) => document.getElementById(id);

// Session DOM nodes stay bound to their original task even while detached.
const welcomeMarkup = $("project-messages").innerHTML;
function projectSession(workspaceId) {
  if (!state.sessions.has(workspaceId)) state.sessions.set(workspaceId, { messages: [], task: null, draft: "", command: "", serviceCommand: "", generation: 0 });
  return state.sessions.get(workspaceId);
}
function renderConversation(workspaceId) {
  if (workspaceId !== state.currentWorkspace?.id) return;
  const container = $("project-messages"), session = projectSession(workspaceId);
  container.replaceChildren(...session.messages);
  if (!session.messages.length) {
    container.innerHTML = welcomeMarkup;
    document.querySelectorAll("[data-suggest]").forEach((item) => item.onclick = () => { $("project-input").value = item.dataset.suggest; sendProjectMessage(); });
  }
  container.scrollTop = container.scrollHeight;
}
function addProjectMessage(workspaceId, message) {
  projectSession(workspaceId).messages.push(message);
  renderConversation(workspaceId);
}
function updateSessionTask(workspaceId, task) {
  const session = projectSession(workspaceId);
  if (session.task?.id === task.id) session.task = task;
  if (state.currentWorkspace?.id === workspaceId && state.task?.id === task.id) state.task = task;
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await response.json();
  if (!response.ok) { const payload = data.error && typeof data.error === "object" ? data.error : data; const error = new Error(payload.message || payload.error || "请求失败"); error.approvalRequired = Boolean(payload.approval_required); error.authRequired = response.status === 401; error.payload = payload; if (error.authRequired && !path.startsWith("/api/auth/")) showAuth("login"); throw error; }
  return data;
}
async function callTool(tool, action, workspaceId, argumentsValue = {}, approved = false) { const response = await api("/api/tools/call", { method: "POST", body: JSON.stringify({ api_version: "1.0", tool, action, workspace_id: workspaceId || "", arguments: argumentsValue, approval: approved === true ? { approved: true, source: "user_confirmation" } : {} }) }); return response.data; }

function showAuth(mode = "login") { state.authMode = mode; $("auth-screen").classList.remove("hidden"); $("app-shell").classList.add("auth-locked"); $("auth-title").textContent = mode === "register" ? "注册 CodeSpider" : "登录 CodeSpider"; $("auth-subtitle").textContent = mode === "register" ? "首个注册用户自动成为管理员。" : "登录后管理工程、模型和积分用量。"; $("auth-submit").textContent = mode === "register" ? "注册并登录" : "登录"; $("auth-switch").textContent = mode === "register" ? "已有账号？登录" : "没有账号？注册"; $("auth-error").textContent = ""; $("auth-form").reset(); }
function hideAuth() { $("auth-screen").classList.add("hidden"); $("app-shell").classList.remove("auth-locked"); }
async function submitAuth(event) { event.preventDefault(); try { const endpoint = state.authMode === "register" ? "/api/auth/register" : "/api/auth/login"; await api(endpoint, { method: "POST", body: JSON.stringify({ username: $("auth-username").value.trim(), password: $("auth-password").value }) }); await loadAccount(); hideAuth(); await loadWorkspaces(); } catch (error) { $("auth-error").textContent = error.message || "认证失败"; } }
async function loadAccount() { const account = await api("/api/auth/me"); state.user = account.user; state.models = account.models || []; state.usage = account.usage || { total_calls: 0, total_cost: 0 }; updateAccountUi(account); if (state.user.role === "ADMIN") await loadAdminData(); }
function switchSettingsTab(tab = "account") {
  if (!["account", "models", "users", "defaults"].includes(tab) || (tab !== "account" && state.user?.role !== "ADMIN")) tab = "account";
  state.settingsTab = tab;
  document.querySelectorAll("[data-settings-tab]").forEach((button) => {
    const active = button.dataset.settingsTab === tab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll("[data-settings-section]").forEach((panel) => panel.classList.toggle("hidden", panel.dataset.settingsSection !== tab));
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
async function assignModel(modelId, users) { const username = window.prompt(`输入要分配 ${modelId} 的用户名：`, users.find((user) => user.role === "USER")?.username || ""); const user = users.find((item) => item.username === username); if (!user) return; try { await api(`/api/admin/models/${modelId}/assign`, { method: "POST", body: JSON.stringify({ user_id: user.id }) }); showToast("模型已分配"); } catch (error) { showError(error); } }

function escapeHtml(value) { return String(value ?? "").replace(/[&<>\"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '\"': "&quot;" }[char])); }
function showToast(message) { const toast = $("toast"); toast.textContent = message; toast.classList.add("show"); setTimeout(() => toast.classList.remove("show"), 2300); }
function showError(error) { showToast(error.message || "请求失败"); }
function setView(view) { document.querySelectorAll(".view").forEach((item) => item.classList.remove("active-view")); const target = $(`${view}-view`); if (target) target.classList.add("active-view"); document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === view)); }

async function loadWorkspaces() { const data = await api("/api/workspaces"); state.workspaces = data.items; renderWorkspaceLists(); }
function projectIcon(type) { return type === "python" ? "Py" : type === "vue" ? "V" : type === "java-springboot" ? "J" : "⌘"; }
function modeLabel(mode) { return mode === "divergent" ? "发散模式" : "安全执行模式"; }
function renderWorkspaceLists() { $("sidebar-projects").innerHTML = state.workspaces.length ? state.workspaces.map((workspace) => `<button class="project-item ${state.currentWorkspace?.id === workspace.id ? "active" : ""}" data-workspace="${workspace.id}"><span class="project-symbol">${projectIcon(workspace.project_type)}</span><span><b>${escapeHtml(workspace.name)}</b><small>${escapeHtml(workspace.project_type)}</small></span></button>`).join("") : `<div class="empty-state" style="padding:18px 8px;font-size:11px">还没有工程</div>`; document.querySelectorAll("[data-workspace]").forEach((item) => item.onclick = () => openWorkspace(item.dataset.workspace)); $("project-cards").innerHTML = state.workspaces.map((workspace) => `<article class="project-card" data-workspace="${workspace.id}"><div class="project-card-top"><div class="project-card-icon">${projectIcon(workspace.project_type)}</div><span class="project-card-menu">···</span></div><h3>${escapeHtml(workspace.name)}</h3><p>${escapeHtml(workspace.root)}</p><div class="project-card-footer"><span>${escapeHtml(workspace.project_type)}</span><span>打开项目 ›</span></div></article>`).join(""); document.querySelectorAll(".project-card[data-workspace]").forEach((item) => item.onclick = () => openWorkspace(item.dataset.workspace)); $("empty-projects").classList.toggle("hidden", state.workspaces.length > 0); }

async function openWorkspace(id) {
  const workspace = state.workspaces.find((item) => item.id === id);
  if (!workspace) return;
  if (state.currentWorkspace?.id !== id) {
    if (state.currentWorkspace) Object.assign(projectSession(state.currentWorkspace.id), {
      draft: $("project-input").value, command: $("command").value, serviceCommand: $("service-command").value,
    });
    state.currentWorkspace = workspace;
    const session = projectSession(id);
    state.task = session.task;
    $("project-input").value = session.draft;
    $("command").value = session.command;
    $("service-command").value = session.serviceCommand;
    for (const target of ["file-tree", "symbol-list", "preview-path", "preview-content", "document-preview", "settings-saved", "design-review-result"]) $(target).textContent = "";
    $("file-preview").classList.add("hidden");
    $("document-preview").classList.add("hidden");
    $("symbol-count").textContent = "—";
    $("doc-status").textContent = "未生成";
    $("command-output").textContent = "等待执行命令…";
    $("processes").textContent = "暂无运行中的服务";
    renderConversation(id);
    switchPanel("chat");
  }
  setView("project");
  renderWorkspaceLists();
  updateProjectHeader();
  fillSettings();
  await loadExplorer();
}
function updateProjectHeader() { const workspace = state.currentWorkspace; $("project-name-title").textContent = workspace.name; $("project-meta").textContent = `${workspace.project_type} · ${modeLabel(workspace.execution_mode)} · ${workspace.root}`; $("project-avatar").textContent = projectIcon(workspace.project_type); $("context-project").textContent = workspace.name; $("context-path").textContent = workspace.root; $("context-mode").textContent = modeLabel(workspace.execution_mode); $("context-description").textContent = workspace.description || "还没有添加说明"; }
function openNewProject() { $("new-project-form").classList.remove("hidden"); $("project-name").focus(); }
$("project-name").oninput = () => { $("project-root").placeholder = `~/.codespider/project/${$("project-name").value.trim() || "{项目名称}"}`; };
function closeNewProject() { $("new-project-form").classList.add("hidden"); }
async function createWorkspace() { try { const workspace = await api("/api/workspaces", { method: "POST", body: JSON.stringify({ root: $("project-root").value, name: $("project-name").value }) }); closeNewProject(); await loadWorkspaces(); await openWorkspace(workspace.id); showToast("工程已添加"); } catch (error) { showError(error); } }

function switchPanel(panel) { state.currentPanel = panel; document.querySelectorAll(".project-nav-item").forEach((item) => item.classList.toggle("active", item.dataset.panel === panel)); document.querySelectorAll(".panel-view").forEach((item) => item.classList.remove("active-panel")); const target = $(`${panel}-panel`); if (target) target.classList.add("active-panel"); if (panel === "explorer") loadExplorer(); if (panel === "terminal") listProcesses(); if (panel === "settings") fillSettings(); }
async function loadExplorer() {
  const workspace = state.currentWorkspace;
  if (!workspace) return;
  try {
    let symbols;
    try { symbols = await callTool("code", "symbols", workspace.id); }
    catch (error) {
      if (state.currentWorkspace !== workspace) return;
      if (error.approvalRequired && window.confirm("安全执行模式需要确认分析这个工程的代码结构。是否继续？")) symbols = await callTool("code", "symbols", workspace.id, {}, true);
      else throw error;
    }
    if (state.currentWorkspace !== workspace) return;
    const tree = await callTool("workspace", "list_tree", workspace.id, { limit: 1000 });
    if (state.currentWorkspace !== workspace) return;
    $("file-tree").innerHTML = tree.items.map((item) => `<div class="file-row" data-file="${escapeHtml(item.path)}"><span class="file-glyph">□</span>${escapeHtml(item.path)}</div>`).join("") || `<span class="muted">没有可展示的文件</span>`;
    document.querySelectorAll("[data-file]").forEach((item) => item.onclick = () => previewFile(item.dataset.file));
    $("symbol-list").innerHTML = symbols.items.map((item) => `<div class="symbol-row"><span>${escapeHtml(item.kind)}</span><b>${escapeHtml(item.name)}</b><small>${escapeHtml(item.path)}:${item.line}</small></div>`).join("") || `<span class="muted">暂无符号索引</span>`;
    $("symbol-count").textContent = `${symbols.items.length} 个符号`;
  } catch (error) { if (state.currentWorkspace === workspace) showError(error); }
}
async function previewFile(path, approved = false, workspace = state.currentWorkspace) {
  if (!workspace) return;
  try {
    const data = await callTool("workspace", "read_file", workspace.id, { path }, approved);
    if (state.currentWorkspace !== workspace) return;
    $("file-preview").classList.remove("hidden");
    $("preview-path").textContent = path;
    $("preview-content").textContent = data.content;
  } catch (error) {
    if (state.currentWorkspace !== workspace) return;
    if (error.approvalRequired && window.confirm("安全执行模式需要确认读取这个文件的内容。是否继续？")) return previewFile(path, true, workspace);
    showError(error);
  }
}

async function createTask(goal) {
  const workspace = state.currentWorkspace;
  if (!workspace) return showError(new Error("请先选择工程"));
  const session = projectSession(workspace.id), generation = ++session.generation;
  const pending = appendMessage("agent", "思考中 · 正在生成回复与代码，请稍候…", workspace.id);
  try {
    const requestTask = (contextApproved) => api("/api/tasks", { method: "POST", body: JSON.stringify({ workspace_id: workspace.id, goal, context_approved: contextApproved }) });
    let task;
    try { task = await requestTask(false); }
    catch (error) {
      if (!error.approvalRequired || !window.confirm(`${error.message}\n\n工程：${workspace.name}\n是否继续？`)) throw error;
      task = await requestTask(true);
    }
    if (session.generation === generation) {
      session.task = task;
      if (state.currentWorkspace?.id === workspace.id) state.task = task;
    }
    appendAgentTurn(task, pending);
    if (state.currentWorkspace?.id === workspace.id) switchPanel("chat");
  } catch (error) {
    pending.innerHTML = `<div class="message-bubble" role="alert">${escapeHtml(`生成未完成：${error.message}。请检查模型设置或重试。`)}</div>`;
    if (state.currentWorkspace?.id === workspace.id) showError(error);
  }
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
function appendDesignReview(event, workspaceId) {
  const message = document.createElement("div"); message.className = "message agent";
  message.innerHTML = designPreview({design_review:event.payload}); addProjectMessage(workspaceId,message);
}
function appendAgentTurn(task, existingMessage = null) {
  const message = existingMessage || document.createElement("div");
  message.className = "message agent";
  const thinking = (task.thinking || []).map((item) => `<div class="thinking-line"><b>${escapeHtml(item.title)}</b><span>${escapeHtml(item.summary)}</span></div>`).join("");
  const steps = (task.plan || []).map((step) => `<div class="thinking-line"><b>${escapeHtml(step.step)}. ${escapeHtml(step.title)}</b><span>${escapeHtml(step.detail)}</span></div>`).join("");
  const count = task.patches?.length || 0;
  message.innerHTML = `<div class="message-bubble">${escapeHtml(task.summary || "方案已准备好，请查看下方详情。")}</div>
    <p class="task-status" role="status">${count ? `待确认：将修改 ${count} 个文件，批准后写入并运行验证。` : "当前方案没有代码变更；批准后仅分析和验证工程。生成代码请在设置中选择已配置的大模型。"}</p>
    <details class="thinking-card"><summary><span class="thinking-label">方案详情</span><span class="thinking-meta">${task.plan?.length || 0} 个步骤 · ${count} 个文件</span></summary><div class="thinking-body">${thinking}${steps}<div class="thinking-line"><b>执行目录</b><span>${escapeHtml(task.workspace_snapshot?.root || state.workspaces.find((item) => item.id === task.workspace_id)?.root || "")}</span></div>${designPreview(task)}${patchPreview(task)}<p>批准后运行工程验证；新 Vue 工程会安装依赖（禁用安装脚本）。</p></div></details>
    <button class="approve-inline">批准执行</button>`;
  const button = message.querySelector(".approve-inline"), statusNode = message.querySelector(".task-status");
  button.onclick = () => approveTask(task, button, statusNode);
  if (!existingMessage) addProjectMessage(task.workspace_id, message);
}
function appendMessage(role, text, workspaceId = state.currentWorkspace?.id) { const message = document.createElement("div"); message.className = `message ${role}`; message.innerHTML = `<div class="message-bubble">${escapeHtml(text)}</div>`; addProjectMessage(workspaceId, message); return message; }
async function sendProjectMessage() { const input = $("project-input"); const goal = input.value.trim(); if (!goal) return; input.value = ""; appendMessage("user", goal); await createTask(goal); }
function sendFreeMessage() { const input = $("free-input"); const text = input.value.trim(); if (!text) return; input.value = ""; const container = $("free-messages"); const welcome = container.querySelector(".welcome-message"); if (welcome) welcome.remove(); const message = document.createElement("div"); message.className = "message user"; message.innerHTML = `<div class="message-bubble">${escapeHtml(text)}</div>`; container.appendChild(message); const answer = document.createElement("div"); answer.className = "message agent"; answer.innerHTML = `<div class="message-bubble">我可以先帮你梳理这个问题。选择一个具体工程后，我还能继续读取代码、生成补丁并运行验证。</div>`; container.appendChild(answer); container.scrollTop = container.scrollHeight; }

async function approveTask(task, button, statusNode = null) {
  if (!task || button.disabled) return;
  if (task.workspace_id !== state.currentWorkspace?.id) return showError(new Error("请先打开这个任务所属的工程"));
  button.disabled = true;
  button.textContent = "提交中…";
  try {
    const approved = await api(`/api/tasks/${task.id}/approve`, { method: "POST", body: "{}" });
    updateSessionTask(task.workspace_id, approved);
    button.textContent = "执行中…";
    if (statusNode) statusNode.textContent = task.patches?.length ? "已批准，正在写入文件并执行验证。" : "已批准，正在分析和验证工程。";
    appendMessage("agent", "任务已批准，Agent 正在执行工程分析和验证命令。", task.workspace_id);
    pollTask({ taskId: task.id, workspaceId: task.workspace_id, after: 0, button, statusNode });
  } catch (error) {
    button.disabled = false;
    button.textContent = "批准执行";
    appendMessage("agent", `批准失败：${error.message}。可以重试。`, task.workspace_id);
    showError(error);
  }
}
function appendToolEvent(event, workspaceId) { const request = event.payload?.request || {}; const message = document.createElement("div"); message.className = "message agent"; message.innerHTML = `<details class="thinking-card tool-card"><summary><span class="thinking-label">工具调用</span><span class="thinking-meta">调用 ${escapeHtml(request.tool || "tool")}.${escapeHtml(request.action || "call")}</span></summary><div class="thinking-body"><div class="thinking-line"><b>工具请求</b><span>${escapeHtml(JSON.stringify(request.arguments || {}))}</span></div></div></details>`; addProjectMessage(workspaceId, message); }
async function pollTask(run) {
  if (!run || run.finished) return;
  try {
    const data = await api(`/api/tasks/${run.taskId}/events?after=${run.after}`);
    for (const event of data.items) {
      if (event.sequence <= run.after) continue;
      if (event.type === "tool.call") appendToolEvent(event, run.workspaceId);
      if (event.type === "file.changed") appendMessage("agent", `已写入文件：${event.payload.path || event.payload.relative_path || "工程文件"}`, run.workspaceId);
      if (event.type === "process.output") appendMessage("agent", `验证命令：${event.payload.command || ""}\n退出码：${event.payload.exit_code}\n${(event.payload.output || "").slice(-12000)}`, run.workspaceId);
      if (event.type === "agent.notice") appendMessage("agent", event.payload.message, run.workspaceId);
      if (event.type === "design.reviewed") appendDesignReview(event, run.workspaceId);
      if (["task.succeeded", "task.failed", "task.cancelled"].includes(event.type) && !run.terminalSeen) {
        const result = event.payload.message || event.payload.error || ({"task.succeeded": "执行完成", "task.failed": "执行失败", "task.cancelled": "任务已取消"})[event.type];
        appendMessage("agent", result, run.workspaceId);
        if (run.statusNode) run.statusNode.textContent = result;
        run.terminalSeen = true;
      }
      run.after = event.sequence;
    }
    const latest = await api(`/api/tasks/${run.taskId}`);
    updateSessionTask(run.workspaceId, latest);
    run.failures = 0;
    const terminal = ["succeeded", "failed", "cancelled"].includes(latest.status);
    if (terminal && run.terminalSeen) {
      run.finished = true;
      run.button.textContent = ({ succeeded: "已完成", failed: "执行失败", cancelled: "已取消" })[latest.status];
      return;
    }
    // State and events are separate reads: completion can happen between them.
    run.button.textContent = terminal ? "同步最终结果…" : "执行中…";
    setTimeout(() => pollTask(run), 900);
  } catch (error) {
    run.failures = (run.failures || 0) + 1;
    run.button.textContent = "连接中断，正在重试…";
    if (run.failures === 1 && state.currentWorkspace?.id === run.workspaceId) showError(error);
    setTimeout(() => pollTask(run), Math.min(900 * 2 ** Math.min(run.failures, 5), 15000));
  }
}
async function runCommand(approved = false, workspace = state.currentWorkspace, command = $("command").value.trim()) {
  if (!workspace) return showError(new Error("请先选择工程"));
  if (!command) return showError(new Error("请输入命令"));
  try {
    const result = await callTool("process", "run", workspace.id, { command }, approved);
    if (state.currentWorkspace === workspace) $("command-output").textContent = `risk=${result.risk} exit=${result.exit_code}\n${result.output}`;
  } catch (error) {
    if (state.currentWorkspace !== workspace) return;
    if (error.approvalRequired && window.confirm(`${error.message}\n\n命令：${command}\n\n是否继续执行？`)) return runCommand(true, workspace, command);
    showError(error);
  }
}
async function startService(approved = false, workspace = state.currentWorkspace, command = $("service-command").value.trim()) {
  if (!workspace) return showError(new Error("请先选择工程"));
  if (!command) return showError(new Error("请输入启动命令"));
  try {
    await callTool("process", "start", workspace.id, { command }, approved);
    await listProcesses(workspace);
  } catch (error) {
    if (state.currentWorkspace !== workspace) return;
    if (error.approvalRequired && window.confirm(`${error.message}\n\n服务命令：${command}\n\n是否继续启动？`)) return startService(true, workspace, command);
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
async function generateDocument(approved = false, workspace = state.currentWorkspace) {
  if (!workspace) return showError(new Error("请先选择工程"));
  try {
    const result = await callTool("document", "generate", workspace.id, {}, approved);
    if (state.currentWorkspace !== workspace) return;
    $("document-preview").classList.remove("hidden");
    $("document-preview").textContent = result.content;
    $("doc-status").textContent = "已生成";
    showToast("文档已生成");
  } catch (error) {
    if (state.currentWorkspace !== workspace) return;
    if (error.approvalRequired && window.confirm(`${error.message}\n\n是否继续读取工程并生成文档？`)) return generateDocument(true, workspace);
    showError(error);
  }
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
    if (error.approvalRequired && window.confirm("结构审查需要读取工程源码。是否继续？")) return reviewProjectDesign(true, workspace);
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
$("sidebar-toggle").onclick = () => $("app-shell").classList.toggle("sidebar-collapsed"); $("focus-toggle").onclick = () => $("app-shell").classList.toggle("context-hidden"); $("toggle-context").onclick = () => $("app-shell").classList.toggle("context-hidden"); $("context-close").onclick = () => $("app-shell").classList.add("context-hidden"); $("new-project").onclick = openNewProject; $("home-add-project").onclick = openNewProject; $("empty-add-project").onclick = openNewProject; $("close-new-project").onclick = closeNewProject; $("create-project").onclick = createWorkspace; $("project-send").onclick = sendProjectMessage; $("free-send").onclick = sendFreeMessage; $("refresh-explorer").onclick = loadExplorer; $("review-design").onclick = () => reviewProjectDesign(); $("close-preview").onclick = () => $("file-preview").classList.add("hidden"); $("run-command").onclick = () => runCommand(); $("start-service").onclick = () => startService(); $("stop-services").onclick = stopServices; $("generate-doc").onclick = () => generateDocument(); $("save-settings").onclick = saveSettings; $("reindex-project").onclick = reindexProject; $("project-settings-btn").onclick = () => switchPanel("settings"); $("quick-send").onclick = () => { setView("free-chat"); $("free-input").value = $("quick-chat").value; sendFreeMessage(); };
$("global-settings").onclick = () => { setView("global-settings"); loadGlobalSettings(); }; $("save-global-settings").onclick = () => saveGlobalSettings(false); $("clear-api-key").onclick = () => { if (window.confirm("确认清除本机保存的 API Key？")) saveGlobalSettings(true); };
$("auth-form").onsubmit = submitAuth; $("auth-switch").onclick = () => showAuth(state.authMode === "login" ? "register" : "login"); $("logout-btn").onclick = async () => { try { await api("/api/auth/logout", { method: "POST", body: "{}" }); } finally { showAuth("login"); } }; $("save-account-model").onclick = saveAccountModel; $("add-admin-model").onclick = addAdminModel;
$("project-input").addEventListener("keydown", (event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") sendProjectMessage(); }); $("free-input").addEventListener("keydown", (event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") sendFreeMessage(); });

api("/api/health").then(async () => { $("health").innerHTML = "<i></i>在线"; try { await loadAccount(); hideAuth(); await loadWorkspaces(); } catch (error) { if (!error.authRequired) showError(error); } }).catch(() => { $("health").innerHTML = "<i style='background:#c86f62'></i>离线"; });
