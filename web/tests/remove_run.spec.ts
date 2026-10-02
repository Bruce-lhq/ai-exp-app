import { test, expect } from '@playwright/test';

test('stopped managed run has confirmed delete and cancel keeps it', async ({ page }) => {
  let removed = false;
  let logRequests = 0;
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body: any = [];
    if (path === '/api/runs') body = [
      ...(!removed ? [{id:'two-b',display_name:'2B 已停止实验',status:'stopped'}] : []),
      {id:'active',display_name:'当前训练',status:'running'},
      {id:'starting',display_name:'正在启动',status:'starting'},
    ];
    if (path === '/api/queue') body = {runs:[]};
    if (path.endsWith('/log')) { logRequests++; body = {text:'final log'}; }
    if (path === '/api/analysis/series') body = {series:[],warnings:[]};
    if (path.endsWith('/remove')) { expect(route.request().postDataJSON().confirmed).toBe(true); removed = true; body = {}; }
    await route.fulfill({json:body});
  });
  await page.goto('/');
  const remove = page.getByRole('button', {name:'删除 2B 已停止实验 的监控记录',exact:true});
  await expect(remove).toHaveText('');
  await expect(page.getByRole('button', {name:'删除 当前训练 的监控记录',exact:true})).toHaveCount(0);
  await expect(page.getByRole('button', {name:'删除 正在启动 的监控记录',exact:true})).toBeDisabled();
  await remove.click();
  await page.getByRole('button', {name:'取消',exact:true}).click();
  expect(removed).toBe(false);
  expect(logRequests).toBe(0);
  await remove.click();
  await page.getByRole('button', {name:'确认删除记录',exact:true}).click();
  await expect(page.getByRole('button', {name:/2B 已停止实验/})).toHaveCount(0);
});

test('slow deletion hides immediately, stale refresh stays hidden, failure restores record', async ({ page }) => {
  let finishRemoval!: () => void;
  const pending = new Promise<void>(resolve => { finishRemoval = resolve; });
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/remove')) {
      await pending;
      await route.fulfill({status:502,json:{detail:'连接失败'}});
      return;
    }
    const body = path === '/api/runs' ? [{id:'slow',display_name:'慢速删除测试',status:'stopped'}]
      : path === '/api/queue' ? {runs:[]}
      : path === '/api/analysis/series' ? {series:[],warnings:[]} : [];
    await route.fulfill({json:body});
  });
  await page.goto('/');
  const remove = page.getByRole('button', {name:'删除 慢速删除测试 的监控记录',exact:true});
  await remove.click();
  await page.getByRole('button', {name:'确认删除记录',exact:true}).click();
  await expect(remove).toHaveCount(0);
  await expect(page.getByRole('button', {name:'确认删除记录',exact:true})).toHaveCount(0);
  await expect(page.getByText('正在从云端更新…', {exact:true})).toHaveCount(0);
  await page.getByRole('button', {name:'刷新',exact:true}).click();
  await expect(remove).toHaveCount(0);
  finishRemoval();
  await expect(remove).toBeVisible();
  await expect(page.getByText('删除未完成，记录已恢复：连接失败', {exact:true})).toBeVisible();
});
