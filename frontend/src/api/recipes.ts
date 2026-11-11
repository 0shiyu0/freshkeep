/** 菜谱与采购清单（阶段 8.11~8.13）。 */
import { apiDelete, apiGet, apiPost, apiPut, request } from './http'
import type { PageResult } from './ingredients'

export interface RecipeItem {
  id?: string
  ingredient_id: string
  ingredient_name?: string
  weight: string | null
  quantity: string | null
  unit_id?: string | null
  note?: string
  available_weight?: string
}

export interface Recipe {
  id: string
  name: string
  category: string
  servings: string
  duration_minutes: number | null
  steps: string
  note: string
  image_url: string | null
  created_at: string
  items: RecipeItem[]
}

export interface RecipeListItem {
  id: string
  name: string
  category: string
  servings: string
  duration_minutes: number | null
  item_count: number
  created_at: string
  image_url: string | null
}

export interface MatchRow {
  ingredient_id: string
  ingredient_name: string
  required_weight: string
  available_weight: string
  shortage_weight: string
  sufficient: boolean
  unmeasured: boolean
}

export interface RecipeMatch {
  recipe_id: string
  recipe_name: string
  servings: string
  can_cook: boolean
  missing_count: number
  items: MatchRow[]
}

export interface ShoppingList {
  id: string
  name: string
  status: string
  created_at: string
  completed_at: string | null
  items: Array<{
    id: string
    ingredient_id: string | null
    ingredient_name: string
    suggested_weight: string | null
    suggested_quantity: string | null
    source: string
    is_completed: boolean
    note: string
  }>
}

export const recipeApi = {
  list: (params: Record<string, unknown> = {}) =>
    apiGet<PageResult<RecipeListItem>>('/recipes', params),
  detail: (id: string) => apiGet<Recipe>(`/recipes/${id}`),
  create: (data: Record<string, unknown>) => apiPost<Recipe>('/recipes', data),
  update: (id: string, data: Record<string, unknown>) => apiPut<Recipe>(`/recipes/${id}`, data),
  remove: (id: string) => apiDelete<{ deleted: boolean }>(`/recipes/${id}`),
  match: (id: string, servings?: string) =>
    apiGet<RecipeMatch>(`/recipes/${id}/match`, servings ? { servings } : {}),
  shoppingListFromRecipes: (data: { recipe_ids: string[]; servings_map?: Record<string, string>; name?: string }) =>
    apiPost<{ id: string; name: string; status: string; items: Array<Record<string, unknown>>; message: string }>(
      '/shopping-lists/from-recipes',
      data
    ),
  shoppingLists: () => apiGet<PageResult<{ id: string; name: string; status: string; item_count: number; open_count: number; created_at: string }>>('/shopping-lists'),
  shoppingList: (id: string) => apiGet<ShoppingList>(`/shopping-lists/${id}`),
}
