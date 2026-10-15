import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
const source=await fs.readFile(new URL('../frontend/app.js',import.meta.url),'utf8');
const nodes=new Map(),requests=[];
let prompts=0;
function element(){return {value:'',innerHTML:'',textContent:'',dataset:{},classList:{add(){},remove(){},toggle(){}},addEventListener(){},focus(){},querySelector(){return null;},appendChild(){},replaceChildren(){}};}
const context=vm.createContext({document:{getElementById(id){if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);},querySelectorAll(){return [];},createElement:element},window:{confirm(){prompts++;return true;}},setTimeout(){return 1;},clearTimeout(){},fetch:async(path,options={})=>{
 const body=options.body?JSON.parse(options.body):null;
 if(path==='/api/tasks'){
  requests.push(body);
  return {ok:true,json:async()=>({id:'task1',workspace_id:'ws1',plan:[],patches:[]})};
 }
 return {ok:true,json:async()=>({items:[]})};
}});
vm.runInContext(source,context);
await new Promise(resolve=>setTimeout(resolve,0));
vm.runInContext('state.currentWorkspace={id:"ws1",name:"Example"}; appendAgentTurn=()=>{}; switchPanel=()=>{}; showError=()=>{};',context);
await vm.runInContext('createTask("Generate")',context);
assert.equal(requests.length,1);
assert.equal(prompts,0);
assert.equal(requests[0].goal,'Generate');
assert.equal(requests[0].context_approved,undefined);
const preview=vm.runInContext('patchPreview({patches:[{path:"App.vue",operation:"create",replacement:"<script>alert(1)</script>"}]})',context);
assert.ok(preview.includes('&lt;script&gt;'));assert.ok(!preview.includes('<script>'));
console.log('PASS: generation without read confirmation and escaped patch preview');
const designMarkup=vm.runInContext(`designPreview({design:{modules:[{path:'a.py',responsibility:'<script>bad</script>',depends_on:[]}],interfaces:[{path:'a.py',symbol:'f',inputs:{x:'integer'},outputs:'integer',errors:[]}]},design_review:{mode:'enforce',passed:true,metrics:{modules:1,classes:0,functions:1},modules:[{path:'a.py',layer:'core',parser:'python-ast',symbols:[{kind:'function',name:'f',line:1,parameter_names:['x']}],calls:[{caller:'f',callee:'g'}]}],dependencies:[],findings:[],limitations:['Static only']}})`,context);
assert.ok(designMarkup.includes('&lt;script&gt;'));assert.ok(!designMarkup.includes('<script>'));
assert.ok(designMarkup.includes('f(x)'));assert.ok(designMarkup.includes('Static only'));
assert.ok(designMarkup.includes('integer'));assert.ok(!designMarkup.includes('[object Object]'));
console.log('PASS: design contracts, function evidence and escaped structure preview');
