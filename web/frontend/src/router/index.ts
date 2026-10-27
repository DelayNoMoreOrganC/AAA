import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/setup', name: 'setup', component: () => import('../views/Setup.vue') },
    { path: '/login', name: 'login', component: () => import('../views/Login.vue') },
    { path: '/register', name: 'register', component: () => import('../views/Register.vue') },
    { path: '/', redirect: '/cases' },
    { path: '/cases', name: 'cases', component: () => import('../views/Dashboard.vue') },
    { path: '/cases/:id', name: 'case-detail', component: () => import('../views/CaseDetail.vue') },
    { path: '/cases/:id/tasks/:taskId', name: 'task', component: () => import('../views/TaskProgress.vue') },
    { path: '/settings', name: 'settings', component: () => import('../views/Settings.vue') },
    { path: '/feedback', name: 'feedback', component: () => import('../views/Feedback.vue') },
    { path: '/admin', name: 'admin', component: () => import('../views/Admin.vue') },
  ],
})

router.beforeEach((to, _from, next) => {
  const auth = useAuthStore()
  if (to.name !== 'login' && to.name !== 'register' && to.name !== 'setup' && !auth.token) {
    next({ name: 'login' })
  } else if (['settings', 'admin'].includes(String(to.name)) && !auth.isAdmin) {
    next({ name: 'cases' })
  } else {
    next()
  }
})

export default router
