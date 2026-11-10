/** 库存域（M5）：聚合、汇总、流水、盘点、报损。 */
import { apiGet, apiPost, request } from './http'
import type { PageResult } from './ingredients'

export interface InventoryRow {
  ingredient_id: string
  name: string
  category_id: string | null
  category_path: string
  total_quantity: string
  total_weight: string
  total_cost: string
  batch_count: number
  nearest_expiry: string | null
  days_to_expiry: number | null
  is_low_stock: boolean
  minimum_weight: string
  minimum_quantity: string
  weight_unit_symbol: string | null
  quantity_unit_name: string | null
}

export interface InventorySummary {
  total_weight: string
  total_cost: string
  total_quantity: string
  ingredient_count: number
  batch_count: number
  low_stock_count: number
  expiring_count: number
  expired_count: number
}

export interface TransactionRow {
  id: string
  transaction_no: string
  type: string
  ingredient_id: string
  ingredient_name: string
  quantity_delta: string
  weight_delta: string
  cost_delta: string
  reason: string
  related_object_type: string | null
  related_object_id: string | null
  created_at: string
}

export interface AdjustmentResult {
  transaction_id: string
  transaction_no: string
  batch_id: string
  batch_no: string
  quantity_delta: string
  weight_delta: string
  cost_delta: string
  batch_remaining_weight: string
  batch_remaining_cost: string
  status: string
}

export interface SpoilageResult {
  transaction_id: string
  transaction_no: string
  weight: string
  quantity: string
  cost: string
  allocations: Array<{
    batch_id: string
    batch_no: string
    weight_delta: string
    cost_delta: string
    batch_remaining_weight: string
    batch_remaining_cost: string
  }>
}

/** 流水类型 → 中文名（展示与筛选共用，避免各处硬编码字符串）。 */
export const TX_TYPE_LABEL: Record<string, string> = {
  purchase: '入库',
  consume: '消耗',
  spoilage: '报损',
  adjustment: '盘点',
  reverse: '冲销',
}

export const inventoryApi = {
  list: (params: Record<string, unknown> = {}) =>
    apiGet<PageResult<InventoryRow>>('/inventory', params),
  summary: () => apiGet<InventorySummary>('/inventory/summary'),
  transactions: (params: Record<string, unknown> = {}) =>
    apiGet<PageResult<TransactionRow>>('/inventory/transactions', params),
  adjust: (data: {
    batch_id: string
    actual_weight?: string
    actual_quantity?: string
    reason: string
  }) => apiPost<AdjustmentResult>('/inventory/adjustments', data),
  stocktake: (items: Array<Record<string, unknown>>) =>
    apiPost<{ items: AdjustmentResult[] }>('/inventory/stocktake', { items }),
  spoilage: (data: Record<string, unknown>) => apiPost<SpoilageResult>('/inventory/spoilage', data),
}

/** 数字展示：去掉无意义的尾零（仅展示层，不回写）。 */
export function trimNum(v: string): string {
  const n = Number(v)
  return Number.isFinite(n) ? String(n) : v
}
