import { test, expect } from '@playwright/test';

test('stopped managed run has confirmed delete and cancel keeps it', async ({ page }) => {
  let removed = false;
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body: any = [];
    if (path === '/api/runs') body = removed ? [] : [{id:'two-b',display_name:'2B 已停止实验',status:'stopped'}];
    if (path === '/api/queue') body = {runs:[]};
    if (path.endsWith('/log')) body = {text:'final log'};
    if (path === '/api/analysis/series') body = {series:[],warnings:[]};
    if (path.endsWith('/remove')) { expect(route.request().postDataJSON().confirmed).toBe(true); removed = true; body = {}; }
    await route.fulfill({json:body});
  });
  await page.goto('/');
  await page.getByRole('button', {name:/2B 已停止实验/}).click();
  await page.getByRole('button', {name:'删除记录',exact:true}).click();
  await page.getByRole('button', {name:'取消',exact:true}).click();
  expect(removed).toBe(false);
  await page.getByRole('button', {name:'删除记录',exact:true}).click();
  await page.getByRole('button', {name:'确认删除记录',exact:true}).click();
  await expect(page.getByRole('button', {name:/2B 已停止实验/})).toHaveCount(0);
});
