/**
 * 登录态：一次校验 + 全局共享，避免每个页面各自打 /auth/me。
 */
import { defineStore } from 'pinia'

import { authApi, type MeInfo } from '@/api/auth'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    me: null as MeInfo | null,
    checked: false,
    loading: false,
  }),

  getters: {
    authenticated: (s) => s.me !== null,
    displayName: (s) => s.me?.display_name || s.me?.username || '',
    hasPassword: (s) => s.me?.has_password ?? false,
  },

  actions: {
    /** 拉取当前会话；未登录时静默置空（不弹错误提示）。 */
    async fetchMe(force = false) {
      if (this.checked && !force) return this.me
      this.loading = true
      try {
        this.me = await authApi.me()
      } catch {
        this.me = null
      } finally {
        this.checked = true
        this.loading = false
      }
      return this.me
    },

    async pair(code: string) {
      await authApi.pair(code)
      await this.fetchMe(true)
    },

    async login(username: string, password: string) {
      await authApi.login(username, password)
      await this.fetchMe(true)
    },

    async logout() {
      try {
        await authApi.logout()
      } finally {
        this.me = null
        this.checked = true
      }
    },

    async changePassword(oldPassword: string, newPassword: string, confirm: string) {
      await authApi.changePassword(oldPassword, newPassword, confirm)
      await this.fetchMe(true)
    },

    async setPassword(newPassword: string, confirm: string) {
      await authApi.setPassword(newPassword, confirm)
      await this.fetchMe(true)
    },
  },
})
