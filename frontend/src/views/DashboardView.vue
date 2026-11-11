<script setup lang="ts">
/** 首页（M6）：库存价值、期间金额、最近入库、临期提醒、营养摄入。 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { dashboardApi, pct, type DashboardNutrition, type DashboardSummary } from '@/api/dashboard'
import StatsPanel from '@/components/StatsPanel.vue'
import { useAppStore } from '@/stores/app'
import { notifyError, notifySuccess } from '@/utils/notify'

const router = useRouter()
const app = useAppStore()

const summary = ref<DashboardSummary | null>(null)
const nutrition = ref<DashboardNutrition | null>(null)
const period = ref<'today' | '3d' | 'week' | 'month'>('today')
const loading = ref(false)
const targetModal = ref(false)
const targetDraft = ref<Record<string, string>>({})
const saving = ref(false)

const periods = [
  { key: 'today', label: '今日' },
  { key: '3d', label: '近三天' },
  { key: 'week', label: '本周' },
  { key: 'month', label: '本月' },
] as const

async function loadSummary() {
  loading.value = true
  try {
    summary.value = await dashboardApi.summary()
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '加载汇总失败')
  } finally {
    loading.value = false
  }
}

async function loadNutrition() {
  try {
    nutrition.value = await dashboardApi.nutrition(period.value)
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '加载营养失败')
  }
}

async function openTargets() {
  const res = await dashboardApi.targets()
  const draft: Record<string, string> = {}
  for (const t of res.items) draft[t.code] = t.target_value
  targetDraft.value = draft
  targetModal.value = true
}

async function saveTargets() {
  if (saving.value) return
  const items = Object.entries(targetDraft.value)
    .filter(([, v]) => v.trim() !== '' && Number(v) > 0)
    .map(([code, v]) => ({ code, target_value: v.trim(), period: 'daily' }))
  if (items.length === 0) {
    notifyError('至少填一个目标值')
    return
  }
  saving.value = true
  try {
    await dashboardApi.saveTargets(items)
    notifySuccess('营养目标已保存')
    targetModal.value = false
    await loadNutrition()
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '保存失败')
  } finally {
    saving.value = false
  }
}

watch(period, loadNutrition)
onMounted(async () => {
  await loadSummary()
  await loadNutrition()
})
</script>

<template>
  <div class="page-head">
    <div>
      <h1>概览</h1>
      <p>
        库存价值、期间收支与营养摄入
        <template v-if="summary"> · {{ summary.period_start }} ~ {{ summary.period_end }}</template>
      </p>
    </div>
    <div class="head-actions">
      <span class="status-mini" :class="app.healthClass">{{ app.healthText }}</span>
      <button class="btn" @click="router.push('/alerts')">提醒</button>
      <button class="btn" @click="router.push('/scan')">扫码 / 识别</button>
      <button class="btn" @click="router.push('/purchase')">+ 采购入库</button>
      <button class="btn" @click="router.push('/consume')">− 记一笔消耗</button>
    </div>
  </div>

  <div v-if="loading && !summary" class="card empty"><p>加载中…</p></div>

  <template v-else-if="summary">
    <!-- 统计面板：概览卡片 + 趋势图 + 分类占比 + 排行 + 周转 + 最近操作 -->
    <StatsPanel />

    <!-- 提醒 -->
    <section class="card alerts">
      <button class="alert" :class="{ 'alert--warn': summary.expiring_count > 0 }" @click="router.push('/batches')">
        <strong>{{ summary.expiring_count }}</strong>
        <span>临期 7 天内</span>
      </button>
      <button class="alert" :class="{ 'alert--danger': summary.expired_count > 0 }" @click="router.push('/batches')">
        <strong>{{ summary.expired_count }}</strong>
        <span>已过期</span>
      </button>
      <button class="alert" :class="{ 'alert--warn': summary.low_stock_count > 0 }" @click="router.push('/inventory')">
        <strong>{{ summary.low_stock_count }}</strong>
        <span>低库存</span>
      </button>
    </section>

    <!-- 最近入库 -->
    <section class="card">
      <div class="card__head">
        <h2>最近入库</h2>
        <button class="btn btn--ghost" @click="router.push('/batches')">全部批次</button>
      </div>
      <div v-if="summary.recent_batches.length === 0" class="muted-line">
        还没有入库记录，先点「+ 采购入库」。
      </div>
      <div v-for="b in summary.recent_batches" :key="b.batch_id" class="recent" @click="router.push(`/batches/${b.batch_id}`)">
        <span class="mono">{{ b.batch_no }}</span>
        <span class="recent__name">{{ b.ingredient_name }}</span>
        <span>{{ Number(b.weight) }}g</span>
        <span>¥{{ b.cost }}</span>
        <span class="muted">{{ b.purchase_date }}</span>
      </div>
    </section>

    <!-- 营养 -->
    <section class="card">
      <div class="card__head">
        <h2>营养摄入</h2>
        <div class="seg">
          <button v-for="p in periods" :key="p.key" class="seg__btn"
                  :class="{ 'seg__btn--on': period === p.key }" @click="period = p.key">
            {{ p.label }}
          </button>
        </div>
      </div>

      <div v-if="!nutrition" class="muted-line">加载中…</div>

      <!-- 无记录与 0 摄入必须区分 -->
      <div v-else-if="!nutrition.has_records" class="empty-nutrition">
        <p><strong>这段时间没有消耗记录</strong></p>
        <p class="muted">{{ nutrition.start_date }} ~ {{ nutrition.end_date }} · 不是「摄入为 0」，只是还没记录</p>
        <p class="disclaimer">{{ nutrition.disclaimer }}</p>
        <button class="btn" style="margin-top: 8px" @click="router.push('/consume')">去记一笔消耗</button>
      </div>

      <template v-else>
        <div class="nutri-grid">
          <div v-for="n in nutrition.items" :key="n.code" class="nutri">
            <span class="nutri__name">{{ n.name }}</span>
            <strong class="nutri__value">{{ Number(n.actual_value) }}<small>{{ n.unit }}</small></strong>
            <span v-if="n.target_value" class="nutri__target">
              日目标 {{ Number(n.target_value) }}
              <template v-if="nutrition && nutrition.days > 0">
                · 窗口 {{ Number(n.period_target) }}
              </template>
              · {{ pct(n.achievement) }}
            </span>
            <span v-else class="nutri__target muted">未设目标</span>
          </div>
        </div>
        <p class="disclaimer">{{ nutrition.disclaimer }} · 共 {{ nutrition.record_count }} 笔消耗</p>
      </template>

      <div class="nutri-actions">
        <button class="btn btn--ghost" @click="openTargets">设置营养目标</button>
      </div>
    </section>

    <!-- 营养目标弹层 -->
    <div v-if="targetModal" class="modal-mask" @click.self="targetModal = false">
      <div class="modal">
        <h3>每日营养目标</h3>
        <div v-for="n in nutrition?.items || []" :key="n.code" class="target-row">
          <span>{{ n.name }}（{{ n.unit }}）</span>
          <input v-model="targetDraft[n.code]" inputmode="decimal" placeholder="留空表示不设" />
        </div>
        <div class="modal__foot">
          <button class="btn" @click="targetModal = false">取消</button>
          <button class="btn btn--primary" :disabled="saving" @click="saveTargets">
            {{ saving ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>
  </template>
</template>

<style scoped>
.status-mini { font-size: 11.5px; color: var(--text-3); }
.status-mini.ok { color: var(--green); }
.status-mini.down { color: var(--red); }


.alerts { display: flex; gap: 12px; flex-wrap: wrap; }
.alert {
  flex: 1; min-width: 110px; display: flex; flex-direction: column; gap: 3px;
  padding: 10px 12px; border: 1px solid var(--line); border-radius: 10px;
  background: transparent; cursor: pointer; text-align: left;
}
.alert strong { font-size: 20px; font-variant-numeric: tabular-nums; }
.alert span { font-size: 11.5px; color: var(--text-3); }
.alert--warn { border-color: #f0dfb8; background: #fdf9ef; }
.alert--danger { border-color: #f2c9c6; background: #fdf2f1; }

.recent {
  display: flex; align-items: center; gap: 14px; padding: 9px 0;
  font-size: 13px; border-top: 1px dashed var(--line); cursor: pointer;
  font-variant-numeric: tabular-nums; flex-wrap: wrap;
}
.recent:hover { color: var(--green); }
.recent__name { font-weight: 600; min-width: 90px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px; color: var(--text-3); }
.muted { color: var(--text-3); font-size: 11.5px; }
.muted-line { font-size: 13px; color: var(--text-3); padding: 6px 0; }

.seg { display: flex; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
.seg__btn { padding: 5px 12px; font-size: 12px; background: transparent; border: 0; cursor: pointer; color: var(--text-2); }
.seg__btn--on { background: var(--green); color: #fff; }

.nutri-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 12px; margin-top: 6px; }
.nutri { display: flex; flex-direction: column; gap: 3px; padding: 10px; border: 1px solid var(--line); border-radius: 10px; }
.nutri__name { font-size: 11.5px; color: var(--text-3); }
.nutri__value { font-size: 18px; font-variant-numeric: tabular-nums; }
.nutri__value small { font-size: 11px; color: var(--text-3); margin-left: 3px; font-weight: 400; }
.nutri__target { font-size: 11px; color: var(--text-2); }
.empty-nutrition { padding: 14px 0; }
.empty-nutrition p { font-size: 13px; }
.disclaimer { font-size: 11.5px; color: var(--text-3); margin-top: 12px; }
.nutri-actions { margin-top: 10px; }

.modal-mask { position: fixed; inset: 0; background: rgba(0,0,0,.28); display: grid; place-items: center; z-index: 50; }
.modal { background: #fff; border-radius: 14px; padding: 18px 20px; width: min(420px, 92vw); max-height: 80vh; overflow: auto; }
.modal h3 { margin: 0 0 12px; font-size: 15px; }
.target-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 6px 0; font-size: 13px; }
.target-row input {
  width: 110px; height: 32px; padding: 0 10px; border: 1px solid var(--line);
  border-radius: 8px; font-size: 13px; text-align: right;
}
.modal__foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
@media (max-width: 720px) {
  .grid--2 { grid-template-columns: 1fr; }
}
</style>
