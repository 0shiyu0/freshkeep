<script setup lang="ts">
/** 消耗录入（M4）：按 FEFO 自动分配批次，展示成本分摊与营养快照。 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NSelect } from 'naive-ui'

import { ingredientApi, type IngredientListItem } from '@/api/ingredients'
import { batchApi, type BatchItem } from '@/api/batches'
import { consumptionApi, type ConsumptionResult } from '@/api/consumptions'
import { notifyError, notifySuccess } from '@/utils/notify'

const route = useRoute()
const router = useRouter()

const ingredients = ref<IngredientListItem[]>([])
const picked = ref<string | null>(null)
const weight = ref('')
const quantity = ref('')
const note = ref('')
const batches = ref<BatchItem[]>([])
const result = ref<ConsumptionResult | null>(null)
const loading = ref(false)
const submitting = ref(false)

const selected = computed(() => ingredients.value.find((i) => i.id === picked.value) ?? null)
const options = computed(() =>
  ingredients.value.map((i) => ({ label: i.name, value: i.id }))
)
const available = computed(() =>
  batches.value.reduce((sum, b) => sum + Number(b.remaining_weight || 0), 0)
)
const canSubmit = computed(() =>
  !!picked.value && (Number(weight.value) > 0 || Number(quantity.value) > 0) && !submitting.value
)

async function loadIngredients() {
  const res = await ingredientApi.list({ page_size: 100 })
  ingredients.value = res.items
  const fromQuery = String(route.query.ingredient || '')
  if (fromQuery && res.items.some((i) => i.id === fromQuery)) picked.value = fromQuery
}

async function loadBatches() {
  if (!picked.value) return (batches.value = [])
  const res = await batchApi.list({ ingredient_id: picked.value, status: 'active', page_size: 100 })
  batches.value = res.items.filter((b) => Number(b.remaining_weight) > 0 || Number(b.remaining_quantity) > 0)
}

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  result.value = null
  try {
    const payload: Record<string, unknown> = {
      ingredient_id: picked.value,
      note: note.value.trim(),
    }
    if (Number(weight.value) > 0) payload.weight = weight.value.trim()
    if (Number(quantity.value) > 0) payload.quantity = quantity.value.trim()
    const res = await consumptionApi.create(payload)
    result.value = res
    notifySuccess(`已记录消耗，成本 ¥${res.consumption.cost}`)
    weight.value = ''
    quantity.value = ''
    await loadBatches()
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '记录失败')
  } finally {
    submitting.value = false
  }
}

watch(picked, () => { result.value = null; void loadBatches() })
onMounted(async () => {
  loading.value = true
  try { await loadIngredients(); await loadBatches() } finally { loading.value = false }
})
</script>

<template>
  <div class="page-head">
    <div>
      <h1>记录消耗</h1>
      <p>按先到期先出（FEFO）自动分配批次，成本与营养同时结算</p>
    </div>
    <button class="btn" @click="router.push('/records')">查看记录</button>
  </div>

  <section class="card">
    <div class="form-row">
      <label>食材
        <NSelect v-model:value="picked" :options="options" filterable placeholder="搜索食材名称"
                 :loading="loading" />
      </label>
      <label>重量（{{ selected?.weight_unit?.symbol || 'g' }}）
        <input v-model="weight" inputmode="decimal" placeholder="如 300" />
      </label>
      <label>数量（{{ selected?.quantity_unit?.name || '数量' }}）
        <input v-model="quantity" inputmode="decimal" placeholder="可留空" />
      </label>
    </div>
    <div class="form-row">
      <label class="grow">备注
        <input v-model="note" placeholder="可留空，如「做沙拉」" />
      </label>
    </div>
    <p class="hint">
      数量与重量至少填一项；只填数量时会按食材的换算关系折算重量，没有换算关系则按数量扣减批次。
    </p>
    <div class="submit-line">
      <span v-if="selected" class="muted">当前可用：{{ available }}g（{{ batches.length }} 个批次）</span>
      <NButton type="primary" :disabled="!canSubmit" :loading="submitting" @click="submit">记录消耗</NButton>
    </div>
  </section>

  <section v-if="result" class="card">
    <h2>本次结果 · {{ result.consumption.consumption_no }}</h2>
    <div class="result-grid">
      <div><span>消耗重量</span><b>{{ result.consumption.weight }}g</b></div>
      <div><span>消耗成本</span><b>¥{{ result.consumption.cost }}</b></div>
      <div><span>分配批次</span><b>{{ result.allocations.length }} 个</b></div>
    </div>
    <h3>批次分配</h3>
    <div v-for="a in result.allocations" :key="a.batch_id" class="alloc">
      <span class="mono">{{ a.batch_no }}</span>
      <span>{{ a.weight_delta }}g</span>
      <span>{{ a.cost_delta }} 元</span>
      <span class="muted">单位成本 {{ a.unit_cost ?? '—' }}</span>
    </div>
    <h3 v-if="result.nutrition.length">营养估算（按库存消耗量，非实际摄入记录）</h3>
    <div v-for="n in result.nutrition" :key="n.code" class="alloc">
      <span>{{ n.name }}</span><span>{{ n.actual_value }} {{ n.unit }}</span>
    </div>
  </section>

  <section v-else-if="!loading && ingredients.length === 0" class="card empty">
    <h3>还没有食材档案</h3>
    <p>先建一个食材并入库，才能记录消耗。</p>
    <button class="btn btn--primary" style="margin-top: 10px" @click="router.push('/ingredients/new')">
      + 新增食材
    </button>
  </section>
</template>

<style scoped>
.form-row { display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 12px; }
.form-row label { display: flex; flex-direction: column; gap: 5px; font-size: 12.5px; color: var(--text-2); min-width: 180px; }
.form-row label.grow { flex: 1; }
.form-row input {
  height: 34px; padding: 0 10px; border: 1px solid var(--line); border-radius: 8px;
  background: var(--bg-card, #fff); font-size: 14px;
}
.hint { font-size: 11.5px; color: var(--text-3); margin: 4px 0 14px; }
.submit-line { display: flex; align-items: center; justify-content: flex-end; gap: 14px; }
.muted { color: var(--text-3); font-size: 12.5px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.result-grid { display: flex; gap: 28px; margin: 12px 0 18px; flex-wrap: wrap; }
.result-grid div { display: flex; flex-direction: column; gap: 4px; }
.result-grid span { font-size: 12px; color: var(--text-3); }
.result-grid b { font-size: 18px; font-variant-numeric: tabular-nums; }
h3 { font-size: 13px; margin: 16px 0 8px; }
.alloc {
  display: flex; gap: 18px; padding: 8px 0; font-size: 13px;
  border-top: 1px dashed var(--line); font-variant-numeric: tabular-nums; flex-wrap: wrap;
}
.empty { text-align: center; padding: 28px 0; }
@media (max-width: 720px) {
  .form-row label { min-width: 100%; }
  .submit-line { justify-content: space-between; }
}
</style>
