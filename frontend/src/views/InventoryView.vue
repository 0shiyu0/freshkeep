<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NSelect } from 'naive-ui'

import { catalogApi, type Category, type StorageLocation } from '@/api/catalog'
import { ingredientApi, type IngredientListItem } from '@/api/ingredients'
import { inventoryApi, trimNum, type InventorySummary } from '@/api/inventory'

const router = useRouter()

const keyword = ref('')
const categoryId = ref<string | null>(null)
const locationId = ref<string | null>(null)
const includeInactive = ref(false)
const items = ref<IngredientListItem[]>([])
const total = ref(0)
const loading = ref(false)
const categories = ref<Category[]>([])
const locations = ref<StorageLocation[]>([])
const summary = ref<InventorySummary | null>(null)

const categoryOptions = computed(() => {
  const parents = categories.value.filter((c) => !c.parent_id)
  const opts: Array<{ label: string; value: string }> = []
  for (const p of parents) {
    opts.push({ label: p.name, value: p.id })
    for (const child of categories.value.filter((c) => c.parent_id === p.id)) {
      opts.push({ label: `　${child.name}`, value: child.id })
    }
  }
  return opts
})

const locationOptions = computed(() =>
  locations.value.map((l) => ({ label: l.name, value: l.id }))
)

async function loadSummary() {
  try {
    summary.value = await inventoryApi.summary()
  } catch {
    // 汇总失败不阻塞列表：链路异常时页面其余部分仍可用
  }
}

let timer: number | undefined
async function load() {
  loading.value = true
  try {
    const res = await ingredientApi.list({
      q: keyword.value.trim() || undefined,
      category_id: categoryId.value ?? undefined,
      location_id: locationId.value ?? undefined,
      include_inactive: includeInactive.value || undefined,
      page_size: 50,
    })
    items.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

watch([keyword, categoryId, locationId, includeInactive], () => {
  window.clearTimeout(timer)
  timer = window.setTimeout(load, 260)
})

onMounted(async () => {
  void loadSummary()
  const [cats, locs] = await Promise.all([catalogApi.categories(), catalogApi.locations()])
  categories.value = cats.items
  locations.value = locs.items
  await load()
})
</script>

<template>
  <div class="page-head">
    <div>
      <h1>库存食材</h1>
      <p>共 {{ total }} 个食材 · 支持中文、拼音全拼与首字母搜索</p>
    </div>
    <div class="head-actions">
      <button class="btn" @click="router.push('/consume')">− 记一笔消耗</button>
      <button class="btn" @click="router.push('/batches')">批次</button>
      <button class="btn" @click="router.push('/purchase')">+ 采购入库</button>
      <button class="btn btn--primary" @click="router.push('/ingredients/new')">+ 新增食材</button>
    </div>
  </div>

  <div v-if="summary" class="card summary-bar">
    <div><span>库存总价值</span><b>¥{{ summary.total_cost }}</b></div>
    <div><span>总重量</span><b>{{ trimNum(summary.total_weight) }} g</b></div>
    <div><span>食材 / 批次</span><b>{{ summary.ingredient_count }} / {{ summary.batch_count }}</b></div>
    <div><span>临期 7 天内</span><b :class="{ 'summary-bar__alert': summary.expiring_count > 0 }">{{ summary.expiring_count }}</b></div>
    <div><span>低库存</span><b :class="{ 'summary-bar__alert': summary.low_stock_count > 0 }">{{ summary.low_stock_count }}</b></div>
  </div>

  <div class="filters card">
    <input v-model="keyword" class="filters__input" placeholder="搜索：鸡胸肉 / jixiongrou / jxr" />
    <n-select
      v-model:value="categoryId"
      :options="categoryOptions"
      placeholder="全部分类"
      clearable
      size="small"
      style="width: 150px"
    />
    <n-select
      v-model:value="locationId"
      :options="locationOptions"
      placeholder="全部位置"
      clearable
      size="small"
      style="width: 130px"
    />
    <label class="filters__check">
      <input v-model="includeInactive" type="checkbox" />
      含停用
    </label>
  </div>

  <div v-if="loading" class="empty"><p>加载中…</p></div>

  <div v-else-if="items.length === 0" class="empty">
    <span class="empty__icon">🧺</span>
    <h3>还没有匹配的食材</h3>
    <p>换个关键词，或先新增一个食材档案。<br />示例：鸡胸肉 · 250g/包 · 冷冻室</p>
  </div>

  <div v-else class="list">
    <article
      v-for="item in items"
      :key="item.id"
      class="row card"
      :class="{ 'row--off': !item.is_active }"
      @click="router.push(`/ingredients/${item.id}`)"
    >
      <div class="row__thumb">
        <img v-if="item.image_url" :src="item.image_url" :alt="item.name" />
        <span v-else>{{ item.name.slice(0, 1) }}</span>
      </div>
      <div class="row__main">
        <div class="row__title">
          <strong>{{ item.name }}</strong>
          <span v-if="!item.is_active" class="tag tag--muted">已停用</span>
        </div>
        <div class="row__meta">
          <span class="tag">{{ item.category_path }}</span>
          <span v-if="item.location_name" class="row__loc">{{ item.location_name }}</span>
        </div>
      </div>
      <div class="row__side">
        <div class="row__unit">{{ item.unit_weight_display }}</div>
        <div class="row__min">最低 {{ item.minimum_stock_display }}</div>
      </div>
    </article>
  </div>
</template>

<style scoped>
.filters {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  padding: 12px;
  margin-bottom: 14px;
}
.filters__input {
  flex: 1;
  min-width: 180px;
  height: 32px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: 9px;
  font-size: 13px;
  background: var(--surface);
  color: var(--text);
  outline: none;
}
.filters__input:focus { border-color: var(--green); }
.filters__check {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12.5px;
  color: var(--text-2);
  cursor: pointer;
}
.list { display: flex; flex-direction: column; gap: 10px; }
.row {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 14px;
  cursor: pointer;
  transition: border-color .15s, transform .15s;
}
.row:hover { border-color: #d6d0c2; transform: translateY(-1px); }
.row--off { opacity: .62; }
.row__thumb {
  width: 52px; height: 52px;
  border-radius: 10px;
  background: var(--green-weak);
  display: grid; place-items: center;
  overflow: hidden;
  flex: none;
  font-weight: 700;
  color: var(--green);
}
.row__thumb img { width: 100%; height: 100%; object-fit: cover; }
.row__main { flex: 1; min-width: 0; }
.row__title { display: flex; align-items: center; gap: 8px; }
.row__title strong { font-size: 15px; }
.row__meta { display: flex; align-items: center; gap: 8px; margin-top: 5px; }
.row__loc { font-size: 12px; color: var(--text-3); }
.row__side { text-align: right; flex: none; }
.row__unit { font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }
.row__min { font-size: 11.5px; color: var(--text-3); margin-top: 3px; }

.summary-bar { display: flex; gap: 30px; flex-wrap: wrap; }
.summary-bar div { display: flex; flex-direction: column; gap: 3px; }
.summary-bar span { font-size: 11.5px; color: var(--text-3); }
.summary-bar b { font-size: 17px; font-variant-numeric: tabular-nums; }
.summary-bar__alert { color: var(--red); }
@media (max-width: 720px) { .summary-bar { gap: 18px; } .summary-bar b { font-size: 15px; } }
</style>
