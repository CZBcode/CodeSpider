const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs=require('node:fs'),http=require('node:http'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../frontend');
const server=http.createServer((req,res)=>{const file=path.join(root,req.url==='/'?'index.html':req.url);if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}res.setHeader('Content-Type',file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':'text/html');res.end(fs.readFileSync(file));});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],writes=[];
  let status='running',historyJobs=[],ambiguous=false;
  const task={id:'task-code',workspace_id:'A',conversation_turn_id:'turn-code',status:'created',summary:'三个模块已生成，等待审批',plan:[],patches:[]};
  const job=()=>({id:'gen_code',workspace_id:'A',goal:'生成 Python 项目',created_at:new Date().toISOString(),status,
    progress:{stage:'正在生成 service.py',completed:1,total:3},error:status==='failed'?'当前批次超时，已保存进度。':'',...(status==='completed'?{task}:{})});
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/**',async route=>{
   const request=route.request(),url=new URL(request.url()),body=request.postDataJSON();if(body)writes.push({path:url.pathname,body});
   let data={items:[]},code=200;
   if(url.pathname==='/api/health')data={ok:true};
   if(url.pathname==='/api/auth/me')data={user:{id:'alice',username:'alice',role:'USER',balance:500},models:[],usage:{total_calls:0}};
   if(url.pathname==='/api/workspaces')data={items:[{id:'A',name:'生成测试',root:'/project/A'},{id:'B',name:'另一个项目',root:'/project/B'}]};
   if(url.pathname==='/api/tools/call')data={ok:true,data:{items:[]}};
   if(url.pathname==='/api/conversations')data={items:[],generations:url.searchParams.get('workspace_id')==='A'?historyJobs:[]};
   if(url.pathname.endsWith('/recommendation'))data={plugin:{id:'plugin.python',name:'Python 工程'},recommendation:'推荐 Python 工程，适合自动化与数据处理。',requires_choice:ambiguous,alternatives:[{id:'plugin.python',name:'Python 工程',enabled:true},{id:'plugin.vue',name:'Vue 工程',enabled:true}]};
   if(url.pathname==='/api/tasks'){data=job();code=202;}
   if(url.pathname==='/api/generations/gen_code')data=job();
   if(url.pathname.endsWith('/resume')){status='completed';data=job();code=202;}
   await route.fulfill({status:code,contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.goto(process.env.LARGE_TEST_URL || `http://127.0.0.1:${server.address().port}`);
  await page.waitForFunction(()=>state.workspaces.length===2);
  assert.equal(await page.locator('#context-artifacts').count(),0);
  assert.equal(await page.locator('#context-panel').getByText('相关产物').count(),0);
  assert.equal(await page.locator('#project-nav [data-panel="explorer"]').count(),1);
  await page.evaluate(()=>openWorkspace('A'));
  await page.locator('#project-input').fill('生成 Python 项目');await page.locator('#project-send').click();
  await page.waitForFunction(()=>document.getElementById('project-messages').textContent.includes('1/3 个文件'));
  assert.equal(writes.find(w=>w.path==='/api/tasks').body.async_generation,true);
  assert.equal(writes.find(w=>w.path==='/api/tasks').body.plugin_id,'plugin.python');
  await page.screenshot({path:'/tmp/codespider-batch-progress.png'});
  await page.evaluate(()=>openWorkspace('B'));status='failed';
  await page.waitForFunction(()=>projectSession('A').messages.some(m=>m.textContent.includes('继续生成')));
  assert.equal(await page.locator('#project-messages .resume-generation').count(),0);
  await page.evaluate(()=>openWorkspace('A'));await page.locator('.resume-generation').click();
  await page.locator('#project-messages .approve-inline').waitFor();
  assert.equal(writes.filter(w=>w.path.endsWith('/resume')).length,1);
  assert.equal(writes.filter(w=>w.path==='/api/tasks').length,1);
  assert.equal(await page.locator('#project-messages .activity-dots').count(),0);
  // Restore an interrupted job after refresh without reissuing a model request.
  historyJobs=[{...job(),status:'interrupted',task:undefined,error:'服务重启，已保存批次可继续。',draft:{files:26,repair_pending:true,repair_round:3}}];
  await page.evaluate(async()=>{resetConversations();state.workspaces=[{id:'A',name:'生成测试',root:'/project/A'}];await openWorkspace('A');});
  await page.locator('#project-messages .resume-generation').waitFor();
  assert.equal(await page.locator('#project-messages .resume-generation').textContent(),'继续修复');
  assert.ok((await page.locator('#project-messages').textContent()).includes('已保留 26 个文件'));
  assert.equal(writes.filter(w=>w.path==='/api/tasks').length,1);
  // Ambiguous stacks become a recommendation dialog; cancellation does not generate.
  ambiguous=true;
  await page.locator('#project-input').fill('Python 或 Vue 都可以');await page.locator('#project-send').click();
  await page.locator('#app-dialog').waitFor();
  assert.equal(await page.locator('#app-dialog-title').textContent(),'确认本项目的技术栈');
  await page.locator('#app-dialog-cancel').click();
  assert.equal(writes.filter(w=>w.path==='/api/tasks').length,1);
  await page.locator('#project-input').fill('Python 或 Vue 都可以');await page.locator('#project-send').click();
  await page.locator('#app-dialog').waitFor();await page.locator('#app-dialog-input').fill('Vue 工程');
  await page.locator('#app-dialog-confirm').click();
  await page.waitForFunction(()=>document.querySelectorAll('#project-messages .approve-inline').length>0);
  assert.equal(writes.filter(w=>w.path==='/api/tasks').at(-1).body.plugin_id,'plugin.vue');
  assert.deepEqual(errors,[]);
  console.log('PASS: async generation progress, account/project binding, resume, reload, stack recommendation/choice/cancel and redundant links removed');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
