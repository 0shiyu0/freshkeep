/** 批次域：入库、批次列表、临期/过期（M3）。 */
import { apiGet, apiPost, request } from './http'
import type { PageResult } from './ingredients'

export interface BatchItem {
  id: string
  batch_no: string
  ingredient_id: string
  ingredient_name: string
  purchase_date: string
  production_date: string | null
  expiry_date: string | null
  opened_date: string | null
  storage_location_id: string | null
  location_name: string | null
  initial_quantity: string
  remaining_quantity: string
  initial_weight: string
  remaining_weight: string
  purchase_cost: string
  remaining_cost: string
  unit_cost: string | null
  status: string
  note: string
  days_to_expiry: number | null
  created_at: string
}

export interface BatchCreateInput {
  ingredient_id: string
  purchase_date?: string
  production_date?: string | null
  expiry_date?: string | null
  opened_date?: string | null
  storage_location_id?: string | null
  quantity?: string
  weight?: string
  purchase_cost?: string
  quantity_unit_id?: string | null
  weight_unit_id?: string | null
  note?: string
}

export const batchApi = {
  create: (data: BatchCreateInput) =>
    apiPost<{ batch: BatchItem; transaction: { id: string; transaction_no: string } }>(
      '/batches',
      data
    ),
  list: (params: Record<string, unknown> = {}) =>
    apiGet<PageResult<BatchItem>>('/batches', params),
  detail: (id: string) => apiGet<BatchItem>(`/batches/${id}`),
  expiring: (days = 7) => apiGet<{ items: BatchItem[] }>('/batches/expiring', { days }),
  expired: () => apiGet<{ items: BatchItem[] }>('/batches/expired'),
  updateMeta: (id: string, data: Record<string, unknown>) =>
    request<BatchItem>({ url: `/batches/${id}`, method: 'PUT', data }),
}

/** 到期紧迫度 → 展示样式（中文习惯：越紧急越红）。 */
export function expiryClass(b: BatchItem): string {
  if (b.days_to_expiry === null) return 'muted'
  if (b.days_to_expiry < 0) return 'expired'
  if (b.days_to_expiry <= 1) return 'danger'
  if (b.days_to_expiry <= 3) return 'warn'
  return 'ok'
}

export function expiryText(b: BatchItem): string {
  if (b.days_to_expiry === null) return '无到期日'
  if (b.days_to_expiry < 0) return `已过期 ${-b.days_to_expiry} 天`
  if (b.days_to_expiry === 0) return '今天到期'
  return `剩 ${b.days_to_expiry} 天`
}
