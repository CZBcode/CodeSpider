// PLAYWRIGHT_MODULE=/path/to/playwright CHROME_PATH=/path/to/chrome node tests/frontend_turns.cjs
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs=require('node:fs'),http=require('node:http'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../frontend');
const server=http.createServer((req,res)=>{const file=path.join(root,req.url==='/'?'index.html':req.url);if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}res.setHeader('Content-Type',file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':'text/html');res.end(fs.readFileSync(file));});
const task=(id,status)=>({id,workspace_id:'A',status,summary:'准备实现日期转换工具类与测试。',patches:[{path:'DateUtils.java',operation:'create',replacement:'class DateUtils {}'}],plan:[],thinking:[]});
const events=(id,status)=>[
 {sequence:1,type:'tool.call',payload:{request:{tool:'code',action:'index',arguments:{}}}},
 {sequence:2,type:'file.changed',payload:{path:'DateUtils.java'}},
 {sequence:3,type:'tool.retry',payload:{message:'正在重试构建',details:'临时网络错误'}},
 {sequence:4,type:'process.output',payload:{command:'mvn -q test',exit_code:status==='succeeded'?0:1,output:'完整构建输出 <keep literal>\ncompiler output'}},
 {sequence:5,type:`task.${status}`,payload:{message:status==='succeeded'?'已生成日期转换工具类，验证通过。':status==='failed'?'文件已写入，但 Maven 测试未通过。请展开执行过程查看错误后重试。':'任务已取消，已写入的文件予以保留。',details:status==='failed'?'raw failure detail':''}}
];
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],writes=[];let history=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/**',async route=>{
   const url=new URL(route.request().url()),body=route.request().postDataJSON();if(body)writes.push({path:url.pathname,body});
   let data={items:[]};
   if(url.pathname==='/api/health')data={ok:true};
   if(url.pathname==='/api/auth/me')data={user:{id:'alice',username:'alice',role:'USER',balance:500},models:[],usage:{total_calls:0}};
   if(url.pathname==='/api/conversations')data={items:url.searchParams.get('workspace_id')==='A'?history:[]};
   if(url.pathname==='/api/tools/call')data={ok:true,data:{items:[]}};
   await route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.goto(process.env.TURN_TEST_URL || `http://127.0.0.1:${server.address().port}`);
  await page.waitForFunction(()=>state.user?.id==='alice');
  await page.evaluate(async()=>{state.workspaces=[{id:'A',name:'日期转换工程',root:'/project/A'},{id:'B',name:'其他工程',root:'/project/B'}];await openWorkspace('A');});
  for(const status of ['succeeded','failed','cancelled']){
   const id='task-'+status;
   await page.evaluate(({task,events})=>{
    appendMessage('user','实现日期转换工具类：'+task.id,'A');
    const controls=appendAgentTurn({...task,status:'created'});
    window.currentRun={taskId:task.id,workspaceId:'A',task,...controls};
    appendMessage('agent','任务已批准，正在执行。','A',task.id);
    for(const event of events.slice(0,-1))renderTaskEvent(event,currentRun);
   },{task:task(id,status),events:events(id,status)});
   assert.equal(await page.locator(`#project-messages>.completed-turn[data-task-id="${id}"]`).count(),0);
   // Another turn is still pending and must remain actionable.
   if(status==='failed')await page.evaluate(()=>appendAgentTurn({id:'pending',workspace_id:'A',status:'created',summary:'另一个待审批方案',patches:[]}));
   await page.evaluate(({event,status})=>{renderTaskEvent(event,currentRun);finishTaskView(currentRun,status);},{event:events(id,status).at(-1),status});
   const group=page.locator(`#project-messages>.completed-turn[data-task-id="${id}"]`);
   assert.equal(await group.count(),1);
   assert.equal(await group.locator(':scope > .turn-process').getAttribute('open'),null);
   assert.equal(await group.locator(':scope > .turn-conclusion').count(),1);
   assert.equal(await group.locator('.turn-process-body').isVisible(),false);
   assert.equal(await group.locator('.approve-inline').isVisible(),false);
   assert.equal(await group.locator('.turn-conclusion').textContent(),events(id,status).at(-1).payload.message);
   assert.equal(await page.locator(`#project-messages>.message[data-task-id="${id}"]`).count(),1);
   await group.locator(':scope > details > summary').click();
   assert.ok((await group.locator('.turn-process-body').innerText()).includes('已写入文件：DateUtils.java'));
   await group.locator('.execution-card > summary').first().click();
   assert.ok((await group.innerText()).includes('完整构建输出 <keep literal>'));
   await page.evaluate(()=>finishTaskView(currentRun,currentRun.task.status));
   assert.equal(await group.locator(':scope > .turn-process').getAttribute('open'),'');
   await group.locator(':scope > details > summary').click();
   if(status==='failed')assert.equal(await page.locator('#project-messages>.message[data-task-id="pending"] .approve-inline').isVisible(),true);
  }
  // Switching projects retains grouping and never leaks its contents to B.
  await page.evaluate(()=>openWorkspace('B'));assert.equal(await page.locator('#project-messages .completed-turn').count(),0);
  await page.evaluate(()=>openWorkspace('A'));assert.equal(await page.locator('#project-messages>.completed-turn').count(),3);
  // Restore old saved events in a fresh session; missing terminal events also get a final summary.
  history=['succeeded','failed','cancelled'].map(status=>({id:'turn-'+status,goal:'历史需求 '+status,task:task('saved-'+status,status),events:events('saved-'+status,status)}));
  history.push({id:'old-error',goal:'缺少终止事件的历史任务',task:{...task('old-error','failed'),error:'历史构建失败'},events:events('old-error','failed').slice(0,-1)});
  await page.evaluate(async()=>{resetConversations();state.workspaces=[{id:'A',name:'日期转换工程',root:'/project/A'}];await openWorkspace('A');});
  assert.equal(await page.locator('#project-messages>.completed-turn').count(),4);
  assert.equal(await page.locator('#project-messages>.completed-turn>.turn-process[open]').count(),0);
  assert.equal(await page.locator('#project-messages>.completed-turn>.turn-conclusion:visible').count(),4);
  await page.evaluate(()=>loadConversation('A',true));
  assert.equal(await page.locator('#project-messages>.completed-turn').count(),4);
  assert.equal(writes.filter(x=>x.path.endsWith('/approve')).length,0);
  await page.screenshot({path:'/tmp/codespider-turns-desktop.png'});
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:'/tmp/codespider-turns-mobile.png'});
  assert.deepEqual(errors,[]);
  console.log('PASS: success/failure/cancellation collapse whole turns, one conclusion, expandable complete history, pending-task isolation, project switching, reload and legacy missing terminal events');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
