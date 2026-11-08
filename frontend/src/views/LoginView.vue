<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NInput, NTabPane, NTabs } from 'naive-ui'

import { useAuthStore } from '@/stores/auth'
import { notifySuccess } from '@/utils/notify'

const router = useRouter()
const auth = useAuthStore()

const tab = ref<'pair' | 'password'>('pair')
const code = ref('')
const username = ref('owner')
const password = ref('')
const busy = ref(false)

async function doPair() {
  if (!code.value.trim()) return
  busy.value = true
  try {
    await auth.pair(code.value.trim().toUpperCase())
    notifySuccess('配对成功')
    router.replace('/')
  } finally {
    busy.value = false
  }
}

async function doLogin() {
  if (!username.value || !password.value) return
  busy.value = true
  try {
    await auth.login(username.value.trim(), password.value)
    notifySuccess('登录成功')
    router.replace('/')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="login">
    <div class="login__card card">
      <div class="login__head">
        <span class="brand__mark">鲜</span>
        <div>
          <h1>鲜度</h1>
          <p class="muted">家庭食材库存与营养管理</p>
        </div>
      </div>

      <n-tabs v-model:value="tab" type="segment" animated>
        <n-tab-pane name="pair" tab="配对码">
          <p class="login__tip">
            在服务器上执行 <code>docker compose exec api python -m app.cli pair</code>
            获取 6 位配对码（10 分钟内有效，一次性）。
          </p>
          <n-input
            v-model:value="code"
            placeholder="例如 4K7T2M"
            size="large"
            maxlength="6"
            style="letter-spacing: 3px; text-align: center; font-weight: 600"
            @keyup.enter="doPair"
          />
          <n-button
            type="primary"
            block
            size="large"
            style="margin-top: 14px"
            :loading="busy"
            :disabled="!code.trim()"
            @click="doPair"
          >
            配对并进入
          </n-button>
        </n-tab-pane>

        <n-tab-pane name="password" tab="账号密码">
          <n-input v-model:value="username" placeholder="用户名" size="large" style="margin-top: 4px" />
          <n-input
            v-model:value="password"
            type="password"
            show-password-on="click"
            placeholder="密码"
            size="large"
            style="margin-top: 10px"
            @keyup.enter="doLogin"
          />
          <n-button
            type="primary"
            block
            size="large"
            style="margin-top: 14px"
            :loading="busy"
            :disabled="!username || !password"
            @click="doLogin"
          >
            登录
          </n-button>
          <p class="login__tip" style="margin-top: 12px">
            尚未设置密码？先用配对码进入，再到「设置 → 修改密码」设置。
          </p>
        </n-tab-pane>
      </n-tabs>
    </div>
  </div>
</template>

<style scoped>
.login {
  display: grid;
  place-items: center;
  min-height: calc(100vh - var(--topbar-h) - 40px);
  padding: 10px;
}
.login__card {
  width: 100%;
  max-width: 380px;
  padding: 22px;
}
.login__head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 18px;
}
.login__head h1 { font-size: 20px; font-weight: 700; }
.login__tip {
  font-size: 12.5px;
  color: var(--text-2);
  line-height: 1.7;
  margin: 10px 0;
}
</style>
