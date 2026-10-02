import { test, expect } from '@playwright/test';

test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

test('phone navigation, readable curves and queue ordering preserve server revision', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem('analysis.ids', '["h"]'));
  let queue = ['a', 'b'];
  let reordered = false;
  let paused = false;
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body: any = [];
    if (path === '/api/settings/local') body = { configured: true };
    if (path === '/api/connection') body = { connected: true };
    if (path === '/api/runs') body = [{ id: 'live', display_name: '运行实验', status: 'running' }];
    if (path === '/api/queue') body = { revision: 12, runs: queue.map(id => ({ id, display_name: id === 'a' ? '队列A' : '队列B' })) };
    if (path === '/api/queue/order') {
      const data = route.request().postDataJSON();
      expect(data.revision).toBe(12);
      expect(data.run_ids).toEqual(['b', 'a']);
      queue = data.run_ids;
      reordered = true;
      body = {};
    }
    if (path === '/api/runs/live/pause') { expect(route.request().postDataJSON().confirmed).toBe(true); paused = true; body = {}; }
    if (path.endsWith('/log')) body = { text: 'live log' };
    if (path === '/api/templates') body = [{id:'default',name:'默认模板',columns:[{id:'name',kind:'name',title:'实验'}]}];
    if (path === '/api/analysis/table') body = { headers: ['实验', 'best_val_ppl', 'final_val_ppl', 'parameters'], rows: [['历史实验', '30.00 @2.00B', '32.00 @2.50B', '94.00M']], warnings: [], markdown: '|实验|' };
    if (path === '/api/history') body = [{ id: 'h', name: '历史实验', visibility: 'visible', status: 'completed', source: {kind:'local'} }];
    if (path === '/api/analysis/series') body = { metrics: ['val_ppl'], axes: ['tokens'], series: [{id:'h',name:'长实验名称用来验证手机端图例不会缩成细小文字',points:[{x:1e9,y:42},{x:2e9,y:30}]}], warnings: [] };
    if (path === '/api/projects') body = [{id:'p',name:'通用训练',is_default:true}];
    if (path.endsWith('/schema')) body = {fields:[{key:'learning_rate',kind:'number',has_default:true,default:0.0002}],integration:{}};
    if (path.endsWith('/editor-initial')) body = {training:{learning_rate:0.0002},runtime:{gpu_count:1}};
    if (path.endsWith('/parameter-display')) body = {};
    await route.fulfill({json:body});
  });
  await page.goto('/');
  await expect(page.getByLabel('曲线图例')).toBeVisible();
  await expect(page.getByRole('img', {name:'val_ppl 实验曲线'})).toBeVisible();
  expect(await page.locator('.chart').evaluate(element => element.clientHeight)).toBeGreaterThanOrEqual(400);
  await page.screenshot({ path: testInfo.outputPath('phone-monitor.png'), fullPage: true });
  await page.getByRole('button',{name:'队列B上移',exact:true}).tap();
  await expect.poll(() => reordered).toBe(true);
  for (const name of ['配置实验', '历史管理', '画图与列表', '运行监控']) {
    const button = page.getByRole('button',{name,exact:true});
    await button.tap();
    await expect(button).toHaveAttribute('aria-current','page');
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.setViewportSize({ width: 320, height: 720 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.setViewportSize({ width: 390, height: 844 });
  }
  await page.getByRole('button', {name:'运行实验',exact:false}).tap();
  await page.getByRole('button', {name:'暂停实验',exact:true}).tap();
  expect(paused).toBe(false);
  await page.getByRole('button', {name:'确认暂停',exact:true}).tap();
  await expect.poll(() => paused).toBe(true);
  await page.getByRole('button',{name:'画图与列表',exact:true}).tap();
  await page.getByRole('tab',{name:'列表',exact:true}).tap();
  await expect(page.getByRole('cell',{name:'30.00 @2.00B'})).toBeVisible();
  expect(await page.locator('.table-scroll').evaluate(element => element.scrollWidth > element.clientWidth)).toBe(true);
  const dismiss = page.getByRole('button', {name: '关闭提醒', exact: true});
  if (await dismiss.isVisible()) await dismiss.tap();
  await page.screenshot({ path: testInfo.outputPath('phone-table.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});

test('phone disconnection keeps last status and exposes tunnel recovery guidance', async ({ page }) => {
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/connection' || path === '/api/runs') return route.abort('failed');
    let body: any = [];
    if (path === '/api/settings/local') body = { configured: true };
    if (path === '/api/queue') body = { runs: [] };
    if (path === '/api/analysis/series') body = { series: [], warnings: [] };
    await route.fulfill({json:body});
  });
  await page.goto('/');
  await expect(page.getByText('连接已中断，显示上次数据。请检查 VPN 与 SSH 隧道；恢复后自动重连。训练继续运行。')).toBeVisible();
  await expect(page.locator('.connection-warning')).toContainText('工作台连接中断');
});

test('GPU-hosted settings explain directory ownership and save direct-agent mode', async ({ page }) => {
  let saved: any;
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body: any = [];
    if (path === '/api/settings/local') {
      if (route.request().method() === 'PUT') saved = route.request().postDataJSON();
      body = { configured: true, local_settings: { connection_mode: 'ssh', ssh_alias: 'gpu', remote_python: '/usr/bin/python3', remote_agent: '/workspace/agent.pyz', remote_state_dir: '/workspace/state' } };
    }
    if (path === '/api/queue') body = { runs: [] };
    if (path === '/api/analysis/series') body = { series: [], warnings: [] };
    await route.fulfill({json:body});
  });
  await page.goto('/');
  await page.getByRole('button',{name:'工作空间设置',exact:true}).tap();
  await page.getByLabel('连接方式',{exact:true}).selectOption('local');
  await expect(page.getByLabel('代理主机标识',{exact:true})).toHaveValue('gpu');
  await expect(page.getByText(/本地导入也浏览 GPU 文件，不是 iPhone 文件夹/)).toBeVisible();
  await page.getByRole('button',{name:'保存设置',exact:true}).tap();
  await expect.poll(() => saved?.connection_mode).toBe('local');
  expect(saved.remote_state_dir).toBe('/workspace/state');
});
