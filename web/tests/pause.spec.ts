import { test, expect } from '@playwright/test';

test('external run must be adopted before confirmed pause', async ({ page }) => {
  let adopted = false;
  const actions: string[] = [];
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body: any = [];
    if (path === '/api/runs') body = [{ id:'external', external:true, adopted, display_name:'终端实验', status:'external_running' }];
    if (path === '/api/queue') body = { runs:[], paused:false };
    if (path.endsWith('/log')) body = { text:'日志' };
    if (path === '/api/analysis/series') body = { series:[], warnings:[] };
    if (path.endsWith('/adopt')) { adopted = true; actions.push('adopt'); body = { adopted }; }
    if (path.endsWith('/pause')) { expect(route.request().postDataJSON().confirmed).toBe(true); actions.push('pause'); body = {}; }
    await route.fulfill({ json:body });
  });
  await page.goto('/');
  await page.getByRole('button', { name:/终端实验/ }).click();
  await expect(page.getByRole('button', { name:'暂停实验', exact:true })).toHaveCount(0);
  await page.getByRole('button', { name:'接管进程', exact:true }).click();
  await page.getByRole('button', { name:'暂停实验', exact:true }).click();
  await expect(page.getByText(/暂停后暂不能通过工作台续跑/)).toBeVisible();
  expect(actions).toEqual(['adopt']);
  await page.getByRole('button', { name:'确认暂停' }).click();
  await expect.poll(() => actions).toEqual(['adopt','pause']);
});

test('pause requires confirmation and resumes through the shared entry', async ({ page }) => {
  let status = 'running';
  const mutations: string[] = [];
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body: any = [];
    if (path === '/api/runs') body = [{ id:'r', display_name:'测试实验', status }];
    if (path === '/api/queue') body = { runs:[], paused:false };
    if (path.endsWith('/log')) body = { text:'日志' };
    if (path === '/api/analysis/series') body = { series:[], warnings:[] };
    if (path.endsWith('/pause')) {
      expect(route.request().postDataJSON().confirmed).toBe(true);
      mutations.push('pause'); status = 'paused'; body = { status };
    }
    if (path.endsWith('/resume')) { mutations.push('resume'); status = 'queued'; body = { status }; }
    await route.fulfill({ json:body });
  });
  await page.goto('/');
  await page.getByRole('button', { name:/测试实验/ }).click();
  await page.getByRole('button', { name:'暂停实验', exact:true }).click();
  expect(mutations).toEqual([]);
  await page.getByRole('button', { name:'确认暂停' }).click();
  await expect(page.getByText('已暂停', { exact:true })).toBeVisible();
  await expect(page.getByRole('button', { name:'继续实验' })).toHaveCount(0);
  await page.getByRole('button', { name:'严格续跑', exact:true }).click();
  await page.getByLabel('续跑实验').selectOption('r');
  await page.getByRole('button', { name:'校验并加入队列' }).click();
  await expect.poll(() => mutations).toEqual(['pause','resume']);
});
