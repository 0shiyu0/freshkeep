<script setup lang="ts">
/** 盘点与报损（阶段 5）：盘点按批次提交实际重量，报损按食材 FEFO 扣批次。
 *  两类操作都写流水并留原因，可在下方「最近记录」追溯。 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NSelect } from 'naive-ui'

import { batchApi, expiryClass, expiryText, type BatchItem } from '@/api/batches'
import { ingredientApi, type IngredientListItem } from '@/api/ingredients'
import { inventoryApi, TX_TYPE_LABEL, trimNum, type TransactionRow } from '@/api/inventory'
import { notifyError, notifySuccess } from '@/utils/notify'

const router = useRouter()
const tab = ref<'stocktake' | 'spoilage'>('stocktake')

const ingredients = ref<IngredientListItem[]>([])
const picked = ref<string | null>(null)
const batches = ref<BatchItem[]>([])
const draft = reactive<Record<string, string>>({})
const loading = ref(false)
const busy = ref(false)

const spoil = reactive({ weight: '', quantity: '', reason: '变质' })
const recent = ref<TransactionRow[]>([])

const options = computed(() => ingredients.value.map((i) => ({ label: i.name, value: i.id })))
const selected = computed(() => ingredients.value.find((i) => i.id === picked.value) ?? null)
const available = computed(() =>
  batches.value.reduce((sum, b) => sum + Number(b.remaining_weight || 0), 0),
)
const filledCount = computed(() => Object.values(draft).filter((v) => v.trim() !== '').length)

async function loadIngredients() {
  const res = await ingredientApi.list({ page_size: 200 })
  ingredients.value = res.items
  if (!picked.value && res.items.length) picked.value = res.items[0].id
}

async function loadBatches() {
  if (!picked.value) return (batches.value = [])
  loading.value = true
  try {
    const res = await batchApi.list({
      ingredient_id: picked.value,
      status: 'active',
      page_size: 100,
    })
    batches.value = res.items
    for (const key of Object.keys(draft)) delete draft[key]
    for (const b of res.items) draft[b.id] = trimNum(b.remaining_weight)
  } finally {
    loading.value = false
  }
}

async function loadRecent() {
  try {
    const type = tab.value === 'stocktake' ? 'adjustment' : 'spoilage'
    const res = await inventoryApi.transactions({ type, page_size: 8 })
    recent.value = res.items
  } catch {
    /* 最近记录失败不影响主流程 */
  }
}

async function submitStocktake() {
  if (busy.value) return
  const rows = batches.value
    .map((b) => ({ batch_id: b.id, value: (draft[b.id] || '').trim(), before: b.remaining_weight }))
    .filter((r) => r.value !== '' && Number(r.value) >= 0)
  const changed = rows.filter((r) => Number(r.value) !== Number(r.before))
  if (changed.length === 0) {
    notifyError('没有差异：请修改至少一个批次的实际重量')
    return
  }
  busy.value = true
  try {
    const res = await inventoryApi.stocktake(
      changed.map((r) => ({ batch_id: r.batch_id, actual_weight: r.value, reason: '盘点' })),
    )
    notifySuccess(`已盘点 ${res.items.length} 个批次并生成调整流水`)
    await Promise.all([loadBatches(), loadRecent()])
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '盘点失败（未产生任何调整）')
  } finally {
    busy.value = false
  }
}

async function submitSpoilage() {
  if (busy.value || !picked.value) return
  const w = spoil.weight.trim()
  const q = spoil.quantity.trim()
  if (!w && !q) {
    notifyError('重量与数量至少填一项')
    return
  }
  if (!spoil.reason.trim()) {
    notifyError('请填写报损原因')
    return
  }
  busy.value = true
  try {
    const res = await inventoryApi.spoilage({
      ingredient_id: picked.value,
      weight: w || undefined,
      quantity: q || undefined,
      reason: spoil.reason.trim(),
    })
    notifySuccess(`已报损 ${trimNum(res.weight)}g，成本 ${res.cost} 元`)
    spoil.weight = ''
    spoil.quantity = ''
    await Promise.all([loadBatches(), loadRecent()])
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '报损失败')
  } finally {
    busy.value = false
  }
}

function fmtTime(s: string) {
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? s : d.toLocaleString('zh-CN', { hour12: false })
}

watch(picked, loadBatches)
watch(tab, loadRecent)
onMounted(async () => {
  await loadIngredients()
  await Promise.all([loadBatches(), loadRecent()])
})
</script>

<template>
  <div class="page-head">
    <div>
      <h1>盘点 / 报损</h1>
      <p>盘点生成 adjustment 流水，报损生成 spoilage 流水，两者都保留原因可追溯</p>
    </div>
    <div class="head-actions">
      <button class="btn" @click="router.push('/inventory')">返回库存</button>
      <button class="btn" @click="router.push('/records')">全部记录</button>
    </div>
  </div>

  <div class="tabs card">
    <button class="tab" :class="{ 'tab--on': tab === 'stocktake' }" @click="tab = 'stocktake'">
      盘点
    </button>
    <button class="tab" :class="{ 'tab--on': tab === 'spoilage' }" @click="tab = 'spoilage'">
      报损
    </button>
  </div>

  <section class="card">
    <label class="field"
      >食材
      <NSelect
        v-model:value="picked"
        :options="options"
        filterable
        placeholder="搜索食材名称 / 拼音"
      />
    </label>

    <!-- 盘点：逐批次提交实际重量 -->
    <template v-if="tab === 'stocktake'">
      <div v-if="loading" class="muted-line">加载批次…</div>
      <div v-else-if="batches.length === 0" class="empty-inline">
        <p>这个食材还没有批次，先去 <a @click="router.push('/purchase')">采购入库</a>。</p>
      </div>
      <template v-else>
        <p class="hint">提交的是**实际称重**，服务端反算差异；没有差异的行不会被提交。</p>
        <div v-for="b in batches" :key="b.id" class="st-row">
          <div class="st-row__info">
            <span class="mono">{{ b.batch_no }}</span>
            <span class="st-row__label">账面 {{ trimNum(b.remaining_weight) }}g</span>
            <span class="expiry" :class="`expiry--${expiryClass(b)}`">{{ expiryText(b) }}</span>
          </div>
          <input v-model="draft[b.id]" inputmode="decimal" placeholder="实际 g" />
        </div>
        <div class="foot">
          <span class="muted">已修改 {{ filledCount }} 行（提交时只发有差异的）</span>
          <NButton type="primary" :loading="busy" @click="submitStocktake">提交盘点</NButton>
        </div>
      </template>
    </template>

    <!-- 报损：按食材 FEFO 扣批次 -->
    <template v-else>
      <p class="hint">当前可用 {{ available }}g · 按先到期先出扣减，成本按批次单位成本核算。</p>
      <div class="form-row">
        <label class="field"
          >报损重量（g）
          <input v-model="spoil.weight" inputmode="decimal" placeholder="如 200" />
        </label>
        <label class="field"
          >数量（{{ selected?.quantity_unit?.name || '数量' }}）
          <input v-model="spoil.quantity" inputmode="decimal" placeholder="可留空" />
        </label>
        <label class="field"
          >原因
          <input v-model="spoil.reason" placeholder="如 变质 / 过期 / 丢弃" />
        </label>
      </div>
      <div class="foot">
        <span class="muted">报损不可撤销，请确认数量</span>
        <NButton type="primary" :loading="busy" @click="submitSpoilage">提交报损</NButton>
      </div>
    </template>
  </section>

  <!-- 最近记录：追溯入口 -->
  <section class="card">
    <div class="card__head">
      <h2>最近{{ tab === 'stocktake' ? '盘点' : '报损' }}记录</h2>
      <button class="btn btn--ghost" @click="router.push('/records')">查看全部</button>
    </div>
    <div v-if="recent.length === 0" class="muted-line">暂无记录</div>
    <div v-for="r in recent" :key="r.id" class="rec">
      <span class="tx-tag" :class="`tx-tag--${r.type}`">{{ TX_TYPE_LABEL[r.type] || r.type }}</span>
      <span class="mono">{{ r.transaction_no }}</span>
      <span class="rec__name">{{ r.ingredient_name }}</span>
      <span>{{ trimNum(r.weight_delta) }}g</span>
      <span>{{ r.cost_delta }} 元</span>
      <span class="muted">{{ r.reason }}</span>
      <span class="muted">{{ fmtTime(r.created_at) }}</span>
    </div>
  </section>
</template>

<style scoped>
.tabs {
  display: flex;
  gap: 8px;
  padding: 8px;
  margin-bottom: 14px;
}
.tab {
  padding: 7px 18px;
  border-radius: 9px;
  border: 1px solid transparent;
  background: transparent;
  font-size: 13.5px;
  cursor: pointer;
  color: var(--text-2);
}
.tab--on {
  background: var(--green-weak);
  color: var(--green);
  border-color: #cfe3d6;
  font-weight: 600;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 12.5px;
  color: var(--text-2);
}
.field input {
  height: 34px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  font-size: 14px;
}
.form-row {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  margin-top: 12px;
}
.form-row .field {
  min-width: 150px;
  flex: 1;
}
.hint {
  font-size: 11.5px;
  color: var(--text-3);
  margin: 10px 0;
}
.st-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 0;
  border-top: 1px dashed var(--line);
  flex-wrap: wrap;
}
.st-row__info {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.st-row__label {
  font-size: 12.5px;
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}
.st-row input {
  width: 110px;
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  text-align: right;
}
.foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 14px;
  flex-wrap: wrap;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11.5px;
  color: var(--text-3);
}
.muted {
  color: var(--text-3);
  font-size: 11.5px;
}
.muted-line {
  font-size: 13px;
  color: var(--text-3);
  padding: 6px 0;
}
.empty-inline {
  padding: 12px 0;
  font-size: 13px;
}
.empty-inline a {
  color: var(--green);
  cursor: pointer;
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
.card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.card__head h2 {
  margin: 0;
}
.rec {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  font-size: 12.5px;
  border-top: 1px dashed var(--line);
  flex-wrap: wrap;
  font-variant-numeric: tabular-nums;
}
.rec__name {
  font-weight: 600;
}
.tx-tag {
  font-size: 11.5px;
  padding: 2px 9px;
  border-radius: 999px;
  font-weight: 500;
}
.tx-tag--purchase {
  background: var(--green-weak);
  color: var(--green);
}
.tx-tag--consume {
  background: #eef2fb;
  color: #3d5a9a;
}
.tx-tag--spoilage {
  background: #fbeae8;
  color: var(--red);
}
.tx-tag--adjustment {
  background: #fdf3e2;
  color: #b8860b;
}
.tx-tag--reverse {
  background: #f0efe9;
  color: var(--text-2);
}
@media (max-width: 720px) {
  .form-row .field {
    min-width: 100%;
  }
  .st-row input {
    width: 90px;
  }
}
</style>
