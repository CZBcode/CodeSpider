const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs=require('node:fs'),http=require('node:http'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../frontend');
const server=http.createServer((req,res)=>{const file=path.join(root,req.url==='/'?'index.html':req.url);res.setHeader('Content-Type',file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':'text/html');res.end(fs.readFileSync(file));});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],writes=[];
  let ready=false,status='running',chatStatus='running',restoring=false;
  const intent={status:'ready',summary:'我会增加删除入口和二次确认，保留最近15轮对话并归档更早内容。',goals:['增加删除功能'],constraints:['最近15轮原文','<img src=x onerror=alert(1)>'],steps:['检查删除边界','实现并测试']};
  const task={id:'task-intent',workspace_id:'A',conversation_turn_id:'turn-project',status:'created',summary:'方案已生成',plan:[],patches:[],intent};
  const job=(chat=false)=>({id:chat?'gen_chat':'gen_project',kind:chat?'chat':'project',turn_id:chat?'turn-chat':'turn-project',workspace_id:chat?'':'A',goal:'需求',created_at:new Date().toISOString(),status:chat?chatStatus:status,
   progress:{stage:ready?'正在继续处理':'正在理解你的需求…',...(ready?{intent}:{})},
   ...(chat?{reply:'最终回答',intent}:status==='completed'?{task}:{}),error:'当前批次暂时失败'});
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/**',async route=>{
   const req=route.request(),url=new URL(req.url()),body=req.postDataJSON();if(body)writes.push({path:url.pathname,body});
   let data={items:[]},code=200;
   if(url.pathname==='/api/health')data={ok:true};
   if(url.pathname==='/api/auth/me')data={user:{id:'alice',username:'alice',role:'USER',balance:500},models:[],usage:{total_calls:0}};
   if(url.pathname==='/api/workspaces')data={items:[{id:'A',name:'用户系统',root:'/project/A'}]};
   if(url.pathname==='/api/tools/call')data={ok:true,data:{items:[]}};
   if(url.pathname==='/api/conversations'&&restoring&&url.searchParams.get('workspace_id')==='A')data={items:[{id:'turn-project',generation_id:'gen_project',goal:'需求',status:'generating',intent}],generations:[job()]};
   if(url.pathname.endsWith('/recommendation'))data={plugin:{id:'plugin.python'},requires_choice:false};
   if(url.pathname==='/api/tasks'){data=job();code=202;}
   if(url.pathname==='/api/conversations/free'){data=job(true);code=202;}
   if(url.pathname==='/api/generations/gen_project')data=job();
   if(url.pathname==='/api/generations/gen_chat')data=job(true);
   await route.fulfill({status:code,contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.goto(process.env.INTENT_TEST_URL || `http://127.0.0.1:${server.address().port}`);
  await page.waitForFunction(()=>state.workspaces.length===1);
  await page.evaluate(()=>openWorkspace('A'));
  await page.locator('#project-input').fill('增加项目删除与二次确认，最近15轮对话保留原文，更早对话归档。');await page.locator('#project-send').click();
  await page.waitForFunction(()=>document.querySelector('.thinking-hint')?.textContent.includes('正在理解'));
  assert.equal(writes.find(x=>x.path==='/api/tasks').body.intent_preview,true);
  ready=true;
  await page.locator('#project-messages .intent-summary').waitFor();
  assert.equal(await page.locator('#project-messages .intent-summary').textContent(),intent.summary);
  assert.equal(await page.locator('#project-messages .approve-inline').count(),0);
  await page.locator('.intent-expand>summary').click();
  assert.equal(await page.locator('.intent-brief img').count(),0);
  assert.ok((await page.locator('.intent-brief').innerText()).includes('<img src=x onerror=alert(1)>'));
  await page.screenshot({path:'/tmp/codespider-intent-desktop.png'});
  restoring=true;
  await page.evaluate(()=>loadConversation('A',true));
  assert.equal(await page.locator('#project-messages .intent-summary').count(),1);
  assert.equal(await page.locator('#project-messages .intent-expand').getAttribute('open'),'');
  status='completed';restoring=false;
  await page.locator('.approve-inline').waitFor();
  assert.equal(await page.locator('.intent-collapsed').getAttribute('open'),null);
  await page.evaluate(task=>{
   const message=projectSession('A').messages.find(m=>m.dataset.taskId===task.id);
   const controls=appendAgentTurn({...task,status:'failed'},message);
   finishTaskView({taskId:task.id,workspaceId:'A',task:{...task,status:'failed'},...controls},'failed');
  },task);
  assert.equal(await page.locator('.completed-turn>.turn-process').getAttribute('open'),null);
  await page.evaluate(()=>setView('free-chat'));
  await page.locator('#free-input').fill('先解释一下设计方案');await page.locator('#free-send').click();
  await page.locator('#free-messages .intent-summary').waitFor();
  assert.equal(writes.find(x=>x.path==='/api/conversations/free').body.intent_preview,true);
  chatStatus='failed';
  await page.locator('#free-messages .resume-generation').waitFor();
  assert.equal(await page.locator('#free-messages .intent-collapsed').getAttribute('open'),null);
  chatStatus='completed';
  await page.evaluate(job=>watchGeneration(job,projectSession('').messages.at(-1),''),job(true));
  assert.equal(await page.locator('#free-messages .message-bubble').last().textContent(),'最终回答');
  assert.equal(await page.locator('#free-messages .intent-collapsed').getAttribute('open'),null);
  await page.setViewportSize({width:390,height:844});
  await page.locator('#free-messages .intent-collapsed>summary').click();
  const bounds=await page.locator('#free-messages .intent-brief').boundingBox();assert.ok(bounds.x>=0&&bounds.x+bounds.width<=391);
  assert.deepEqual(errors,[]);
  console.log('PASS: intent precedes results, durable history binding without duplicates, escaped details, success/failure collapse, free chat and mobile layout');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
