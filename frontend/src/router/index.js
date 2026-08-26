import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    redirect: '/login',
  },
  {
    path: '/chat',
    name: 'Chat',
    component: () => import('../views/ChatView.vue'),
    meta: { title: '对话助手', requiresAuth: true },
  },
  {
    path: '/jobs',
    name: 'Jobs',
    component: () => import('../views/JobListView.vue'),
    meta: { title: '岗位推荐', requiresAuth: true },
  },
  {
    path: '/jobs/analysis/:id?',
    name: 'JobAnalysis',
    component: () => import('../views/JobAnalysisView.vue'),
    meta: { title: '岗位分析', requiresAuth: true },
  },
  {
    path: '/resume',
    name: 'Resume',
    component: () => import('../views/ResumeView.vue'),
    meta: { title: '简历管理', requiresAuth: true },
  },
  {
    path: '/profile',
    name: 'Profile',
    component: () => import('../views/ProfileView.vue'),
    meta: { title: '我的画像', requiresAuth: true },
  },
  {
    path: '/traces',
    name: 'Traces',
    component: () => import('../views/TraceView.vue'),
    meta: { title: 'Agent运行记录', requiresAuth: true },
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/LoginView.vue'),
    meta: { title: '登录' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const hasToken = !!localStorage.getItem('token')

  if (to.meta.requiresAuth && !hasToken) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }

  if (to.name === 'Login' && hasToken) {
    return { name: 'Chat' }
  }

  document.title = `${to.meta.title || '求职卫士'} - JobGuard`
})

export default router
