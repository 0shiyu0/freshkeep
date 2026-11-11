/** 浏览器通知（阶段 9）：用户显式授权后才发送，默认关闭。
 *  通知只做提醒，不触发任何库存写入；应用内通知中心仍是主通道。
 */

const KEY = 'freshkeep.browser-notifications.enabled'

export const browserNotifications = {
  supported(): boolean {
    return typeof window !== 'undefined' && 'Notification' in window
  },
  permission(): NotificationPermission | 'unsupported' {
    return this.supported() ? Notification.permission : 'unsupported'
  },
  enabled(): boolean {
    return localStorage.getItem(KEY) === '1' && this.permission() === 'granted'
  },
  setEnabled(v: boolean) {
    localStorage.setItem(KEY, v ? '1' : '0')
  },
  async request(): Promise<NotificationPermission | 'unsupported'> {
    if (!this.supported()) return 'unsupported'
    const result = await Notification.requestPermission()
    this.setEnabled(result === 'granted')
    return result
  },
  show(title: string, body: string, tag = 'freshkeep-alert'): boolean {
    if (!this.enabled()) return false
    const options: NotificationOptions = {
      body, tag, icon: '/icons/icon-192.png', badge: '/icons/icon-192.png',
    }
    try {
      const n = new Notification(title, options)
      n.onclick = () => {
        window.focus()
        n.close()
      }
      return true
    } catch {
      // 部分移动浏览器只允许通过 Service Worker 发通知
      void navigator.serviceWorker?.ready
        .then((registration) => registration.showNotification(title, options))
        .catch(() => undefined)
      return false
    }
  },
}
