import type { CapacitorConfig } from '@capacitor/cli'

/**
 * Capacitor 配置。三处关键设置缺一不可（见 docs/final-plan.md §3.3）：
 *  1. webDir 指向 Vite 产物，App 打包前端而不是加载远程 URL；
 *  2. androidScheme = 'http'，让 WebView 的 origin 是 http://localhost，
 *     向 http://NAS_IP 发请求才不会被判为"混合内容"；
 *  3. server.cleartext = true，允许明文 HTTP（家庭内网，ATS/cleartext 例外在原生工程里配）。
 */
const config: CapacitorConfig = {
  appId: 'com.0shiyu0.freshkeep',
  appName: '鲜度',
  webDir: 'dist',
  server: {
    androidScheme: 'http',
    cleartext: true,
  },
  plugins: {
    SplashScreen: { launchShowDuration: 600, backgroundColor: '#f5f3ee', showSpinner: false },
  },
}

export default config
