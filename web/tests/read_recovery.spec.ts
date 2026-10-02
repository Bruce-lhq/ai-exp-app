import { test, expect } from '@playwright/test';

test('configuration read failure shows retry and recovery restores existing presets', async ({ page }) => {
  let disconnected = true;
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/projects' && disconnected) { await route.abort(); return; }
    let body: any = [];
    if (path === '/api/projects') body = [{id:'p',name:'已有项目',is_default:true}];
    if (path.endsWith('/schema')) body = {fields:[{key:'learning_rate',kind:'number',default:0.001,has_default:true}],code:{}};
    if (path.endsWith('/editor-initial')) body = {training:{learning_rate:0.001},runtime:{gpu_count:1}};
    if (path.endsWith('/presets')) body = [{id:'saved',name:'已有参数组',parameters:{training:{learning_rate:0.001},runtime:{gpu_count:1}}}];
    if (path.endsWith('/parameter-display')) body = {};
    if (path.endsWith('/inspect')) body = {branches:[]};
    if (path === '/api/queue') body = {runs:[]};
    if (path === '/api/analysis/series') body = {series:[]};
    await route.fulfill({json:body});
  });
  await page.goto('/');
  await page.getByRole('button',{name:'配置实验',exact:true}).click();
  await expect(page.getByRole('alert')).toBeVisible();
  disconnected = false;
  await page.getByRole('button',{name:'重新加载配置',exact:true}).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.getByText('已有参数组',{exact:true})).toBeVisible();
});

test('failed history refresh keeps loaded records and successful refresh clears the error', async ({ page }) => {
  let disconnected = false;
  await page.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    if(path==='/api/history' && disconnected){await route.abort();return;}
    let body:any=[];
    if(path==='/api/history')body=[{id:'h',name:'已有历史',visibility:'visible',source:{kind:'remote',path:'/runs/h'},tags:[]}];
    if(path==='/api/queue')body={runs:[]};
    if(path==='/api/analysis/series')body={series:[]};
    await route.fulfill({json:body});
  });
  await page.clock.install();
  await page.goto('/');
  await page.getByRole('button',{name:'历史管理',exact:true}).click();
  await expect(page.getByText('已有历史',{exact:true})).toBeVisible();
  disconnected=true;
  await page.clock.fastForward(10001);
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByText('已有历史',{exact:true})).toBeVisible();
  disconnected=false;
  await page.clock.fastForward(10001);
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.getByText('已有历史',{exact:true})).toBeVisible();
});
