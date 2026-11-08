/**
 * 前端日志与异常记录。
 *
 * 三层兜底：
 *  1. 未捕获异常（window.onerror / unhandledrejection）→ 全局上报
 *  2. Vue 组件错误（app.config.errorHandler）→ 全局上报
 *  3. 接口错误（axios 拦截器）→ 由 http.ts 主动调用 logError
 *
 * 上报走 POST /api/v1/system/client-logs，落到后端同一份日志文件里；
 * 失败则静默（日志系统本身不能把主流程拖垮）。
 */
import axios from 'axios'

const BASE = import.meta.env.VITE_API_BASE || '/api/v1'
const buffer: Array<Record<string, unknown>> = []
let flushTimer: number | null = null

function flatten(err: unknown): Record<string, unknown> {
  if (err instanceof Error) {
    return { name: err.name, message: err.message, stack: err.stack }
  }
  if (typeof err === 'object' && err !== null) {
    const e = err as Record<string, unknown>
    return { name: String(e.name ?? 'Object'), message: String(e.message ?? ''), detail: e }
  }
  return { message: String(err) }
}

/** 记录一条前端错误：控制台 + 批量上报 */
export function logError(scope: string, err: unknown, extra: Record<string, unknown> = {}) {
  const payload = {
    scope,
    url: location.pathname,
    ts: new Date().toISOString(),
    ...flatten(err),
    ...extra,
  }
  console.error(`[${scope}]`, err, extra)
  buffer.push(payload)
  scheduleFlush()
}

function scheduleFlush() {
  if (flushTimer !== null) return
  flushTimer = window.setTimeout(() => {
    flushTimer = null
    const batch = buffer.splice(0, buffer.length)
    if (!batch.length) return
    // 用裸 axios，避免走业务拦截器（否则上报失败会触发 toast，形成噪音）
    axios.post(`${BASE}/system/client-logs`, { entries: batch }, { timeout: 5000 }).catch(() => {
      /* 上报失败静默 */
    })
  }, 1500)
}

/** 安装全局兜底 */
export function installGlobalErrorHandlers() {
  window.addEventListener('error', (event) => {
    logError('window.error', event.error ?? event.message, {
      source: event.filename,
      line: event.lineno,
      column: event.colno,
    })
  })
  window.addEventListener('unhandledrejection', (event) => {
    logError('unhandledrejection', event.reason)
  })
}
