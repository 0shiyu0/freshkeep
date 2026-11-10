<script setup lang="ts">
/** 批次详情（阶段 3）：初始/剩余/成本/单位成本 + 四个日期 + 该批次流水。 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { batchApi, expiryClass, expiryText, type BatchItem } from '@/api/batches'
import { inventoryApi, TX_TYPE_LABEL, trimNum, type TransactionRow } from '@/api/inventory'

const route = useRoute()
const router = useRouter()
const id = computed(() => String(route.params.id))

const batch = ref<BatchItem | null>(null)
const flows = ref<TransactionRow[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    batch.value = await batchApi.detail(id.value)
    const res = await inventoryApi.transactions({ batch_id: id.value, page_size: 50 })
    flows.value = res.items
  } finally {
    loading.value = false
  }
}

/** 属性表：初始/剩余/成本三段一律并排展示，避免只看到剩余而不知原始量 */
const attrs = computed(() => {
  if (!batch.value) return []
  const b = batch.value
  return [
    { label: '批次号', value: b.batch_no, mono: true },
    { label: '状态', value: b.status === 'active' ? '有库存' : b.status === 'depleted' ? '已耗尽' : '已作废' },
    { label: '购买日期', value: b.purchase_date },
    { label: '生产日期', value: b.production_date || '未填' },
    { label: '到期日期', value: b.expiry_date || '未填' },
    { label: '开封日期', value: b.opened_date || '未填' },
    { label: '储存位置', value: b.location_name || '未指定' },
    { label: '初始重量', value: `${trimNum(b.initial_weight)} g` },
    { label: '剩余重量', value: `${trimNum(b.remaining_weight)} g` },
    { label: '初始数量', value: trimNum(b.initial_quantity) },
    { label: '剩余数量', value: trimNum(b.remaining_quantity) },
    { label: '采购成本', value: `¥ ${b.purchase_cost}` },
    { label: '剩余成本', value: `¥ ${b.remaining_cost}` },
    { label: '单位成本', value: b.unit_cost ? `${b.unit_cost} 元/g` : '未记录' },
    { label: '备注', value: b.note || '—' },
  ]
})

function fmtTime(s: string) {
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? s : d.toLocaleString('zh-CN', { hour12: false })
}

onMounted(load)
</script>

<template>
  <div v-if="loading" class="card empty"><p>加载中…</p></div>

  <template v-else-if="batch">
    <div class="page-head">
      <div>
        <h1>{{ batch.ingredient_name }} · {{ batch.batch_no }}</h1>
        <p>
          购买 {{ batch.purchase_date }}
          <template v-if="batch.expiry_date"> · 到期 {{ batch.expiry_date }}</template>
          <span class="expiry" :class="`expiry--${expiryClass(batch)}`">{{ expiryText(batch) }}</span>
        </p>
      </div>
      <div class="head-actions">
        <button class="btn" @click="router.push(`/ingredients/${batch.ingredient_id}`)">食材档案</button>
        <button class="btn" @click="router.push(`/consume?ingredient=${batch.ingredient_id}`)">记一笔消耗</button>
        <button class="btn" @click="router.push('/batches')">批次列表</button>
      </div>
    </div>

    <section class="card">
      <h2>批次属性</h2>
      <div v-for="a in attrs" :key="a.label" class="attr">
        <span class="attr__label">{{ a.label }}</span>
        <span class="attr__value" :class="{ mono: a.mono }">{{ a.value }}</span>
      </div>
    </section>

    <section class="card">
      <h2>该批次流水（{{ flows.length }}）</h2>
      <div v-if="flows.length === 0" class="muted-line">暂无流水</div>
      <div v-for="f in flows" :key="f.id" class="flow">
        <span class="tx-tag" :class="`tx-tag--${f.type}`">{{ TX_TYPE_LABEL[f.type] || f.type }}</span>
        <span class="mono">{{ f.transaction_no }}</span>
        <span class="flow__delta">
          <template v-if="Number(f.weight_delta)">{{ trimNum(f.weight_delta) }}g</template>
          <template v-if="Number(f.cost_delta)"> · {{ f.cost_delta }} 元</template>
        </span>
        <span class="flow__time">{{ fmtTime(f.created_at) }}</span>
        <span v-if="f.reason" class="flow__reason">{{ f.reason }}</span>
      </div>
      <p class="hint">流水按分配表反查：一条跨多批次的流水会同时出现在各批次下。</p>
    </section>
  </template>

  <div v-else class="card empty">
    <h3>找不到这个批次</h3>
    <p>可能已被删除。</p>
    <button class="btn" style="margin-top: 12px" @click="router.push('/batches')">返回批次列表</button>
  </div>
</template>

<style scoped>
.empty { text-align: center; padding: 26px 0; }
.attr { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; padding: 9px 0; }
.attr + .attr { border-top: 1px dashed var(--line); }
.attr__label { font-size: 13px; color: var(--text-2); flex: none; }
.attr__value { font-size: 13.5px; font-weight: 500; text-align: right; font-variant-numeric: tabular-nums; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.muted-line { font-size: 13px; color: var(--text-3); padding: 6px 0; }
.hint { font-size: 11.5px; color: var(--text-3); margin: 10px 0 0; }
.expiry { font-size: 11.5px; padding: 2px 8px; border-radius: 999px; font-weight: 500; margin-left: 6px; }
.expiry--ok { background: var(--green-weak); color: var(--green); }
.expiry--warn { background: #fdf3e2; color: #b8860b; }
.expiry--danger { background: #fbeae8; color: var(--red); }
.expiry--expired { background: var(--red); color: #fff; }
.expiry--muted { background: #f0efe9; color: var(--text-3); }
.flow {
  display: flex; align-items: center; gap: 12px; padding: 9px 0;
  font-size: 13px; flex-wrap: wrap; border-top: 1px dashed var(--line);
  font-variant-numeric: tabular-nums;
}
.tx-tag { font-size: 11.5px; padding: 2px 9px; border-radius: 999px; font-weight: 500; }
.tx-tag--purchase { background: var(--green-weak); color: var(--green); }
.tx-tag--consume { background: #eef2fb; color: #3d5a9a; }
.tx-tag--spoilage { background: #fbeae8; color: var(--red); }
.tx-tag--adjustment { background: #fdf3e2; color: #b8860b; }
.tx-tag--reverse { background: #f0efe9; color: var(--text-2); }
.flow__delta { font-weight: 600; }
.flow__time, .flow__reason { font-size: 11.5px; color: var(--text-3); }
</style>
