// Real browser + production assets, controlled API responses (no model calls).
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs=require('node:fs'),http=require('node:http'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../frontend');
const server=http.createServer((req,res)=>{const file=path.join(root,req.url==='/'?'index.html':req.url);if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}res.setHeader('Content-Type',file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':'text/html');res.end(fs.readFileSync(file));});
const timing={started_at:'2026-10-13T10:00:00Z',response_finished_at:'2026-10-13T10:00:03Z',finished_at:'2026-10-13T10:00:03Z',generation_duration_ms:3000,duration_ms:3000};
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000},timezoneId:'Asia/Shanghai'}),errors=[];
  let releaseFree,releaseProject,history=[];
  let projectRequestedResolve;
  const projectRequested=new Promise(resolve=>projectRequestedResolve=resolve);
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/**',async route=>{
   const url=new URL(route.request().url());let data={items:[]},status=200;
   if(url.pathname==='/api/health')data={ok:true};
   if(url.pathname==='/api/auth/me')data={user:{id:'alice',username:'alice',role:'USER',balance:500},models:[],usage:{total_calls:0}};
   if(url.pathname==='/api/workspaces')data={items:[{id:'A',name:'计时演示',root:'/project/A'}]};
   if(url.pathname==='/api/tools/call')data={ok:true,data:{items:[]}};
   if(url.pathname==='/api/conversations')data={items:url.searchParams.get('workspace_id')===''?history:[]};
   if(url.pathname==='/api/conversations/free')({data,status}=await new Promise(resolve=>releaseFree=resolve));
   if(url.pathname==='/api/tasks')({data,status}=await new Promise(resolve=>{releaseProject=resolve;projectRequestedResolve();}));
   await route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.goto(process.env.TIMING_TEST_URL || `http://127.0.0.1:${server.address().port}`);
  await page.waitForFunction(()=>state.workspaces.some(w=>w.id==='A'));
  await page.evaluate(async()=>{setView('free-chat');await loadConversation('');});
  await page.locator('#free-input').fill('请解释如何拆分一个订单模块');await page.locator('#free-send').click();
  const pending=page.locator('#free-messages>.agent').last();
  await pending.locator('.activity-dots i').first().waitFor();
  assert.equal(await pending.locator('.activity-dots i').first().evaluate(el=>getComputedStyle(el).animationName),'thinking-bounce');
  assert.ok((await page.locator('#free-messages>.user .message-meta time').last().textContent()).includes(':'));
  const initial=await pending.locator('.message-duration').textContent();
  await page.waitForFunction(initial=>document.querySelector('#free-messages>.agent:last-child .message-duration').textContent!==initial,initial);
  await page.screenshot({path:'/tmp/codespider-thinking-desktop.png'});
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:'/tmp/codespider-thinking-mobile.png'});
  const bounds=await pending.boundingBox();assert.ok(bounds.x>=0&&bounds.x+bounds.width<=391);
  await page.emulateMedia({reducedMotion:'reduce'});
  assert.equal(await pending.locator('.activity-dots i').first().evaluate(el=>getComputedStyle(el).animationName),'none');
  await page.emulateMedia({reducedMotion:'no-preference'});
  releaseFree({status:201,data:{id:'free1',reply:'模块拆分说明',timing}});
  await page.waitForFunction(()=>document.querySelector('#free-messages>.agent:last-child .message-bubble').textContent==='模块拆分说明');
  assert.equal(await pending.locator('.activity-dots').count(),0);
  assert.equal(await pending.locator('.message-duration').textContent(),'耗时 3 秒');
  assert.equal(await pending.locator('.message-meta time').getAttribute('datetime'),'2026-10-13T10:00:03.000Z');
  assert.equal(await pending.locator('.message-meta').getAttribute('data-live-start'),'');
  // Failures also stop the indicator and keep a duration.
  await page.locator('#free-input').fill('失败示例');await page.locator('#free-send').click();
  await page.locator('#free-messages .activity-dots').waitFor();
  await page.waitForFunction(()=>document.querySelector('#free-messages>.agent:last-child .message-duration').textContent.includes('秒'));
  releaseFree({status:400,data:{error:'模型暂时不可用'}});
  await page.locator('#free-messages [role="alert"]').waitFor();
  assert.equal(await page.locator('#free-messages .activity-dots').count(),0);
  assert.equal(await page.locator('#free-messages>.agent').last().locator('.message-meta').getAttribute('data-live-start'),'');
  // Project execution: live indicator, then one collapsed conclusion with total duration.
  await page.setViewportSize({width:1440,height:1000});await page.evaluate(()=>openWorkspace('A'));
  await page.locator('#project-input').fill('实现订单模块');await page.locator('#project-send').click();
  await page.locator('#project-messages .activity-dots').waitFor();
  const task={id:'task1',workspace_id:'A',status:'created',summary:'方案已生成',plan:[],patches:[],timing:{...timing,finished_at:'',duration_ms:null}};
  await projectRequested;
  releaseProject({status:201,data:task});
  await page.locator('#project-messages .approve-inline').waitFor();
  assert.equal(await page.locator('#project-messages>.agent .message-duration').textContent(),'生成耗时 3 秒');
  await page.evaluate(task=>{
    const message=projectSession('A').messages.find(m=>m.dataset.taskId===task.id);
    const controls=appendAgentTurn({...task,status:'executing'},message);
    window.testRun={taskId:task.id,workspaceId:'A',task:{...task,status:'executing'},...controls};
  },task);
  assert.equal(await page.locator('#project-messages .activity-dots').count(),1);
  for(const status of ['succeeded','failed','cancelled']){
    await page.evaluate(status=>{
      testRun.terminalSeen=false;
      renderTaskEvent({type:'task.'+status,created_at:'2026-10-13T10:01:10Z',payload:{message:'本轮结束'}},testRun);
      finishTaskView(testRun,status);
    },status);
    const group=page.locator('#project-messages>.completed-turn');
    assert.equal(await group.locator(':scope>.message-meta .message-duration').textContent(),'本轮耗时 1 分 10 秒');
    assert.equal(await group.locator('details').first().getAttribute('open'),null);
    assert.equal(await group.locator('.activity-dots').count(),0);
  }
  // Reload uses durable timestamps; old records without finish dates never keep ticking.
  history=[{id:'saved',goal:'昨日消息',reply:'昨日回复',status:'completed',created_at:timing.started_at,timing},
    {id:'legacy',goal:'旧版消息',reply:'旧版回复',status:'completed',created_at:timing.started_at},
    {id:'interrupted',goal:'中断请求',error:'服务已重启',status:'interrupted',created_at:timing.started_at}];
  await page.evaluate(async()=>{resetConversations();state.user={id:'alice'};setView('free-chat');await loadConversation('');});
  assert.equal(await page.locator('#free-messages>.agent .message-duration').first().textContent(),'耗时 3 秒');
  assert.equal(await page.locator('#free-messages>.agent .message-duration').nth(1).textContent(),'耗时未记录');
  assert.equal(await page.locator('#free-messages .activity-dots').count(),0);
  assert.equal(await page.locator('#free-messages [data-live-start]:not([data-live-start=""])').count(),0);
  assert.deepEqual(errors,[]);
  console.log('PASS: animated waiting, live clock, reduced motion, mobile layout, free/project success/failure/cancellation, persisted times and legacy unknown duration');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
