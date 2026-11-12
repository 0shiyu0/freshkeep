/** 临期提醒与通知中心（阶段 8）。 */
import { apiGet, apiPost, request } from './http'
import type { PageResult } from './ingredients'

export interface NotificationRow {
  id: string
  type: 'expiring' | 'expired' | 'low_stock' | 'backup'
  batch_id: string | null
  ingredient_id: string | null
  ingredient_name: string
  batch_no: string
  status: string
  payload: Record<string, unknown>
  created_at: string
  sent_at: string | null
}

export interface AlertSummary {
  unread: number
  expiring: number
  expired: number
  low_stock: number
}

export interface PurchaseSuggestion {
  ingredient_id: string
  name: string
  total_weight: string
  minimum_weight: string
  suggested_weight: string | null
  suggested_quantity: string | null
  reason: string
  last_unit_cost: string | null
  estimated_cost: string | null
  weight_symbol: string
}

export const alertsApi = {
  scan: (days = 7) =>
    apiPost<{ created: number; by_type: Record<string, number> }>(`/alerts/scan?days=${days}`, {}),
  summary: () => apiGet<AlertSummary>('/alerts/summary'),
  list: (params: Record<string, unknown> = {}) =>
    apiGet<PageResult<NotificationRow>>('/alerts/notifications', params),
  read: (id: string) => apiPost<{ updated: number }>(`/alerts/notifications/${id}/read`),
  readAll: () => apiPost<{ updated: number }>('/alerts/notifications/read-all'),
  suggestions: () =>
    apiGet<{ items: PurchaseSuggestion[]; total: number; estimated_total: string | null }>(
      '/purchase/suggestions',
    ),
}
