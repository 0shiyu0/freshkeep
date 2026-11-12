/**
 * Axios 实例与统一错误处理。
 *
 * 约定（见 docs/api.md §1）：
 *  - 基础路径 /api/v1，生产由 nginx 反代到 api 容器，开发由 Vite 代理
 *  - 成功统一 { success, data, message, request_id }，失败 { success:false, error:{code,message,details} }
 *  - 数值（金额/重量/营养）在 JSON 里是**字符串**，不要直接参与算术
 */
import axios, { AxiosError, type AxiosRequestConfig } from 'axios'

import { notifyError } from '@/utils/notify'
import { logError } from '@/utils/logger'

export interface ApiEnvelope<T> {
  success: boolean
  data?: T
  message?: string
  request_id?: string
}

export interface ApiErrorBody {
  code: string
  message: string
  details?: Record<string, unknown>
}

/** 统一后的错误对象：调用方只需看 code / message */
export class ApiError extends Error {
  code: string
  status: number
  requestId: string
  details?: Record<string, unknown>

  constructor(body: ApiErrorBody, status: number, requestId: string) {
    super(body.message || '请求失败')
    this.name = 'ApiError'
    this.code = body.code || 'UNKNOWN'
    this.status = status
    this.requestId = requestId
    this.details = body.details
  }
}

export const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/api/v1',
  timeout: 15000,
  headers: { Accept: 'application/json' },
})

/** 未认证时的统一出口，由路由/布局注册 */
let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

http.interceptors.request.use((config) => {
  // 每个请求带一个可追踪的 request id，后端日志里能对上
  const rid =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID().replace(/-/g, '')
      : Math.random().toString(16).slice(2) + Date.now().toString(16)
  config.headers.set?.('X-Request-Id', rid)
  return config
})

http.interceptors.response.use(
  (res) => res,
  async (error: AxiosError<{ error?: ApiErrorBody; request_id?: string }>) => {
    const { response, config } = error
    const rid = response?.data?.request_id || response?.headers?.['x-request-id'] || ''
    const url = config?.url || ''

    // 网络层失败：没有 response
    if (!response) {
      const netErr = new ApiError(
        {
          code: error.code === 'ECONNABORTED' ? 'TIMEOUT' : 'NETWORK_ERROR',
          message:
            error.code === 'ECONNABORTED'
              ? '请求超时，请检查网络或服务状态'
              : '无法连接服务端，请确认服务是否启动',
        },
        0,
        rid,
      )
      logError('http', netErr, { url })
      notifyError(netErr.message)
      return Promise.reject(netErr)
    }

    const body = response.data?.error ?? {
      code: `HTTP_${response.status}`,
      message: response.statusText || '请求失败',
    }
    const apiErr = new ApiError(body, response.status, rid)

    if (response.status === 401) {
      onUnauthorized?.()
    } else if (response.status >= 500) {
      // 5xx 属于服务端问题，额外上报一次，便于从后端日志定位
      logError('http', apiErr, { url, status: response.status })
    }

    notifyError(apiErr.message)
    return Promise.reject(apiErr)
  },
)

/** 统一取 data 的便捷方法 */
export async function request<T>(config: AxiosRequestConfig): Promise<T> {
  const res = await http.request<ApiEnvelope<T>>(config)
  return res.data?.data as T
}

export const apiGet = <T>(url: string, params?: Record<string, unknown>) =>
  request<T>({ url, method: 'GET', params })

export const apiPut = <T>(url: string, data?: unknown) => request<T>({ url, method: 'PUT', data })
export const apiDelete = <T>(url: string) => request<T>({ url, method: 'DELETE' })
export const apiPost = <T>(url: string, data?: unknown, idempotencyKey?: string) =>
  request<T>({
    url,
    method: 'POST',
    data,
    headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined,
  })
