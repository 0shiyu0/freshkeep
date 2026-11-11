/** 食材档案与图片。 */
import { apiGet, apiPost, request } from './http'

export interface UnitBrief {
  id: string
  name: string
  symbol: string
  dimension: string
}

export interface IngredientListItem {
  id: string
  name: string
  category_id: string | null
  category_path: string
  image_url: string | null
  quantity_unit: UnitBrief | null
  weight_unit: UnitBrief | null
  unit_weight_display: string
  minimum_stock_display: string
  location_name: string | null
  is_active: boolean
  updated_at: string | null
}

export interface NutritionItem {
  code: string
  name: string
  unit: string
  value: string
  basis_amount: string
  source: string
  version: number
  basis_unit_id: string
}

export interface IngredientDetail extends IngredientListItem {
  brand: string
  specification: string
  note: string
  nutrition_basis_display: string
  default_unit_weight: string | null
  minimum_quantity: string | null
  minimum_weight: string | null
  can_convert: boolean
  barcodes: Array<{ barcode: string; barcode_type: string }>
  nutrition: NutritionItem[]
  created_at: string | null
}

export interface ListQuery {
  q?: string
  category_id?: string
  location_id?: string
  include_inactive?: boolean
  page?: number
  page_size?: number
  sort_by?: string
  sort_order?: string
}

export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export const ingredientApi = {
  list: (params: ListQuery = {}) => apiGet<PageResult<IngredientListItem>>('/ingredients', params as Record<string, unknown>),
  suggest: (q: string, limit = 8) =>
    apiGet<{ items: Array<{ id: string; name: string; pinyin: string }> }>('/ingredients/search', { q, limit }),
  detail: (id: string) => apiGet<IngredientDetail>(`/ingredients/${id}`),
  create: (data: Record<string, unknown>) => apiPost<{ id: string }>('/ingredients', data),
  update: (id: string, data: Record<string, unknown>) =>
    request<{ id: string }>({ url: `/ingredients/${id}`, method: 'PUT', data }),
  deactivate: (id: string) => apiPost<{ is_active: boolean }>(`/ingredients/${id}/deactivate`),
  activate: (id: string) => apiPost<{ is_active: boolean }>(`/ingredients/${id}/activate`),
  convert: (id: string, quantity: string) =>
    apiGet<{ quantity: string; weight: string; unit_weight: string; basis: string }>(
      `/ingredients/${id}/conversion`,
      { quantity }
    ),
  barcodeLookup: (code: string) =>
    apiGet<{ barcode: string; ingredient: { id: string; name: string; is_active: boolean } }>(
      `/barcodes/${encodeURIComponent(code)}`
    ),
  bindBarcode: (ingredientId: string, barcode: string, barcodeType = 'ean13') =>
    apiPost<{ id: string; barcode: string }>('/barcodes', {
      ingredient_id: ingredientId,
      barcode,
      barcode_type: barcodeType,
    }),
  /** 整体替换营养档案（版本化，历史快照不受影响） */
  updateNutrition: (
    id: string,
    items: Array<{ code: string; value: string; basis_amount: string; basis_unit_id: string; source: string }>
  ) => request<{ updated: number }>({ url: `/ingredients/${id}/nutrition`, method: 'PUT', data: { items } }),
  unbindBarcode: (barcodeId: string) =>
    request<{ deleted: boolean }>({ url: `/barcodes/${barcodeId}`, method: 'DELETE' }),
}

export interface UploadedFile {
  id: string
  url: string
  mime_type: string
  size_bytes: number
  checksum: string
}

export const fileApi = {
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<UploadedFile>({ url: '/files/upload', method: 'POST', data: form })
  },
  remove: (id: string) => request<{ deleted: boolean }>({ url: `/files/${id}`, method: 'DELETE' }),
}
