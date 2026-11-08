/**
 * 轻量提示：用 Naive UI 的离散 API，避免为了一个 toast 引整套 Provider。
 */
import { createDiscreteApi } from 'naive-ui'

const { message } = createDiscreteApi(['message'], {
  configProviderProps: { themeOverrides: { common: { borderRadius: '10px' } } },
})

export function notifyError(text: string, duration = 4000) {
  message.error(text, { duration, closable: true })
}

export function notifySuccess(text: string, duration = 2500) {
  message.success(text, { duration })
}

export function notifyInfo(text: string, duration = 2500) {
  message.info(text, { duration })
}
