// Acceptance for the saved model-generated visual cases; selectors follow their actual DOM.
const assert=require('node:assert/strict');

async function dialogFits(page,dialog){
 const box=await dialog.boundingBox();
 assert.ok(box&&box.width<=page.viewportSize().width&&box.x>=0,'Dialog must fit viewport');
 await page.keyboard.press('Tab');
 assert.ok(await dialog.evaluate(el=>el.contains(document.activeElement)),'Keyboard focus must stay in dialog');
}

module.exports=async function checkBehavior(page,name){
 if(name==='studio'){
  assert.equal(await page.locator('.case-item').count(),3);
  await page.getByRole('button',{name:'品牌',exact:true}).click();
  assert.equal(await page.locator('.case-item').count(),2);
  await page.getByRole('button',{name:'空间',exact:true}).click();
  assert.equal(await page.locator('.case-item').count(),1);
  await page.getByRole('button',{name:'全部',exact:true}).click();
  assert.equal(await page.locator('.case-item').count(),3);
  await page.getByRole('button',{name:'提交咨询',exact:true}).click();
  await page.getByText('请填写所有必填项。',{exact:true}).waitFor();
  await page.getByLabel('姓名',{exact:true}).fill('浏览器验收');
  await page.getByLabel('邮箱',{exact:true}).fill('invalid');
  await page.getByLabel('项目描述',{exact:true}).fill('设计一套品牌视觉。');
  await page.getByRole('button',{name:'提交咨询',exact:true}).click();
  await page.getByText('请输入有效的邮箱地址。',{exact:true}).waitFor();
  await page.getByLabel('邮箱',{exact:true}).fill('preview@example.com');
  await page.getByRole('button',{name:'提交咨询',exact:true}).click();
  await page.locator('#success-message').waitFor({state:'visible'});
  await page.locator('#contact-form').waitFor({state:'hidden'});
 }else if(name==='board'){
  assert.equal(await page.locator('.task-card').count(),3);
  await page.locator('#search-input').fill('不存在的任务');
  assert.equal(await page.locator('.task-card').count(),0);
  await page.locator('#search-input').fill('');
  await page.locator('#btn-add-task').click();
  const dialog=page.locator('#dialog-create');
  await dialogFits(page,dialog);
  await page.locator('#input-title').fill('   ');
  await page.locator('#btn-submit').click();
  await page.locator('#title-error').waitFor({state:'visible'});
  await page.locator('#input-title').fill('视觉验收任务 <img src=x onerror=alert(1)>');
  await page.locator('#input-priority').selectOption('high');
  await page.locator('#btn-submit').click();
  await dialog.waitFor({state:'hidden'});
  assert.equal(await page.locator('.task-card').count(),4);
  assert.equal(await page.locator('.task-card img').count(),0,'Title must render as text');
  assert.equal(await page.locator('#stat-todo').innerText(),'2');
  await page.locator('#search-input').fill('视觉验收任务');
  assert.equal(await page.locator('.task-card').count(),1);
  await page.locator('.task-card button').click();
  assert.equal(await page.locator('[data-lane="inprogress"] .task-card').count(),1);
  assert.equal(await page.locator('#stat-inprogress').innerText(),'2');
  await page.locator('.task-card button').click();
  assert.equal(await page.locator('[data-lane="done"] .task-card').count(),1);
  assert.equal(await page.locator('#stat-done').innerText(),'2');
  await page.locator('#btn-add-task').click();
  await page.keyboard.press('Escape');
  await dialog.waitFor({state:'hidden'});
 }else if(name==='members'){
  assert.equal(await page.locator('.el-table__body-wrapper tbody tr').count(),3);
  const search=page.locator('input').first();
  await search.fill('林');
  assert.equal(await page.locator('.el-table__body-wrapper tbody tr').count(),1);
  await search.fill('不存在的成员');
  assert.equal(await page.locator('.el-table__body-wrapper tbody tr').count(),0);
  await search.fill('');
  await page.getByRole('button',{name:/添加成员/}).click();
  const dialog=page.locator('.el-dialog:visible');
  await dialogFits(page,dialog);
  await dialog.getByRole('button',{name:/保存|确认添加|确定/}).click();
  await dialog.locator('.el-form-item__error').first().waitFor();
  const inputs=dialog.locator('input');
  await inputs.nth(0).fill('浏览器验收');
  await inputs.nth(1).fill('invalid');
  await dialog.getByRole('button',{name:/保存|确认添加|确定/}).click();
  await dialog.locator('.el-form-item__error').first().waitFor();
  await inputs.nth(1).fill('preview@example.com');
  await dialog.getByRole('button',{name:/保存|确认添加|确定/}).click();
  await dialog.waitFor({state:'hidden'});
  assert.equal(await page.locator('.el-table__body-wrapper tbody tr').count(),4);
  await page.getByText('浏览器验收',{exact:true}).waitFor();
 }
};
