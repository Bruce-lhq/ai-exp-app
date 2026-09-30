import { test, expect } from '@playwright/test';

test('step-only metrics choose an available curve without requiring perplexity or tokens', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem('analysis.ids', '["h"]'));
  const requests: any[] = [];
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body: any = [];
    if (path === '/api/history') body = [{id:'h',name:'Classifier',status:'completed',visibility:'visible',source:{kind:'local'}}];
    if (path === '/api/queue') body = {runs:[]};
    if (path === '/api/analysis/series') {
      const request = route.request().postDataJSON(); requests.push(request);
      body = {metrics:['accuracy'],axes:['step'], warnings:[], series:
        request.metric === 'accuracy' && request.x_axis === 'step'
          ? [{id:'h',name:'Classifier',points:[{x:1,y:.5},{x:2,y:.9}]}] : []};
    }
    await route.fulfill({json:body});
  });
  await page.goto('/');
  await page.getByRole('button', {name:'画图与列表',exact:true}).click();
  await expect(page.getByLabel('横轴', {exact:true})).toHaveValue('step');
  await expect.poll(() => requests.some(request => request.metric === 'accuracy' && request.x_axis === 'step')).toBe(true);
  await expect(page.getByRole('button', {name:'下载 PNG',exact:true})).toBeEnabled();
  expect(errors).toEqual([]);
});

test('explicit worker mapping hides duplicate GPU control while data-loader workers do not', async ({ page }) => {
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body: any = [];
    const mapped = path.includes('/mapped/');
    if (path === '/api/projects') body = [{id:'mapped',name:'Distributed',is_default:true},{id:'plain',name:'Plain Python'}];
    if (path.endsWith('/schema')) body = {
      fields:[{key:'num_workers',kind:'integer',has_default:true,default:4}],
      integration:{runtime:mapped ? {workers_parameter:'num_workers'} : {}},
    };
    if (path.endsWith('/editor-initial')) body = {training:{num_workers:4},runtime:{gpu_count:mapped ? 4 : 1}};
    if (path.endsWith('/parameter-display')) body = {};
    if (path === '/api/queue') body = {runs:[]};
    if (path === '/api/analysis/series') body = {series:[],warnings:[]};
    await route.fulfill({json:body});
  });
  await page.goto('/');
  await page.getByRole('button', {name:'配置实验',exact:true}).click();
  await expect(page.getByLabel('num_workers', {exact:true})).toHaveValue('4');
  await expect(page.getByLabel('GPU 卡数', {exact:true})).toHaveCount(0);
  await page.getByRole('combobox', {name:'常用项目',exact:true}).selectOption('plain');
  await expect(page.getByLabel('GPU 卡数', {exact:true})).toHaveValue('1');
  await expect(page.getByLabel('num_workers', {exact:true})).toHaveValue('4');
});
