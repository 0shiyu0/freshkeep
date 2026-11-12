<script setup lang="ts">
/** 菜谱（阶段 8.11）：列表、搜索、新建/编辑（含食材需求行）。 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NSelect } from 'naive-ui'

import { ingredientApi, type IngredientListItem } from '@/api/ingredients'
import { recipeApi, type RecipeListItem } from '@/api/recipes'
import { notifyError, notifySuccess } from '@/utils/notify'

const router = useRouter()
const items = ref<RecipeListItem[]>([])
const total = ref(0)
const loading = ref(false)
const keyword = ref('')

const modal = ref(false)
const editingId = ref<string | null>(null)
const busy = ref(false)
const ingredients = ref<IngredientListItem[]>([])
const form = reactive<{
  name: string
  category: string
  servings: string
  duration_minutes: string
  steps: string
  note: string
  items: Array<{ ingredient_id: string | null; weight: string; quantity: string }>
}>({
  name: '',
  category: '',
  servings: '1',
  duration_minutes: '',
  steps: '',
  note: '',
  items: [{ ingredient_id: null, weight: '', quantity: '' }],
})

const options = computed(() => ingredients.value.map((i) => ({ label: i.name, value: i.id })))

async function load() {
  loading.value = true
  try {
    const res = await recipeApi.list({
      page_size: 50,
      ...(keyword.value.trim() ? { q: keyword.value.trim() } : {}),
    })
    items.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

async function loadIngredients() {
  const res = await ingredientApi.list({ page_size: 200 })
  ingredients.value = res.items
}

function openCreate() {
  editingId.value = null
  Object.assign(form, {
    name: '',
    category: '',
    servings: '1',
    duration_minutes: '',
    steps: '',
    note: '',
  })
  form.items = [{ ingredient_id: null, weight: '', quantity: '' }]
  modal.value = true
}

async function openEdit(id: string) {
  try {
    const d = await recipeApi.detail(id)
    editingId.value = id
    Object.assign(form, {
      name: d.name,
      category: d.category,
      servings: Number(d.servings).toString(),
      duration_minutes: d.duration_minutes == null ? '' : String(d.duration_minutes),
      steps: d.steps,
      note: d.note,
    })
    form.items = d.items.map((i) => ({
      ingredient_id: i.ingredient_id,
      weight: i.weight ? String(Number(i.weight)) : '',
      quantity: i.quantity ? String(Number(i.quantity)) : '',
    }))
    modal.value = true
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '加载失败')
  }
}

function addRow() {
  form.items.push({ ingredient_id: null, weight: '', quantity: '' })
}

function removeRow(idx: number) {
  if (form.items.length <= 1) return
  form.items.splice(idx, 1)
}

async function save() {
  if (busy.value) return
  const rows = form.items
    .filter((r) => r.ingredient_id && (Number(r.weight) > 0 || Number(r.quantity) > 0))
    .map((r) => ({
      ingredient_id: r.ingredient_id,
      weight: r.weight.trim() || undefined,
      quantity: r.quantity.trim() || undefined,
    }))
  if (!form.name.trim()) return notifyError('请填写菜谱名称')
  if (rows.length === 0) return notifyError('至少填一项食材与用量')
  busy.value = true
  try {
    const payload = {
      name: form.name.trim(),
      category: form.category.trim(),
      servings: form.servings || '1',
      duration_minutes: form.duration_minutes ? Number(form.duration_minutes) : null,
      steps: form.steps,
      note: form.note,
      items: rows,
    }
    if (editingId.value) await recipeApi.update(editingId.value, payload)
    else await recipeApi.create(payload)
    notifySuccess(editingId.value ? '菜谱已更新' : '菜谱已创建')
    modal.value = false
    await load()
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '保存失败')
  } finally {
    busy.value = false
  }
}

async function remove(id: string) {
  if (!window.confirm('删除这个菜谱？')) return
  try {
    await recipeApi.remove(id)
    notifySuccess('已删除')
    await load()
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '删除失败')
  }
}

let timer: number | undefined
watch(keyword, () => {
  window.clearTimeout(timer)
  timer = window.setTimeout(load, 250)
})
onMounted(async () => {
  await loadIngredients()
  await load()
})
</script>

<template>
  <div class="page-head">
    <div>
      <h1>菜谱</h1>
      <p>共 {{ total }} 个菜谱 · 可查看现有库存能否做成，并按缺口生成采购清单</p>
    </div>
    <div class="head-actions">
      <button class="btn" @click="router.push('/shopping-lists')">采购清单</button>
      <button class="btn btn--primary" @click="openCreate">+ 新建菜谱</button>
    </div>
  </div>

  <section class="card filters">
    <input v-model="keyword" class="filters__input" placeholder="搜索菜谱名称或分类" />
  </section>

  <div v-if="loading" class="card empty"><p>加载中…</p></div>
  <section v-else-if="items.length === 0" class="card empty">
    <h3>{{ keyword ? '没有匹配的菜谱' : '还没有菜谱' }}</h3>
    <p>建一个菜谱，就能看到库存够不够、缺多少。</p>
    <button class="btn btn--primary" style="margin-top: 10px" @click="openCreate">
      + 新建菜谱
    </button>
  </section>

  <div v-else class="list">
    <article
      v-for="r in items"
      :key="r.id"
      class="row card"
      @click="router.push(`/recipes/${r.id}`)"
    >
      <div class="row__main">
        <div class="row__title">
          <strong>{{ r.name }}</strong>
          <span v-if="r.category" class="tag">{{ r.category }}</span>
        </div>
        <div class="row__meta">
          <span>{{ r.item_count }} 种食材</span>
          <span v-if="r.duration_minutes">{{ r.duration_minutes }} 分钟</span>
          <span>{{ Number(r.servings) }} 份</span>
        </div>
      </div>
      <div class="row__ops">
        <button class="btn btn--tiny" @click.stop="openEdit(r.id)">编辑</button>
        <button class="btn btn--tiny" @click.stop="remove(r.id)">删除</button>
      </div>
    </article>
  </div>

  <!-- 新建/编辑 -->
  <div v-if="modal" class="modal-mask" @click.self="modal = false">
    <div class="modal">
      <h3>{{ editingId ? '编辑菜谱' : '新建菜谱' }}</h3>
      <div class="grid2">
        <label class="field">名称<input v-model="form.name" placeholder="如 鸡胸肉沙拉" /></label>
        <label class="field"
          >分类<input v-model="form.category" placeholder="可选，如 减脂餐"
        /></label>
        <label class="field">份数<input v-model="form.servings" inputmode="decimal" /></label>
        <label class="field"
          >时长（分钟）<input
            v-model="form.duration_minutes"
            inputmode="numeric"
            placeholder="可选"
        /></label>
      </div>
      <label class="field"
        >步骤<textarea v-model="form.steps" rows="3" placeholder="每行一步" />
      </label>

      <h4>食材需求</h4>
      <div v-for="(row, idx) in form.items" :key="idx" class="item-row">
        <NSelect
          v-model:value="row.ingredient_id"
          :options="options"
          filterable
          placeholder="选择食材"
          size="small"
          style="flex: 1"
        />
        <input v-model="row.weight" inputmode="decimal" placeholder="重量 g" />
        <input v-model="row.quantity" inputmode="decimal" placeholder="数量" />
        <button class="btn btn--tiny" @click="removeRow(idx)">删</button>
      </div>
      <button class="btn btn--ghost" style="margin-top: 8px" @click="addRow">+ 加一项</button>

      <div class="modal__foot">
        <button class="btn" @click="modal = false">取消</button>
        <NButton type="primary" :loading="busy" @click="save">保存</NButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
.filters {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 12px;
  margin-bottom: 14px;
}
.filters__input {
  flex: 1;
  height: 32px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: 9px;
  font-size: 13px;
}
.list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  cursor: pointer;
  flex-wrap: wrap;
}
.row__main {
  flex: 1;
  min-width: 160px;
}
.row__title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.row__title strong {
  font-size: 15px;
}
.row__meta {
  display: flex;
  gap: 12px;
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-3);
  flex-wrap: wrap;
}
.row__ops {
  display: flex;
  gap: 6px;
}
.btn--tiny {
  padding: 3px 9px;
  font-size: 11.5px;
  border-radius: 6px;
}
.empty {
  text-align: center;
  padding: 26px 0;
}

.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.28);
  display: grid;
  place-items: center;
  z-index: 50;
}
.modal {
  background: #fff;
  border-radius: 14px;
  padding: 18px 20px;
  width: min(560px, 94vw);
  max-height: 88vh;
  overflow: auto;
}
.modal h3 {
  margin: 0 0 12px;
  font-size: 15px;
}
.modal h4 {
  font-size: 13px;
  margin: 14px 0 6px;
}
.grid2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12.5px;
  color: var(--text-2);
  margin-bottom: 8px;
}
.field input,
.field textarea {
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  font-size: 14px;
  font-family: inherit;
}
.item-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
}
.item-row input {
  width: 88px;
  height: 30px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 7px;
  font-size: 12.5px;
  text-align: right;
}
.modal__foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}
@media (max-width: 720px) {
  .grid2 {
    grid-template-columns: 1fr;
  }
  .item-row {
    flex-wrap: wrap;
  }
}
</style>
