import { createRouter, createWebHistory } from 'vue-router'

import AuthView from '../views/AuthView.vue'
import SignUpView from '../views/SignUpView.vue'
import WorkspaceRouteView from '../views/WorkspaceRouteView.vue'

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/:pathMatch(.*)*',
      redirect: (to) => {
        const path = Array.isArray(to.params.pathMatch)
          ? `/${to.params.pathMatch.join('/')}`
          : `/${to.params.pathMatch ?? ''}`

        if (path === '/auth' || path.startsWith('/auth/')) {
          return { name: 'auth', params: { clerkPath: path.slice('/auth'.length).replace(/^\/+/, '') } }
        }

        if (path === '/sign-up' || path.startsWith('/sign-up/')) {
          return {
            name: 'sign-up',
            params: { clerkPath: path.slice('/sign-up'.length).replace(/^\/+/, '') },
          }
        }

        return { name: 'workspace' }
      },
    },
    {
      path: '/',
      name: 'workspace',
      component: WorkspaceRouteView
    },
    {
      path: '/auth/:clerkPath(.*)*',
      name: 'auth',
      component: AuthView
    },
    {
      path: '/sign-up/:clerkPath(.*)*',
      name: 'sign-up',
      component: SignUpView
    }
  ]
})
