<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NInput, NModal } from 'naive-ui'

import { ingredientApi, fileApi, type IngredientDetail } from '@/api/ingredients'
import { notifyError, notifySuccess } from '@/utils/notify'

const route = useRoute()
const router = useRouter()
const id = computed(() => String(route.params.id))

const data = ref<IngredientDetail | null>(null)
const loading = ref(false)
const busy = ref(false)

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
  } finally {
    loading.value = false
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
</style>
