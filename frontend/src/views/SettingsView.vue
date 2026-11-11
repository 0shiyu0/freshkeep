<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { NInput, NInputNumber, NSelect, NTabs, NTabPane } from 'naive-ui'

import { authApi, type DeviceInfo } from '@/api/auth'
import { backupApi, type BackupItem, type TaskStatus } from '@/api/backup'
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

// ---------------------------------------------------------------- 备份与导出（M7）
const backups = ref<BackupItem[]>([])
const tasks = ref<TaskStatus | null>(null)
const backupBusy = ref(false)

function fmtSize(n: number) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}

async function loadBackupData() {
  try {
    const [b, t] = await Promise.all([backupApi.list(), backupApi.tasks()])
    backups.value = b.items
    tasks.value = t
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '加载备份信息失败')
  }
}

async function createBackup() {
  backupBusy.value = true
  try {
    const res = await backupApi.create()
    notifySuccess(`已生成 ${res.name}（${res.tables} 张表 / ${res.total_rows} 行）`)
    await loadBackupData()
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '备份失败')
  } finally {
    backupBusy.value = false
  }
}

async function verifyBackup(name: string) {
  try {
    const res = await backupApi.verify(name)
    if (res.ok) notifySuccess(`备份可读：${res.tables} 张表 / ${res.total_rows} 行`)
    else notifyError(`校验失败：${res.error || res.missing.join(', ')}`)
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '校验失败')
  }
}

async function runJob(id: string) {
  try {
    await backupApi.runJob(id)
    notifySuccess(`已执行 ${id}`)
    await loadBackupData()
  } catch (err) {
    notifyError(err instanceof Error ? err.message : '执行失败')
  }
}

function downloadBackup(name: string) {
  window.open(`/api/v1/backups/${encodeURIComponent(name)}/download`, '_blank')
}

function downloadCsv(kind: 'transactions' | 'consumptions') {
  window.open(`/api/v1/export/${kind}.csv`, '_blank')
}

onMounted(loadBackupData)
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

  <!-- 备份与导出（M7） -->
  <section class="card">
    <div class="card__head">
      <h2>备份与导出</h2>
      <div class="head-actions">
        <button class="btn" :disabled="backupBusy" @click="createBackup">
          {{ backupBusy ? '备份中…' : '立即备份' }}
        </button>
        <button class="btn" @click="downloadCsv('transactions')">导出流水 CSV</button>
        <button class="btn" @click="downloadCsv('consumptions')">导出消耗 CSV</button>
      </div>
    </div>
    <p class="muted">
      备份是逻辑导出（schema.sql + 每表 CSV + manifest 打包为 tar.gz），不依赖 pg_dump；
      文件落在服务器的 backups 目录。
    </p>

    <div v-if="backups.length === 0" class="muted">还没有备份</div>
    <div v-for="b in backups" :key="b.name" class="backup">
      <div class="backup__main">
        <span class="mono">{{ b.name }}</span>
        <span class="muted">{{ fmtSize(b.size_bytes) }} · {{ b.created_at?.slice(0, 19).replace('T', ' ') }}</span>
      </div>
      <div class="head-actions">
        <button class="btn btn--tiny" @click="verifyBackup(b.name)">校验</button>
        <button class="btn btn--tiny" @click="downloadBackup(b.name)">下载</button>
      </div>
    </div>

    <div v-if="tasks" class="tasks">
      <h3>定时任务 <span class="tag" :class="tasks.running ? '' : 'tag--muted'">
        {{ tasks.running ? '运行中' : tasks.enabled ? '已启用（未运行）' : '未启用' }}
      </span></h3>
      <div v-for="j in tasks.jobs" :key="j.id" class="task">
        <span class="task__name">{{ j.desc }}</span>
        <span class="muted">{{ j.cron }}</span>
        <span class="muted">{{ j.next_run ? j.next_run.slice(0, 16) : '—' }}</span>
        <button class="btn btn--tiny" @click="runJob(j.id)">立即执行</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.field { margin-bottom: 10px; }
.inline-form { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.hint { font-size: 12px; color: var(--text-3); margin-top: 10px; line-height: 1.6; }
.kv--child { padding-left: 18px; }
.kv--child span { color: var(--text-2); }
.btn--mini { height: 24px; padding: 0 8px; font-size: 11.5px; margin-left: 8px; }

.card__head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.card__head h2 { margin: 0; }
.head-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.backup { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 0; border-top: 1px dashed var(--line); flex-wrap: wrap; }
.backup__main { display: flex; flex-direction: column; gap: 2px; min-width: 220px; }
.mono { font-family: ui-monospace, monospace; font-size: 12.5px; }
.muted { color: var(--text-3); font-size: 11.5px; }
.btn--tiny { padding: 3px 9px; font-size: 11.5px; border-radius: 6px; }
.tasks { margin-top: 16px; }
.tasks h3 { font-size: 13px; margin: 0 0 6px; display: flex; align-items: center; gap: 8px; }
.task { display: grid; grid-template-columns: 1fr auto auto auto; gap: 10px; align-items: center; padding: 7px 0; border-top: 1px dashed var(--line); font-size: 12.5px; }
</style>
