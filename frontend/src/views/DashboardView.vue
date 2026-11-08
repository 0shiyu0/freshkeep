<script setup lang="ts">
import { computed } from 'vue'

import { useAppStore } from '@/stores/app'

const app = useAppStore()

const rows = computed(() => [
  { label: '服务状态', value: app.ok ? '正常' : '不可用' },
  { label: '后端版本', value: app.version || '—' },
  { label: '数据库', value: app.db?.connected ? `已连接 ${app.db.database ?? ''}` : '未连接' },
  { label: 'PostgreSQL', value: app.db?.server_version ?? '—' },
  { label: '业务表数', value: app.db?.tables != null ? String(app.db.tables) : '—' },
  { label: '迁移版本', value: app.db?.migration ?? '未执行' },
  {
    label: '连接池',
    value: app.db?.pool
      ? `${app.db.pool.size} 常驻 + ${app.db.pool.max_overflow} 上限，占用 ${app.db.pool.checked_out}`
      : '—',
  },
  { label: '探测耗时', value: app.latencyMs ? `${app.latencyMs} ms` : '—' },
])
</script>

<template>
  <div class="page-head">
    <div>
      <h1>概览</h1>
      <p>阶段 1 只验证基础设施：前端 → 后端 → 数据库 整条链路是否打通。</p>
    </div>
    <button class="btn btn--primary" :disabled="app.probing" @click="app.probe()">
      {{ app.probing ? '检测中…' : '重新检测' }}
    </button>
  </div>

  <div class="grid grid--2">
    <section class="card">
      <h2>链路自检</h2>
      <div v-for="row in rows" :key="row.label" class="kv">
        <span>{{ row.label }}</span>
        <em>{{ row.value }}</em>
      </div>
    </section>

    <section class="card">
      <h2>接下来</h2>
      <p>
        基础设施就绪后进入 M0 收尾，然后按 M1 认证 → M2 档案 → M3 批次 → M4 消耗 →
        M5 库存 → M6 首页与营养 → M8 前端页面推进。
      </p>
      <div style="margin-top: 12px; display: flex; gap: 8px; flex-wrap: wrap">
        <span class="tag">Docker Compose</span>
        <span class="tag">FastAPI</span>
        <span class="tag">PostgreSQL 16</span>
        <span class="tag">Vue 3 + TS</span>
        <span class="tag tag--muted">阶段 1</span>
      </div>
      <p v-if="!app.ready" style="margin-top: 12px">
        <span class="tag tag--warn">提示</span>
        数据库未连接时，查看 <code>storage/logs/api.log</code> 或
        <code>docker compose logs api</code>。
      </p>
    </section>
  </div>
</template>
