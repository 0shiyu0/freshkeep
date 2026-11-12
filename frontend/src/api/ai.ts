/** AI 辅助（阶段 8）：识别只产生草稿，确认才建档/入库。 */
import { apiGet, apiPost, request } from './http'

export interface DraftWarning {
  code: string
  field: string
  message: string
  before?: unknown
  after?: unknown
}

export interface RecognitionDraft {
  id: string
  status: 'pending' | 'confirmed' | 'rejected'
  provider: string
  model: string
  image_url: string | null
  warnings: DraftWarning[]
  draft: {
    name?: string
    brand?: string
    specification?: string
    barcode?: string
    category?: string
    nutrition?: Array<{ code: string; value: string; basis_amount: string; basis_unit: string }>
    production_date?: string | null
    expiry_date?: string | null
    shelf_life_days?: number | null
    storage_location_id?: string | null
    weight?: string
    quantity?: string
    purchase_cost?: string
  }
  confirmed_entity_type: string | null
  confirmed_entity_id: string | null
  created_at: string
  confirmed_at: string | null
}

export interface ProductLookup {
  found: boolean
  source: string
  barcode: string
  ingredient_id?: string
  ingredient_name?: string
  brand?: string
  specification?: string
  message?: string
  source_error?: string
  product?: {
    name: string
    brand: string
    specification: string
    barcode: string
    nutrition: Array<{ code: string; value: string; basis_amount: string; basis_unit: string }>
    source_label?: string
  }
}

export interface AiSettings {
  kind: 'none' | 'stub' | 'openai_compatible'
  base_url: string
  api_key: string
  model: string
  enabled: boolean
  timeout_seconds: number
}

export const aiApi = {
  recognize: (data: { image_file_id?: string; hint?: string; manual?: Record<string, unknown> }) =>
    apiPost<RecognitionDraft>('/ai/recognitions', data),
  get: (id: string) => apiGet<RecognitionDraft>(`/ai/recognitions/${id}`),
  patch: (id: string, patch: Record<string, unknown>) =>
    request<RecognitionDraft>({ url: `/ai/recognitions/${id}`, method: 'PATCH', data: { patch } }),
  confirm: (id: string, target: 'ingredient' | 'batch', ingredientId?: string) =>
    apiPost<{ draft: RecognitionDraft; ingredient_id?: string; batch_id?: string }>(
      `/ai/recognitions/${id}/confirm`,
      { target, ingredient_id: ingredientId ?? null },
    ),
  reject: (id: string) => apiPost<RecognitionDraft>(`/ai/recognitions/${id}/reject`),
  settings: () => apiGet<AiSettings>('/ai/settings'),
  saveSettings: (data: AiSettings) =>
    request<{ saved: boolean }>({ url: '/ai/settings', method: 'PUT', data }),
}

export const productApi = {
  lookup: (barcode: string) => apiGet<ProductLookup>('/products/lookup', { barcode }),
}
