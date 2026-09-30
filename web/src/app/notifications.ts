export async function enableSystemNotifications(): Promise<string> {
  const native = (window as any).webkit?.messageHandlers?.notifications;
  if (native) {
    const result = await native.postMessage('enable');
    if (result === 'granted') return '系统通知已启用';
    if (result === 'settings_opened') return '已打开系统通知设置，请选择实验工作台';
    return '请在系统设置 → 通知 → 实验工作台中允许通知';
  }
  if (!('Notification' in window)) return '此浏览器不支持系统通知，请使用 Mac 应用';
  const permission = await Notification.requestPermission();
  if (permission === 'granted') return '系统通知已启用';
  window.alert('请打开浏览器地址栏旁的网站设置，将“通知”设为允许；如仍无通知，请检查系统设置中的浏览器通知权限。');
  return '请在浏览器的网站设置中允许通知';
}
