import { test, expect } from '@playwright/test';

test('footer reports the running backend rather than the frontend build version', async ({page}) => {
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body: any = [];
    if (path === '/api/health') body = {version:'2.3.4'};
    if (path === '/api/settings/local') body = {configured:true,local_settings:{ssh_host:'gpu'}};
    if (path === '/api/connection') body = {connected:true};
    if (path === '/api/queue') body = {runs:[]};
    if (path === '/api/analysis/series') body = {series:[],metrics:['val_ppl']};
    await route.fulfill({json:body});
  });
  await page.goto('/');
  await expect(page.locator('.version span')).toHaveText('v2.3.4');
  await expect(page.locator('.version span')).toHaveAttribute('title', /后台：2\.3\.4；界面：/);
});
