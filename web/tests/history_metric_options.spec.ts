import { test, expect } from '@playwright/test';

test('monitor comparisons exclude hidden history and drop an archived selection on refresh', async ({ page }) => {
  let archived = false;
  const requests: any[] = [];
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body: any = [];
    if (path === '/api/history') body = [
      { id: 'visible', name: '可见历史', visibility: archived ? 'archived' : 'visible' },
      ...['archived', 'removed', 'tracking'].map(visibility => ({ id: visibility, name: visibility, visibility })),
    ];
    if (path === '/api/queue') body = { runs: [], paused: false };
    if (path === '/api/analysis/series') {
      const request = route.request().postDataJSON();
      requests.push(request);
      body = { series: [], metrics: ['val_ppl'], axes: ['tokens'], warnings: [`缺少 ${request.metric}`] };
    }
    await route.fulfill({ json: body });
  });
  await page.goto('/');
  const picker = page.locator('details').filter({ hasText: '历史对照' });
  await picker.locator('summary').click();
  await expect(picker.getByRole('checkbox')).toHaveCount(1);
  await picker.getByLabel('可见历史').check();
  await expect.poll(() => requests.at(-1)?.history_ids).toEqual(['visible']);
  for (const metric of ['R_min', 'R_mean', 'train_ppl', 'update_rms']) {
    await page.getByLabel('指标', { exact: true }).selectOption(metric);
    await expect(page.getByText(`缺少 ${metric}`, { exact: true })).toBeVisible();
    await expect(page.getByLabel('指标', { exact: true })).toHaveValue(metric);
  }
  archived = true;
  await page.evaluate(() => window.dispatchEvent(new Event('workspace-sync-changed')));
  await expect(picker.getByRole('checkbox')).toHaveCount(0);
  await expect(picker.locator('summary')).toHaveText('历史对照（0）');
  await expect.poll(() => requests.at(-1)?.history_ids).toEqual([]);
});

test('plot and table offer training diagnostics even when selected experiments lack them', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('analysis.ids', '["base"]'));
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body: any = [];
    if (path === '/api/history') body = [{ id: 'base', name: 'baseline' }];
    if (path === '/api/queue') body = { runs: [], paused: false };
    if (path === '/api/templates') body = [{ id: 'default', name: '默认模板', columns: [{ id: 'name', kind: 'name', title: '实验' }] }];
    if (path === '/api/analysis/series') {
      const { metric } = route.request().postDataJSON();
      body = { series: [], metrics: ['val_ppl'], axes: ['tokens'], warnings: [`baseline：缺少 ${metric}`] };
    }
    if (path === '/api/analysis/table') body = { headers: [], rows: [], warnings: [], markdown: '' };
    await route.fulfill({ json: body });
  });
  await page.goto('/');
  await page.getByRole('button', { name: '画图与列表', exact: true }).click();
  for (const metric of ['R_min', 'R_mean', 'train_ppl', 'update_rms']) {
    await page.getByLabel('指标', { exact: true }).selectOption(metric);
    await expect(page.getByText(`baseline：缺少 ${metric}`, { exact: true })).toBeVisible();
    await expect(page.getByLabel('指标', { exact: true })).toHaveValue(metric);
  }
  await page.getByRole('tab', { name: '列表', exact: true }).click();
  await page.getByRole('button', { name: '编辑列与模板' }).click();
  await page.getByLabel('列类型').selectOption('metric');
  for (const metric of ['R_min', 'R_mean', 'train_ppl', 'update_rms']) {
    await expect(page.getByLabel('选择指标列').locator(`option[value="${metric}"]`)).toHaveCount(1);
  }
});

test('live comparison and offline plotting use the same metric dropdown', async ({ page }) => {
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body: any = [];
    if (path === '/api/queue') body = { runs: [], paused: false };
    if (path === '/api/analysis/series') body = { series: [], metrics: ['train_ppl', 'learning_rate', 'best_train_tokens', 'tokens_per_second', 'latest_val_perplexity', 'best_val_loss'], axes: ['tokens'], warnings: [] };
    await route.fulfill({ json: body });
  });
  await page.goto('/');
  const metric = page.getByLabel('指标', { exact: true });
  await expect(metric.getByRole('option', { name: 'learning_rate', exact: true })).toHaveCount(1);
  const options = await metric.locator('option').allTextContents();
  for (const hidden of ['best_train_tokens', 'tokens_per_second', 'latest_val_perplexity', 'best_val_loss']) {
    expect(options).not.toContain(hidden);
  }
  await page.getByRole('button', { name: '画图与列表', exact: true }).click();
  await expect(metric.getByRole('option', { name: 'learning_rate', exact: true })).toHaveCount(1);
  expect(await metric.locator('option').allTextContents()).toEqual(options);
});
