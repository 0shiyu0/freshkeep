/** 统计（阶段 6）：库存价值、趋势、分类占比、排行、周转、最近操作。 */
import { apiGet } from './http'

export type Granularity = 'day' | 'week' | 'month' | 'year'

export interface SeriesPoint {
  bucket: string
  label: string
  purchase_amount: string
  consumption_amount: string
  purchase_weight: string
  consumption_weight: string
}

export interface CategoryRow {
  name: string
  amount: string
  ratio: string
  weight: string
}

export interface TopConsumedRow {
  ingredient_id: string
  name: string
  weight: string
  cost: string
  times: number
}

export interface TurnoverRow {
  ingredient_id: string
  name: string
  purchase_times: number
  consume_times: number
  consumed_weight: string
}

export interface OperationRow {
  id: string
  transaction_no: string
  type: string
  ingredient_name: string
  weight_delta: string
  cost_delta: string
  reason: string
  created_at: string
}

export interface StatsOverview {
  granularity: Granularity
  start_date: string
  end_date: string
  has_data: boolean
  stock: { cost: string; weight: string; ingredient_count: number; batch_count: number }
  purchase: { total_amount: string; total_weight: string }
  consumption: { total_amount: string; total_weight: string }
  series: SeriesPoint[]
  category_breakdown: CategoryRow[]
  top_consumed: TopConsumedRow[]
  turnover: TurnoverRow[]
  recent_operations: OperationRow[]
}

export const statsApi = {
  overview: (params: { granularity: Granularity; from_date?: string; to_date?: string }) =>
    apiGet<StatsOverview>('/stats/overview', params as unknown as Record<string, unknown>),
}

/** 百分比：ratio 是 0~1 小数 */
export function ratioText(v: string | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return `${(Number(v) * 100).toFixed(1)}%`
}
