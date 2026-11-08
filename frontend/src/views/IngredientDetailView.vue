<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NInput, NModal, NSelect } from 'naive-ui'

import { ingredientApi, fileApi, type IngredientDetail } from '@/api/ingredients'
import { batchApi, expiryClass, expiryText, type BatchItem } from '@/api/batches'
import { catalogApi, type StorageLocation } from '@/api/catalog'
import { notifyError, notifySuccess } from '@/utils/notify'

const route = useRoute()
const router = useRouter()
const id = computed(() => String(route.params.id))

const data = ref<IngredientDetail | null>(null)
const loading = ref(false)
const busy = ref(false)

// 批次（M3）
const batches = ref<BatchItem[]>([])
const locations = ref<StorageLocation[]>([])
const purchaseModal = ref(false)
const purchasing = ref(false)
const purchaseForm = reactive({
  purchase_date: new Date().toISOString().slice(0, 10),
  expiry_date: '',
  storage_location_id: '',
  quantity: '',
  weight: '',
  purchase_cost: '',
  note: '',
})

// 图片
const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)

// 条码
const barcodeModal = ref(false)
const newBarcode = ref('')

async function load() {
  loading.value = true
  try {
    data.value = await ingredientApi.detail(id.value)
    const [b, locs] = await Promise.all([
      batchApi.list({ ingredient_id: id.value, page_size: 50 }),
      catalogApi.locations(),
    ])
    batches.value = b.items
    locations.value = locs.items
  } finally {
    loading.value = false
  }
}

// 批次剩余量展示：优先重量，纯数量管理只显示数量
function remainingText(b: BatchItem): string {
  if (b.remaining_weight !== '0.000') return `${Number(b.remaining_weight)}g`
  if (b.remaining_quantity !== '0.000') return `${Number(b.remaining_quantity)}${data.value?.quantity_unit?.name ?? ''}`
  return '0'
}

async function submitPurchase() {
  if (purchasing.value) return
  const quantity = purchaseForm.quantity.trim() || '0'
  const weight = purchaseForm.weight.trim() || '0'
  if (quantity === '0' && weight === '0') {
    notifyError('数量与重量至少填一项')
    return
  }
  purchasing.value = true
  try {
    await batchApi.create({
      ingredient_id: id.value,
      purchase_date: purchaseForm.purchase_date || undefined,
      expiry_date: purchaseForm.expiry_date || null,
      storage_location_id: purchaseForm.storage_location_id || null,
      quantity,
      weight,
      purchase_cost: purchaseForm.purchase_cost.trim() || '0',
      quantity_unit_id: data.value?.quantity_unit?.id ?? null,
      weight_unit_id: data.value?.weight_unit?.id ?? null,
      note: purchaseForm.note.trim(),
    })
    notifySuccess('入库成功，已生成批次与流水')
    purchaseModal.value = false
    purchaseForm.expiry_date = ''
    purchaseForm.storage_location_id = ''
    purchaseForm.quantity = ''
    purchaseForm.weight = ''
    purchaseForm.purchase_cost = ''
    purchaseForm.note = ''
    await load()
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '入库失败')
  } finally {
    purchasing.value = false
  }
}

/** 属性表：完全按验收要求逐项呈现，缺值显示「未设置」而不是空白 */
const attrs = computed(() => {
  if (!data.value) return []
  const d = data.value
  return [
    { label: '默认数量单位', value: d.quantity_unit ? d.quantity_unit.name : '未设置', hint: '' },
    {
      label: '默认重量单位',
      value: d.weight_unit ? d.weight_unit.symbol || d.weight_unit.name : '未设置',
      hint: '',
    },
    {
      label: '每包重量',
      value: d.unit_weight_display,
      hint: d.can_convert ? '存在换算关系，可按数量推算重量' : '无换算关系，禁止自动推算',
    },
    { label: '最低库存', value: d.minimum_stock_display, hint: '' },
    { label: '营养基准', value: d.nutrition_basis_display, hint: '' },
    { label: '储存位置', value: d.location_name || '未设置', hint: '' },
  ]
})

async function toggleActive() {
  if (!data.value) return
  busy.value = true
  try {
    if (data.value.is_active) {
      await ingredientApi.deactivate(id.value)
      notifySuccess('已停用，默认列表不再显示')
    } else {
      await ingredientApi.activate(id.value)
      notifySuccess('已重新启用')
    }
    await load()
  } finally {
    busy.value = false
  }
}

function pickFile() {
  fileInput.value?.click()
}

async function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (file.size > 5 * 1024 * 1024) {
    notifyError('图片不能超过 5 MB')
    return
  }
  uploading.value = true
  try {
    const asset = await fileApi.upload(file)
    await ingredientApi.update(id.value, { image_asset_id: asset.id })
    notifySuccess('图片已更新')
    await load()
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '上传失败')
  } finally {
    uploading.value = false
  }
}

async function removeImage() {
  if (!data.value?.image_url) return
  const assetId = data.value.image_url.split('/').slice(-2)[0]
  try {
    await ingredientApi.update(id.value, { image_asset_id: null })
    await fileApi.remove(assetId)
    notifySuccess('图片已删除')
    await load()
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '删除失败')
  }
}

async function addBarcode() {
  const code = newBarcode.value.trim()
  if (!code) return
  try {
    await ingredientApi.bindBarcode(id.value, code)
    notifySuccess('条码已绑定')
    barcodeModal.value = false
    newBarcode.value = ''
    await load()
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '绑定失败')
  }
}

onMounted(load)
</script>

<template>
  <div v-if="loading" class="empty"><p>加载中…</p></div>

  <template v-else-if="data">
    <div class="detail-head">
      <button class="btn btn--ghost" @click="router.push('/inventory')">← 返回</button>
      <div class="detail-head__actions">
        <button class="btn" @click="router.push(`/ingredients/${id}/edit`)">编辑</button>
        <button class="btn" :disabled="busy" @click="toggleActive">
          {{ data.is_active ? '停用' : '启用' }}
        </button>
      </div>
    </div>

    <!-- 头部：名称 + 分类标签 + 启用状态 -->
    <section class="hero card">
      <div class="hero__thumb" @click="pickFile">
        <img v-if="data.image_url" :src="data.image_url" :alt="data.name" />
        <span v-else>{{ uploading ? '…' : '＋' }}</span>
      </div>
      <input ref="fileInput" type="file" accept="image/png,image/jpeg,image/webp" hidden @change="onFileChange" />

      <div class="hero__text">
        <div class="hero__title">
          <h1>{{ data.name }}</h1>
          <span class="tag" :class="data.is_active ? '' : 'tag--muted'">
            {{ data.is_active ? '启用中' : '已停用' }}
          </span>
        </div>
        <div class="hero__tags">
          <span class="tag tag--muted">{{ data.category_path }}</span>
          <span v-if="data.brand" class="hero__brand">{{ data.brand }}</span>
          <span v-if="data.specification" class="hero__brand">{{ data.specification }}</span>
        </div>
      </div>
    </section>

    <!-- 属性表：验收要求的六项 -->
    <section class="card">
      <h2>属性</h2>
      <div v-for="a in attrs" :key="a.label" class="attr">
        <span class="attr__label">{{ a.label }}</span>
        <span class="attr__value">
          {{ a.value }}
          <small v-if="a.hint" class="attr__hint">{{ a.hint }}</small>
        </span>
      </div>
    </section>

    <!-- 批次（M3）：入库历史与剩余 -->
    <section class="card">
      <div class="card__head">
        <h2>批次（{{ batches.length }}）</h2>
        <div class="head-actions">
          <button class="btn" @click="router.push(`/consume?ingredient=${id}`)">− 记一笔消耗</button>
          <button class="btn" @click="purchaseModal = true">＋ 入库</button>
        </div>
      </div>
      <div v-if="batches.length === 0" class="muted-line">还没有批次，点「入库」记录第一次采购。</div>
      <div v-for="b in batches" :key="b.id" class="batch-row">
        <div class="batch-row__main">
          <span class="batch-row__no mono">{{ b.batch_no }}</span>
          <span v-if="b.location_name" class="tag tag--muted">{{ b.location_name }}</span>
          <span class="expiry" :class="`expiry--${expiryClass(b)}`">{{ expiryText(b) }}</span>
        </div>
        <div class="batch-row__nums">
          <span>剩余 <b>{{ remainingText(b) }}</b></span>
          <span v-if="b.remaining_cost !== '0.00'">成本 ¥{{ b.remaining_cost }}</span>
          <span v-if="b.status === 'depleted'" class="tag tag--muted">已耗尽</span>
        </div>
      </div>
    </section>

    <!-- 图片操作 -->
    <section class="card">
      <h2>图片</h2>
      <div v-if="data.image_url" class="img-box">
        <img :src="data.image_url" :alt="data.name" />
        <div class="img-box__ops">
          <button class="btn" @click="pickFile">更换</button>
          <button class="btn btn--danger" @click="removeImage">删除</button>
        </div>
      </div>
      <div v-else class="img-empty">
        <button class="btn" :disabled="uploading" @click="pickFile">
          {{ uploading ? '上传中…' : '上传图片（JPG / PNG / WebP，≤5MB）' }}
        </button>
      </div>
    </section>

    <!-- 营养档案 -->
    <section class="card">
      <h2>营养档案（{{ data.nutrition_basis_display }}）</h2>
      <div v-if="data.nutrition.length === 0" class="muted-line">未录入营养数据</div>
      <div v-for="n in data.nutrition" :key="n.code" class="attr">
        <span class="attr__label">{{ n.name }}</span>
        <span class="attr__value">{{ n.value }} {{ n.unit }}</span>
      </div>
    </section>

    <!-- 条码 -->
    <section class="card">
      <div class="card__head">
        <h2>条码</h2>
        <button class="btn" @click="barcodeModal = true">+ 绑定</button>
      </div>
      <div v-if="data.barcodes.length === 0" class="muted-line">尚未绑定条码</div>
      <div v-for="b in data.barcodes" :key="b.barcode" class="attr">
        <span class="attr__label">{{ b.barcode_type.toUpperCase() }}</span>
        <span class="attr__value mono">{{ b.barcode }}</span>
      </div>
    </section>

    <NModal v-model:show="barcodeModal" preset="card" title="绑定条码" style="max-width: 360px">
      <NInput v-model:value="newBarcode" placeholder="扫描或输入条码数字" @keyup.enter="addBarcode" />
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <NButton @click="barcodeModal = false">取消</NButton>
          <NButton type="primary" @click="addBarcode">绑定</NButton>
        </div>
      </template>
    </NModal>

    <!-- 入库表单（M3）：双计量，数量与重量至少填一项 -->
    <NModal v-model:show="purchaseModal" preset="card" title="采购入库" style="max-width: 420px">
      <div class="form-grid">
        <label>购买日期<input v-model="purchaseForm.purchase_date" type="date" /></label>
        <label>到期日期<input v-model="purchaseForm.expiry_date" type="date" /></label>
        <label>数量（{{ data?.quantity_unit?.name ?? '数量' }}，如 2）
          <input v-model="purchaseForm.quantity" inputmode="decimal" placeholder="可留空" /></label>
        <label>重量（{{ data?.weight_unit?.symbol ?? 'g' }}，如 500）
          <input v-model="purchaseForm.weight" inputmode="decimal" placeholder="可留空" /></label>
        <label>总价（元）<input v-model="purchaseForm.purchase_cost" inputmode="decimal" placeholder="0" /></label>
        <label class="form-grid--full">储存位置
          <NSelect
            v-model:value="purchaseForm.storage_location_id"
            :options="locations.map(l => ({ label: l.name, value: l.id }))"
            placeholder="默认用食材的储存位置"
            clearable
          /></label>
        <label class="form-grid--full">备注
          <NInput v-model:value="purchaseForm.note" placeholder="可留空" /></label>
      </div>
      <p class="form-tip">至少填一项数量或重量；两者都填则同时记录（双计量）。</p>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <NButton @click="purchaseModal = false">取消</NButton>
          <NButton type="primary" :loading="purchasing" @click="submitPurchase">入库</NButton>
        </div>
      </template>
    </NModal>
  </template>

  <div v-else class="empty">
    <span class="empty__icon">🔍</span>
    <h3>找不到这个食材</h3>
    <p>可能已被删除。</p>
    <button class="btn" style="margin-top: 12px" @click="router.push('/inventory')">返回列表</button>
  </div>
</template>

<style scoped>
.detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.detail-head__actions { display: flex; gap: 8px; }
.btn--ghost { background: transparent; border-color: transparent; padding: 0 6px; }
.btn--danger { color: var(--red); border-color: #f2c9c6; }

.hero { display: flex; align-items: center; gap: 16px; }
.hero__thumb {
  width: 76px; height: 76px;
  border-radius: 14px;
  background: var(--green-weak);
  color: var(--green);
  display: grid; place-items: center;
  font-size: 26px; font-weight: 300;
  overflow: hidden;
  cursor: pointer;
  flex: none;
  border: 1px dashed #cfe3d6;
}
.hero__thumb img { width: 100%; height: 100%; object-fit: cover; }
.hero__text { min-width: 0; }
.hero__title { display: flex; align-items: center; gap: 10px; }
.hero__title h1 { font-size: 20px; font-weight: 700; letter-spacing: -.3px; }
.hero__tags { display: flex; align-items: center; gap: 8px; margin-top: 7px; flex-wrap: wrap; }
.hero__brand { font-size: 12px; color: var(--text-3); }

.attr {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  padding: 9px 0;
}
.attr + .attr { border-top: 1px dashed var(--line); }
.attr__label { font-size: 13px; color: var(--text-2); flex: none; }
.attr__value { font-size: 13.5px; font-weight: 500; text-align: right; font-variant-numeric: tabular-nums; }
.attr__hint { display: block; font-size: 11px; color: var(--text-3); font-weight: 400; margin-top: 2px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.card__head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.card__head h2 { margin: 0; }
.muted-line { font-size: 13px; color: var(--text-3); padding: 6px 0; }

.img-box { display: flex; align-items: center; gap: 14px; }
.img-box img { width: 120px; height: 120px; object-fit: cover; border-radius: 12px; border: 1px solid var(--line); }
.img-box__ops { display: flex; flex-direction: column; gap: 8px; }
.img-empty { display: flex; }

/* 批次 */
.batch-row {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; padding: 10px 0; flex-wrap: wrap;
}
.batch-row + .batch-row { border-top: 1px dashed var(--line); }
.batch-row__main { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.batch-row__no { font-size: 12px; color: var(--text-3); }
.batch-row__nums {
  display: flex; align-items: center; gap: 12px;
  font-size: 12.5px; color: var(--text-2);
  font-variant-numeric: tabular-nums;
}
.batch-row__nums b { font-size: 13.5px; color: var(--text-1); }

.expiry { font-size: 11.5px; padding: 2px 8px; border-radius: 999px; font-weight: 500; }
.expiry--ok { background: var(--green-weak); color: var(--green); }
.expiry--warn { background: #fdf3e2; color: #b8860b; }
.expiry--danger { background: #fbeae8; color: var(--red); }
.expiry--expired { background: var(--red); color: #fff; }
.expiry--muted { background: var(--bg-weak, #f0efe9); color: var(--text-3); }

/* 入库表单 */
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 14px; }
.form-grid--full { grid-column: 1 / -1; }
.form-grid label { display: flex; flex-direction: column; gap: 4px; font-size: 12.5px; color: var(--text-2); }
.form-grid input {
  height: 34px; padding: 0 10px; border: 1px solid var(--line); border-radius: 8px;
  background: var(--bg-card, #fff); font-size: 14px;
}
.form-tip { font-size: 11.5px; color: var(--text-3); margin: 10px 0 0; }

@media (max-width: 720px) {
  .form-grid { grid-template-columns: 1fr; }
}
</style>
