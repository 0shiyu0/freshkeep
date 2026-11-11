<script setup lang="ts">
/** 扫码与 AI 识别（阶段 8）：识别只生成待确认草稿，人工核对后才建档/入库。 */
import { computed, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton } from 'naive-ui'

import { aiApi, productApi, type ProductLookup, type RecognitionDraft } from '@/api/ai'
import { fileApi } from '@/api/files'
import { ingredientApi, type IngredientListItem } from '@/api/ingredients'
import { notifyError, notifySuccess } from '@/utils/notify'

const router = useRouter()

const barcode = ref('')
const scanning = ref(false)
const video = ref<HTMLVideoElement | null>(null)
const lookup = ref<ProductLookup | null>(null)
const draft = ref<RecognitionDraft | null>(null)
const busy = ref(false)
const ingredients = ref<IngredientListItem[]>([])
const targetIngredientId = ref<string | null>(null)
const form = ref<Record<string, any>>({})

let stream: MediaStream | null = null
let timer: number | undefined
let detector: any = null

const warnings = computed(() => draft.value?.warnings ?? [])
const hasDateWarning = computed(() =>
  warnings.value.some((w) => w.code.startsWith('DATE_') || w.code === 'EXPIRY_IN_PAST')
)
const scanSupported = computed(
  () => typeof navigator !== 'undefined' && 'mediaDevices' in navigator && !!(window as any).BarcodeDetector
)

async function loadIngredients() {
  try {
    const res = await ingredientApi.list({ page_size: 200 })
    ingredients.value = res.items
  } catch {
    /* 非关键路径 */
  }
}

async function startScan() {
  if (!scanSupported.value) {
    notifyError('当前浏览器不支持条码识别，请手动输入条码')
    return
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
    if (video.value) {
      video.value.srcObject = stream
      await video.value.play()
    }
    const Detector = (window as any).BarcodeDetector
    detector = new Detector({ formats: ['ean13', 'ean8', 'upc_a', 'code_128', 'qr_code'] })
    scanning.value = true
    const tick = async () => {
      if (!scanning.value || !video.value || !detector) return
      try {
        const codes = await detector.detect(video.value)
        if (codes?.length) {
          const code = String(codes[0].rawValue || '').trim()
          if (code) {
            barcode.value = code
            stopScan()
            await doLookup()
            return
          }
        }
      } catch {
        /* 单帧识别失败继续 */
      }
      timer = window.setTimeout(tick, 600)
    }
    void tick()
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '无法打开摄像头，请检查权限或手动输入')
    stopScan()
  }
}

function stopScan() {
  scanning.value = false
  if (timer) window.clearTimeout(timer)
  stream?.getTracks().forEach((t) => t.stop())
  stream = null
  if (video.value) video.value.srcObject = null
}

async function doLookup() {
  const code = barcode.value.trim()
  if (!code) return
  busy.value = true
  try {
    lookup.value = await productApi.lookup(code)
    if (lookup.value.found && lookup.value.source === 'local' && lookup.value.ingredient_id) {
      notifySuccess(`本地已收录：${lookup.value.ingredient_name}`)
    }
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '查询失败')
  } finally {
    busy.value = false
  }
}

function useProduct() {
  const p = lookup.value?.product
  return aiApi.recognize({
    hint: p?.name || lookup.value?.ingredient_name || '',
    manual: p
      ? {
          name: p.name, brand: p.brand, specification: p.specification,
          barcode: p.barcode, nutrition: p.nutrition,
        }
      : { name: lookup.value?.ingredient_name || '', barcode: barcode.value },
  })
}

async function createDraft(pending: Promise<RecognitionDraft>) {
  busy.value = true
  try {
    draft.value = await pending
    form.value = { ...(draft.value.draft || {}) }
    await loadIngredients()
    notifySuccess('已生成待确认信息，请核对')
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '识别失败')
  } finally {
    busy.value = false
  }
}

async function useLookup() {
  await createDraft(useProduct())
}

async function uploadPhoto(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  busy.value = true
  try {
    const asset = await fileApi.upload(file)
    await createDraft(aiApi.recognize({ image_file_id: asset.id, hint: barcode.value }))
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '上传失败')
  } finally {
    busy.value = false
  }
}

async function manualBlank() {
  await createDraft(aiApi.recognize({ hint: barcode.value, manual: { barcode: barcode.value } }))
}

async function saveDraft() {
  if (!draft.value) return
  busy.value = true
  try {
    draft.value = await aiApi.patch(draft.value.id, form.value)
    form.value = { ...(draft.value.draft || {}) }
    notifySuccess('修正已保存')
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '保存失败')
  } finally {
    busy.value = false
  }
}

async function confirm(target: 'ingredient' | 'batch') {
  if (!draft.value) return
  if (target === 'batch' && !targetIngredientId.value) {
    notifyError('入库前请选择已有食材')
    return
  }
  if (hasDateWarning.value) {
    const ok = window.confirm('日期存在告警，已核对包装上的生产日期与保质期？')
    if (!ok) return
  }
  busy.value = true
  try {
    await aiApi.patch(draft.value.id, form.value)
    const res = await aiApi.confirm(draft.value.id, target, targetIngredientId.value ?? undefined)
    notifySuccess(target === 'ingredient' ? '已创建食材档案' : '已入库并生成流水')
    draft.value = null
    lookup.value = null
    barcode.value = ''
    if (res.batch_id) router.push(`/batches/${res.batch_id}`)
    else if (res.ingredient_id) router.push(`/ingredients/${res.ingredient_id}`)
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '确认失败')
  } finally {
    busy.value = false
  }
}

async function reject() {
  if (!draft.value) return
  try {
    await aiApi.reject(draft.value.id)
    draft.value = null
    notifySuccess('已忽略本次识别')
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '操作失败')
  }
}

onBeforeUnmount(stopScan)
</script>

<template>
  <div class="page-head">
    <div>
      <h1>扫码 / 识别</h1>
      <p>拍照识别只生成待确认信息，核对后才建档或入库</p>
    </div>
    <div class="head-actions">
      <button class="btn" @click="router.push('/alerts')">提醒</button>
      <button class="btn" @click="router.push('/inventory')">库存</button>
    </div>
  </div>

  <!-- 扫码 -->
  <section class="card">
    <div class="card__head">
      <h2>条码</h2>
      <span class="muted">{{ scanSupported ? '摄像头可用' : '当前浏览器不支持扫码，请手动输入' }}</span>
    </div>
    <div class="scan-row">
      <input v-model="barcode" class="scan-input" placeholder="条码数字，或直接扫码" inputmode="numeric" />
      <NButton type="primary" :loading="busy" @click="doLookup">查询</NButton>
      <NButton v-if="!scanning" :disabled="!scanSupported" @click="startScan">开始扫码</NButton>
      <NButton v-else @click="stopScan">停止</NButton>
    </div>
    <video v-show="scanning" ref="video" class="scan-video" playsinline muted />
    <div class="photo-row">
      <label class="btn btn--ghost">
        拍照识别包装
        <input type="file" accept="image/*" capture="environment" hidden @change="uploadPhoto" />
      </label>
      <button class="btn btn--ghost" @click="manualBlank">手动填写</button>
    </div>
  </section>

  <!-- 查询结果 -->
  <section v-if="lookup" class="card">
    <h2>查询结果</h2>
    <p v-if="lookup.found && lookup.source === 'local'" class="hit">
      本地已收录：<strong>{{ lookup.ingredient_name }}</strong>
      <button class="btn btn--tiny" @click="router.push(`/ingredients/${lookup.ingredient_id}`)">查看档案</button>
    </p>
    <p v-else-if="lookup.found && lookup.product" class="hit">
      {{ lookup.product.source_label || '外部数据源' }}：<strong>{{ lookup.product.name }}</strong>
      <template v-if="lookup.product.brand">· {{ lookup.product.brand }}</template>
      <template v-if="lookup.product.specification"> · {{ lookup.product.specification }}</template>
      <button class="btn btn--tiny" @click="useLookup">用这些信息生成待确认</button>
    </p>
    <p v-else class="miss">
      {{ lookup.message || '未查到' }}
      <template v-if="lookup.source_error">（{{ lookup.source_error }}）</template>
      <button class="btn btn--tiny" @click="manualBlank">手动填写</button>
    </p>
  </section>

  <!-- 待确认 -->
  <section v-if="draft" class="card">
    <div class="card__head">
      <h2>待确认信息</h2>
      <span class="tag">来源 {{ draft.provider }}</span>
    </div>

    <div v-if="warnings.length" class="warn-box">
      <p class="warn-box__title">请逐条核对（AI 可能把生产日期识别成保质期）：</p>
      <div v-for="(w, i) in warnings" :key="i" class="warn">
        <span class="warn__code">{{ w.code }}</span>
        <span>{{ w.message }}</span>
      </div>
    </div>

    <div class="grid2">
      <label class="field">名称
        <input v-model="form.name" placeholder="商品名称" />
      </label>
      <label class="field">品牌
        <input v-model="form.brand" placeholder="可留空" />
      </label>
      <label class="field">规格
        <input v-model="form.specification" placeholder="如 500g" />
      </label>
      <label class="field">条码
        <input v-model="form.barcode" placeholder="可留空" />
      </label>
      <label class="field">生产日期
        <input v-model="form.production_date" type="date" />
      </label>
      <label class="field">到期日期
        <input v-model="form.expiry_date" type="date" />
      </label>
    </div>

    <h3>营养（每 100g）</h3>
    <div v-if="!(form.nutrition || []).length" class="muted">未识别到营养数据，可留空</div>
    <div v-for="(n, i) in form.nutrition || []" :key="n.code" class="nutri-row">
      <span class="nutri-row__name">{{ n.code }}</span>
      <input v-model="n.value" inputmode="decimal" />
      <span class="muted">{{ n.basis_unit }}/{{ n.basis_amount }}</span>
    </div>

    <h3>入库信息（确认入库时使用）</h3>
    <div class="grid2">
      <label class="field">重量（g）
        <input v-model="form.weight" inputmode="decimal" placeholder="如 500" />
      </label>
      <label class="field">采购总价（元）
        <input v-model="form.purchase_cost" inputmode="decimal" placeholder="如 18.00" />
      </label>
    </div>

    <div class="foot">
      <NButton @click="saveDraft" :loading="busy">保存修正</NButton>
      <NButton @click="reject">忽略</NButton>
      <NButton type="primary" :loading="busy" @click="confirm('ingredient')">确认创建食材档案</NButton>
    </div>

    <div class="foot foot--batch">
      <select v-model="targetIngredientId" class="select">
        <option :value="null">选择已有食材后入库…</option>
        <option v-for="i in ingredients" :key="i.id" :value="i.id">{{ i.name }}</option>
      </select>
      <NButton type="primary" :disabled="!targetIngredientId" :loading="busy" @click="confirm('batch')">
        确认入库
      </NButton>
    </div>
    <p class="muted note">确认前不会产生任何库存变动；入库仍走标准五步事务。</p>
  </section>
</template>

<style scoped>
.card__head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 8px; }
.card__head h2 { margin: 0; }
h3 { font-size: 13px; margin: 16px 0 8px; }
.scan-row { display: flex; gap: 8px; flex-wrap: wrap; }
.scan-input {
  flex: 1; min-width: 180px; height: 36px; padding: 0 12px;
  border: 1px solid var(--line); border-radius: 9px; font-size: 14px;
}
.scan-video { width: 100%; max-height: 260px; margin-top: 10px; border-radius: 10px; background: #000; object-fit: cover; }
.photo-row { display: flex; gap: 10px; margin-top: 10px; flex-wrap: wrap; }
.photo-row .btn { cursor: pointer; }
.hit, .miss { font-size: 13.5px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.miss { color: var(--text-2); }
.btn--tiny { padding: 3px 9px; font-size: 11.5px; border-radius: 6px; }

.warn-box { background: #fdf9ef; border: 1px solid #f0dfb8; border-radius: 10px; padding: 10px 12px; margin: 6px 0 12px; }
.warn-box__title { font-size: 12.5px; margin-bottom: 6px; }
.warn { display: flex; gap: 8px; font-size: 12px; color: #8a6d1f; padding: 3px 0; }
.warn__code { font-family: ui-monospace, monospace; font-size: 11px; opacity: .8; }

.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.field { display: flex; flex-direction: column; gap: 4px; font-size: 12.5px; color: var(--text-2); }
.field input {
  height: 34px; padding: 0 10px; border: 1px solid var(--line);
  border-radius: 8px; font-size: 14px;
}
.nutri-row { display: flex; align-items: center; gap: 10px; padding: 4px 0; }
.nutri-row__name { width: 80px; font-size: 12.5px; color: var(--text-2); }
.nutri-row input { width: 90px; height: 32px; padding: 0 8px; border: 1px solid var(--line); border-radius: 7px; text-align: right; }
.muted { color: var(--text-3); font-size: 11.5px; }
.note { margin-top: 8px; }
.foot { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 16px; }
.foot--batch { margin-top: 10px; align-items: center; }
.select {
  flex: 1; min-width: 180px; height: 34px; padding: 0 10px;
  border: 1px solid var(--line); border-radius: 8px; font-size: 13px; background: #fff;
}
@media (max-width: 720px) {
  .grid2 { grid-template-columns: 1fr; }
}
</style>
