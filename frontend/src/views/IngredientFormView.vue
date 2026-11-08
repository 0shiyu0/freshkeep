<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NInputNumber, NSelect, NSwitch, NInput as NNInput } from 'naive-ui'

import { catalogApi, type Category, type NutritionDefinition, type StorageLocation, type Unit } from '@/api/catalog'
import { ingredientApi } from '@/api/ingredients'
import { notifyError, notifySuccess } from '@/utils/notify'

const route = useRoute()
const router = useRouter()
const id = computed(() => (route.params.id ? String(route.params.id) : null))
const isEdit = computed(() => id.value !== null)

const categories = ref<Category[]>([])
const units = ref<Unit[]>([])
const locations = ref<StorageLocation[]>([])
const definitions = ref<NutritionDefinition[]>([])
const loading = ref(true)
const saving = ref(false)

const form = reactive({
  name: '',
  category_id: null as string | null,
  brand: '',
  specification: '',
  default_quantity_unit_id: null as string | null,
  default_weight_unit_id: null as string | null,
  default_unit_weight: null as number | null,
  minimum_quantity: 0 as number | null,
  minimum_weight: 0 as number | null,
  nutrition_basis_amount: null as number | null,
  nutrition_basis_unit_id: null as string | null,
  default_storage_location_id: null as string | null,
  note: '',
  nutrition: {} as Record<string, number | null>,
})

const quantityUnits = computed(() => units.value.filter((u) => u.dimension === 'quantity'))
const weightUnits = computed(() => units.value.filter((u) => u.dimension === 'weight'))
const hasConversion = computed(() => form.default_unit_weight !== null && form.default_unit_weight > 0)

const catOptions = computed(() => {
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
const unitOpt = (list: Unit[]) => list.map((u) => ({ label: `${u.name}${u.symbol && u.symbol !== u.name ? ` (${u.symbol})` : ''}`, value: u.id }))
const locOptions = computed(() => locations.value.map((l) => ({ label: l.name, value: l.id })))

/** 换算提示：明确告诉用户"能算"还是"不能算"，避免误以为系统会猜 */
const conversionHint = computed(() => {
  if (!hasConversion.value) {
    return '未设置每包重量：数量与重量之间没有换算关系，系统不会自动推算。'
  }
  const q = quantityUnits.value.find((u) => u.id === form.default_quantity_unit_id)
  const w = weightUnits.value.find((u) => u.id === form.default_weight_unit_id)
  return `1 ${q?.name ?? '数量单位'} = ${form.default_unit_weight} ${w?.symbol || w?.name || 'g'}`
})

async function load() {
  loading.value = true
  try {
    const [cats, us, locs, defs] = await Promise.all([
      catalogApi.categories(),
      catalogApi.units(),
      catalogApi.locations(),
      catalogApi.nutritionDefinitions(),
    ])
    categories.value = cats.items
    units.value = us.items
    locations.value = locs.items
    definitions.value = defs.items

    if (isEdit.value && id.value) {
      const d = await ingredientApi.detail(id.value)
      Object.assign(form, {
        name: d.name,
        category_id: d.category_id,
        brand: d.brand,
        specification: d.specification,
        default_quantity_unit_id: d.quantity_unit?.id ?? null,
        default_weight_unit_id: d.weight_unit?.id ?? null,
        default_unit_weight: d.default_unit_weight ? Number(d.default_unit_weight) : null,
        minimum_quantity: d.minimum_quantity ? Number(d.minimum_quantity) : 0,
        minimum_weight: d.minimum_weight ? Number(d.minimum_weight) : 0,
        nutrition_basis_amount: d.nutrition.length ? Number(d.nutrition[0].basis_amount) : null,
        nutrition_basis_unit_id: d.weight_unit?.id ?? null,
        default_storage_location_id: d.nutrition.length ? null : null,
        note: d.note,
      })
      for (const n of d.nutrition) form.nutrition[n.code] = Number(n.value)
      const detail = await ingredientApi.detail(id.value)
      form.default_storage_location_id = locations.value.find((l) => l.name === detail.location_name)?.id ?? null
    }
  } finally {
    loading.value = false
  }
}

// 清空数量单位时同步清空换算值，避免留下"有值但没有单位"的半套状态
watch(
  () => form.default_quantity_unit_id,
  (v) => {
    if (!v) form.default_unit_weight = null
  }
)

async function submit() {
  if (!form.name.trim()) {
    notifyError('请填写食材名称')
    return
  }
  if (hasConversion.value && (!form.default_quantity_unit_id || !form.default_weight_unit_id)) {
    notifyError('设置每包重量时，必须同时选择数量单位与重量单位')
    return
  }
  saving.value = true
  try {
    const payload: Record<string, unknown> = {
      name: form.name.trim(),
      category_id: form.category_id,
      brand: form.brand,
      specification: form.specification,
      default_quantity_unit_id: form.default_quantity_unit_id,
      default_weight_unit_id: form.default_weight_unit_id,
      default_unit_weight: form.default_unit_weight === null ? null : String(form.default_unit_weight),
      minimum_quantity: String(form.minimum_quantity ?? 0),
      minimum_weight: String(form.minimum_weight ?? 0),
      nutrition_basis_amount: form.nutrition_basis_amount === null ? null : String(form.nutrition_basis_amount),
      nutrition_basis_unit_id: form.nutrition_basis_unit_id,
      default_storage_location_id: form.default_storage_location_id,
      note: form.note,
      nutrition: Object.entries(form.nutrition)
        .filter(([, v]) => v !== null && v !== undefined)
        .map(([code, value]) => ({
          code,
          value: String(value),
          basis_amount: String(form.nutrition_basis_amount ?? 100),
          basis_unit_id: form.nutrition_basis_unit_id ?? form.default_weight_unit_id,
        })),
    }

    if (isEdit.value && id.value) {
      await ingredientApi.update(id.value, payload)
      notifySuccess('已保存')
      router.push(`/ingredients/${id.value}`)
    } else {
      const res = await ingredientApi.create(payload)
      notifySuccess('食材已创建')
      router.push(`/ingredients/${res.id}`)
    }
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-if="loading" class="empty"><p>加载中…</p></div>

  <template v-else>
    <div class="page-head">
      <div>
        <h1>{{ isEdit ? '编辑食材' : '新增食材' }}</h1>
        <p>带 * 为必填。数量与重量是两个独立维度，需显式设置换算关系。</p>
      </div>
      <div style="display: flex; gap: 8px">
        <button class="btn" @click="router.back()">取消</button>
        <button class="btn btn--primary" :disabled="saving" @click="submit">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </div>
    </div>

    <section class="card">
      <h2>基础信息</h2>
      <div class="field">
        <label>食材名称 *</label>
        <NNInput v-model:value="form.name" placeholder="如：鸡胸肉" maxlength="50" />
      </div>
      <div class="field">
        <label>分类</label>
        <NSelect v-model:value="form.category_id" :options="catOptions" placeholder="选择分类" clearable />
      </div>
      <div class="field-row">
        <div class="field">
          <label>品牌</label>
          <NNInput v-model:value="form.brand" placeholder="如：圣农" maxlength="50" />
        </div>
        <div class="field">
          <label>规格</label>
          <NNInput v-model:value="form.specification" placeholder="如：500g/袋" maxlength="50" />
        </div>
      </div>
    </section>

    <section class="card">
      <h2>计量与换算</h2>
      <div class="field-row">
        <div class="field">
          <label>默认数量单位</label>
          <NSelect v-model:value="form.default_quantity_unit_id" :options="unitOpt(quantityUnits)" placeholder="如：包" clearable />
        </div>
        <div class="field">
          <label>默认重量单位</label>
          <NSelect v-model:value="form.default_weight_unit_id" :options="unitOpt(weightUnits)" placeholder="如：克" clearable />
        </div>
      </div>

      <div class="field">
        <label>
          每包重量（克）
          <span class="field__hint">留空 = 无换算关系</span>
        </label>
        <NInputNumber
          v-model:value="form.default_unit_weight"
          :min="0"
          :precision="3"
          placeholder="如：250 表示 1 包 = 250 克"
          style="width: 100%"
          :disabled="!form.default_quantity_unit_id || !form.default_weight_unit_id"
        />
        <p class="field__note" :class="{ 'field__note--warn': !hasConversion }">{{ conversionHint }}</p>
      </div>
    </section>

    <section class="card">
      <h2>库存策略</h2>
      <div class="field-row">
        <div class="field">
          <label>最低库存（数量）</label>
          <NInputNumber v-model:value="form.minimum_quantity" :min="0" :precision="3" style="width: 100%" />
        </div>
        <div class="field">
          <label>最低库存（重量）</label>
          <NInputNumber v-model:value="form.minimum_weight" :min="0" :precision="3" style="width: 100%" />
        </div>
      </div>
      <div class="field">
        <label>储存位置</label>
        <NSelect v-model:value="form.default_storage_location_id" :options="locOptions" placeholder="如：冷冻室" clearable />
      </div>
    </section>

    <section class="card">
      <h2>营养基准</h2>
      <div class="field-row">
        <div class="field">
          <label>基准量</label>
          <NInputNumber v-model:value="form.nutrition_basis_amount" :min="0" :precision="3" placeholder="如：100" style="width: 100%" />
        </div>
        <div class="field">
          <label>基准单位</label>
          <NSelect v-model:value="form.nutrition_basis_unit_id" :options="unitOpt(units)" placeholder="如：克" clearable />
        </div>
      </div>

      <div v-for="d in definitions" :key="d.code" class="field field--inline">
        <label>{{ d.name }}（{{ d.unit }}）</label>
        <NInputNumber
          v-model:value="form.nutrition[d.code]"
          :min="0"
          :precision="4"
          placeholder="未填则不统计"
          style="width: 160px"
        />
      </div>
    </section>

    <section class="card">
      <h2>备注</h2>
      <NNInput v-model:value="form.note" type="textarea" :rows="2" maxlength="500" show-count placeholder="可选" />
    </section>

    <div class="save-bar">
      <button class="btn btn--primary" :disabled="saving" @click="submit">
        {{ saving ? '保存中…' : isEdit ? '保存修改' : '创建食材' }}
      </button>
    </div>
  </template>
</template>

<style scoped>
.field { margin-bottom: 12px; }
.field:last-child { margin-bottom: 0; }
.field > label {
  display: block;
  font-size: 12.5px;
  color: var(--text-2);
  margin-bottom: 6px;
}
.field__hint { color: var(--text-3); font-size: 11.5px; margin-left: 4px; }
.field__note { font-size: 11.5px; margin-top: 6px; color: var(--text-3); }
.field__note--warn { color: var(--amber); }
.field-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.field--inline { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.field--inline > label { margin-bottom: 0; }
.save-bar { display: flex; justify-content: flex-end; margin-top: 14px; }
@media (max-width: 640px) {
  .field-row { grid-template-columns: 1fr; }
}
</style>
