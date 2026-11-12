<script setup lang="ts">
/** 库存总览（阶段 5）：数据源为 `/inventory`（v_inventory 聚合，与后端一致）。
 *  支持搜索 + 分类 + 状态 + 位置组合筛选、行内快速消耗、多选批量消耗。 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NSelect } from 'naive-ui'

import { catalogApi, type Category, type StorageLocation } from '@/api/catalog'
import { consumptionApi } from '@/api/consumptions'
import { inventoryApi, trimNum, type InventoryRow, type InventorySummary } from '@/api/inventory'
import { notifyError, notifySuccess } from '@/utils/notify'

const router = useRouter()

const items = ref<InventoryRow[]>([])
const total = ref(0)
const loading = ref(false)
const summary = ref<InventorySummary | null>(null)
const categories = ref<Category[]>([])
const locations = ref<StorageLocation[]>([])

const keyword = ref('')
const categoryId = ref<string | null>(null)
const locationId = ref<string | null>(null)
const status = ref<string | null>(null)
const lowStockOnly = ref(false)

// 快速消耗
const quickTarget = ref<InventoryRow | null>(null)
const quickForm = reactive({ weight: '', quantity: '' })
const quickBusy = ref(false)

// 批量消耗
const batchMode = ref(false)
const selected = ref<Set<string>>(new Set())
const batchModal = ref(false)
const batchDraft = reactive<Record<string, string>>({})
const batchBusy = ref(false)

/** 进出批量模式时清空已选，避免把上一次的选择带到新会话（模板只传函数名，便于格式化） */
function toggleBatchMode() {
  batchMode.value = !batchMode.value
  if (!batchMode.value) selected.value = new Set()
}

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '正常', value: 'normal' },
  { label: '临期 7 天', value: 'expiring' },
  { label: '已过期', value: 'expired' },
  { label: '无库存', value: 'out_of_stock' },
]

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
const locationOptions = computed(() => locations.value.map((l) => ({ label: l.name, value: l.id })))
const selectedCount = computed(() => selected.value.size)

let timer: number | undefined
async function load() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page_size: 100 }
    if (keyword.value.trim()) params.q = keyword.value.trim()
    if (categoryId.value) params.category_id = categoryId.value
    if (locationId.value) params.location_id = locationId.value
    if (status.value) params.status = status.value
    if (lowStockOnly.value) params.is_low_stock = true
    const res = await inventoryApi.list(params)
    items.value = res.items
    total.value = res.total
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '加载库存失败')
  } finally {
    loading.value = false
  }
}

async function loadSummary() {
  try {
    summary.value = await inventoryApi.summary()
  } catch {
    // 汇总失败不阻塞列表
  }
}

/** 库存状态标签：正常 / 临期 / 过期 / 无货 */
function rowStatus(item: InventoryRow): { text: string; cls: string } {
  const hasStock = Number(item.total_weight) > 0 || Number(item.total_quantity) > 0
  if (!hasStock) return { text: '无库存', cls: 'st-none' }
  const d = item.days_to_expiry
  if (d === null || d === undefined) return { text: '正常', cls: 'st-ok' }
  if (d < 0) return { text: `已过期 ${-d} 天`, cls: 'st-expired' }
  if (d <= 1) return { text: d === 0 ? '今天到期' : '明天到期', cls: 'st-danger' }
  if (d <= 7) return { text: `剩 ${d} 天`, cls: 'st-warn' }
  return { text: '正常', cls: 'st-ok' }
}

function remainingText(item: InventoryRow): string {
  const w = Number(item.total_weight)
  if (w > 0) return `${trimNum(item.total_weight)}${item.weight_unit_symbol || 'g'}`
  const q = Number(item.total_quantity)
  if (q > 0) return `${trimNum(item.total_quantity)}${item.quantity_unit_name || ''}`
  return '0'
}

// ---- 快速消耗
function openQuick(item: InventoryRow) {
  quickTarget.value = item
  quickForm.weight = ''
  quickForm.quantity = ''
}

async function submitQuick() {
  if (!quickTarget.value || quickBusy.value) return
  const w = quickForm.weight.trim()
  const q = quickForm.quantity.trim()
  if (!w && !q) {
    notifyError('重量与数量至少填一项')
    return
  }
  quickBusy.value = true
  try {
    const payload: Record<string, unknown> = { ingredient_id: quickTarget.value.ingredient_id }
    if (w) payload.weight = w
    if (q) payload.quantity = q
    const res = await consumptionApi.create(payload)
    notifySuccess(`已扣减 ${res.consumption.weight}g，成本 ¥${res.consumption.cost}`)
    quickTarget.value = null
    await Promise.all([load(), loadSummary()])
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '消耗失败')
  } finally {
    quickBusy.value = false
  }
}

// ---- 批量消耗
function toggleSelect(item: InventoryRow) {
  const next = new Set(selected.value)
  const key = item.ingredient_id
  if (next.has(key)) next.delete(key)
  else next.add(key)
  selected.value = next
}

function openBatch() {
  if (selected.value.size === 0) {
    notifyError('先选择要消耗的食材')
    return
  }
  for (const key of Object.keys(batchDraft)) delete batchDraft[key]
  batchModal.value = true
}

async function submitBatch() {
  if (batchBusy.value) return
  const rows = items.value.filter((i) => selected.value.has(i.ingredient_id))
  const payload = rows
    .map((r) => ({ id: r.ingredient_id, v: (batchDraft[r.ingredient_id] || '').trim() }))
    .filter((x) => x.v !== '' && Number(x.v) > 0)
  if (payload.length === 0) {
    notifyError('至少为一个食材填写消耗重量')
    return
  }
  batchBusy.value = true
  try {
    const res = await consumptionApi.createBatch(
      payload.map((p) => ({ ingredient_id: p.id, weight: p.v })),
      '批量消耗',
    )
    notifySuccess(`已批量扣减 ${res.total} 个食材`)
    batchModal.value = false
    selected.value = new Set()
    batchMode.value = false
    await Promise.all([load(), loadSummary()])
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '批量消耗失败（整批已回滚）')
  } finally {
    batchBusy.value = false
  }
}

watch([keyword, categoryId, locationId, status, lowStockOnly], () => {
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
      <h1>库存总览</h1>
      <p>共 {{ total }} 个食材 · 数据来自库存聚合（与后端一致）</p>
    </div>
    <div class="head-actions">
      <button class="btn" @click="router.push('/scan')">扫码 / 识别</button>
      <button class="btn" @click="router.push('/recipes')">菜谱</button>
      <button class="btn" @click="router.push('/stocktake')">盘点 / 报损</button>
      <button class="btn" @click="router.push('/batches')">批次</button>
      <button class="btn" @click="router.push('/purchase')">+ 采购入库</button>
      <button class="btn btn--primary" @click="router.push('/ingredients/new')">+ 新增食材</button>
    </div>
  </div>

  <div v-if="summary" class="card summary-bar">
    <div>
      <span>库存总价值</span><b>¥{{ summary.total_cost }}</b>
    </div>
    <div>
      <span>总重量</span><b>{{ trimNum(summary.total_weight) }} g</b>
    </div>
    <div>
      <span>食材 / 批次</span><b>{{ summary.ingredient_count }} / {{ summary.batch_count }}</b>
    </div>
    <div>
      <span>临期 7 天内</span
      ><b :class="{ 'summary-bar__alert': summary.expiring_count > 0 }">{{
        summary.expiring_count
      }}</b>
    </div>
    <div>
      <span>低库存</span
      ><b :class="{ 'summary-bar__alert': summary.low_stock_count > 0 }">{{
        summary.low_stock_count
      }}</b>
    </div>
  </div>

  <div class="filters card">
    <input v-model="keyword" class="filters__input" placeholder="搜索：鸡胸肉 / jixiongrou / jxr" />
    <NSelect
      v-model:value="categoryId"
      :options="categoryOptions"
      placeholder="全部分类"
      clearable
      size="small"
      style="width: 150px"
    />
    <NSelect
      v-model:value="status"
      :options="statusOptions"
      placeholder="全部状态"
      size="small"
      style="width: 130px"
    />
    <NSelect
      v-model:value="locationId"
      :options="locationOptions"
      placeholder="全部位置"
      clearable
      size="small"
      style="width: 130px"
    />
    <label class="filters__check">
      <input v-model="lowStockOnly" type="checkbox" /> 只看低库存
    </label>
    <button class="btn" :class="{ 'btn--primary': batchMode }" @click="toggleBatchMode">
      {{ batchMode ? '退出批量' : '批量消耗' }}
    </button>
  </div>

  <div v-if="loading" class="empty"><p>加载中…</p></div>

  <div v-else-if="items.length === 0" class="empty">
    <span class="empty__icon">🧺</span>
    <h3>没有匹配的食材</h3>
    <p>换个筛选条件，或先入库。<br />提示：状态「无库存」可以找出还没入库的食材。</p>
  </div>

  <div v-else class="list">
    <article
      v-for="item in items"
      :key="item.ingredient_id"
      class="row card"
      @click="batchMode ? toggleSelect(item) : router.push(`/ingredients/${item.ingredient_id}`)"
    >
      <label v-if="batchMode" class="row__check" @click.stop>
        <input
          type="checkbox"
          :checked="selected.has(item.ingredient_id)"
          @change="toggleSelect(item)"
        />
      </label>
      <div class="row__main">
        <div class="row__title">
          <strong>{{ item.name }}</strong>
          <span class="st" :class="rowStatus(item).cls">{{ rowStatus(item).text }}</span>
          <span v-if="item.is_low_stock" class="tag tag--warn">低库存</span>
        </div>
        <div class="row__meta">
          <span class="tag">{{ item.category_path }}</span>
          <span class="row__sub">{{ item.batch_count }} 个批次</span>
        </div>
      </div>
      <div class="row__side">
        <div class="row__qty">{{ remainingText(item) }}</div>
        <div class="row__cost">¥{{ item.total_cost }}</div>
      </div>
      <button v-if="!batchMode" class="btn btn--tiny row__quick" @click.stop="openQuick(item)">
        − 消耗
      </button>
    </article>
  </div>

  <!-- 批量操作栏 -->
  <div v-if="batchMode" class="batch-bar">
    <span>已选 {{ selectedCount }} 项</span>
    <button class="btn" @click="selected = new Set(items.map((i) => i.ingredient_id))">全选</button>
    <button class="btn btn--primary" :disabled="selectedCount === 0" @click="openBatch">
      批量消耗
    </button>
  </div>

  <!-- 快速消耗弹层 -->
  <div v-if="quickTarget" class="modal-mask" @click.self="quickTarget = null">
    <div class="modal">
      <h3>消耗 · {{ quickTarget.name }}</h3>
      <p class="muted">当前可用 {{ remainingText(quickTarget) }}，按先到期先出扣减</p>
      <label class="field"
        >重量（{{ quickTarget.weight_unit_symbol || 'g' }}）
        <input v-model="quickForm.weight" inputmode="decimal" placeholder="如 100" />
      </label>
      <label class="field"
        >数量（{{ quickTarget.quantity_unit_name || '数量' }}）
        <input v-model="quickForm.quantity" inputmode="decimal" placeholder="可留空" />
      </label>
      <div class="modal__foot">
        <button class="btn" @click="quickTarget = null">取消</button>
        <NButton type="primary" :loading="quickBusy" @click="submitQuick">确认消耗</NButton>
      </div>
    </div>
  </div>

  <!-- 批量消耗弹层 -->
  <div v-if="batchModal" class="modal-mask" @click.self="batchModal = false">
    <div class="modal">
      <h3>批量消耗（{{ selectedCount }} 项）</h3>
      <p class="muted">只填需要消耗的重量；留空的项不提交。整批失败会全部回滚。</p>
      <div
        v-for="item in items.filter((i) => selected.has(i.ingredient_id))"
        :key="item.ingredient_id"
        class="batch-row"
      >
        <span class="batch-row__name">{{ item.name }}</span>
        <span class="muted">{{ remainingText(item) }}</span>
        <input v-model="batchDraft[item.ingredient_id]" inputmode="decimal" placeholder="重量 g" />
      </div>
      <div class="modal__foot">
        <button class="btn" @click="batchModal = false">取消</button>
        <NButton type="primary" :loading="batchBusy" @click="submitBatch">提交批量消耗</NButton>
      </div>
    </div>
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
.filters__input:focus {
  border-color: var(--green);
}
.filters__check {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12.5px;
  color: var(--text-2);
  cursor: pointer;
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
  transition:
    border-color 0.15s,
    transform 0.15s;
}
.row:hover {
  border-color: #d6d0c2;
  transform: translateY(-1px);
}
.row__check {
  display: flex;
  align-items: center;
}
.row__main {
  flex: 1;
  min-width: 0;
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
  align-items: center;
  gap: 8px;
  margin-top: 5px;
  flex-wrap: wrap;
}
.row__sub {
  font-size: 12px;
  color: var(--text-3);
}
.row__side {
  text-align: right;
  flex: none;
}
.row__qty {
  font-size: 14px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.row__cost {
  font-size: 11.5px;
  color: var(--text-3);
  margin-top: 3px;
}
.row__quick {
  flex: none;
}

.st {
  font-size: 11.5px;
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 500;
}
.st-ok {
  background: var(--green-weak);
  color: var(--green);
}
.st-warn {
  background: #fdf3e2;
  color: #b8860b;
}
.st-danger {
  background: #fbeae8;
  color: var(--red);
}
.st-expired {
  background: var(--red);
  color: #fff;
}
.st-none {
  background: #f0efe9;
  color: var(--text-3);
}
.btn--tiny {
  padding: 3px 9px;
  font-size: 11.5px;
  border-radius: 6px;
}

.summary-bar {
  display: flex;
  gap: 30px;
  flex-wrap: wrap;
}
.summary-bar div {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.summary-bar span {
  font-size: 11.5px;
  color: var(--text-3);
}
.summary-bar b {
  font-size: 17px;
  font-variant-numeric: tabular-nums;
}
.summary-bar__alert {
  color: var(--red);
}

.batch-bar {
  position: fixed;
  left: 50%;
  transform: translateX(-50%);
  bottom: 76px;
  display: flex;
  align-items: center;
  gap: 10px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 10px 14px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.08);
  z-index: 40;
}
.batch-bar span {
  font-size: 13px;
  color: var(--text-2);
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
  width: min(440px, 92vw);
  max-height: 82vh;
  overflow: auto;
}
.modal h3 {
  margin: 0 0 6px;
  font-size: 15px;
}
.muted {
  color: var(--text-3);
  font-size: 12px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12.5px;
  color: var(--text-2);
  margin-top: 10px;
}
.field input,
.batch-row input {
  height: 34px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  font-size: 14px;
}
.batch-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 0;
  border-top: 1px dashed var(--line);
}
.batch-row__name {
  flex: 1;
  font-size: 13.5px;
  font-weight: 500;
}
.batch-row input {
  width: 100px;
  text-align: right;
}
.modal__foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}

@media (max-width: 720px) {
  .summary-bar {
    gap: 18px;
  }
  .summary-bar b {
    font-size: 15px;
  }
  .row {
    flex-wrap: wrap;
  }
  .row__side {
    text-align: left;
    display: flex;
    gap: 12px;
    align-items: baseline;
  }
  .row__quick {
    margin-left: auto;
  }
  .filters__input {
    min-width: 100%;
  }
}
</style>
