import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router.js'
import App from './App.vue'
import './assets/main.css'
import './utils/markdown.js'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')