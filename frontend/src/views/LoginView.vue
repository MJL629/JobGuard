<template>
  <div class="login-view">
    <div class="login-card">
      <div class="login-header">
        <span class="logo-icon">🛡️</span>
        <h1>JobGuard</h1>
        <p>求职卫士 - 智能岗位筛选与简历优化</p>
      </div>

      <el-form @submit.prevent="submit">
        <el-alert
          v-if="errorMessage"
          :title="errorMessage"
          type="error"
          :closable="false"
          show-icon
          style="margin-bottom: 16px"
        />
        <el-form-item>
          <el-input placeholder="用户名" v-model="username" :prefix-icon="User" />
        </el-form-item>
        <el-form-item v-if="mode === 'register'">
          <el-input placeholder="邮箱（选填）" v-model="email" />
        </el-form-item>
        <el-form-item>
          <el-input placeholder="密码" type="password" v-model="password" :prefix-icon="Lock" show-password />
        </el-form-item>
        <el-form-item>
          <el-button
            native-type="submit"
            type="primary"
            style="width: 100%"
            :loading="loading"
            :disabled="!username.trim() || password.length < 6"
          >
            {{ mode === 'login' ? '登录' : '注册并登录' }}
          </el-button>
        </el-form-item>
      </el-form>

      <div class="login-footer">
        <span>{{ mode === 'login' ? '还没有账号？' : '已经有账号？' }}</span>
        <el-link type="primary" @click="toggleMode">
          {{ mode === 'login' ? '立即注册' : '返回登录' }}
        </el-link>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Lock, User } from '@element-plus/icons-vue'
import { useUserStore } from '../stores/user'

const username = ref('')
const password = ref('')
const email = ref('')
const mode = ref('login')
const loading = ref(false)
const errorMessage = ref('')
const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const toggleMode = () => {
  mode.value = mode.value === 'login' ? 'register' : 'login'
  errorMessage.value = ''
}

const submit = async () => {
  if (!username.value.trim() || password.value.length < 6) return
  loading.value = true
  errorMessage.value = ''
  try {
    if (mode.value === 'login') {
      await userStore.loginUser(username.value.trim(), password.value)
    } else {
      await userStore.registerUser(username.value.trim(), password.value, email.value.trim() || null)
    }
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/chat'
    await router.replace(redirect)
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || '操作失败，请检查用户名、密码或网络连接'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-view {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
}

.login-card {
  width: 400px;
  padding: 40px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
}

.login-header {
  text-align: center;
  margin-bottom: 32px;
}

.logo-icon {
  font-size: 48px;
}

.login-header h1 {
  font-size: 24px;
  color: #303133;
  margin: 12px 0 8px;
}

.login-header p {
  font-size: 14px;
  color: #909399;
}

.login-footer {
  text-align: center;
  font-size: 14px;
  color: #909399;
}
</style>
