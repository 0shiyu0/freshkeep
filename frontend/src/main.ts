import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { installGlobalErrorHandlers, logError } from './utils/logger'
import './styles/main.css'

installGlobalErrorHandlers()

const app = createApp(App)

// Vue 组件内未捕获的错误也走统一上报
app.config.errorHandler = (err, _instance, info) => {
  logError('vue.errorHandler', err, { info })
}

app.use(createPinia()).use(router).mount('#app')
