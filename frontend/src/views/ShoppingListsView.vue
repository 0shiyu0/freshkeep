<script setup lang="ts">
/** 采购清单（阶段 8.13）：按菜谱合并生成，只列缺口；不自动改库存。 */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { recipeApi, type ShoppingList } from '@/api/recipes'
import { notifyError, notifySuccess } from '@/utils/notify'

const router = useRouter()
const lists = ref<
  Array<{
    id: string
    name: string
    status: string
    item_count: number
    open_count: number
    created_at: string
  }>
>([])
const detail = ref<ShoppingList | null>(null)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const res = await recipeApi.shoppingLists()
    lists.value = res.items
    if (res.items.length && !detail.value) await open(res.items[0].id)
  } finally {
    loading.value = false
  }
}

async function open(id: string) {
  try {
    detail.value = await recipeApi.shoppingList(id)
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '加载失败')
  }
}

async function toggle(itemId: string, done: boolean) {
  try {
    await recipeApi.toggleItem(itemId, done)
    if (detail.value) detail.value = await recipeApi.shoppingList(detail.value.id)
    await load()
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '操作失败')
  }
}

async function completeAll() {
  if (!detail.value) return
  try {
    await recipeApi.completeList(detail.value.id)
    notifySuccess('清单已完成')
    await load()
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '操作失败')
  }
}

async function importNow() {
  if (!detail.value) return
  if (!window.confirm(`按清单「${detail.value.name}」一键入库？成本按最近采购单价估算。`)) return
  try {
    const res = await recipeApi.importList(detail.value.id)
    notifySuccess(
      `已入库 ${res.batches.length} 个批次，估算成本 ¥${res.total_cost}` +
        (res.zero_cost_ingredients.length
          ? `（${res.zero_cost_ingredients.length} 项无历史价按 0 记，请补录）`
          : ''),
    )
    await load()
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '入库失败')
  }
}

async function fromLowStock() {
  try {
    const res = await recipeApi.fromLowStock('低库存补货')
    if (res.items.length === 0) notifySuccess('没有低库存食材')
    else notifySuccess(`已按低库存生成 ${res.items.length} 项`)
    await load()
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '生成失败')
  }
}

function fmt(s: string) {
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? s : d.toLocaleString('zh-CN', { hour12: false })
}

onMounted(load)
</script>

<template>
  <div class="page-head">
    <div>
      <h1>采购清单</h1>
      <p>由菜谱缺口合并生成；清单只是待办，不会改变库存</p>
    </div>
    <div class="head-actions">
      <button class="btn" @click="router.push('/recipes')">菜谱</button>
      <button class="btn" @click="fromLowStock">按低库存生成</button>
      <button class="btn" @click="router.push('/purchase')">+ 采购入库</button>
    </div>
  </div>

  <div v-if="loading && lists.length === 0" class="card empty"><p>加载中…</p></div>

  <section v-else-if="lists.length === 0" class="card empty">
    <h3>还没有采购清单</h3>
    <p>在菜谱详情页点「按缺口生成采购清单」，会在这里出现。</p>
    <button class="btn btn--primary" style="margin-top: 10px" @click="router.push('/recipes')">
      去菜谱
    </button>
  </section>

  <div v-else class="grid">
    <section class="card lists">
      <h2>清单（{{ lists.length }}）</h2>
      <div
        v-for="l in lists"
        :key="l.id"
        class="list-row"
        :class="{ 'list-row--on': detail?.id === l.id }"
        @click="open(l.id)"
      >
        <div>
          <div class="list-row__name">{{ l.name }}</div>
          <div class="list-row__meta">
            {{ fmt(l.created_at) }} · {{ l.item_count }} 项（待办 {{ l.open_count }}）
          </div>
        </div>
        <span class="tag">{{ l.status === 'open' ? '待采购' : l.status }}</span>
      </div>
    </section>

    <section v-if="detail" class="card">
      <div class="card__head">
        <h2>{{ detail.name }}</h2>
        <div class="head-actions">
          <span class="tag">{{ detail.items.length }} 项</span>
          <button v-if="detail.status === 'open'" class="btn btn--tiny" @click="importNow">
            一键入库
          </button>
          <button v-if="detail.status === 'open'" class="btn btn--tiny" @click="completeAll">
            全部完成
          </button>
        </div>
      </div>
      <div v-if="detail.items.length === 0" class="muted-line">这份清单没有需要采购的项</div>
      <div
        v-for="i in detail.items"
        :key="i.id"
        class="item"
        :class="{ 'item--done': i.is_completed }"
      >
        <input
          type="checkbox"
          :checked="i.is_completed"
          @change="toggle(i.id, ($event.target as HTMLInputElement).checked)"
        />
        <div class="item__main">
          <div class="item__name">{{ i.ingredient_name }}</div>
          <div class="item__meta">
            建议 {{ i.suggested_weight ? Number(i.suggested_weight) + 'g' : '—' }}
            <span class="src">{{ i.source === 'recipe' ? '来自菜谱' : i.source }}</span>
          </div>
        </div>
        <button
          class="btn btn--tiny"
          @click="router.push(`/purchase?ingredient=${i.ingredient_id || ''}`)"
        >
          去入库
        </button>
      </div>
      <p class="muted note">按缺口生成：需求（含份数缩放）相加 − 现有库存，只保留正缺口。</p>
    </section>
  </div>
</template>

<style scoped>
.empty {
  text-align: center;
  padding: 26px 0;
}
.grid {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 14px;
  align-items: start;
}
.lists h2 {
  margin: 0 0 8px;
}
.list-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 10px;
  border-radius: 9px;
  cursor: pointer;
}
.list-row:hover {
  background: #f7f6f2;
}
.list-row--on {
  background: var(--green-weak);
}
.list-row__name {
  font-size: 13.5px;
  font-weight: 500;
}
.list-row__meta {
  font-size: 11px;
  color: var(--text-3);
  margin-top: 2px;
}
.card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.card__head h2 {
  margin: 0;
}
.item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 0;
  border-top: 1px dashed var(--line);
}
.item--done .item__name {
  text-decoration: line-through;
  color: var(--text-3);
}
.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.item__main {
  flex: 1;
}
.item__name {
  font-size: 14px;
  font-weight: 500;
}
.item__meta {
  font-size: 11.5px;
  color: var(--text-3);
  margin-top: 2px;
  display: flex;
  gap: 8px;
}
.src {
  font-family: ui-monospace, monospace;
  font-size: 10.5px;
  opacity: 0.8;
}
.btn--tiny {
  padding: 3px 9px;
  font-size: 11.5px;
  border-radius: 6px;
}
.muted {
  color: var(--text-3);
  font-size: 11.5px;
}
.muted-line {
  font-size: 13px;
  color: var(--text-3);
  padding: 6px 0;
}
.note {
  margin-top: 10px;
}
@media (max-width: 860px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
