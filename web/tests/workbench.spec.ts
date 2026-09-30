import {test,expect} from '@playwright/test';
test('training metrics skip only missing curves and speed can be added to table', async ({page}) => {
 let columns: any[] = [];
 await page.addInitScript(() => localStorage.setItem('analysis.ids', '["base","ca"]'));
 await page.route('**/api/**', async route => {
  const path = new URL(route.request().url()).pathname;
  let body: any = [];
  if (path === '/api/queue') body = {runs: [], paused: false};
  if (path === '/api/history') body = [{id:'base',name:'λ=0'},{id:'ca',name:'λ=0.5'}];
  if (path === '/api/templates') body = [{id:'default',name:'默认模板',columns:[{id:'name',kind:'name',title:'实验'}]}];
  if (path === '/api/analysis/series') {
   const requested = route.request().postDataJSON();
   const caOnly = ['R_min','R_mean','update_rms'].includes(requested.metric);
   const ids = caOnly ? ['ca'] : requested.history_ids;
   body = {series:ids.map((id:string)=>({id,name:id,points:[{x:1e9,y:caOnly?.2:42}]})),
     metrics:['val_ppl','train_ppl','R_min','R_mean','update_rms','ca/L01/T01'],warnings:caOnly?['λ=0：缺少 R_min，跳过此曲线，保留选择']:[]};
  }
  if (path === '/api/analysis/table') { columns=route.request().postDataJSON().columns; body={headers:[],rows:[],warnings:[],markdown:''}; }
  await route.fulfill({json:body});
 });
 await page.goto('/');
 await page.getByRole('button',{name:'画图与列表',exact:true}).click();
 await expect(page.getByLabel('指标',{exact:true}).locator('option[value="ca/L01/T01"]')).toHaveCount(0);
 await page.getByLabel('指标',{exact:true}).selectOption('R_min');
 await expect(page.getByText('λ=0：缺少 R_min，跳过此曲线，保留选择',{exact:true})).toBeVisible();
 await expect(page.getByRole('img',{name:'R_min 实验曲线'})).toBeVisible();
 await page.locator('.history-picker summary').click();
 await expect(page.getByLabel('λ=0',{exact:true})).toBeChecked();
 await expect(page.getByLabel('λ=0.5',{exact:true})).toBeChecked();
 await page.locator('.history-picker summary').click();
 await page.getByLabel('指标',{exact:true}).selectOption('train_ppl');
 await expect(page.getByText('λ=0：缺少 R_min，跳过此曲线，保留选择',{exact:true})).toBeHidden();
 await page.getByRole('tab',{name:'列表',exact:true}).click();
 await page.getByRole('button',{name:'编辑列与模板'}).click();
 await page.getByLabel('列类型').selectOption('metric');
 await page.getByLabel('选择指标列').selectOption('tokens_per_second');
 await page.getByRole('button',{name:'添加',exact:true}).click();
 await expect.poll(()=>columns.some(c=>c.field==='tokens_per_second' && c.aggregate==='final')).toBe(true);
});
test('slow live curves do not overlap or restart when status and log update', async ({page}) => {
 let curveRequests = 0, statusRequests = 0;
 let release: () => void = () => {};
 const waiting = new Promise<void>(resolve => { release = resolve; });
 await page.route('**/api/**', async route => {
  const path = new URL(route.request().url()).pathname;
  let body: any = [];
  if (path === '/api/runs') {
   statusRequests++;
   body = [{id: 'slow', display_name: '慢连接实验', status: 'external_running'}];
  }
  if (path === '/api/queue') body = {runs: [], paused: false};
  if (path.endsWith('/log')) body = {text: 'latest log'};
  if (path === '/api/analysis/series') {
   if (route.request().postDataJSON().live_ids?.includes('slow')) { curveRequests++; await waiting; }
   body = {series: [{id: 'slow', name: '慢连接实验', points: [{x: 1e9, y: 42}]}], warnings: []};
  }
  await route.fulfill({json: body}).catch(() => {});
 });
 await page.goto('/');
 await expect.poll(() => curveRequests).toBe(1);
 const statusBefore = statusRequests;
 await page.getByRole('button', {name: /慢连接实验/}).click();
 await expect(page.getByText('latest log', {exact: true})).toBeVisible();
 await expect.poll(() => statusRequests, {timeout: 6000}).toBeGreaterThan(statusBefore);
 expect(curveRequests).toBe(1);
 await expect(page.locator('.loading-overlay')).toHaveCount(0);
 release();
 await expect(page.getByRole('img', {name: 'val_ppl 实验曲线'})).toBeVisible();
});
test('cached plots render without cloud loading or hidden project requests', async ({page}) => {
 let projectRequests = 0, seriesRequests = 0, metricRequests = 0, holdSeries = false;
 await page.addInitScript(() => localStorage.setItem('analysis.ids', '["cached"]'));
 await page.route('**/api/**', async route => {
  const path = new URL(route.request().url()).pathname;
  let body: any = [];
  if (path.startsWith('/api/projects')) projectRequests++;
  if (path === '/api/connection') body = {connected: false};
  if (path === '/api/queue') body = {runs: [], paused: false};
  if (path === '/api/history') body = [{id: 'cached', name: '本地备注'}];
  if (path.endsWith('/metrics')) { metricRequests++; body = {metadata: {val_ppl: {}}}; }
  if (path === '/api/analysis/series') {
   if (route.request().postDataJSON().history_ids.includes('cached')) {
    if (holdSeries) { await route.abort(); return; }
    seriesRequests++;
    expect(route.request().postDataJSON().live_ids).toBeUndefined();
   }
   body = {series: [{id: 'cached', name: '本地备注', points: [{x: 1e9, y: 42}, {x: 2e9, y: 35}]}], warnings: []};
  }
  await route.fulfill({json: body});
 });
 await page.goto('/');
 await expect(page.locator('.live-chart-panel .chart')).toBeVisible();
 const liveBounds = await page.locator('.live-chart-panel .chart').boundingBox();
 expect(liveBounds!.height / liveBounds!.width).toBeCloseTo(1401 / 2061, 2);
 await page.getByRole('button', {name: '画图与列表', exact: true}).click();
 await expect(page.getByRole('img', {name: 'val_ppl 实验曲线'})).toBeVisible();
 await expect(page.locator('.loading-overlay')).toHaveCount(0);
 const heading = await page.locator('.analysis-heading').boundingBox();
 const tabs = await page.getByRole('tablist').boundingBox();
 const picker = await page.locator('.history-picker').boundingBox();
 expect(Math.abs(tabs!.x + tabs!.width / 2 - heading!.x - heading!.width / 2)).toBeLessThan(2);
 expect(Math.abs(tabs!.y + tabs!.height / 2 - picker!.y - picker!.height / 2)).toBeLessThan(2);
 const chart = page.locator('#plot-panel .chart');
 const bounds = await chart.boundingBox();
 expect(bounds).not.toBeNull();
 expect(bounds!.height / bounds!.width).toBeCloseTo(1401 / 2061, 2);
 await expect(page.getByRole('tabpanel', {name: '列表', exact: true})).toBeHidden();
 await page.getByRole('tab', {name: '列表', exact: true}).click();
 await expect(page.getByRole('tabpanel', {name: '画图', exact: true})).toBeHidden();
 await expect(page.getByRole('heading', {name: '实验列表', exact: true})).toBeVisible();
 await page.getByRole('tab', {name: '画图', exact: true}).click();
 await expect(page.getByRole('img', {name: 'val_ppl 实验曲线'})).toBeVisible();
 expect(projectRequests).toBe(0);
 const count = seriesRequests;
 await page.getByLabel('图标题', {exact: true}).fill('离线缓存图');
 await expect(page.getByLabel('图标题', {exact: true})).toHaveValue('离线缓存图');
 expect(seriesRequests).toBe(count);
 expect(metricRequests).toBe(0);
 holdSeries = true;
 await page.getByRole('button', {name: '历史管理', exact: true}).click();
 await page.getByRole('button', {name: '画图与列表', exact: true}).click();
 await expect(page.getByRole('img', {name: 'val_ppl 实验曲线'})).toBeVisible();
});
test('schema creates initial preset before dependent requests; editor survives workspace changes',async({page})=>{
 let initialized=false;
 await page.route('**/api/**',async route=>{const path=new URL(route.request().url()).pathname;let body:any=[];
 if(path==='/api/projects')body=[{id:'p',name:'测试项目'}];
 else if(path.endsWith('/schema')){await new Promise(r=>setTimeout(r,80));initialized=true;body={fields:[{key:'lr',kind:'number',default:0.01,has_default:true},{key:'enabled',kind:'boolean',default:true,has_default:true}]}}
 else if(path.endsWith('/presets')){expect(initialized).toBe(true);body=[{id:'preset',name:'源码默认值',parameters:{training:{lr:0.01,enabled:true},runtime:{gpu_count:1}}}]}
 else if(path.endsWith('/editor-initial')){expect(initialized).toBe(true);body={training:{lr:0.001,enabled:true},runtime:{gpu_count:2}}}
 else if(path.endsWith('/inspect'))body={branches:['main']};
 else if(path.endsWith('/parameter-display'))body={};
 else if(path==='/api/connection')body={connected:true};
 else if(path==='/api/queue')body={runs:[],paused:false};
 await route.fulfill({json:body});});
 await page.goto('/');await page.getByRole('button',{name:'配置实验',exact:true}).click();await expect(page.getByLabel('lr',{exact:true})).toHaveValue('1e-3');
 await page.getByLabel('lr',{exact:true}).fill('2K');await page.getByRole('button',{name:'运行监控',exact:true}).click();await page.getByRole('button',{name:'配置实验',exact:true}).click();await expect(page.getByLabel('lr',{exact:true})).toHaveValue('2K');
 await page.getByLabel('lr',{exact:true}).fill('invalid');await page.getByLabel('实验名称').fill('example');await expect(page.getByRole('button',{name:'启动实验',exact:true})).toBeDisabled();
 await page.screenshot({path:'test-results/workbench.png',fullPage:true});
});
test('empty workspaces stay usable without invented experimental results',async({page})=>{await page.route('**/api/**',route=>route.fulfill({json:route.request().url().endsWith('/connection')?{connected:false}:[]}));await page.goto('/');await page.getByRole('button',{name:'配置实验',exact:true}).click();await expect(page.getByText('添加你的第一个项目')).toBeVisible();await page.getByRole('button',{name:'画图与列表',exact:true}).click();await expect(page.getByRole('button',{name:'下载 PNG'})).toBeDisabled();});

test('default project, two directories and flat history args load correctly', async ({page}) => {
 const errors: string[] = [];
 page.on('pageerror', error => errors.push(error.message));
 await page.route('**/api/**', async route => {
  const path = new URL(route.request().url()).pathname;
  const isS1 = path.includes('/s1/');
  let body: any = [];
  if (path === '/api/projects') body = [{id:'w',name:'wonn'}, {id:'s1',name:'s1llt',is_default:true}];
  else if (path.endsWith('/schema')) body = {fields:[{key:'lr',kind:'number',default:isS1 ? .02 : .01,has_default:true}],code:{kind:'working_tree',ref:null}};
  else if (path.endsWith('/editor-initial')) body = {training:{lr:isS1 ? .02 : .01},runtime:{gpu_count:8}};
  else if (path.endsWith('/parameter-display')) body = {};
  else if (path.endsWith('/inspect')) body = {branches:['main']};
  else if (path === '/api/history') body = [{id:'history',name:'历史实验',parameters:{lr:'2K',legacy:'old'}}];
  else if (path.endsWith('/parameters/validate')) {
   const p = route.request().postDataJSON().parameters;
   expect(p.training.lr).toBe('2K');
   body = {parameters:{training:{lr:2000},runtime:p.runtime},errors:[],warnings:[{field:'legacy',message:'当前代码没有此参数，已忽略'}]};
  }
  else if (path === '/api/queue') body = {runs:[],paused:false};
  await route.fulfill({json:body});
 });
 await page.goto('/');
 // Loading history before the editor has ever mounted must also work.
 await page.getByRole('button',{name:'历史管理',exact:true}).click();
 await page.getByRole('button',{name:'载入参数到编辑区'}).click();
 await expect(page.getByLabel('常用项目')).toHaveValue('s1');
 await expect(page.getByLabel('lr',{exact:true})).toHaveValue('2K');
 await expect(page.getByText('legacy：当前代码没有此参数，已忽略')).toBeVisible();
 page.on('dialog', dialog => dialog.accept());
 await page.getByLabel('常用项目').selectOption('w');
 await expect(page.getByLabel('lr',{exact:true})).toHaveValue('0.01');
 await page.getByLabel('常用项目').selectOption('s1');
 await expect(page.getByLabel('lr',{exact:true})).toHaveValue('0.02');
 await page.getByPlaceholder('搜索参数、备注或标签').fill('nothing');
 await page.getByRole('button',{name:'历史管理',exact:true}).click();
 await page.getByRole('button',{name:'载入参数到编辑区'}).click();
 await expect(page.getByLabel('lr',{exact:true})).toHaveValue('2K');
 await expect(page.getByPlaceholder('搜索参数、备注或标签')).toHaveValue('');
 expect(errors).toEqual([]);
});
