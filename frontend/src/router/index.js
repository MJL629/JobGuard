import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    redirect: '/chat',
  },
  {
    path: '/chat',
    name: 'Chat',
    component: () => import('../views/ChatView.vue'),
    meta: { title: '对话助手' },
  },
  {
    path: '/jobs',
    name: 'Jobs',
    component: () => import('../views/JobListView.vue'),
    meta: { title: '岗位推荐' },
  },
  {
    path: '/jobs/analysis/:id?',
    name: 'JobAnalysis',
    component: () => import('../views/JobAnalysisView.vue'),
    meta: { title: '岗位分析' },
  },
  {
    path: '/resume',
    name: 'Resume',
    component: () => import('../views/ResumeView.vue'),
    meta: { title: '简历管理' },
  },
  {
    path: '/profile',
    name: 'Profile',
    component: () => import('../views/ProfileView.vue'),
    meta: { title: '我的画像' },
  },
  {
    path: '/agent-ops',
    name: 'AgentOps',
    component: () => import('../views/AgentOpsView.vue'),
    meta: { title: 'Agent 运行与评估' },
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
  const hasToken = Boolean(localStorage.getItem('token'))
  if (to.name !== 'Login' && !hasToken) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'Login' && hasToken) {
    return { name: 'Chat' }
  }
  return true
})

export default router
