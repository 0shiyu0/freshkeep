<script setup lang="ts">
/** 记录页（M4）：消耗记录列表、状态筛选与撤销。
 *  完整的「全部流水」视图（入库/调整/报损）依赖 M5 的 /inventory/transactions，尚未实现。 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NSelect } from 'naive-ui'

import { consumptionApi, type Consumption } from '@/api/consumptions'
import { notifyError, notifySuccess } from '@/utils/notify'

const router = useRouter()
const items = ref<Consumption[]>([])
const total = ref(0)
const loading = ref(false)
const status = ref<string | null>(null)
const busyId = ref<string | null>(null)

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '已完成', value: 'completed' },
  { label: '已撤销', value: 'reversed' },
]

const hasFilter = computed(() => !!status.value)

async function load() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page_size: 50 }
    if (status.value) params.status = status.value
    const res = await consumptionApi.list(params)
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

async function doReverse(row: Consumption) {
  busyId.value = row.id
  try {
    await consumptionApi.reverse(row.id, '页面撤销')
    notifySuccess('已撤销，批次库存已恢复')
    await load()
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '撤销失败')
  } finally {
    busyId.value = null
  }
}

watch(status, load)
onMounted(load)
</script>

<template>
  <div class="page-head">
    <div>
      <h1>消耗记录</h1>
      <p>共 {{ total }} 条 · 撤销通过反向流水恢复库存，原记录保留</p>
    </div>
    <button class="btn btn--primary" @click="router.push('/consume')">+ 记一笔消耗</button>
  </div>

  <section class="card filters">
    <NSelect v-model:value="status" :options="statusOptions" placeholder="全部状态" size="small" style="width: 140px" />
    <span class="muted">入库 / 盘点 / 报损流水将在 M5 接入</span>
  </section>

  <div v-if="loading" class="card empty"><p>加载中…</p></div>

  <section v-else-if="items.length === 0" class="card empty">
    <h3>{{ hasFilter ? '这个筛选下没有记录' : '还没有消耗记录' }}</h3>
    <p>每次消耗都会生成流水、批次分配与营养快照。</p>
    <button class="btn btn--primary" style="margin-top: 10px" @click="router.push('/consume')">
      去记一笔消耗
    </button>
  </section>

  <template v-else>
    <section v-for="row in items" :key="row.id" class="card record">
      <div class="record__head">
        <span class="mono">{{ row.consumption_no }}</span>
        <span class="tag" :class="row.status === 'completed' ? '' : 'tag--muted'">
          {{ row.status === 'completed' ? '已完成' : '已撤销' }}
        </span>
      </div>
      <div class="record__body">
        <div class="record__name">{{ row.ingredient_name }}</div>
        <div class="record__nums">
          <span>{{ Number(row.weight) }}g</span>
          <span v-if="Number(row.quantity) > 0">{{ Number(row.quantity) }}{{ ' ' }}数量单位</span>
          <span>¥{{ row.cost }}</span>
        </div>
        <div class="record__meta">
          <span>{{ fmtTime(row.consumed_at) }}</span>
          <span v-if="row.note">{{ row.note }}</span>
        </div>
      </div>
      <div class="record__ops">
        <NButton v-if="row.status === 'completed'" size="small" :loading="busyId === row.id"
                 @click="doReverse(row)">撤销</NButton>
        <button v-else class="btn btn--ghost" @click="router.push('/records')">查看记录</button>
      </div>
    </section>
  </template>
</template>

<style scoped>
.filters { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.muted { color: var(--text-3); font-size: 12px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--text-3); }
.empty { text-align: center; padding: 26px 0; }
.record { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.record__head { display: flex; flex-direction: column; gap: 6px; min-width: 130px; }
.record__body { flex: 1; min-width: 180px; }
.record__name { font-size: 15px; font-weight: 600; }
.record__nums { display: flex; gap: 14px; margin-top: 4px; font-size: 13px; font-variant-numeric: tabular-nums; }
.record__meta { display: flex; gap: 12px; margin-top: 4px; font-size: 11.5px; color: var(--text-3); flex-wrap: wrap; }
.record__ops { flex: none; }
.btn--ghost { background: transparent; border-color: transparent; padding: 0 6px; }
@media (max-width: 720px) {
  .record__head { flex-direction: row; align-items: center; min-width: 100%; }
  .record__ops { margin-left: auto; }
}
</style>
