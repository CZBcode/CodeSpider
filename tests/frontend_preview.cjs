// Real npm/Vite build, real HTTP tools and browser iframe; no mocked build/API.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {spawn} = require('node:child_process');
const readline = require('node:readline');
const assert = require('node:assert/strict');
(async () => {
  const child = spawn('python3', ['-m', 'tests.preview_fixture'], {cwd:require('node:path').resolve(__dirname,'..'), env:process.env});
  let errors = ''; child.stderr.on('data', data => errors += data);
  const fixture = await new Promise((resolve,reject) => {
    const lines = readline.createInterface({input:child.stdout});
    lines.once('line', line => {resolve(JSON.parse(line));lines.close();});
    child.once('exit', code => reject(new Error(`fixture exit ${code}: ${errors}`)));
  });
  const browser = await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const pageErrors=[]; page.on('pageerror', error => pageErrors.push(error.message));
    await page.goto(fixture.url);
    await page.waitForFunction(() => state.workspaces.length === 2);
    await page.evaluate(id => openWorkspace(id), fixture.workspace);
    await page.locator('[data-panel="live-preview"]').click();
    await page.locator('#preview-build').click();
    await page.locator('#app-dialog-confirm').click();
    await page.waitForFunction(() => /最新预览已发布|失败/.test(document.querySelector('#live-preview-status').textContent), null, {timeout:360000});
    assert.ok((await page.locator('#live-preview-status').innerText()).includes('最新预览已发布'), await page.locator('#live-preview-log').innerText());
    let frame = page.frameLocator('#live-preview-frame');
    await frame.getByRole('heading',{name:'First preview'}).waitFor();
    await frame.getByRole('button',{name:'Count 0'}).click();
    assert.equal(await frame.getByRole('button').innerText(),'Count 1');
    const initial = await page.locator('#live-preview-frame').getAttribute('src');
    const actualFrame = page.frames().find(f => f.url().includes('/preview/'));
    const isolation = await actualFrame.evaluate(async () => {
      let parentBlocked=false,storageBlocked=false,apiBlocked=false;
      try {void parent.document.body;} catch {parentBlocked=true;}
      try {localStorage.setItem('escape','bad');} catch {storageBlocked=true;}
      try {await fetch('/api/auth/me');} catch {apiBlocked=true;}
      return {parentBlocked,storageBlocked,apiBlocked};
    });
    assert.deepEqual(isolation,{parentBlocked:true,storageBlocked:true,apiBlocked:true});
    const update = await (await page.request.post(fixture.url+'/fixture/update',{data:{}})).json();
    await page.waitForFunction(async id => (await (await fetch('/api/tasks/'+id)).json()).status==='succeeded',update.id,{timeout:180000});
    await frame.getByRole('heading',{name:'Updated preview'}).waitFor({timeout:15000});
    const latest = await page.locator('#live-preview-frame').getAttribute('src'); assert.notEqual(initial,latest);
    await page.screenshot({path:'/tmp/codespider-live-preview.png'});
    await page.reload(); await page.waitForFunction(()=>state.workspaces.length===2);
    await page.evaluate(id=>openWorkspace(id),fixture.workspace); await page.locator('[data-panel="live-preview"]').click();
    await frame.getByRole('heading',{name:'Updated preview'}).waitFor();
    assert.equal(await page.locator('#live-preview-frame').getAttribute('src'),latest);
    const broken=await (await page.request.post(fixture.url+'/fixture/update',{data:{broken:true}})).json();
    await page.waitForFunction(async id => (await (await fetch('/api/tasks/'+id)).json()).status==='failed',broken.id,{timeout:180000});
    await page.waitForFunction(()=>document.querySelector('#live-preview-status').textContent.includes('构建失败'));
    assert.equal(await page.locator('#live-preview-frame').getAttribute('src'),latest);
    assert.equal(await page.locator('#live-preview-details').getAttribute('open'),null);
    await frame.getByRole('heading',{name:'Updated preview'}).waitFor();
    await page.evaluate(id=>openWorkspace(id),fixture.other);
    assert.equal(await page.locator('#live-preview-frame').getAttribute('src'),null);
    await page.locator('[data-panel="live-preview"]').click();
    await page.waitForFunction(()=>document.querySelector('#preview-build').disabled);
    await page.evaluate(()=>resetConversations());
    assert.equal(await page.locator('#live-preview-frame').getAttribute('src'),null);
    assert.deepEqual(pageErrors,[]);
    console.log('PASS: real Vue SFC build, scripts/CSS, interactive preview, approved-task automatic publish, live update, reload persistence, failed-build last-good preview, collapsed logs, account/project cleanup and browser sandbox isolation');
  } finally {await browser.close();child.kill('SIGTERM');}
})().catch(error=>{console.error(error);process.exitCode=1;});
