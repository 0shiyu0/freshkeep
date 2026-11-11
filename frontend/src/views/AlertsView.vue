<script setup lang="ts">
/** 提醒中心（阶段 8.8 / 8.10）：临期/过期/低库存通知 + 采购建议。 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton } from 'naive-ui'

import { alertsApi, type AlertSummary, type NotificationRow, type PurchaseSuggestion } from '@/api/alerts'
import { notifyError, notifySuccess } from '@/utils/notify'

const router = useRouter()
const tab = ref<'notifications' | 'purchase'>('notifications')
const summary = ref<AlertSummary | null>(null)
const items = ref<NotificationRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const suggestions = ref<PurchaseSuggestion[]>([])
const estimatedTotal = ref<string | null>(null)
const loading = ref(false)
const scanning = ref(false)

const typeLabel: Record<string, string> = {
  expiring: '临期',
  expired: '已过期',
  low_stock: '低库存',
  backup: '备份',
}
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

async function loadSummary() {
  try { summary.value = await alertsApi.summary() } catch { /* 非关键 */ }
}

async function loadList() {
  loading.value = true
  try {
    const res = await alertsApi.list({ page: page.value, page_size: pageSize })
    items.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

async function loadSuggestions() {
  try {
    const res = await alertsApi.suggestions()
    suggestions.value = res.items
    estimatedTotal.value = res.estimated_total
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '加载建议失败')
  }
}

async function scanNow() {
  scanning.value = true
  try {
    const res = await alertsApi.scan(7)
    notifySuccess(res.created > 0 ? `新增 ${res.created} 条提醒` : '没有新的提醒')
    await Promise.all([loadSummary(), loadList()])
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '扫描失败')
  } finally {
    scanning.value = false
  }
}

async function markRead(row: NotificationRow) {
  try {
    await alertsApi.read(row.id)
    items.value = items.value.filter((i) => i.id !== row.id)
    total.value = Math.max(0, total.value - 1)
    await loadSummary()
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '操作失败')
  }
}

async function markAll() {
  try {
    const res = await alertsApi.readAll()
    notifySuccess(`已读 ${res.updated} 条`)
    await Promise.all([loadSummary(), loadList()])
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '操作失败')
  }
}

function goto(n: number) {
  page.value = Math.min(Math.max(1, n), totalPages.value)
  void loadList()
}

function fmtTime(s: string) {
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? s : d.toLocaleString('zh-CN', { hour12: false })
}

onMounted(async () => {
  await Promise.all([loadSummary(), loadList(), loadSuggestions()])
})
</script>

<template>
  <div class="page-head">
    <div>
      <h1>提醒</h1>
      <p>临期、过期与低库存提醒；建议仅供采购参考，不会自动改动库存</p>
    </div>
    <div class="head-actions">
      <NButton :loading="scanning" @click="scanNow">立即扫描</NButton>
      <button class="btn" @click="router.push('/scan')">扫码识别</button>
    </div>
  </div>

  <div v-if="summary" class="cards">
    <div class="stat" :class="{ warn: summary.expiring > 0 }">
      <span>临期 7 天内</span><strong>{{ summary.expiring }}</strong>
    </div>
    <div class="stat" :class="{ danger: summary.expired > 0 }">
      <span>已过期</span><strong>{{ summary.expired }}</strong>
    </div>
    <div class="stat" :class="{ warn: summary.low_stock > 0 }">
      <span>低库存</span><strong>{{ summary.low_stock }}</strong>
    </div>
    <div class="stat">
      <span>待处理合计</span><strong>{{ summary.unread }}</strong>
    </div>
  </div>

  <div class="tabs card">
    <button class="tab" :class="{ 'tab--on': tab === 'notifications' }" @click="tab = 'notifications'">通知</button>
    <button class="tab" :class="{ 'tab--on': tab === 'purchase' }" @click="tab = 'purchase'">采购建议</button>
  </div>

  <!-- 通知 -->
  <template v-if="tab === 'notifications'">
    <section class="card">
      <div class="card__head">
        <h2>待处理（{{ total }}）</h2>
        <button class="btn btn--ghost" @click="markAll">全部已读</button>
      </div>
      <div v-if="loading" class="muted-line">加载中…</div>
      <div v-else-if="items.length === 0" class="muted-line">
        没有待处理提醒。点「立即扫描」按当前库存生成。
      </div>
      <div v-for="n in items" :key="n.id" class="notice">
        <span class="nt" :class="`nt--${n.type}`">{{ typeLabel[n.type] || n.type }}</span>
        <div class="notice__main">
          <div class="notice__title">
            {{ n.ingredient_name || '（未知食材）' }}
            <span v-if="n.batch_no" class="mono">{{ n.batch_no }}</span>
          </div>
          <div class="notice__meta">
            <span v-if="n.payload?.expiry_date">到期 {{ n.payload.expiry_date }}</span>
            <span v-if="n.payload?.remaining_weight != null">剩余 {{ n.payload.remaining_weight }}g</span>
            <span v-if="n.payload?.minimum_weight != null">最低 {{ n.payload.minimum_weight }}g</span>
            <span class="muted">{{ fmtTime(n.created_at) }}</span>
          </div>
        </div>
        <button class="btn btn--tiny" @click="markRead(n)">已读</button>
      </div>
      <div v-if="total > pageSize" class="pager">
        <button class="btn" :disabled="page <= 1" @click="goto(page - 1)">上一页</button>
        <span class="muted">第 {{ page }} / {{ totalPages }} 页</span>
        <button class="btn" :disabled="page >= totalPages" @click="goto(page + 1)">下一页</button>
      </div>
    </section>
  </template>

  <!-- 采购建议 -->
  <template v-else>
    <section class="card">
      <div class="card__head">
        <h2>建议采购（{{ suggestions.length }} 项）</h2>
        <span v-if="estimatedTotal" class="muted">预估合计 ¥{{ estimatedTotal }}</span>
      </div>
      <div v-if="suggestions.length === 0" class="muted-line">
        没有低库存食材。可在食材档案里设置「最低库存」后生效。
      </div>
      <div v-for="s in suggestions" :key="s.ingredient_id" class="suggest">
        <div class="suggest__main">
          <div class="suggest__name">{{ s.name }}</div>
          <div class="suggest__meta">
            现有 {{ Number(s.total_weight) }}{{ s.weight_symbol }} · 最低 {{ Number(s.minimum_weight) }}{{ s.weight_symbol }}
            <span class="reason">{{ s.reason }}</span>
          </div>
        </div>
        <div class="suggest__num">
          <strong>{{ s.suggested_weight ? Number(s.suggested_weight) + s.weight_symbol : '—' }}</strong>
          <small v-if="s.estimated_cost">≈ ¥{{ s.estimated_cost }}</small>
        </div>
        <button class="btn btn--tiny" @click="router.push(`/purchase?ingredient=${s.ingredient_id}`)">去入库</button>
      </div>
      <p class="muted note">
        建议量 = 最低库存 − 现有库存；未设最低库存时按近 30 天用量估算 7 天覆盖量。仅作参考。
      </p>
    </section>
  </template>
</template>

<style scoped>
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 12px; margin-bottom: 14px; }
.stat { display: flex; flex-direction: column; gap: 3px; padding: 11px 12px; border: 1px solid var(--line); border-radius: 10px; }
.stat span { font-size: 11.5px; color: var(--text-3); }
.stat strong { font-size: 20px; font-variant-numeric: tabular-nums; }
.stat.warn { border-color: #f0dfb8; background: #fdf9ef; }
.stat.danger { border-color: #f2c9c6; background: #fdf2f1; }

.tabs { display: flex; gap: 8px; padding: 8px; margin-bottom: 14px; }
.tab { padding: 7px 18px; border-radius: 9px; border: 1px solid transparent; background: transparent; font-size: 13.5px; cursor: pointer; color: var(--text-2); }
.tab--on { background: var(--green-weak); color: var(--green); border-color: #cfe3d6; font-weight: 600; }

.card__head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 8px; }
.card__head h2 { margin: 0; }
.muted-line { font-size: 13px; color: var(--text-3); padding: 8px 0; }
.muted { color: var(--text-3); font-size: 11.5px; }
.mono { font-family: ui-monospace, monospace; font-size: 11.5px; color: var(--text-3); }

.notice { display: flex; align-items: center; gap: 12px; padding: 9px 0; border-top: 1px dashed var(--line); flex-wrap: wrap; }
.notice__main { flex: 1; min-width: 160px; }
.notice__title { font-size: 14px; font-weight: 500; display: flex; gap: 8px; align-items: baseline; }
.notice__meta { display: flex; gap: 12px; margin-top: 3px; font-size: 11.5px; color: var(--text-3); flex-wrap: wrap; }
.nt { font-size: 11px; padding: 2px 8px; border-radius: 999px; font-weight: 500; }
.nt--expiring { background: #fdf3e2; color: #b8860b; }
.nt--expired { background: #fbeae8; color: var(--red); }
.nt--low_stock { background: #eef2fb; color: #3d5a9a; }
.nt--backup { background: #f0efe9; color: var(--text-2); }
.btn--tiny { padding: 3px 9px; font-size: 11.5px; border-radius: 6px; }

.suggest { display: flex; align-items: center; gap: 12px; padding: 10px 0; border-top: 1px dashed var(--line); flex-wrap: wrap; }
.suggest__main { flex: 1; min-width: 160px; }
.suggest__name { font-size: 14px; font-weight: 600; }
.suggest__meta { font-size: 11.5px; color: var(--text-3); margin-top: 3px; display: flex; gap: 8px; flex-wrap: wrap; }
.reason { font-family: ui-monospace, monospace; font-size: 10.5px; opacity: .75; }
.suggest__num { text-align: right; display: flex; flex-direction: column; gap: 2px; }
.suggest__num strong { font-size: 15px; font-variant-numeric: tabular-nums; }
.suggest__num small { font-size: 11px; color: var(--text-3); }
.pager { display: flex; align-items: center; justify-content: center; gap: 12px; padding: 12px 0 4px; }
.note { margin-top: 10px; }
@media (max-width: 720px) {
  .cards { grid-template-columns: repeat(2, 1fr); }
  .suggest__num { text-align: left; }
}
</style>
