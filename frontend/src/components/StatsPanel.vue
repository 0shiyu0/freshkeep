<script setup lang="ts">
/** 统计面板（阶段 6）：时间筛选 + 趋势图 + 分类占比 + 消耗排行 + 周转 + 最近操作。
 *  图表用内联 SVG，不引入图表库，保证移动端首屏体积。 */
import { computed, onMounted, ref, watch } from 'vue'

import { ratioText, statsApi, type Granularity, type StatsOverview } from '@/api/stats'
import { TX_TYPE_LABEL, trimNum } from '@/api/inventory'
import { notifyError } from '@/utils/notify'

const granularity = ref<Granularity>('day')
const fromDate = ref('')
const toDate = ref('')
const data = ref<StatsOverview | null>(null)
const loading = ref(false)

const grains: Array<{ key: Granularity; label: string }> = [
  { key: 'day', label: '按日' },
  { key: 'week', label: '按周' },
  { key: 'month', label: '按月' },
  { key: 'year', label: '按年' },
]

async function load() {
  loading.value = true
  try {
    data.value = await statsApi.overview({
      granularity: granularity.value,
      from_date: fromDate.value || undefined,
      to_date: toDate.value || undefined,
    })
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '加载统计失败')
  } finally {
    loading.value = false
  }
}

/** 趋势图坐标：宽 100 高 40 的 viewBox，双折线 + 面积 */
const chart = computed(() => {
  const s = data.value?.series ?? []
  if (s.length === 0) return null
  const max = Math.max(
    1,
    ...s.map((p) => Number(p.purchase_amount)),
    ...s.map((p) => Number(p.consumption_amount))
  )
  const stepX = s.length > 1 ? 100 / (s.length - 1) : 0
  const y = (v: number) => 40 - (v / max) * 36
  const line = (key: 'purchase_amount' | 'consumption_amount') =>
    s.map((p, i) => `${(i * stepX).toFixed(2)},${y(Number(p[key])).toFixed(2)}`).join(' ')
  const area = (key: 'purchase_amount' | 'consumption_amount') => {
    const pts = s.map((p, i) => `${(i * stepX).toFixed(2)},${y(Number(p[key])).toFixed(2)}`)
    return `M0,40 L${pts.join(' L')} L100,40 Z`
  }
  return {
    max,
    purchaseLine: line('purchase_amount'),
    consumptionLine: line('consumption_amount'),
    purchaseArea: area('purchase_amount'),
    consumptionArea: area('consumption_amount'),
    first: s[0].label,
    last: s[s.length - 1].label,
  }
})

/** 排行/占比的条形宽度（相对最大值） */
function barWidth(value: string, max: string): string {
  const v = Number(value)
  const m = Number(max)
  if (!(m > 0)) return '0%'
  return `${Math.max(2, Math.round((v / m) * 100))}%`
}
const maxCategory = computed(() =>
  data.value?.category_breakdown.length
    ? data.value.category_breakdown[0].amount
    : '0'
)
const maxTop = computed(() =>
  data.value?.top_consumed.length ? data.value.top_consumed[0].weight : '0'
)

function fmtTime(s: string) {
  const d = new Date(s)
  return Number.isNaN(d.getTime())
    ? s
    : d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}

watch([granularity, fromDate, toDate], load)
onMounted(load)
</script>

<template>
  <section class="card">
    <div class="card__head stats-head">
      <h2>统计</h2>
      <div class="seg">
        <button v-for="g in grains" :key="g.key" class="seg__btn"
                :class="{ 'seg__btn--on': granularity === g.key }" @click="granularity = g.key">
          {{ g.label }}
        </button>
      </div>
      <div class="range">
        <input v-model="fromDate" type="date" />
        <span>~</span>
        <input v-model="toDate" type="date" />
      </div>
    </div>

    <p v-if="data" class="muted">
      {{ data.start_date }} ~ {{ data.end_date }}
      · 库存价值按**剩余成本**计（不是采购总额）
    </p>

    <div v-if="loading && !data" class="muted-line">加载中…</div>

    <template v-else-if="data">
      <!-- 概览卡片 -->
      <div class="cards">
        <div class="stat">
          <span>库存价值（剩余成本）</span>
          <strong>¥{{ data.stock.cost }}</strong>
          <small>{{ trimNum(data.stock.weight) }}g · {{ data.stock.batch_count }} 个批次</small>
        </div>
        <div class="stat">
          <span>期间采购</span>
          <strong>¥{{ data.purchase.total_amount }}</strong>
          <small>{{ trimNum(data.purchase.total_weight) }}g</small>
        </div>
        <div class="stat">
          <span>期间消耗</span>
          <strong>¥{{ data.consumption.total_amount }}</strong>
          <small>{{ trimNum(data.consumption.total_weight) }}g</small>
        </div>
        <div class="stat">
          <span>消耗 / 采购</span>
          <strong>{{ Number(data.purchase.total_amount) > 0
            ? ratioText(String(Number(data.consumption.total_amount) / Number(data.purchase.total_amount)))
            : '—' }}</strong>
          <small>期间无采购时不计算</small>
        </div>
      </div>

      <!-- 趋势 -->
      <h3>采购与消耗趋势</h3>
      <div v-if="chart" class="chart">
        <svg viewBox="0 0 100 44" preserveAspectRatio="none" class="chart__svg">
          <path :d="chart.purchaseArea" fill="rgba(61,122,90,.12)" />
          <path :d="chart.consumptionArea" fill="rgba(61,90,154,.10)" />
          <polyline :points="chart.purchaseLine" fill="none" stroke="#3d7a5a" stroke-width="1.2" />
          <polyline :points="chart.consumptionLine" fill="none" stroke="#3d5a9a" stroke-width="1.2" />
        </svg>
        <div class="chart__axis">
          <span>{{ chart.first }}</span>
          <span>{{ chart.last }}</span>
        </div>
        <div class="legend">
          <span><i class="dot dot--purchase" />采购</span>
          <span><i class="dot dot--consume" />消耗</span>
          <span class="muted">峰值 ¥{{ chart.max.toFixed(2) }}</span>
        </div>
      </div>
      <div v-else class="muted-line">这段时间没有流水</div>

      <!-- 分类占比 + 消耗排行 -->
      <div class="grid grid--2">
        <div>
          <h3>分类支出占比</h3>
          <div v-if="data.category_breakdown.length === 0" class="muted-line">期间没有消耗</div>
          <div v-for="c in data.category_breakdown" :key="c.name" class="bar-row">
            <span class="bar-row__name">{{ c.name }}</span>
            <div class="bar"><i :style="{ width: barWidth(c.amount, maxCategory) }" /></div>
            <span class="bar-row__val">¥{{ c.amount }} · {{ ratioText(c.ratio) }}</span>
          </div>
        </div>
        <div>
          <h3>消耗排行（按重量）</h3>
          <div v-if="data.top_consumed.length === 0" class="muted-line">期间没有消耗</div>
          <div v-for="t in data.top_consumed.slice(0, 5)" :key="t.ingredient_id" class="bar-row">
            <span class="bar-row__name">{{ t.name }}</span>
            <div class="bar bar--blue"><i :style="{ width: barWidth(t.weight, maxTop) }" /></div>
            <span class="bar-row__val">{{ trimNum(t.weight) }}g · {{ t.times }} 次</span>
          </div>
        </div>
      </div>

      <!-- 周转 -->
      <h3>库存周转</h3>
      <div v-if="data.turnover.length === 0" class="muted-line">期间没有采购或消耗</div>
      <div v-else class="turnover">
        <div class="turnover__head">
          <span>食材</span><span>采购次数</span><span>消耗次数</span><span>消耗量</span>
        </div>
        <div v-for="r in data.turnover.slice(0, 10)" :key="r.ingredient_id" class="turnover__row">
          <span>{{ r.name }}</span>
          <span>{{ r.purchase_times }}</span>
          <span>{{ r.consume_times }}</span>
          <span>{{ trimNum(r.consumed_weight) }}g</span>
        </div>
      </div>

      <!-- 最近操作 -->
      <div class="card__head ops-head">
        <h3>最近操作</h3>
        <a class="link" @click="$router.push('/records')">查看全部</a>
      </div>
      <div v-if="data.recent_operations.length === 0" class="muted-line">还没有操作记录</div>
      <div v-for="op in data.recent_operations" :key="op.id" class="op">
        <span class="tx-tag" :class="`tx-tag--${op.type}`">{{ TX_TYPE_LABEL[op.type] || op.type }}</span>
        <span class="op__name">{{ op.ingredient_name }}</span>
        <span class="op__delta">
          <template v-if="Number(op.weight_delta)">{{ trimNum(op.weight_delta) }}g</template>
          <template v-if="Number(op.cost_delta)"> · {{ op.cost_delta }} 元</template>
        </span>
        <span class="muted">{{ fmtTime(op.created_at) }}</span>
      </div>
    </template>
  </section>
</template>

<style scoped>
.stats-head { flex-wrap: wrap; gap: 10px; }
.stats-head h2 { margin: 0; }
.seg { display: flex; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
.seg__btn { padding: 4px 11px; font-size: 12px; background: transparent; border: 0; cursor: pointer; color: var(--text-2); }
.seg__btn--on { background: var(--green); color: #fff; }
.range { display: flex; align-items: center; gap: 5px; font-size: 12px; color: var(--text-3); }
.range input {
  height: 30px; padding: 0 8px; border: 1px solid var(--line);
  border-radius: 7px; font-size: 12.5px; background: var(--surface); color: var(--text);
}
.muted { color: var(--text-3); font-size: 11.5px; }
.muted-line { font-size: 13px; color: var(--text-3); padding: 6px 0; }
h3 { font-size: 13px; margin: 16px 0 8px; }

.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-top: 8px; }
.stat { display: flex; flex-direction: column; gap: 3px; padding: 11px 12px; border: 1px solid var(--line); border-radius: 10px; }
.stat span { font-size: 11.5px; color: var(--text-3); }
.stat strong { font-size: 19px; font-variant-numeric: tabular-nums; }
.stat small { font-size: 11px; color: var(--text-3); }

.chart { margin-top: 6px; }
.chart__svg { width: 100%; height: 120px; display: block; }
.chart__axis { display: flex; justify-content: space-between; font-size: 10.5px; color: var(--text-3); }
.legend { display: flex; gap: 14px; align-items: center; margin-top: 6px; font-size: 11.5px; color: var(--text-2); }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }
.dot--purchase { background: #3d7a5a; }
.dot--consume { background: #3d5a9a; }

.grid--2 { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.bar-row { display: grid; grid-template-columns: 74px 1fr auto; align-items: center; gap: 8px; padding: 4px 0; }
.bar-row__name { font-size: 12.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bar { height: 8px; background: #f0efe9; border-radius: 999px; overflow: hidden; }
.bar i { display: block; height: 100%; background: #8fb8a1; border-radius: 999px; }
.bar--blue i { background: #8fa3c8; }
.bar-row__val { font-size: 11px; color: var(--text-3); font-variant-numeric: tabular-nums; white-space: nowrap; }

.turnover { font-size: 12.5px; }
.turnover__head, .turnover__row {
  display: grid; grid-template-columns: 1.6fr .8fr .8fr .8fr; gap: 8px;
  padding: 6px 0; border-bottom: 1px dashed var(--line);
}
.turnover__head { color: var(--text-3); font-size: 11.5px; }
.turnover__row span:not(:first-child) { text-align: right; font-variant-numeric: tabular-nums; }

.ops-head { display: flex; align-items: center; justify-content: space-between; margin: 16px 0 6px; }
.ops-head h3 { margin: 0; }
.link { font-size: 12px; color: var(--green); cursor: pointer; }
.op { display: flex; align-items: center; gap: 10px; padding: 7px 0; border-top: 1px dashed var(--line); flex-wrap: wrap; font-size: 12.5px; }
.op__name { font-weight: 500; }
.op__delta { font-variant-numeric: tabular-nums; }
.tx-tag { font-size: 11px; padding: 2px 8px; border-radius: 999px; font-weight: 500; }
.tx-tag--purchase { background: var(--green-weak); color: var(--green); }
.tx-tag--consume { background: #eef2fb; color: #3d5a9a; }
.tx-tag--spoilage { background: #fbeae8; color: var(--red); }
.tx-tag--adjustment { background: #fdf3e2; color: #b8860b; }
.tx-tag--reverse { background: #f0efe9; color: var(--text-2); }

@media (max-width: 860px) {
  .grid--2 { grid-template-columns: 1fr; }
  .cards { grid-template-columns: repeat(2, 1fr); }
  .stat strong { font-size: 17px; }
  .turnover__head, .turnover__row { grid-template-columns: 1.4fr .7fr .7fr .8fr; }
  .bar-row { grid-template-columns: 66px 1fr auto; }
}
</style>
