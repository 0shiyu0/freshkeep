/**
 * 业务接口封装。每个模块一个文件，这里先做系统级。
 */
import { apiGet } from './http'

export interface HealthInfo {
  status: 'ok' | 'degraded'
  db: boolean
  version: string
  env?: string
}

export interface PingInfo {
  name: string
  version: string
  api: number
  initialized: boolean | null
  needs_pair: boolean
  server_time: string
}

export interface DbInfo {
  connected: boolean
  server_version?: string
  database?: string
  tables?: number
  migration?: string | null
  pool?: { size: number; max_overflow: number; checked_out: number }
  error?: string
}

export const systemApi = {
  health: () => apiGet<HealthInfo>('/health'),
  ping: () => apiGet<PingInfo>('/ping'),
  db: () => apiGet<DbInfo>('/system/db'),
}
