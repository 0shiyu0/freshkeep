/**
 * 全局状态：连接健康度、后端版本、数据库状态。
 * 布局与首页共用这一份，避免多处各自探测。
 */
import { defineStore } from 'pinia'

import { systemApi, type DbInfo, type PingInfo } from '@/api'
import { logError } from '@/utils/logger'

interface AppState {
  probing: boolean
  ok: boolean
  latencyMs: number
  version: string
  ping: PingInfo | null
  db: DbInfo | null
  errorText: string
  lastCheckedAt: string
}

export const useAppStore = defineStore('app', {
  state: (): AppState => ({
    probing: false,
    ok: false,
    latencyMs: 0,
    version: '',
    ping: null,
    db: null,
    errorText: '',
    lastCheckedAt: '',
  }),

  getters: {
    envLabel: (s) => s.ping?.name ?? '未连接',
    healthText(s): string {
      if (s.probing) return '检测中…'
      if (!s.ok) return s.errorText || '服务不可用'
      if (s.db && !s.db.connected) return '后端正常，数据库异常'
      return '服务正常'
    },
    healthClass(s): string {
      if (s.probing) return 'is-pending'
      if (!s.ok) return 'is-down'
      if (s.db && !s.db.connected) return 'is-warn'
      return 'is-up'
    },
    ready: (s) => s.ok && !!s.db?.connected,
  },

  actions: {
    async probe() {
      this.probing = true
      this.errorText = ''
      const started = performance.now()
      try {
        const [ping, db] = await Promise.all([systemApi.ping(), systemApi.db()])
        this.ping = ping
        this.db = db
        this.version = ping.version
        this.ok = true
        if (!db.connected) this.errorText = db.error ?? '数据库未连接'
      } catch (err) {
        this.ok = false
        this.ping = null
        this.db = null
        this.errorText = '无法连接后端，请确认容器是否启动'
        logError('app.probe', err)
      } finally {
        this.latencyMs = Math.round(performance.now() - started)
        this.lastCheckedAt = new Date().toLocaleTimeString()
        this.probing = false
      }
    },
  },
})
