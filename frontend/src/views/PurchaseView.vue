<script setup lang="ts">
/** 采购入库（阶段 3）：独立页面，食材可搜索选择，四个日期齐全。
 *  每次提交都由后端生成独立批次 + purchase 流水（同事务），前端不拼装业务数据。 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NSelect } from 'naive-ui'

import { ingredientApi, type IngredientListItem } from '@/api/ingredients'
import { batchApi, type BatchCreateInput, type BatchItem } from '@/api/batches'
import { catalogApi, type StorageLocation } from '@/api/catalog'
import { notifyError, notifySuccess } from '@/utils/notify'

const route = useRoute()
const router = useRouter()

const ingredients = ref<IngredientListItem[]>([])
const locations = ref<StorageLocation[]>([])
const loading = ref(false)
const submitting = ref(false)
const result = ref<{ batch: BatchItem; transaction: { transaction_no: string } } | null>(null)

const picked = ref<string | null>(null)
const form = reactive({
  purchase_date: new Date().toISOString().slice(0, 10),
  production_date: '',
  expiry_date: '',
  opened_date: '',
  storage_location_id: '',
  quantity: '',
  weight: '',
  purchase_cost: '',
  note: '',
})

const selected = computed(() => ingredients.value.find((i) => i.id === picked.value) ?? null)
const options = computed(() => ingredients.value.map((i) => ({ label: i.name, value: i.id })))
const locationOptions = computed(() => locations.value.map((l) => ({ label: l.name, value: l.id })))
const canSubmit = computed(() => {
  if (!picked.value || submitting.value) return false
  return Number(form.weight) > 0 || Number(form.quantity) > 0
})
/** 单位成本预览：只有填了价格和重量才有意义，纯展示不参与计算 */
const unitCostPreview = computed(() => {
  const w = Number(form.weight)
  const c = Number(form.purchase_cost)
  if (!(w > 0) || !(c >= 0)) return '—'
  return (c / w).toFixed(4)
})

async function load() {
  loading.value = true
  try {
    const [ings, locs] = await Promise.all([
      ingredientApi.list({ page_size: 200 }),
      catalogApi.locations(),
    ])
    ingredients.value = ings.items
    locations.value = locs.items
    const preset = String(route.query.ingredient || '')
    if (preset && ings.items.some((i) => i.id === preset)) picked.value = preset
    else if (ings.items.length === 1) picked.value = ings.items[0].id
  } finally {
    loading.value = false
  }
}

function resetForm() {
  form.quantity = ''
  form.weight = ''
  form.purchase_cost = ''
  form.expiry_date = ''
  form.production_date = ''
  form.opened_date = ''
  form.note = ''
}

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  result.value = null
  try {
    const payload: BatchCreateInput = {
      ingredient_id: picked.value,
      purchase_date: form.purchase_date || undefined,
      production_date: form.production_date || null,
      expiry_date: form.expiry_date || null,
      opened_date: form.opened_date || null,
      storage_location_id: form.storage_location_id || null,
      quantity: form.quantity.trim() || '0',
      weight: form.weight.trim() || '0',
      purchase_cost: form.purchase_cost.trim() || '0',
      quantity_unit_id: selected.value?.quantity_unit?.id ?? null,
      weight_unit_id: selected.value?.weight_unit?.id ?? null,
      note: form.note.trim(),
    }
    const res = await batchApi.create(payload)
    result.value = res
    notifySuccess(`入库成功：批次 ${res.batch.batch_no}`)
    resetForm()
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '入库失败')
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page-head">
    <div>
      <h1>采购入库</h1>
      <p>每次入库生成一个独立批次，并自动写入 purchase 库存流水</p>
    </div>
    <div class="head-actions">
      <button class="btn" @click="router.push('/batches')">批次列表</button>
      <button class="btn" @click="router.push('/inventory')">返回库存</button>
    </div>
  </div>

  <section class="card">
    <div class="form-row">
      <label class="grow">食材
        <NSelect v-model:value="picked" :options="options" filterable placeholder="搜索食材名称 / 拼音"
                 :loading="loading" />
      </label>
    </div>

    <div class="form-row">
      <label>数量（{{ selected?.quantity_unit?.name || '数量' }}）
        <input v-model="form.quantity" inputmode="decimal" placeholder="如 2，可留空" /></label>
      <label>重量（{{ selected?.weight_unit?.symbol || 'g' }}）
        <input v-model="form.weight" inputmode="decimal" placeholder="如 500" /></label>
      <label>采购总价（元）
        <input v-model="form.purchase_cost" inputmode="decimal" placeholder="如 18.00" /></label>
      <label>单位成本（元/克，自动算）
        <input :value="unitCostPreview" readonly class="readonly" /></label>
    </div>

    <div class="form-row">
      <label>购买日期<input v-model="form.purchase_date" type="date" /></label>
      <label>生产日期<input v-model="form.production_date" type="date" /></label>
      <label>到期日期<input v-model="form.expiry_date" type="date" /></label>
      <label>开封日期<input v-model="form.opened_date" type="date" /></label>
    </div>

    <div class="form-row">
      <label class="grow">储存位置
        <NSelect v-model:value="form.storage_location_id" :options="locationOptions"
                 placeholder="如 冷冻室 / 冷藏室 / 常温" clearable /></label>
      <label class="grow">备注
        <input v-model="form.note" placeholder="可留空，如「超市促销」" /></label>
    </div>

    <p class="hint">
      数量与重量至少填一项；有换算关系时只填数量会自动折算重量。
      到期日期不能早于生产日期；单位成本由后端按批次核算，这里只是预览。
    </p>
    <div class="submit-line">
      <span v-if="selected" class="muted">
        {{ selected.name }} · {{ selected.category_path }}
        <template v-if="selected.unit_weight_display"> · {{ selected.unit_weight_display }}</template>
      </span>
      <NButton type="primary" :disabled="!canSubmit" :loading="submitting" @click="submit">确认入库</NButton>
    </div>
  </section>

  <section v-if="result" class="card">
    <h2>入库成功 · {{ result.batch.batch_no }}</h2>
    <div class="result-grid">
      <div><span>初始 / 剩余重量</span><b>{{ result.batch.initial_weight }} / {{ result.batch.remaining_weight }} g</b></div>
      <div><span>采购成本</span><b>¥{{ result.batch.purchase_cost }}</b></div>
      <div><span>单位成本</span><b>{{ result.batch.unit_cost ?? '—' }} 元/g</b></div>
      <div><span>流水号</span><b class="mono">{{ result.transaction.transaction_no }}</b></div>
    </div>
    <div class="head-actions">
      <button class="btn" @click="router.push(`/batches/${result.batch.id}`)">查看批次详情</button>
      <button class="btn" @click="result = null">继续入库</button>
    </div>
  </section>

  <section v-else-if="!loading && ingredients.length === 0" class="card empty">
    <h3>还没有食材档案</h3>
    <p>先建一个食材，再录入采购。</p>
    <button class="btn btn--primary" style="margin-top: 10px" @click="router.push('/ingredients/new')">
      + 新增食材
    </button>
  </section>
</template>

<style scoped>
.form-row { display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 12px; }
.form-row label { display: flex; flex-direction: column; gap: 5px; font-size: 12.5px; color: var(--text-2); min-width: 160px; }
.form-row label.grow { flex: 1; min-width: 220px; }
.form-row input {
  height: 34px; padding: 0 10px; border: 1px solid var(--line); border-radius: 8px;
  background: var(--bg-card, #fff); font-size: 14px;
}
.form-row input.readonly { background: #f6f5f1; color: var(--text-2); }
.hint { font-size: 11.5px; color: var(--text-3); margin: 4px 0 14px; }
.submit-line { display: flex; align-items: center; justify-content: space-between; gap: 14px; flex-wrap: wrap; }
.muted { color: var(--text-3); font-size: 12.5px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.result-grid { display: flex; gap: 26px; margin: 12px 0 16px; flex-wrap: wrap; }
.result-grid div { display: flex; flex-direction: column; gap: 4px; }
.result-grid span { font-size: 12px; color: var(--text-3); }
.result-grid b { font-size: 16px; font-variant-numeric: tabular-nums; }
.empty { text-align: center; padding: 26px 0; }
@media (max-width: 720px) { .form-row label { min-width: 100%; } .submit-line { justify-content: flex-start; } }
</style>
