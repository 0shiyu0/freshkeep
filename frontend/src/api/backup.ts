/** 备份、导出与定时任务（M7）。 */
import { apiGet, apiPost, request } from './http'

export interface BackupItem {
  name: string
  size_bytes: number
  created_at: string
}

export interface TaskStatus {
  enabled: boolean
  running: boolean
  jobs: Array<{ id: string; desc: string; cron: string; next_run: string | null }>
}

export const backupApi = {
  create: () =>
    apiPost<{ name: string; size_bytes: number; sha256: string; tables: number; total_rows: number }>('/backup', {}),
  list: () => apiGet<{ items: BackupItem[]; total: number }>('/backups'),
  verify: (name: string) =>
    apiPost<{ ok: boolean; tables: number; total_rows: number; missing: string[]; error?: string }>(
      `/backups/${encodeURIComponent(name)}/verify`,
      {}
    ),
  tasks: () => apiGet<TaskStatus>('/tasks'),
  runJob: (id: string) => apiPost<Record<string, unknown>>(`/tasks/${id}/run`, {}),
  /** CSV 走浏览器直接下载，带 Cookie/Bearer 由 axios 拦截器不参与，这里用 request 取 blob */
  exportCsv: (kind: 'transactions' | 'consumptions') =>
    request<Blob>({ url: `/export/${kind}.csv`, method: 'GET', responseType: 'blob' }),
}
