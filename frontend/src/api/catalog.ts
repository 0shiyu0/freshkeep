/** 基础资料：分类 / 单位 / 储存位置 / 营养项目。 */
import { apiGet, apiPost, request } from './http'

export interface Category {
  id: string
  name: string
  parent_id: string | null
  parent_name: string | null
  sort_order: number
  is_active: boolean
  ingredient_count: number
}

export interface Unit {
  id: string
  name: string
  symbol: string
  dimension: 'quantity' | 'weight' | 'volume'
  precision: number
  is_system: boolean
  usage_count: number
}

export interface StorageLocation {
  id: string
  name: string
  description: string
  sort_order: number
}

export interface NutritionDefinition {
  id: string
  code: string
  name: string
  unit: string
  sort_order: number
}

export const catalogApi = {
  categories: () => apiGet<{ items: Category[]; total: number }>('/categories'),
  createCategory: (data: { name: string; parent_id?: string | null; sort_order?: number }) =>
    apiPost<Category>('/categories', data),
  updateCategory: (id: string, data: Record<string, unknown>) =>
    request<Category>({ url: `/categories/${id}`, method: 'PUT', data }),
  deleteCategory: (id: string) => request<{ deleted: boolean }>({ url: `/categories/${id}`, method: 'DELETE' }),
  sortCategories: (items: Array<{ id: string; sort_order: number }>) =>
    request<{ updated: number }>({ url: '/categories/sort', method: 'PUT', data: { items } }),

  units: (dimension?: string) =>
    apiGet<{ items: Unit[]; total: number }>('/units', dimension ? { dimension } : undefined),
  createUnit: (data: { name: string; symbol?: string; dimension: string; precision?: number }) =>
    apiPost<Unit>('/units', data),
  updateUnit: (id: string, data: Record<string, unknown>) =>
    request<Unit>({ url: `/units/${id}`, method: 'PUT', data }),
  deleteUnit: (id: string) => request<{ deleted: boolean }>({ url: `/units/${id}`, method: 'DELETE' }),

  locations: () => apiGet<{ items: StorageLocation[]; total: number }>('/storage-locations'),
  createLocation: (data: { name: string; description?: string; sort_order?: number }) =>
    apiPost<StorageLocation>('/storage-locations', data),
  updateLocation: (id: string, data: Record<string, unknown>) =>
    request<StorageLocation>({ url: `/storage-locations/${id}`, method: 'PUT', data }),
  deleteLocation: (id: string) =>
    request<{ deleted: boolean }>({ url: `/storage-locations/${id}`, method: 'DELETE' }),

  nutritionDefinitions: () =>
    apiGet<{ items: NutritionDefinition[]; total: number }>('/nutrition/definitions'),
}
