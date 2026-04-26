import { createApp } from 'vue'
import { clerkPlugin } from '@clerk/vue'
import './styles.css'
import App from './App.vue'
import { isE2EApp } from './auth/e2e'
import { router } from './router'

const publishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

const app = createApp(App)

if (!isE2EApp) {
  if (!publishableKey) {
    throw new Error('Missing VITE_CLERK_PUBLISHABLE_KEY. Add it to the repo root .env file.')
  }

  app.use(clerkPlugin, {
    publishableKey
  })
}

app.use(router)

app.mount('#app')
