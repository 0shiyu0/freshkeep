import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

// 路由与 docs/final-plan.md §1 的页面结构对应
const routes: RouteRecordRaw[] = [
  { path: '/pair', name: 'pair', component: () => import('@/views/PairView.vue') },
  { path: '/', name: 'dashboard', component: () => import('@/views/DashboardView.vue') },
  { path: '/inventory', name: 'inventory', component: () => import('@/views/InventoryView.vue') },
  { path: '/records', name: 'records', component: () => import('@/views/RecordsView.vue') },
  { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// M1 接入真实鉴权后改为读 Pinia 的登录态；现在只保证未实现页面可访问
router.beforeEach((to) => {
  void to
  return true
})

export default router
