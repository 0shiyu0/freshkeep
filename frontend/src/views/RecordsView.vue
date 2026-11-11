<script setup lang="ts">
/** 记录页（M5/M8）：全部库存流水（入库/消耗/报损/盘点/冲销）。
 *  消耗流水可撤销（走反向流水，原记录保留）。 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NSelect } from 'naive-ui'

import { inventoryApi, TX_TYPE_LABEL, trimNum, type TransactionRow } from '@/api/inventory'
import { consumptionApi } from '@/api/consumptions'
import { notifyError, notifySuccess } from '@/utils/notify'

const router = useRouter()
const items = ref<TransactionRow[]>([])
const total = ref(0)
const loading = ref(false)
const type = ref<string | null>(null)
const fromDate = ref('')
const toDate = ref('')
const page = ref(1)
const pageSize = 30
const busyId = ref<string | null>(null)

const typeOptions = [
  { label: '全部类型', value: '' },
  { label: '入库', value: 'purchase' },
  { label: '消耗', value: 'consume' },
  { label: '报损', value: 'spoilage' },
  { label: '盘点', value: 'adjustment' },
  { label: '冲销', value: 'reverse' },
]

const hasFilter = computed(() => !!type.value)

async function load() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page: page.value, page_size: pageSize }
    if (type.value) params.type = type.value
    if (fromDate.value) params.from_date = fromDate.value
    if (toDate.value) params.to_date = toDate.value
    const res = await inventoryApi.transactions(params)
    items.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

function fmtTime(s: string) {
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? s : d.toLocaleString('zh-CN', { hour12: false })
}

/** 数量变化展示：正数带 +，负数原样；0 显示 — */
function deltaText(v: string, unit: string): string {
  const n = Number(v)
  if (!n) return '—'
  return `${n > 0 ? '+' : ''}${trimNum(v)}${unit}`
}

function canReverse(row: TransactionRow): boolean {
  return row.type === 'consume' && row.related_object_type === 'consumption' && !!row.related_object_id
}

async function doReverse(row: TransactionRow) {
  if (!row.related_object_id) return
  busyId.value = row.id
  try {
    await consumptionApi.reverse(row.related_object_id, '记录页撤销')
    notifySuccess('已撤销，库存已恢复')
    await load()
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '撤销失败')
  } finally {
    busyId.value = null
  }
}

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
function goto(next: number) {
  page.value = Math.min(Math.max(1, next), totalPages.value)
}
watch([type, fromDate, toDate], () => { page.value = 1; load() })
watch(page, load)
onMounted(load)
</script>

<template>
  <div class="page-head">
    <div>
      <h1>记录</h1>
      <p>共 {{ total }} 条流水 · 入库 / 消耗 / 报损 / 盘点 / 冲销都记在这里</p>
    </div>
    <div class="head-actions">
      <button class="btn" @click="router.push('/inventory')">去库存</button>
      <button class="btn btn--primary" @click="router.push('/consume')">+ 记一笔消耗</button>
    </div>
  </div>

  <section class="card filters">
    <NSelect v-model:value="type" :options="typeOptions" placeholder="全部类型" size="small" style="width: 140px" />
    <label class="date">从 <input v-model="fromDate" type="date" /></label>
    <label class="date">到 <input v-model="toDate" type="date" /></label>
    <span class="muted">撤销通过反向流水恢复库存，原流水不会删除</span>
  </section>

  <div v-if="loading" class="card empty"><p>加载中…</p></div>

  <section v-else-if="items.length === 0" class="card empty">
    <h3>{{ hasFilter ? '这个类型下没有流水' : '还没有任何流水' }}</h3>
    <p>入库、消耗、盘点、报损都会自动生成流水与批次分配。</p>
    <button class="btn btn--primary" style="margin-top: 10px" @click="router.push('/inventory')">
      去库存页入库
    </button>
  </section>

  <template v-else>
    <section v-for="row in items" :key="row.id" class="card record">
      <div class="record__head">
        <span class="tx-tag" :class="`tx-tag--${row.type}`">{{ TX_TYPE_LABEL[row.type] || row.type }}</span>
        <span class="mono">{{ row.transaction_no }}</span>
      </div>
      <div class="record__body">
        <div class="record__name">{{ row.ingredient_name }}</div>
        <div class="record__nums">
          <span v-if="Number(row.weight_delta)">重量 {{ deltaText(row.weight_delta, 'g') }}</span>
          <span v-if="Number(row.quantity_delta)">数量 {{ deltaText(row.quantity_delta, '') }}</span>
          <span v-if="Number(row.cost_delta)">成本 {{ row.cost_delta }} 元</span>
        </div>
        <div class="record__meta">
          <span>{{ fmtTime(row.created_at) }}</span>
          <span v-if="row.reason">{{ row.reason }}</span>
        </div>
      </div>
      <div class="record__ops">
        <NButton v-if="canReverse(row)" size="small" :loading="busyId === row.id" @click="doReverse(row)">
          撤销
        </NButton>
      </div>
    </section>

    <div class="pager">
      <button class="btn" :disabled="page <= 1" @click="goto(page - 1)">上一页</button>
      <span class="muted">第 {{ page }} / {{ totalPages }} 页 · 共 {{ total }} 条</span>
      <button class="btn" :disabled="page >= totalPages" @click="goto(page + 1)">下一页</button>
    </div>
  </template>
</template>

<style scoped>
.filters { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.date { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: var(--text-2); }
.date input {
  height: 30px; padding: 0 8px; border: 1px solid var(--line);
  border-radius: 7px; font-size: 12.5px; background: var(--surface); color: var(--text);
}
.pager { display: flex; align-items: center; justify-content: center; gap: 12px; padding: 14px 0; flex-wrap: wrap; }
.muted { color: var(--text-3); font-size: 12px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--text-3); }
.empty { text-align: center; padding: 26px 0; }
.record { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.record__head { display: flex; flex-direction: column; gap: 6px; min-width: 132px; align-items: flex-start; }
.record__body { flex: 1; min-width: 180px; }
.record__name { font-size: 15px; font-weight: 600; }
.record__nums { display: flex; gap: 14px; margin-top: 4px; font-size: 13px; font-variant-numeric: tabular-nums; }
.record__meta { display: flex; gap: 12px; margin-top: 4px; font-size: 11.5px; color: var(--text-3); flex-wrap: wrap; }
.record__ops { flex: none; }

.tx-tag { font-size: 11.5px; padding: 2px 9px; border-radius: 999px; font-weight: 500; }
.tx-tag--purchase { background: var(--green-weak); color: var(--green); }
.tx-tag--consume { background: #eef2fb; color: #3d5a9a; }
.tx-tag--spoilage { background: #fbeae8; color: var(--red); }
.tx-tag--adjustment { background: #fdf3e2; color: #b8860b; }
.tx-tag--reverse { background: #f0efe9; color: var(--text-2); }

@media (max-width: 720px) {
  .record__head { flex-direction: row; align-items: center; min-width: 100%; }
  .record__ops { margin-left: auto; }
}
</style>
