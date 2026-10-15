// Run with: node tests/frontend_task_binding.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';

const source = await fs.readFile(new URL('../frontend/app.js', import.meta.url), 'utf8');
function harness() {
  const nodes = new Map(), cards = [], requests = [];
  let sequence = 0;
  function element() {
    let html = '', ownButton;
    return {value: '', textContent: '', dataset: {}, children: [], disabled: false,
      classList: {add() {}, remove() {}, toggle() {}}, focus() {}, addEventListener() {},
      get innerHTML() { return html + this.children.map(child => child.outerHTML || child.innerHTML || child.textContent || '').join(''); },
      get outerHTML() { return '<div>' + (this.innerHTML || this.textContent || '') + '</div>'; },
      get button() { return ownButton || this.children.map(child=>child.button).find(Boolean); },
      set button(value) { ownButton = value; },
      setAttribute() {},
      set innerHTML(value) {
        html = value;
        if (value.includes('class="approve-inline"')) {
          this.button = {disabled: false, onclick: null, textContent: '批准执行'};
          cards.push(this);
        }
      },
      querySelector(selector) { return selector === '.approve-inline' ? this.button : null; },
      appendChild(child) { this.children.push(child); },
      replaceChildren(...children) { this.children = children; },
    };
  }
  function getNode(id) {
    // Model the browser's first-match behavior for any duplicate legacy IDs.
    if (id === 'approve-task') return cards.find(card => card.innerHTML.includes('id="approve-task"'))?.button || null;
    if (!nodes.has(id)) nodes.set(id, element());
    return nodes.get(id);
  }
  const app = {cards, requests, getNode, approveResponse: null};
  const context = vm.createContext({
    document: {getElementById: getNode, querySelectorAll: () => [], createElement: element},
    window: {confirm: () => true}, setTimeout: () => 1, clearTimeout() {},
    fetch: async (path, options = {}) => {
      requests.push(path);
      if (path === '/api/workspaces') return {ok: true, json: async () => ({items: []})};
      if (path === '/api/tasks') {
        const body = JSON.parse(options.body);
        return {ok: true, json: async () => ({id: 'task-' + (++sequence), workspace_id: body.workspace_id,
          goal: body.goal, plan: [], thinking: [], status: 'created', workspace_snapshot: {root: '/original/project'}})};
      }
      if (path.endsWith('/approve') && app.approveResponse) return app.approveResponse(path);
      if (path.includes('/events')) return {ok: true, json: async () => ({items: [{sequence: 1, type: 'task.succeeded', payload: {message: 'done'}}]})};
      return {ok: true, json: async () => ({id: path.split('/')[3], status: path.endsWith('/approve') ? 'executing' : 'succeeded'})};
    },
  });
  vm.runInContext(source, context);
  app.context = context;
  app.run = code => vm.runInContext(code, context);
  return app;
}
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

for (const order of [[0, 1], [1, 0]]) {
  const app = harness();
  await tick();
  app.run('state.currentWorkspace = {id: "project-A"}');
  await app.run('createTask("first")');
  await app.run('createTask("second")');
  assert.equal(app.cards.length, 2);
  assert.ok(app.cards.every(card => typeof card.button.onclick === 'function'));
  assert.ok(app.cards[0].innerHTML.includes('/original/project'));
  for (const index of order) await app.cards[index].button.onclick();
  await tick();
  assert.deepEqual(app.requests.filter(path => path.endsWith('/approve')),
    order.map(index => `/api/tasks/task-${index + 1}/approve`));
  assert.ok(app.requests.includes('/api/tasks/task-1/events?after=0'));
  assert.ok(app.requests.includes('/api/tasks/task-2/events?after=0'));
  assert.equal(app.run('state.task.id'), 'task-2');
  const count = app.requests.length;
  await app.cards[0].button.onclick();
  assert.equal(app.requests.length, count, 'disabled button must not approve twice');
}

const delayed = harness();
await tick();
delayed.run('state.currentWorkspace = {id: "project-A"}');
await delayed.run('createTask("first")');
let respond;
delayed.approveResponse = () => new Promise(resolve => { respond = resolve; });
const pending = delayed.cards[0].button.onclick();
await delayed.run('createTask("second while approval pending")');
respond({ok: true, json: async () => ({id: 'task-1', status: 'executing'})});
await pending;
await tick();
assert.equal(delayed.run('state.task.id'), 'task-2', 'late response must not replace the newer task');
delayed.run('state.currentWorkspace = {id: "project-B"}');
const before = delayed.requests.length;
await delayed.cards[1].button.onclick();
assert.equal(delayed.requests.length, before, 'old project card must not approve from a different project');

const retry = harness();
await tick();
retry.run('state.currentWorkspace = {id: "project-A"}');
await retry.run('createTask("retry")');
retry.approveResponse = async () => ({ok: false, json: async () => ({error: 'temporary failure'})});
await retry.cards[0].button.onclick();
assert.equal(retry.cards[0].button.disabled, false, 'failed approval can be retried');
console.log('PASS: task-specific approval and polling, both approval orders, delayed responses, duplicate clicks, project guard and retry');
