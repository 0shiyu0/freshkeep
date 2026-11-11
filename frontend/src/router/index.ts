import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

// 路由与 docs/ARCHITECTURE.md §6 的页面结构对应
const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { public: true } },
  { path: '/', name: 'dashboard', component: () => import('@/views/DashboardView.vue') },
  { path: '/inventory', name: 'inventory', component: () => import('@/views/InventoryView.vue') },
  { path: '/consume', name: 'consume', component: () => import('@/views/ConsumeView.vue') },
  { path: '/purchase', name: 'purchase', component: () => import('@/views/PurchaseView.vue') },
  { path: '/stocktake', name: 'stocktake', component: () => import('@/views/StocktakeView.vue') },
  { path: '/batches', name: 'batches', component: () => import('@/views/BatchesView.vue') },
  { path: '/batches/:id', name: 'batch-detail', component: () => import('@/views/BatchDetailView.vue') },
  { path: '/ingredients/new', name: 'ingredient-new', component: () => import('@/views/IngredientFormView.vue') },
  { path: '/ingredients/:id', name: 'ingredient-detail', component: () => import('@/views/IngredientDetailView.vue') },
  {
    path: '/ingredients/:id/edit',
    name: 'ingredient-edit',
    component: () => import('@/views/IngredientFormView.vue'),
  },
  { path: '/records', name: 'records', component: () => import('@/views/RecordsView.vue') },
  { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
  { path: '/pair', redirect: '/login' },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

/** 路由守卫：未登录一律去 /login；已登录访问 /login 则回首页 */
router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.checked) await auth.fetchMe()

  if (to.meta.public) {
    if (auth.authenticated && to.name === 'login') return { path: '/' }
    return true
  }
  if (!auth.authenticated) {
    return { path: '/login', query: to.fullPath !== '/' ? { redirect: to.fullPath } : undefined }
  }
  return true
})

export default router
