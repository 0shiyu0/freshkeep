<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'

import { setUnauthorizedHandler } from '@/api/http'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const app = useAppStore()
const auth = useAuthStore()

const navItems = [
  { to: '/', label: '首页', icon: '◧', hint: '总览与营养' },
  { to: '/inventory', label: '库存', icon: '▤', hint: '食材与批次' },
  { to: '/records', label: '记录', icon: '≡', hint: '全部流水' },
  { to: '/settings', label: '设置', icon: '⚙', hint: '设备与备份' },
]

// 登录页是独立流程，不显示侧栏与底栏
const plain = computed(() => route.name === 'login')
const authed = computed(() => auth.authenticated)

// 401 的统一出口：清空登录态并跳登录页
setUnauthorizedHandler(() => {
  auth.me = null
  if (route.name !== 'login') router.replace('/login')
})

onMounted(async () => {
  if (!auth.checked) await auth.fetchMe()
  app.probe()
})
</script>

<template>
  <div class="layout" :class="{ 'layout--plain': plain }">
    <header class="topbar">
      <div class="brand">
        <span class="brand__mark">鲜</span>
        <div class="brand__text">
          <strong>鲜度</strong>
          <small>食材库存与营养</small>
        </div>
      </div>

      <div class="topbar__right">
        <div
          class="status"
          :class="app.healthClass"
          :title="app.lastCheckedAt ? `检测于 ${app.lastCheckedAt}` : ''"
        >
          <i class="status__dot" />
          <span>{{ app.healthText }}</span>
          <em v-if="app.latencyMs">{{ app.latencyMs }}ms</em>
        </div>
        <span v-if="authed" class="topbar__user">{{ auth.displayName }}</span>
      </div>
    </header>

    <aside v-if="!plain" class="sidebar">
      <nav class="sidebar__nav">
        <RouterLink v-for="item in navItems" :key="item.to" :to="item.to" class="side-link">
          <span class="side-link__icon">{{ item.icon }}</span>
          <span class="side-link__label">{{ item.label }}</span>
          <small class="side-link__hint">{{ item.hint }}</small>
        </RouterLink>
      </nav>
      <div class="sidebar__foot">
        <span>v{{ app.version || '—' }}</span>
        <span>{{ app.db?.migration ? `db ${app.db.migration}` : 'db —' }}</span>
      </div>
    </aside>

    <main class="content">
      <RouterView />
    </main>

    <nav v-if="!plain" class="bottomnav">
      <RouterLink v-for="item in navItems" :key="item.to" :to="item.to" class="bottom-link">
        <span class="bottom-link__icon">{{ item.icon }}</span>
        <span>{{ item.label }}</span>
      </RouterLink>
    </nav>
  </div>
</template>
