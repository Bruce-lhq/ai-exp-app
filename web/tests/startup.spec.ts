import { test, expect } from '@playwright/test';

test('interrupted application script shows retry instead of a white screen', async ({ page }) => {
  await page.route('**/src/main.tsx', route => route.abort());
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'AI Experiment', exact: true })).toBeVisible();
  await expect(page.getByRole('status')).toContainText('页面尚未加载完成');
  await expect(page.getByRole('link', { name: '重新加载' })).toHaveAttribute('href', '/');
});

test('stalled application script keeps a loading message and explains recovery', async ({ page }) => {
  let finish!: () => void;
  const pending = new Promise<void>(resolve => { finish = resolve; });
  await page.clock.install();
  await page.route('**/src/main.tsx', async route => { await pending; await route.abort(); });
  try {
    await page.goto('/', { waitUntil: 'commit' });
    await expect(page.getByRole('status')).toHaveText('正在加载工作台…');
    await page.clock.fastForward(10001);
    await expect(page.getByRole('status')).toContainText('请检查 VPN 和 Termius 转发');
  } finally { finish(); }
});
