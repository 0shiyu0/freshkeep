<script setup lang="ts">
/** 批次列表（阶段 3）：跨食材查看所有采购批次，支持搜索与筛选。 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NSelect } from 'naive-ui'

import { batchApi, expiryClass, expiryText, type BatchItem } from '@/api/batches'
import { catalogApi, type StorageLocation } from '@/api/catalog'
import { trimNum } from '@/api/inventory'

const router = useRouter()
const items = ref<BatchItem[]>([])
const locations = ref<StorageLocation[]>([])
const total = ref(0)
const loading = ref(false)
const keyword = ref('')
const status = ref<string | null>('active')
const locationId = ref<string | null>(null)

const statusOptions = [
  { label: '有库存', value: 'active' },
  { label: '已耗尽', value: 'depleted' },
  { label: '全部状态', value: '' },
]
const locationOptions = computed(() => locations.value.map((l) => ({ label: l.name, value: l.id })))

let timer: number | undefined
async function load() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page_size: 60 }
    if (keyword.value.trim()) params.q = keyword.value.trim()
    if (status.value) params.status = status.value
    if (locationId.value) params.location_id = locationId.value
    const res = await batchApi.list(params)
    items.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

watch(keyword, () => {
  window.clearTimeout(timer)
  timer = window.setTimeout(load, 250)
})
watch([status, locationId], load)

onMounted(async () => {
  const locs = await catalogApi.locations()
  locations.value = locs.items
  await load()
})
</script>

<template>
  <div class="page-head">
    <div>
      <h1>采购批次</h1>
      <p>共 {{ total }} 个批次 · 每次采购独立建档，成本与到期日互不影响</p>
    </div>
    <div class="head-actions">
      <button class="btn" @click="router.push('/inventory')">返回库存</button>
      <button class="btn btn--primary" @click="router.push('/purchase')">+ 采购入库</button>
    </div>
  </div>

  <section class="card filters">
    <input
      v-model="keyword"
      class="filters__input"
      placeholder="搜索食材：鸡胸肉 / jixiongrou / jxr"
    />
    <NSelect v-model:value="status" :options="statusOptions" size="small" style="width: 130px" />
    <NSelect
      v-model:value="locationId"
      :options="locationOptions"
      placeholder="全部位置"
      clearable
      size="small"
      style="width: 140px"
    />
  </section>

  <div v-if="loading" class="card empty"><p>加载中…</p></div>

  <section v-else-if="items.length === 0" class="card empty">
    <h3>没有符合条件的批次</h3>
    <p>换个筛选条件，或先录入一次采购。</p>
    <button class="btn btn--primary" style="margin-top: 10px" @click="router.push('/purchase')">
      + 采购入库
    </button>
  </section>

  <template v-else>
    <section
      v-for="b in items"
      :key="b.id"
      class="card batch"
      @click="router.push(`/batches/${b.id}`)"
    >
      <div class="batch__head">
        <span class="mono">{{ b.batch_no }}</span>
        <span class="expiry" :class="`expiry--${expiryClass(b)}`">{{ expiryText(b) }}</span>
        <span v-if="b.status === 'depleted'" class="tag tag--muted">已耗尽</span>
      </div>
      <div class="batch__body">
        <div class="batch__name">{{ b.ingredient_name }}</div>
        <div class="batch__nums">
          <span
            >剩余 <b>{{ trimNum(b.remaining_weight) }}g</b></span
          >
          <span>成本 ¥{{ b.remaining_cost }} / {{ b.purchase_cost }}</span>
          <span v-if="b.unit_cost">单位 {{ b.unit_cost }} 元/g</span>
        </div>
        <div class="batch__meta">
          <span>购买 {{ b.purchase_date }}</span>
          <span v-if="b.expiry_date">到期 {{ b.expiry_date }}</span>
          <span v-if="b.location_name">{{ b.location_name }}</span>
        </div>
      </div>
    </section>
  </template>
</template>

<style scoped>
.filters {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.filters__input {
  flex: 1;
  min-width: 200px;
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  font-size: 13.5px;
  background: var(--bg-card, #fff);
}
.empty {
  text-align: center;
  padding: 26px 0;
}
.batch {
  cursor: pointer;
  transition: border-color 0.15s ease;
}
.batch:hover {
  border-color: var(--green);
}
.batch__head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.batch__body {
  margin-top: 8px;
}
.batch__name {
  font-size: 15px;
  font-weight: 600;
}
.batch__nums {
  display: flex;
  gap: 16px;
  margin-top: 5px;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  flex-wrap: wrap;
}
.batch__nums b {
  font-size: 14px;
}
.batch__meta {
  display: flex;
  gap: 14px;
  margin-top: 5px;
  font-size: 11.5px;
  color: var(--text-3);
  flex-wrap: wrap;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  color: var(--text-3);
}
.expiry {
  font-size: 11.5px;
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 500;
}
.expiry--ok {
  background: var(--green-weak);
  color: var(--green);
}
.expiry--warn {
  background: #fdf3e2;
  color: #b8860b;
}
.expiry--danger {
  background: #fbeae8;
  color: var(--red);
}
.expiry--expired {
  background: var(--red);
  color: #fff;
}
.expiry--muted {
  background: #f0efe9;
  color: var(--text-3);
}
</style>
