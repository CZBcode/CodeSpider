// Real generated projects only; this runner never calls a model or accesses production.
// VISUAL_CASES_DIR=/path/to/cases VISUAL_OUTPUT_DIR=/path/to/report node tests/frontend_prototype_visual.cjs
// Optional AXE_SOURCE=/path/to/axe.min.js adds accessibility diagnostics (not certification).
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {spawn}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path'),readline=require('node:readline'),assert=require('node:assert/strict');

(async()=>{
 const source=process.env.VISUAL_CASES_DIR;
 assert.ok(source,'Set VISUAL_CASES_DIR to the generated case directories');
 const output=path.resolve(process.env.VISUAL_OUTPUT_DIR||'/tmp/codespider-visual-report');
 fs.mkdirSync(output,{recursive:true});
 const selected=(process.env.VISUAL_CASES||'').split(',').filter(Boolean);
 const child=spawn('python3',['-m','tests.prototype_visual_fixture',source,...selected],{cwd:path.resolve(__dirname,'..'),env:process.env});
 let logs='',browser;
 child.stderr.on('data',data=>logs+=data);
 try{
  const fixture=await new Promise((resolve,reject)=>{
   const lines=readline.createInterface({input:child.stdout});
   const timer=setTimeout(()=>reject(new Error('Fixture startup timed out: '+logs)),120000);
   lines.once('line',line=>{clearTimeout(timer);lines.close();try{resolve(JSON.parse(line));}catch(error){reject(error);}});
   child.once('exit',code=>{clearTimeout(timer);reject(new Error(`Fixture exited ${code}: ${logs}`));});
  });
  browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
  const report=[];
  for(const [name,url] of Object.entries(fixture.urls)){
   for(const width of [1440,768,390]){
    const page=await browser.newPage({viewport:{width,height:1000},reducedMotion:'reduce'}),errors=[],external=[],failed=[];
    page.on('pageerror',error=>errors.push(error.message));
    page.on('request',request=>{if(!request.url().startsWith(fixture.base)&&!request.url().startsWith('data:'))external.push(request.url());});
    page.on('response',response=>{if(response.status()>=400)failed.push({url:response.url(),status:response.status()});});
    await page.goto(fixture.base+url,{waitUntil:'networkidle'});
    await page.evaluate(()=>document.fonts.ready);
    const layout=await page.evaluate(()=>({
     viewport:innerWidth,scrollWidth:document.documentElement.scrollWidth,
     title:document.title,headings:[...document.querySelectorAll('h1,h2')].map(e=>e.textContent.trim()),
     bodyFont:getComputedStyle(document.body).fontSize,
     visibleControls:[...document.querySelectorAll('button,a,input,select,textarea')].filter(e=>e.getClientRects().length).length
    }));
    await page.screenshot({path:path.join(output,`${name}-${width}.png`),fullPage:true});
    await page.keyboard.press('Tab');
    const focus=await page.evaluate(()=>{
     const e=document.activeElement,s=getComputedStyle(e);
     return {tag:e.tagName,name:e.getAttribute('aria-label')||e.textContent.trim().slice(0,80),
      outline:s.outline,boxShadow:s.boxShadow,visible:e.matches(':focus-visible')};
    });
    let accessibility=null;
    if(process.env.AXE_SOURCE){
     await page.evaluate(fs.readFileSync(process.env.AXE_SOURCE,'utf8'));
     accessibility=await page.evaluate(async()=>{
      const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}});
      return {violations:r.violations.map(v=>({id:v.id,impact:v.impact,description:v.description,
       nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))})),
       incomplete:r.incomplete.map(v=>v.id),passes:r.passes.length};
     });
    }
    report.push({name,width,layout,focus,errors,external,failed,accessibility});
    fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify({name,width,overflow:layout.scrollWidth>width+1,errors:errors.length,
     accessibilityViolations:accessibility?.violations.length}));
    if(process.env.VISUAL_BEHAVIORS==='1'){
     await require('./prototype_visual_behaviors.cjs')(page,name);
     console.log(`PASS ${name} interactions at ${width}px`);
    }
    await page.close();
   }
  }
  for(const item of report){
   assert.ok(item.layout.scrollWidth<=item.width+1,`${item.name} overflow at ${item.width}`);
   assert.ok(item.layout.headings.length,`${item.name} missing page hierarchy`);
   assert.deepEqual(item.errors,[],`${item.name} browser errors`);
   assert.deepEqual(item.external,[],`${item.name} external dependencies`);
   assert.deepEqual(item.failed,[],`${item.name} failed resource requests`);
   if(item.accessibility)assert.deepEqual(item.accessibility.violations,[],`${item.name} accessibility findings at ${item.width}; see report.json`);
  }
  console.log(`PASS responsive/resource${process.env.AXE_SOURCE?'/automated accessibility':''} checks; screenshots need human review: ${output}`);
 }finally{
  if(browser)await browser.close();
  child.kill('SIGTERM');
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
