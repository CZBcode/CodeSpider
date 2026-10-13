import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
const source=await fs.readFile(new URL('../frontend/app.js',import.meta.url),'utf8');
const nodes=new Map(),requests=[];
let consent=false;
function element(){return {value:'',innerHTML:'',textContent:'',dataset:{},classList:{add(){},remove(){},toggle(){}},addEventListener(){},focus(){},querySelector(){return null;},appendChild(){}};}
const context=vm.createContext({document:{getElementById(id){if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);},querySelectorAll(){return [];},createElement:element},window:{confirm(){return consent;}},setTimeout(){return 1;},clearTimeout(){},fetch:async(path,options={})=>{
 const body=options.body?JSON.parse(options.body):null;
 if(path==='/api/tasks'){
  requests.push(body);
  if(!body.context_approved)return {ok:false,status:409,json:async()=>({error:'Read code approval required',approval_required:true})};
  return {ok:true,json:async()=>({id:'task1',workspace_id:'ws1',plan:[],patches:[]})};
 }
 return {ok:true,json:async()=>({items:[]})};
}});
vm.runInContext(source,context);
await new Promise(resolve=>setTimeout(resolve,0));
vm.runInContext('state.currentWorkspace={id:"ws1",name:"Example"}; appendAgentTurn=()=>{}; switchPanel=()=>{}; showError=()=>{};',context);
await vm.runInContext('createTask("Generate")',context);
assert.equal(requests.length,1);assert.equal(requests[0].context_approved,false);
requests.length=0;consent=true;
await vm.runInContext('createTask("Generate")',context);
assert.deepEqual(requests.map(r=>r.context_approved),[false,true]);
const preview=vm.runInContext('patchPreview({patches:[{path:"App.vue",operation:"create",replacement:"<script>alert(1)</script>"}]})',context);
assert.ok(preview.includes('&lt;script&gt;'));assert.ok(!preview.includes('<script>'));
console.log('PASS: generation context approval/rejection and escaped patch preview');
const designMarkup=vm.runInContext(`designPreview({design:{modules:[{path:'a.py',responsibility:'<script>bad</script>',depends_on:[]}],interfaces:[{path:'a.py',symbol:'f',inputs:{x:'integer'},outputs:'integer',errors:[]}]},design_review:{mode:'enforce',passed:true,metrics:{modules:1,classes:0,functions:1},modules:[{path:'a.py',layer:'core',parser:'python-ast',symbols:[{kind:'function',name:'f',line:1,parameter_names:['x']}],calls:[{caller:'f',callee:'g'}]}],dependencies:[],findings:[],limitations:['Static only']}})`,context);
assert.ok(designMarkup.includes('&lt;script&gt;'));assert.ok(!designMarkup.includes('<script>'));
assert.ok(designMarkup.includes('f(x)'));assert.ok(designMarkup.includes('Static only'));
assert.ok(designMarkup.includes('integer'));assert.ok(!designMarkup.includes('[object Object]'));
console.log('PASS: design contracts, function evidence and escaped structure preview');
