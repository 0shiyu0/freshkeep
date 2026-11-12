/** 首页统计（M6）：库存价值、期间金额、最近入库、临期、营养汇总。 */
import { apiGet, request } from './http'

export interface RecentBatch {
  batch_id: string
  batch_no: string
  ingredient_id: string
  ingredient_name: string
  weight: string
  cost: string
  purchase_date: string
  created_at: string
}

export interface DashboardSummary {
  stock_cost: string
  stock_weight: string
  stock_ingredient_count: number
  batch_count: number
  low_stock_count: number
  expiring_count: number
  expired_count: number
  period_start: string
  period_end: string
  purchase_amount: string
  consumption_amount: string
  spoilage_amount: string
  consumption_ratio: string | null
  recent_batches: RecentBatch[]
}

export interface NutritionItem {
  code: string
  name: string
  unit: string
  actual_value: string
  target_value: string | null // 日目标
  period_target: string | null // 本窗口累计目标（日目标 × 天数）
  achievement: string | null
}

export interface DashboardNutrition {
  period: string
  start_date: string
  end_date: string
  days: number
  has_records: boolean
  record_count: number
  items: NutritionItem[]
  disclaimer: string
}

export interface TargetRow {
  code: string
  name: string
  unit: string
  target_value: string
  period: string
  effective_from: string
}

export const dashboardApi = {
  summary: (params: Record<string, unknown> = {}) =>
    apiGet<DashboardSummary>('/dashboard/summary', params),
  nutrition: (period: string) => apiGet<DashboardNutrition>('/dashboard/nutrition', { period }),
  targets: () => apiGet<{ items: TargetRow[] }>('/nutrition/targets'),
  saveTargets: (items: Array<{ code: string; target_value: string; period: string }>) =>
    request<{ updated: number }>({ url: '/nutrition/targets', method: 'PUT', data: { items } }),
}

/** 百分比展示：achievement 是 0~1 的小数，null 返回「—」。 */
export function pct(v: string | null): string {
  if (v === null || v === undefined) return '—'
  return `${(Number(v) * 100).toFixed(0)}%`
}
