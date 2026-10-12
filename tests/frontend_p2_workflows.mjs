// Run with: node tests/frontend_p2_workflows.mjs
// Execute real application handlers; use controlled HTTP/timers for race cases.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';

const source = await fs.readFile(new URL('../frontend/app.js', import.meta.url), 'utf8');
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const ok = data => ({ok: true, json: async () => data});
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
function harness() {
  const nodes = new Map(), requests = [], timers = [];
  let sequence = 0;
  function element() {
    let html = '', text = '';
    const classes = new Set();
    return {
      value: '', dataset: {}, children: [], disabled: false,
      classList: {add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c),
        toggle(c, on) { if (on) classes.add(c); else classes.delete(c); }},
      focus() {}, addEventListener() {},
      get innerHTML() { return html; },
      set innerHTML(value) {
        html = value; text = ''; this.children = [];
        if (value.includes('class="approve-inline"')) this.button = {disabled: false, textContent: '批准执行'};
      },
      get textContent() { return text; },
      set textContent(value) { text = value; html = ''; this.children = []; },
      querySelector(selector) { return selector === '.approve-inline' ? this.button : null; },
      appendChild(child) { this.children.push(child); },
      replaceChildren(...children) { this.children = children; html = ''; text = ''; },
    };
  }
  function node(id) { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); }
  const app = {node, requests, timers, route: null, prompts: 0};
  const context = vm.createContext({
    document: {getElementById: node, createElement: element, querySelectorAll: () => []},
    window: {confirm: () => { app.prompts++; return true; }},
    setTimeout: (fn, delay) => { timers.push({fn, delay}); return timers.length; }, clearTimeout() {},
    fetch: async (path, options = {}) => {
      const body = options.body ? JSON.parse(options.body) : null;
      requests.push({path, body});
      const routed = app.route?.(path, body);
      if (routed !== undefined) return routed;
      if (path === '/api/workspaces') return ok({items: []});
      if (path === '/api/tasks') return ok({id: `task-${++sequence}`, workspace_id: body.workspace_id,
        status: 'created', plan: [], thinking: [], workspace_snapshot: {root: `/${body.workspace_id}`}});
      if (path.endsWith('/approve')) return ok({id: path.split('/')[3], status: 'executing'});
      if (path.includes('/events')) return ok({items: [{sequence: 1, type: 'task.succeeded', payload: {message: 'A finished'}}]});
      if (path.startsWith('/api/tasks/')) return ok({id: path.split('/')[3], status: 'succeeded'});
      if (path === '/api/tools/call') return ok({data: {items: [], content: 'current', output: 'current', exit_code: 0}});
      return ok({});
    },
  });
  vm.runInContext(source, context);
  app.run = code => vm.runInContext(code, context);
  app.open = id => app.run(`openWorkspace(${JSON.stringify(id)})`);
  app.visible = () => node('project-messages').children.map(n => n.innerHTML).join('\n');
  app.nextPoll = async () => {
    const index = timers.findIndex(timer => timer.fn.toString().includes('pollTask'));
    assert.ok(index >= 0, 'a further polling attempt must be scheduled');
    await timers.splice(index, 1)[0].fn();
    await tick();
  };
  return app;
}
async function ready() {
  const app = harness();
  await tick();
  app.run('state.workspaces = ["A", "B"].map(id => ({id, name: id, root: "/" + id, project_type: "python", execution_mode: "divergent"}))');
  await app.open('A');
  return app;
}

// A -> B -> A: task, conversation nodes and drafts belong to their own project.
{
  const app = await ready();
  app.node('project-input').value = 'A request';
  await app.run('sendProjectMessage()');
  const card = app.node('project-messages').children.find(n => n.button);
  app.node('project-input').value = 'A unfinished draft';
  app.node('command').value = 'A command';
  app.node('service-command').value = 'A service';
  app.node('preview-content').textContent = 'private A content';
  app.node('command-output').textContent = 'A output';
  await app.open('B');
  assert.equal(app.run('state.task'), null);
  assert.equal(app.visible(), '');
  assert.equal(app.node('project-input').value, '');
  assert.equal(app.node('command').value, '');
  assert.equal(app.node('preview-content').textContent, '');
  assert.equal(app.node('command-output').textContent, '等待执行命令…');
  app.node('project-input').value = 'B request';
  await app.run('sendProjectMessage()');
  const bTask = app.run('state.task.id');
  app.node('project-input').value = 'B draft';
  await app.open('A');
  assert.equal(app.run('state.task.id'), 'task-1');
  assert.equal(app.node('project-input').value, 'A unfinished draft');
  assert.equal(app.node('command').value, 'A command');
  assert.equal(app.node('service-command').value, 'A service');
  assert.ok(app.visible().includes('A request'));
  assert.ok(!app.visible().includes('B request'));
  assert.ok(app.node('project-messages').children.includes(card), 'restore the original approval node');
  await card.button.onclick();
  await tick();
  assert.equal(card.button.textContent, '已完成');
  await app.open('B');
  assert.equal(app.run('state.task.id'), bTask);
  assert.equal(app.node('project-input').value, 'B draft');
  assert.ok(!app.visible().includes('A finished'));
}

// A task created or approved while switching projects still returns to A.
for (const operation of ['create', 'approve']) {
  const app = await ready(), response = deferred();
  let pending, card;
  if (operation === 'create') {
    app.route = path => path === '/api/tasks' ? response.promise : undefined;
    pending = app.run('createTask("delayed A")');
  } else {
    await app.run('createTask("A approval")');
    card = app.node('project-messages').children.find(n => n.button);
    app.route = path => path.endsWith('/approve') ? response.promise : undefined;
    pending = card.button.onclick();
  }
  await app.open('B');
  app.node('project-input').value = 'B draft';
  app.run('switchPanel("artifacts")');
  response.resolve(ok({id: 'task-1', workspace_id: 'A', status: operation === 'create' ? 'created' : 'executing', plan: [], thinking: []}));
  await pending; await tick();
  assert.equal(app.run('state.task'), null);
  assert.equal(app.run('state.currentPanel'), 'artifacts');
  assert.equal(app.visible(), '');
  assert.equal(app.node('project-input').value, 'B draft');
  await app.open('A');
  assert.equal(app.run('state.task.id'), 'task-1');
  assert.ok(app.visible().includes('批准执行'));
  if (operation === 'approve') {
    assert.ok(app.visible().includes('A finished'));
    assert.equal(card.button.textContent, '已完成');
  } else assert.ok(app.visible().includes('/A'), 'legacy root fallback must belong to A');
}

// A terminal status preceding its final event must keep polling, across a network failure.
for (const status of ['succeeded', 'failed', 'cancelled']) {
  const app = await ready();
  await app.run('createTask("poll race")');
  let reads = 0;
  app.route = path => {
    if (path.includes('/events')) {
      reads++;
      if (reads <= 2) return ok({items: []});
      if (reads === 3) return Promise.reject(new Error('temporary network failure'));
      return ok({items: [{sequence: 2, type: `task.${status}`, payload: {message: `final-${status}`}}]});
    }
    if (path === '/api/tasks/task-1') return ok({id: 'task-1', status});
  };
  app.run('globalThis.run = {taskId: "task-1", workspaceId: "A", after: 0, button: {}}');
  await app.run('pollTask(run)');
  assert.equal(app.run('run.finished'), undefined);
  assert.equal(app.run('run.button.textContent'), '同步最终结果…');
  await app.open('B');
  await app.nextPoll();
  await app.nextPoll();
  assert.equal(app.run('run.button.textContent'), '连接中断，正在重试…');
  await app.nextPoll();
  assert.equal(app.run('run.finished'), true);
  assert.equal(app.visible(), '');
  await app.open('A');
  assert.equal(app.visible().split(`final-${status}`).length - 1, 1);
  const count = app.requests.length;
  await app.run('pollTask(run)');
  assert.equal(app.requests.length, count, 'finished polling must be idempotent');
}

// A status fetch can fail after rendering the event; retry must not duplicate it.
{
  const app = await ready();
  let statuses = 0;
  app.route = path => {
    if (path === '/api/tasks/task-1' && ++statuses === 1) return Promise.reject(new Error('state unavailable'));
  };
  app.run('globalThis.run = {taskId: "task-1", workspaceId: "A", after: 0, button: {}}');
  await app.run('pollTask(run)');
  await app.nextPoll();
  assert.equal(app.run('run.finished'), true);
  assert.equal(app.visible().split('A finished').length - 1, 1);
  assert.ok(app.requests.some(r => r.path === '/api/tasks/task-1/events?after=1'));
}

// Results already in flight must not overwrite B's previews, settings or output.
for (const [operation, action, target, result] of [
  ['previewFile("main.py")', 'read_file', 'preview-content', {content: 'stale A'}],
  ['generateDocument()', 'generate', 'document-preview', {content: 'stale A'}],
  ['runCommand()', 'run', 'command-output', {output: 'stale A', exit_code: 0}],
  ['listProcesses()', 'list', 'processes', {items: [{pid: 1, status: 'running', command: 'stale A'}]}],
  ['loadExplorer()', 'list_tree', 'file-tree', {items: [{path: 'stale A'}]}],
  ['loadExplorer()', 'symbols', 'symbol-list', {items: [{name: 'stale A', path: 'main.py', line: 1}]}],
  ['saveSettings()', 'settings', 'project-name-title', {id: 'A', name: 'stale A', root: '/A'}],
]) {
  const app = await ready(), response = deferred();
  app.node('command').value = 'A command';
  app.route = (path, body) => (body?.workspace_id === 'A' && body.action === action) || path === '/api/workspaces/A/settings' ? response.promise : undefined;
  const pending = app.run(operation);
  await tick();
  await app.open('B');
  const before = app.node(target).textContent || app.node(target).innerHTML;
  response.resolve(ok(action === 'settings' ? result : {data: result}));
  await pending;
  assert.equal(app.run('state.currentWorkspace.id'), 'B', operation);
  assert.equal(app.node(target).textContent || app.node(target).innerHTML, before, operation);
}

// A delayed approval-required response may not prompt/retry against B.
{
  const app = await ready(), response = deferred();
  app.node('command').value = 'A command';
  app.route = (path, body) => body?.action === 'run' ? response.promise : undefined;
  const pending = app.run('runCommand()');
  await app.open('B');
  response.resolve({ok: false, json: async () => ({error: {message: 'approval required', approval_required: true}})});
  await pending;
  assert.equal(app.prompts, 0);
  assert.equal(app.requests.filter(r => r.body?.action === 'run').length, 1);
}

// A multi-call operation keeps the original execution target after switching.
{
  const app = await ready(), response = deferred();
  let intercepted = false;
  app.route = (path, body) => {
    if (body?.workspace_id === 'A' && body.action === 'list' && !intercepted) {
      intercepted = true; return response.promise;
    }
  };
  const pending = app.run('stopServices()');
  await app.open('B');
  response.resolve(ok({data: {items: [{pid: 123, status: 'running'}]}}));
  await pending;
  const stops = app.requests.filter(r => r.body?.action === 'stop');
  assert.equal(stops.length, 1);
  assert.equal(stops[0].body.workspace_id, 'A');
}
console.log('PASS: project session isolation, delayed create/approval/output/settings, completion races for 3 terminal states, network retries, event deduplication and original service target');
