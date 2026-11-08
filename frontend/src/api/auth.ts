/** 认证接口：配对码 / 密码登录 / 退出 / 改密 / 当前用户。 */
import { apiGet, apiPost, request } from './http'

export interface DeviceInfo {
  id: string
  name: string
  platform: string
  created_at: string
  last_seen_at: string | null
  revoked_at: string | null
  current: boolean
}

export interface MeInfo {
  id: string
  username: string
  display_name: string
  has_password: boolean
  device: DeviceInfo
}

export interface AuthResult {
  token: string | null
  device: DeviceInfo
  user: MeInfo
}

export const authApi = {
  me: () => apiGet<MeInfo>('/auth/me'),
  pair: (code: string, deviceName = '网页', platform = 'web') =>
    apiPost<AuthResult>('/auth/pair', { code, device_name: deviceName, platform }),
  login: (username: string, password: string, deviceName = '网页', platform = 'web') =>
    apiPost<AuthResult>('/auth/login', { username, password, device_name: deviceName, platform }),
  logout: () => apiPost<{ revoked: boolean }>('/auth/logout'),
  setPassword: (newPassword: string, confirm: string) =>
    apiPost<{ has_password: boolean }>('/auth/password/set', {
      new_password: newPassword,
      confirm_password: confirm,
    }),
  changePassword: (oldPassword: string, newPassword: string, confirm: string) =>
    request<{ updated: boolean }>({
      url: '/auth/password',
      method: 'POST',
      data: { old_password: oldPassword, new_password: newPassword, confirm_password: confirm },
    }),
  devices: () => apiGet<{ items: DeviceInfo[]; total: number }>('/auth/devices'),
}
