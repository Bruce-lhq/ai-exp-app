import { afterEach, expect, test, vi } from 'vitest';
import { enableSystemNotifications } from '../src/app/notifications';

afterEach(() => vi.unstubAllGlobals());

test('Mac notification button uses native settings instead of browser permission', async () => {
  const postMessage = vi.fn().mockResolvedValue('settings_opened');
  const requestPermission = vi.fn();
  vi.stubGlobal('window', {webkit:{messageHandlers:{notifications:{postMessage}}},Notification:{requestPermission}});
  expect(await enableSystemNotifications()).toContain('已打开系统通知设置');
  expect(postMessage).toHaveBeenCalledWith('enable');
  expect(requestPermission).not.toHaveBeenCalled();
});

test('native permission approval is reported accurately', async () => {
  vi.stubGlobal('window', {webkit:{messageHandlers:{notifications:{postMessage:vi.fn().mockResolvedValue('granted')}}}});
  expect(await enableSystemNotifications()).toBe('系统通知已启用');
});

test('browser denial provides actionable settings instructions', async () => {
  const alert = vi.fn();
  const Notification = {requestPermission:vi.fn().mockResolvedValue('denied')};
  vi.stubGlobal('window', {Notification,alert});
  vi.stubGlobal('Notification',Notification);
  expect(await enableSystemNotifications()).toContain('网站设置');
  expect(alert).toHaveBeenCalledOnce();
});
