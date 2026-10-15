// PLAYWRIGHT_MODULE=/path/to/playwright node tests/frontend_dialogs.cjs
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs=require('node:fs'), http=require('node:http'), path=require('node:path'), assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../frontend');
const server=http.createServer((req,res)=>{
 const file=path.join(root,req.url==='/'?'index.html':req.url);
 if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}
 res.setHeader('Content-Type',file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':'text/html');
 res.end(fs.readFileSync(file));
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}), writes=[],errors=[],native=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('dialog',async d=>{native.push(d.type());await d.dismiss();});
  await page.route('**/api/**',async route=>{
   const url=new URL(route.request().url()), body=route.request().postDataJSON();
   if(body)writes.push({path:url.pathname,body});
   let data={items:[]},status=200;
   if(url.pathname==='/api/health')data={ok:true};
   if(url.pathname==='/api/workspaces')data={items:[{id:'A',name:'商品管理服务',root:'/project/A',execution_mode:'safe'}]};
   if(url.pathname==='/api/auth/me')data={user:{id:'alice',username:'alice',role:'ADMIN',balance:500},models:[],usage:{total_calls:0}};
   if(url.pathname==='/api/tools/call'){
    if(['run','start','generate'].includes(body.action)&&!body.approval?.approved){status=409;data={error:{message:'此操作需要你的确认。',approval_required:true}};}
    else data={ok:true,data:{items:[],output:'completed',exit_code:0,risk:'low',content:'document'}};
   }
   await route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.goto(process.env.DIALOG_TEST_URL || `http://127.0.0.1:${server.address().port}`);
  await page.waitForFunction(()=>state.user?.id==='alice'&&state.workspaces.some(w=>w.id==='A'));
  await page.evaluate(()=>{state.workspaces=[{id:'A',name:'商品管理服务',root:'/project/A',execution_mode:'safe'}];});
  await page.evaluate(()=>openWorkspace('A'));
  await page.evaluate(()=>switchPanel('terminal'));
  await page.locator('#command').fill('python3 -m unittest discover -v');
  await page.locator('#run-command').click();
  await page.locator('#app-dialog').waitFor({state:'visible'});
  assert.equal(await page.locator('#app-dialog-title').textContent(),'执行这条命令？');
  assert.equal(await page.locator('#app-dialog-detail').textContent(),'python3 -m unittest discover -v');
  assert.equal(await page.evaluate(()=>document.activeElement.id),'app-dialog-cancel');
  await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement.id),'app-dialog-confirm');
  await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement.id),'app-dialog-close');
  await page.locator('#app-dialog-cancel').focus();
  await page.locator('#app-dialog').evaluate(async el=>{await Promise.all(el.getAnimations().map(a=>a.finished));});
  await page.screenshot({path:'/tmp/codespider-dialog-desktop.png'});
  await page.setViewportSize({width:390,height:844});
  const box=await page.locator('#app-dialog').boundingBox();assert.ok(box.x>=0&&box.x+box.width<=390);
  await page.screenshot({path:'/tmp/codespider-dialog-mobile.png'});
  await page.keyboard.press('Escape');await page.locator('#app-dialog').waitFor({state:'hidden'});
  assert.equal(writes.filter(x=>x.body.action==='run').length,1);
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('#run-command').click();
  await page.locator('#app-dialog').waitFor({state:'visible'});
  // Approved execution uses exactly the command the user reviewed.
  await page.evaluate(()=>document.getElementById('command').value='different command');
  await page.locator('#app-dialog-confirm').click();
  await page.waitForFunction(()=>document.getElementById('command-output').textContent.includes('completed'));
  const approved=writes.filter(x=>x.body.action==='run'&&x.body.approval?.approved);
  assert.equal(approved.length,1);assert.equal(approved[0].body.arguments.command,'python3 -m unittest discover -v');
  // Escape/backdrop/close resolve as cancellation, queued dialogs retain their own data.
  await page.evaluate(()=>{window.first=requestDialog({title:'First',message:'<img src=x onerror=alert(1)>'});window.second=requestDialog({title:'Second'});});
  assert.equal(await page.locator('#app-dialog-message img').count(),0);
  await page.locator('#app-dialog-confirm').click();
  await page.waitForFunction(()=>document.getElementById('app-dialog-title').textContent==='Second');
  await page.locator('#app-dialog-close').click();
  assert.deepEqual(await page.evaluate(async()=>[await window.first,await window.second]),[true,null]);
  await page.evaluate(()=>{window.backdropResult=requestDialog({title:'Backdrop'});});
  await page.mouse.click(5,5);assert.equal(await page.evaluate(()=>window.backdropResult),null);
  // Model assignment uses an inline input with validation, never native prompt().
  await page.evaluate(()=>{window.assignment=assignModel('model-a',[{id:'bob',username:'bob',role:'USER'}]);});
  assert.equal(await page.locator('#app-dialog-input').inputValue(),'bob');
  await page.locator('#app-dialog-input').fill('unknown');await page.locator('#app-dialog-confirm').click();
  assert.ok((await page.locator('#app-dialog-error').textContent()).includes('未找到'));
  await page.locator('#app-dialog-input').fill('bob');await page.keyboard.press('Enter');
  await page.evaluate(()=>window.assignment);
  assert.equal(writes.filter(x=>x.path.endsWith('/assign')).length,1);
  // Destructive actions use the danger treatment and cancellation never sends a write.
  await page.evaluate(()=>{window.keyClear=document.getElementById('clear-api-key').onclick();});
  assert.ok((await page.locator('#app-dialog').getAttribute('class')).includes('dialog-danger'));
  await page.keyboard.press('Escape');await page.evaluate(()=>window.keyClear);
  assert.equal(writes.filter(x=>x.path==='/api/settings').length,0);
  // Switching projects while an actual command is pending cannot approve the old request.
  const approvedBefore=writes.filter(x=>x.body.action==='run'&&x.body.approval?.approved).length;
  await page.evaluate(()=>{window.pendingCommand=runCommand(false,state.currentWorkspace,'python3 --version');});
  await page.locator('#app-dialog').waitFor({state:'visible'});
  await page.evaluate(async()=>{state.workspaces.push({id:'B',name:'Other project',root:'/project/B'});await openWorkspace('B');});
  await page.evaluate(()=>window.pendingCommand);
  assert.equal(writes.filter(x=>x.body.action==='run'&&x.body.approval?.approved).length,approvedBefore);
  // Deletion needs two confirmations; cancel/mismatch/switch never sends it.
  const deletions=()=>writes.filter(x=>x.path.endsWith('/delete'));
  await page.evaluate(()=>openWorkspace('A'));
  await page.evaluate(()=>switchPanel('settings'));
  await page.locator('#delete-project').click();
  await page.locator('#app-dialog-cancel').click();
  assert.equal(deletions().length,0);
  await page.locator('#delete-project').click();
  await page.locator('#app-dialog-confirm').click();
  await page.waitForFunction(()=>document.getElementById('app-dialog-title').textContent==='再次确认删除');
  await page.locator('#app-dialog-input').fill('wrong project');
  await page.locator('#app-dialog-confirm').click();
  assert.ok((await page.locator('#app-dialog-error').textContent()).includes('不一致'));
  assert.equal(deletions().length,0);
  await page.locator('#app-dialog-cancel').click();
  await page.locator('#delete-project').click();
  await page.locator('#app-dialog-confirm').click();
  await page.waitForFunction(()=>document.getElementById('app-dialog-title').textContent==='再次确认删除');
  await page.evaluate(()=>openWorkspace('B'));
  assert.equal(await page.locator('#app-dialog').isVisible(),false);
  assert.equal(deletions().length,0);
  await page.evaluate(()=>openWorkspace('A'));
  await page.evaluate(()=>switchPanel('settings'));
  await page.locator('#delete-project').click();
  await page.locator('#app-dialog-confirm').click();
  await page.waitForFunction(()=>document.getElementById('app-dialog-title').textContent==='再次确认删除');
  await page.locator('#app-dialog-input').fill('商品管理服务');
  await page.locator('#app-dialog').evaluate(async el=>{await Promise.all(el.getAnimations().map(a=>a.finished));});
  await page.screenshot({path:'/tmp/codespider-delete-confirmation.png'});
  await page.locator('#app-dialog-confirm').click();
  await page.waitForFunction(()=>state.currentWorkspace===null);
  assert.equal(deletions().length,1);
  assert.deepEqual(deletions()[0].body,{confirmed:true,confirm_name:'商品管理服务'});
  assert.deepEqual(await page.evaluate(()=>state.workspaces.map(w=>w.id)),['B']);
  assert.equal(await page.evaluate(()=>state.sessions.has('A')),false);
  // An account change cancels visible and queued approvals; no request is replayed.
  await page.evaluate(()=>{window.one=requestDialog({title:'Old account'});window.two=requestDialog({title:'Queued'});resetConversations();});
  assert.deepEqual(await page.evaluate(async()=>[await window.one,await window.two]),[null,null]);
  assert.equal(await page.locator('#app-dialog').isVisible(),false);
  assert.deepEqual(native,[]);assert.deepEqual(errors,[]);
  console.log('PASS: browser dialog layout, focus trap, Escape/backdrop/close, explicit approval, captured command, queue, input validation, account cancellation, two-step project deletion and no native dialogs');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
