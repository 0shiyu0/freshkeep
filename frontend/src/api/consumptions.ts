/** 消耗域（M4）：记录消耗、列表、详情、撤销。 */
import { apiGet, apiPost, request } from './http'
import type { PageResult } from './ingredients'

export interface Allocation {
  batch_id: string
  batch_no: string
  quantity_delta: string
  weight_delta: string
  cost_delta: string
  unit_cost: string | null
  batch_remaining_quantity: string | null
  batch_remaining_weight: string | null
  batch_remaining_cost: string | null
}

export interface NutritionSnapshot {
  code: string
  name: string
  actual_value: string
  unit: string
  basis_snapshot: Record<string, unknown>
}

export interface Consumption {
  id: string
  consumption_no: string
  ingredient_id: string
  ingredient_name: string
  quantity: string
  weight: string
  cost: string
  consumed_at: string
  note: string
  status: string
  created_at: string
  allocations?: Allocation[]
  nutrition?: NutritionSnapshot[]
}

export interface ConsumptionResult {
  consumption: Consumption
  allocations: Allocation[]
  nutrition: NutritionSnapshot[]
}

export const consumptionApi = {
  create: (data: Record<string, unknown>) => apiPost<ConsumptionResult>('/consumptions', data),
  /** 批量消耗：整批成功或整批回滚（后端同一请求事务） */
  createBatch: (items: Array<Record<string, unknown>>, note = '') =>
    apiPost<{ items: ConsumptionResult[]; total: number }>('/consumptions/batch', { items, note }),
  list: (params: Record<string, unknown> = {}) =>
    apiGet<PageResult<Consumption>>('/consumptions', params),
  detail: (id: string) => apiGet<Consumption>(`/consumptions/${id}`),
  reverse: (id: string, reason = '') =>
    apiPost<{ status: string; reverse_transaction_no: string }>(`/consumptions/${id}/reverse`, {
      reason,
    }),
}
