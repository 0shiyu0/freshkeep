<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { NInput, NInputNumber, NSelect, NTabs, NTabPane } from 'naive-ui'

import { authApi, type DeviceInfo } from '@/api/auth'
import { catalogApi, type Category, type StorageLocation, type Unit } from '@/api/catalog'
import { useAuthStore } from '@/stores/auth'
import { request } from '@/api/http'
import { notifyError, notifySuccess } from '@/utils/notify'

const auth = useAuthStore()

const devices = ref<DeviceInfo[]>([])
const categories = ref<Category[]>([])
const units = ref<Unit[]>([])
const locations = ref<StorageLocation[]>([])

const pwd = reactive({ old: '', next: '', confirm: '' })
const newCat = reactive({ name: '', parent_id: null as string | null })
const newUnit = reactive({
  name: '',
  symbol: '',
  dimension: 'quantity' as 'quantity' | 'weight' | 'volume',
  precision: 0,
})
const newLoc = reactive({ name: '', description: '' })

const busy = ref(false)

async function loadAll() {
  const [d, c, u, l] = await Promise.all([
    authApi.devices(),
    catalogApi.categories(),
    catalogApi.units(),
    catalogApi.locations(),
  ])
  devices.value = d.items
  categories.value = c.items
  units.value = u.items
  locations.value = l.items
}

async function revoke(id: string) {
  try {
    await request<{ revoked: boolean; self: boolean }>({
      url: `/auth/devices/${id}`,
      method: 'DELETE',
    })
    notifySuccess('已吊销该设备')
    await loadAll()
    await auth.fetchMe(true)
  } catch {
    /* 拦截器已提示 */
  }
}

async function changePassword() {
  if (!pwd.next) return notifyError('请填写新密码')
  if (pwd.next !== pwd.confirm) return notifyError('两次输入的新密码不一致')
  if (pwd.next.length < 8) return notifyError('新密码至少 8 位')
  const hadPassword = auth.hasPassword
  busy.value = true
  try {
    if (hadPassword) await auth.changePassword(pwd.old, pwd.next, pwd.confirm)
    else await auth.setPassword(pwd.next, pwd.confirm)
    notifySuccess(hadPassword ? '密码已修改' : '密码已设置')
    pwd.old = pwd.next = pwd.confirm = ''
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy.value = false
  }
}

async function addCategory() {
  if (!newCat.name.trim()) return
  try {
    await catalogApi.createCategory({ name: newCat.name.trim(), parent_id: newCat.parent_id })
    newCat.name = ''
    notifySuccess('分类已创建')
    await loadAll()
  } catch {
    /* 拦截器已提示 */
  }
}

async function addUnit() {
  if (!newUnit.name.trim()) return
  try {
    await catalogApi.createUnit({
      name: newUnit.name.trim(),
      symbol: newUnit.symbol.trim() || newUnit.name.trim(),
      dimension: newUnit.dimension,
      precision: newUnit.precision,
    })
    newUnit.name = ''
    newUnit.symbol = ''
    notifySuccess('单位已创建')
    await loadAll()
  } catch {
    /* 拦截器已提示 */
  }
}

async function addLocation() {
  if (!newLoc.name.trim()) return
  try {
    await catalogApi.createLocation({ name: newLoc.name.trim(), description: newLoc.description })
    newLoc.name = ''
    newLoc.description = ''
    notifySuccess('位置已创建')
    await loadAll()
  } catch {
    /* 拦截器已提示 */
  }
}

async function removeCategory(c: Category) {
  try {
    await catalogApi.deleteCategory(c.id)
    notifySuccess('已删除')
    await loadAll()
  } catch {
    /* 拦截器已提示 */
  }
}

async function logout() {
  await auth.logout()
  location.href = '/login'
}

onMounted(loadAll)
</script>

<template>
  <div class="page-head">
    <div>
      <h1>设置</h1>
      <p>设备授权、基础字典与账号安全</p>
    </div>
    <button class="btn" @click="logout">退出登录</button>
  </div>

  <n-tabs type="line" animated>
    <n-tab-pane name="device" tab="设备与密码">
      <section class="card">
        <h2>账号</h2>
        <div class="kv"><span>用户名</span><em>{{ auth.me?.username }}</em></div>
        <div class="kv">
          <span>密码</span>
          <em>{{ auth.hasPassword ? '已设置' : '未设置（仅配对码可用）' }}</em>
        </div>
      </section>

      <section class="card">
        <h2>{{ auth.hasPassword ? '修改密码' : '设置密码' }}</h2>
        <div v-if="auth.hasPassword" class="field">
          <NInput v-model:value="pwd.old" type="password" show-password-on="click" placeholder="当前密码" />
        </div>
        <div class="field">
          <NInput v-model:value="pwd.next" type="password" show-password-on="click" placeholder="新密码（≥8 位）" />
        </div>
        <div class="field">
          <NInput v-model:value="pwd.confirm" type="password" show-password-on="click" placeholder="确认新密码" />
        </div>
        <button class="btn btn--primary" :disabled="busy" @click="changePassword">
          {{ auth.hasPassword ? '保存新密码' : '设置密码' }}
        </button>
        <p class="hint" style="margin-top: 10px">
          配对码仍是主通道；密码用于不便扫码时登录。忘记密码可在服务器执行
          <code>docker compose exec api python -m app.cli set-password</code>。
        </p>
      </section>

      <section class="card">
        <h2>已授权设备</h2>
        <div v-for="d in devices" :key="d.id" class="kv">
          <span>
            {{ d.name }}
            <span class="tag tag--muted">{{ d.platform }}</span>
            <span v-if="d.current" class="tag">当前</span>
            <span v-if="d.revoked_at" class="tag tag--danger">已吊销</span>
          </span>
          <em>
            最后活跃 {{ d.last_seen_at ? new Date(d.last_seen_at).toLocaleString() : '—' }}
            <button v-if="!d.revoked_at" class="btn btn--mini" @click="revoke(d.id)">吊销</button>
          </em>
        </div>
      </section>
    </n-tab-pane>

    <n-tab-pane name="category" tab="分类">
      <section class="card">
        <h2>新增分类</h2>
        <div class="inline-form">
          <NInput v-model:value="newCat.name" placeholder="分类名" maxlength="50" />
          <NSelect
            v-model:value="newCat.parent_id"
            :options="categories.filter((c) => !c.parent_id).map((c) => ({ label: c.name, value: c.id }))"
            placeholder="父级（可选）"
            clearable
            style="width: 160px"
          />
          <button class="btn btn--primary" @click="addCategory">添加</button>
        </div>
        <div class="hint">最多两级；同级不允许重名。分类下有食材时删除会被拒绝。</div>
      </section>

      <section class="card">
        <h2>现有分类（{{ categories.length }}）</h2>
        <div v-for="c in categories.filter((x) => !x.parent_id)" :key="c.id">
          <div class="kv">
            <span><strong>{{ c.name }}</strong></span>
            <em>{{ c.ingredient_count }} 个食材</em>
          </div>
          <div
            v-for="child in categories.filter((x) => x.parent_id === c.id)"
            :key="child.id"
            class="kv kv--child"
          >
            <span>{{ child.name }}</span>
            <em>
              {{ child.ingredient_count }} 个
              <button class="btn btn--mini" @click="removeCategory(child)">删除</button>
            </em>
          </div>
        </div>
      </section>
    </n-tab-pane>

    <n-tab-pane name="unit" tab="单位">
      <section class="card">
        <h2>新增单位</h2>
        <div class="inline-form">
          <NInput v-model:value="newUnit.name" placeholder="名称，如 千克" maxlength="20" />
          <NInput v-model:value="newUnit.symbol" placeholder="符号，如 kg" maxlength="10" style="width: 110px" />
          <NSelect
            v-model:value="newUnit.dimension"
            :options="[
              { label: '数量', value: 'quantity' },
              { label: '重量', value: 'weight' },
              { label: '体积', value: 'volume' },
            ]"
            style="width: 110px"
          />
          <NInputNumber v-model:value="newUnit.precision" :min="0" :max="4" style="width: 90px" />
          <button class="btn btn--primary" @click="addUnit">添加</button>
        </div>
        <div class="hint">不同维度之间不参与换算（数量 ≠ 重量）；内置单位不可删除。</div>
      </section>

      <section class="card">
        <h2>现有单位（{{ units.length }}）</h2>
        <div v-for="u in units" :key="u.id" class="kv">
          <span>
            {{ u.name }}
            <span class="tag tag--muted">{{ u.symbol }}</span>
          </span>
          <em>
            {{ u.dimension === 'quantity' ? '数量' : u.dimension === 'weight' ? '重量' : '体积' }}
            · 用于 {{ u.usage_count }} 个食材
          </em>
        </div>
      </section>
    </n-tab-pane>

    <n-tab-pane name="location" tab="储存位置">
      <section class="card">
        <h2>新增位置</h2>
        <div class="inline-form">
          <NInput v-model:value="newLoc.name" placeholder="名称，如 冷冻室" maxlength="30" />
          <NInput v-model:value="newLoc.description" placeholder="说明（可选）" maxlength="200" />
          <button class="btn btn--primary" @click="addLocation">添加</button>
        </div>
      </section>

      <section class="card">
        <h2>现有位置（{{ locations.length }}）</h2>
        <div v-for="l in locations" :key="l.id" class="kv">
          <span>{{ l.name }}</span>
          <em>{{ l.description || '—' }}</em>
        </div>
      </section>
    </n-tab-pane>
  </n-tabs>
</template>

<style scoped>
.field { margin-bottom: 10px; }
.inline-form { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.hint { font-size: 12px; color: var(--text-3); margin-top: 10px; line-height: 1.6; }
.kv--child { padding-left: 18px; }
.kv--child span { color: var(--text-2); }
.btn--mini { height: 24px; padding: 0 8px; font-size: 11.5px; margin-left: 8px; }
</style>
