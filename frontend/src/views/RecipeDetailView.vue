<script setup lang="ts">
/** 菜谱详情（阶段 8.12）：按份数匹配库存，一键生成缺口采购清单。 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton } from 'naive-ui'

import { recipeApi, type Recipe, type RecipeMatch } from '@/api/recipes'
import { notifyError, notifySuccess } from '@/utils/notify'

const route = useRoute()
const router = useRouter()
const id = computed(() => String(route.params.id))

const recipe = ref<Recipe | null>(null)
const match = ref<RecipeMatch | null>(null)
const servings = ref('')
const loading = ref(false)
const busy = ref(false)

async function load() {
  loading.value = true
  try {
    recipe.value = await recipeApi.detail(id.value)
    servings.value = String(Number(recipe.value.servings))
    match.value = await recipeApi.match(id.value, servings.value)
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function rematch() {
  try {
    match.value = await recipeApi.match(id.value, servings.value)
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '匹配失败')
  }
}

async function makeShoppingList() {
  if (busy.value) return
  busy.value = true
  try {
    const res = await recipeApi.shoppingListFromRecipes({
      recipe_ids: [id.value],
      servings_map: { [id.value]: servings.value },
      name: `${recipe.value?.name ?? '菜谱'} 采购清单`,
    })
    if (res.items.length === 0) notifySuccess('现有库存已满足，无需采购')
    else notifySuccess(`已生成采购清单（${res.items.length} 项）`)
    router.push('/shopping-lists')
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '生成失败')
  } finally {
    busy.value = false
  }
}

const legacySteps = computed(() => (recipe.value?.steps ?? []).some((s) => s.legacy))

onMounted(load)
</script>

<template>
  <div v-if="loading" class="card empty"><p>加载中…</p></div>

  <template v-else-if="recipe">
    <div class="page-head">
      <div>
        <h1>{{ recipe.name }}</h1>
        <p>
          <template v-if="recipe.category">{{ recipe.category }} · </template>
          基准 {{ Number(recipe.servings) }} 份
          <template v-if="recipe.duration_minutes"> · {{ recipe.duration_minutes }} 分钟</template>
        </p>
      </div>
      <div class="head-actions">
        <button class="btn" @click="router.push('/recipes')">返回菜谱</button>
        <button class="btn" @click="router.push('/shopping-lists')">采购清单</button>
      </div>
    </div>

    <section class="card">
      <div class="card__head">
        <h2>库存匹配</h2>
        <div class="controls">
          <label
            >做几份
            <input v-model="servings" inputmode="decimal" @change="rematch" />
          </label>
          <span class="badge" :class="match?.can_cook ? 'ok' : 'warn'">
            {{ match?.can_cook ? '可以做' : `缺 ${match?.missing_count ?? 0} 种` }}
          </span>
        </div>
      </div>

      <div v-if="!match || match.items.length === 0" class="muted-line">没有食材需求</div>
      <div v-else class="match">
        <div class="match__head">
          <span>食材</span><span>需求</span><span>现有</span><span>缺口</span>
        </div>
        <div
          v-for="m in match.items"
          :key="m.ingredient_id"
          class="match__row"
          :class="{ 'match__row--short': !m.sufficient }"
        >
          <span>{{ m.ingredient_name }}<em v-if="m.unmeasured">（数量计量）</em></span>
          <span>{{ Number(m.required_weight) }}g</span>
          <span>{{ Number(m.available_weight) }}g</span>
          <span>{{ m.unmeasured ? '—' : Number(m.shortage_weight) + 'g' }}</span>
        </div>
      </div>

      <div class="foot">
        <span class="muted">缺口 = 需求 − 现有库存；不会自动扣减任何库存。</span>
        <NButton type="primary" :loading="busy" @click="makeShoppingList"
          >按缺口生成采购清单</NButton
        >
      </div>
    </section>

    <section class="card">
      <h2>食材（{{ recipe.items.length }}）</h2>
      <div v-for="i in recipe.items" :key="i.id" class="ing">
        <span class="ing__name">{{ i.ingredient_name }}</span>
        <span class="ing__qty">
          <template v-if="i.weight">{{ Number(i.weight) }}g</template>
          <template v-else-if="i.quantity">{{ Number(i.quantity) }}（数量）</template>
        </span>
        <span class="muted">现有 {{ Number(i.available_weight || 0) }}g</span>
      </div>
    </section>

    <section v-if="recipe.steps.length" class="card">
      <div class="card__head">
        <h2>步骤（{{ recipe.steps.length }}）</h2>
        <span v-if="legacySteps" class="tag tag--muted">旧数据按行拆分</span>
      </div>
      <ol class="steps">
        <li v-for="s in recipe.steps" :key="s.seq">
          <span>{{ s.text }}</span>
          <em v-if="s.duration_minutes != null" class="step__time"
            >约 {{ s.duration_minutes }} 分钟</em
          >
        </li>
      </ol>
    </section>

    <section v-if="recipe.note" class="card">
      <h2>备注</h2>
      <p>{{ recipe.note }}</p>
    </section>
  </template>

  <div v-else class="card empty">
    <h3>找不到这个菜谱</h3>
    <button class="btn" style="margin-top: 12px" @click="router.push('/recipes')">
      返回菜谱列表
    </button>
  </div>
</template>

<style scoped>
.empty {
  text-align: center;
  padding: 26px 0;
}
.card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.card__head h2 {
  margin: 0;
}
.controls {
  display: flex;
  align-items: center;
  gap: 10px;
}
.controls label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--text-2);
}
.controls input {
  width: 70px;
  height: 30px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 7px;
  font-size: 13px;
  text-align: right;
}
.badge {
  font-size: 11.5px;
  padding: 2px 9px;
  border-radius: 999px;
  font-weight: 500;
}
.badge.ok {
  background: var(--green-weak);
  color: var(--green);
}
.badge.warn {
  background: #fbeae8;
  color: var(--red);
}

.match {
  font-size: 13px;
}
.match__head,
.match__row {
  display: grid;
  grid-template-columns: 1.6fr 0.8fr 0.8fr 0.8fr;
  gap: 8px;
  padding: 7px 0;
  border-bottom: 1px dashed var(--line);
}
.match__head {
  color: var(--text-3);
  font-size: 11.5px;
}
.match__row span:not(:first-child) {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.match__row--short {
  color: var(--red);
}
.match__row em {
  font-style: normal;
  font-size: 11px;
  color: var(--text-3);
}

.ing {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 7px 0;
  border-top: 1px dashed var(--line);
  font-size: 13px;
}
.ing__name {
  flex: 1;
}
.ing__qty {
  font-variant-numeric: tabular-nums;
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
.foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 14px;
  flex-wrap: wrap;
}
.steps {
  font-size: 13.5px;
  padding-left: 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.steps li {
  line-height: 1.5;
}
.step__time {
  font-style: normal;
  font-size: 11.5px;
  color: var(--text-3);
  margin-left: 8px;
}
@media (max-width: 720px) {
  .match__head,
  .match__row {
    grid-template-columns: 1.4fr 0.8fr 0.8fr 0.8fr;
  }
}
</style>
