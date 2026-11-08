/**
 * 统一 API 客户端。
 *
 * 两条通道（见 docs/final-plan.md §3）：
 *  - Web：与 API 同源，凭据走 HttpOnly Cookie（浏览器自动带，前端不接触令牌）
 *  - App：跨源（capacitor://localhost → http://NAS_IP），凭据走 Authorization: Bearer，
 *         令牌存 iOS Keychain / Android Keystore，不进 localStorage。
 */
import { Capacitor } from '@capacitor/core'

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''
const TOKEN_KEY = 'fk_token'

export interface ApiEnvelope<T> {
  success: boolean
  data?: T
  message?: string
  error?: { code: string; message: string; details?: Record<string, unknown> }
  request_id?: string
}

/** 401 时的统一出口，由 main.ts / 路由守卫接管跳转 */
let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

const isNative = () => Capacitor.isNativePlatform()

async function secureModule(): Promise<any | null> {
  if (!isNative()) return null
  try {
    return await import('capacitor-secure-storage-plugin')
  } catch {
    return null
  }
}

export async function saveToken(token: string): Promise<void> {
  if (!isNative()) return // Web 端令牌只在 HttpOnly Cookie 里
  const mod = await secureModule()
  if (mod) await mod.SecureStoragePlugin.set({ key: TOKEN_KEY, value: token })
}

export async function readToken(): Promise<string | null> {
  if (!isNative()) return null
  const mod = await secureModule()
  if (!mod) return null
  try {
    const res = await mod.SecureStoragePlugin.get({ key: TOKEN_KEY })
    return res?.value ?? null
  } catch {
    return null
  }
}

export async function clearToken(): Promise<void> {
  const mod = await secureModule()
  if (mod) {
    try {
      await mod.SecureStoragePlugin.remove({ key: TOKEN_KEY })
    } catch {
      /* 未存过则忽略 */
    }
  }
}

/** App 端需要知道服务器地址；Web 端为空（同源） */
const BASE_KEY = 'fk_server'
export async function saveServer(url: string) {
  if (isNative()) {
    const mod = await secureModule()
    if (mod) await mod.SecureStoragePlugin.set({ key: BASE_KEY, value: url })
  }
}
export async function readServer(): Promise<string> {
  if (!isNative()) return ''
  const mod = await secureModule()
  if (!mod) return ''
  try {
    const res = await mod.SecureStoragePlugin.get({ key: BASE_KEY })
    return res?.value ?? ''
  } catch {
    return ''
  }
}

async function baseUrl(): Promise<string> {
  if (!isNative()) return API_BASE
  return await readServer()
}

export async function api<T>(
  path: string,
  options: { method?: string; body?: unknown; idempotencyKey?: string; signal?: AbortSignal } = {}
): Promise<ApiEnvelope<T>> {
  const { method = 'GET', body, idempotencyKey, signal } = options
  const base = await baseUrl()
  const url = `${base}/api/v1${path}`

  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey

  if (isNative()) {
    const token = await readToken()
    if (token) headers.Authorization = `Bearer ${token}`
  }

  const res = await fetch(url, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: isNative() ? 'omit' : 'include',
    signal,
  })

  if (res.status === 401) {
    await clearToken()
    onUnauthorized?.()
  }

  const json = (await res.json()) as ApiEnvelope<T>
  if (!res.ok && json?.error) {
    throw Object.assign(new Error(json.error.message), { code: json.error.code, details: json.error.details })
  }
  return json
}

export const get = <T>(path: string) => api<T>(path)
export const post = <T>(path: string, body?: unknown, idempotencyKey?: string) =>
  api<T>(path, { method: 'POST', body, idempotencyKey })
export const put = <T>(path: string, body?: unknown) => api<T>(path, { method: 'PUT', body })
export const del = <T>(path: string) => api<T>(path, { method: 'DELETE' })
