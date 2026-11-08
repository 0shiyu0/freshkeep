<script setup lang="ts">
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { computed } from 'vue'

const route = useRoute()
const tabs = [
  { to: '/', label: '首页', icon: '◧' },
  { to: '/inventory', label: '库存', icon: '▤' },
  { to: '/records', label: '记录', icon: '≡' },
  { to: '/settings', label: '设置', icon: '⚙' },
]
const showTabs = computed(() => route.name !== 'pair')
</script>

<template>
  <div class="app">
    <header class="topbar">
      <h1>鲜度</h1>
      <p class="muted">食材库存与营养管理</p>
    </header>

    <main class="view">
      <RouterView />
    </main>

    <nav v-if="showTabs" class="tabbar">
      <RouterLink v-for="t in tabs" :key="t.to" :to="t.to" class="tab">
        <span class="tab__icon">{{ t.icon }}</span>
        <span>{{ t.label }}</span>
      </RouterLink>
    </nav>
  </div>
</template>
