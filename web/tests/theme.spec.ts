import { test, expect } from '@playwright/test';

test.beforeEach(async ({page}) => {
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body: any = [];
    if (path === '/api/settings/local') body = {configured:true,local_settings:{ssh_host:'gpu'}};
    if (path === '/api/connection') body = {connected:true};
    if (path === '/api/queue') body = {runs:[]};
    if (path === '/api/analysis/series') body = {series:[],metrics:['val_ppl']};
    await route.fulfill({json:body});
  });
});

test('system changes apply only in system mode; explicit choice persists after reload', async ({page}) => {
  await page.emulateMedia({colorScheme:'dark'});
  await page.goto('/');
  await expect(page.getByLabel('外观模式')).toHaveValue('system');
  await expect(page.locator('html')).toHaveAttribute('data-theme','dark');
  await page.getByRole('button',{name:'工作空间设置',exact:true}).click();
  expect(await page.locator('.modal').evaluate(el=>getComputedStyle(el).backgroundColor)).toBe('rgb(27, 36, 51)');
  await page.getByRole('button',{name:'关闭',exact:true}).click();
  await page.getByLabel('外观模式').selectOption('light');
  await page.reload();
  await expect(page.getByLabel('外观模式')).toHaveValue('light');
  await expect(page.locator('html')).toHaveAttribute('data-theme','light');
  await page.emulateMedia({colorScheme:'dark'});
  await expect(page.locator('html')).toHaveAttribute('data-theme','light');
  await page.getByLabel('外观模式').selectOption('system');
  await expect(page.locator('html')).toHaveAttribute('data-theme','dark');
  await page.emulateMedia({colorScheme:'light'});
  await expect(page.locator('html')).toHaveAttribute('data-theme','light');
});

test('dark mode is available on a narrow phone without horizontal overflow', async ({page}) => {
  await page.setViewportSize({width:320,height:720});
  await page.goto('/');
  await page.getByLabel('外观模式').selectOption('dark');
  await expect(page.locator('html')).toHaveAttribute('data-theme','dark');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
