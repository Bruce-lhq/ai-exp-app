import { test, expect } from '@playwright/test';

test('loading flat historical args does not activate the old checkpoint as a strict resume', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body: any = [];
    if (path === '/api/history') body = [{
      id:'h', name:'旧实验', source:{kind:'local'}, status:'completed',
      parameters:{learning_rate:.00005, resume:'/runs/old/latest.pt', run_dir:'/runs/old'},
    }];
    if (path === '/api/projects') body = [{id:'p',name:'project-b',is_default:true}];
    if (path.endsWith('/schema')) body = {fields:[{key:'learning_rate',kind:'number',default:.01,has_default:true}]};
    if (path.endsWith('/editor-initial')) body = {training:{learning_rate:.01},runtime:{gpu_count:1}};
    if (path.endsWith('/parameter-display')) body = {};
    if (path.endsWith('/parameters/validate')) {
      const parameters = route.request().postDataJSON().parameters;
      body = {parameters:{training:{learning_rate:parameters.training.learning_rate},runtime:parameters.runtime},errors:[],warnings:[]};
    }
    if (path === '/api/queue') body = {runs:[]};
    if (path === '/api/analysis/series') body = {series:[],warnings:[]};
    await route.fulfill({json:body});
  });
  await page.goto('/');
  await page.getByRole('button', {name:'历史管理',exact:true}).click();
  await page.getByRole('button', {name:'载入参数到编辑区',exact:true}).click();
  await expect(page.getByLabel('learning_rate', {exact:true})).toHaveValue('5e-5');
  await expect(page.getByLabel('resume', {exact:true})).toHaveCount(0);
  await expect(page.getByText('历史实验参数已载入编辑区', {exact:true})).toBeVisible();
  expect(errors).toEqual([]);
});

test('remote history loads resume into editor and submits using Start', async ({ page }) => {
  let submitted: any;
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body: any = [];
    if (path === '/api/history') body = [{id:'h', name:'历史备注', source:{kind:'remote'}, parameters:{}, status:'paused'}];
    if (path === '/api/history/h/resume-editor') body = {training:{learning_rate:.001},runtime:{gpu_count:4},project_id:'p',display_name:'历史备注 · 续跑',resume:{ticket:'ticket',path:'/runs/a/latest.pt',tokens_seen:5e9}};
    if (path === '/api/projects') body = [{id:'p',name:'project-b',is_default:true}];
    if (path.endsWith('/schema')) body = {fields:[{key:'learning_rate',kind:'number',default:.01,has_default:true}]};
    if (path.endsWith('/editor-initial')) body = {training:{learning_rate:.01},runtime:{gpu_count:1}};
    if (path.endsWith('/parameter-display')) body = {};
    if (path.endsWith('/parameters/validate')) body = {parameters:route.request().postDataJSON().parameters,errors:[],warnings:[]};
    if (path === '/api/queue') body = {runs:[]};
    if (path === '/api/analysis/series') body = {series:[],warnings:[]};
    if (path === '/api/runs' && route.request().method() === 'POST') { submitted = route.request().postDataJSON(); body = {}; }
    await route.fulfill({json:body});
  });
  await page.goto('/');
  await page.getByRole('button', {name:'历史管理',exact:true}).click();
  await page.getByRole('button', {name:'载入续跑到编辑区',exact:true}).click();
  await expect(page.getByLabel('resume', {exact:true})).toHaveValue('/runs/a/latest.pt');
  await expect(page.getByLabel('GPU 卡数')).toHaveValue('4');
  await expect(page.getByLabel('learning_rate')).toHaveValue('1e-3');
  await page.getByRole('button', {name:'启动实验',exact:true}).click();
  await expect.poll(() => submitted?.resume_ticket).toBe('ticket');
  expect(submitted.parameters.runtime.gpu_count).toBe(4);
});
