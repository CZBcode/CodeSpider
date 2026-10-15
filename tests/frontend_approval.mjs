// Run with: node tests/frontend_approval.mjs
// Execute the real handlers with a fake DOM and an API that requires approval.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';

const source = await fs.readFile(new URL('../frontend/app.js', import.meta.url), 'utf8');
const nodes = new Map();
const requests = [];
let confirmed = false;
let prompts = 0;
function element() {
  return {value: '', textContent: '', innerHTML: '', dataset: {}, children: [],
    classList: {add() {}, remove() {}, toggle() {}}, focus() {}, addEventListener() {},
    querySelector() { return null; }, appendChild(child) { this.children.push(child); }};
}
function getNode(id) {
  if (!nodes.has(id)) nodes.set(id, element());
  return nodes.get(id);
}
const context = vm.createContext({
  document: {getElementById: getNode, querySelectorAll: () => [], createElement: element},
  window: {confirm: () => { prompts += 1; return confirmed; }},
  setTimeout: () => 1, clearTimeout() {},
  fetch: async (path, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : null;
    requests.push({path, body});
    if (path === '/api/tools/call' && body.action !== 'list' && body.approval?.approved !== true) {
      return {ok: false, json: async () => ({error: {message: 'approval required', approval_required: true}})};
    }
    return {ok: true, json: async () => path === '/api/workspaces' ? {items: []} :
      {data: {items: [], content: 'document', output: 'ok', exit_code: 0, risk: 'low'}}};
  },
});
vm.runInContext(source, context);
vm.runInContext("requestDialog = async () => window.confirm() ? true : null", context);
await new Promise(resolve => setTimeout(resolve, 0));
vm.runInContext('state.currentWorkspace = {id: "test-project", execution_mode: "safe"}', context);
getNode('command').value = 'python3 -c "print(1)"';
getNode('service-command').value = 'python3 -c "print(1)"';

for (const button of ['run-command', 'start-service', 'generate-doc']) {
  for (const allow of [false, true]) {
    confirmed = allow;
    prompts = 0;
    requests.length = 0;
    await getNode(button).onclick({type: 'click'});
    const calls = requests.filter(item => item.path === '/api/tools/call' && item.body.action !== 'list');
    assert.equal(prompts, 1, `${button} must ask for approval`);
    assert.equal(calls[0].body.approval.approved, undefined, `${button} must not approve its initial call`);
    assert.equal(calls.length, allow ? 2 : 1, `${button} must not retry after rejection`);
    if (allow) assert.equal(calls[1].body.approval.approved, true);
  }
}
// Even an accidental event passed directly cannot be treated as consent.
confirmed = false;
requests.length = 0;
await vm.runInContext('runCommand({type: "click"})', context);
assert.equal(requests[0].body.approval.approved, undefined);
console.log('PASS: 3 action buttons × approve/reject; event objects never authorize execution');
