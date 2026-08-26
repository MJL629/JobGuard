<template>
  <div class="login-view">
    <div class="login-card">
      <div class="login-header">
        <span class="logo-icon">🛡️</span>
        <h1>JobGuard</h1>
        <p>求职卫士 - 智能岗位筛选与简历优化</p>
      </div>

      <el-form @submit.prevent="handleSubmit">
        <el-form-item>
          <el-input placeholder="用户名" v-model="username" :prefix-icon="User" />
        </el-form-item>
        <el-form-item>
          <el-input placeholder="密码" type="password" v-model="password" :prefix-icon="Lock" show-password />
        </el-form-item>
        <el-form-item>
          <el-button native-type="submit" type="primary" style="width: 100%" :disabled="!username || !password" :loading="loading">
            {{ registering ? '注册并登录' : '登录' }}
          </el-button>
        </el-form-item>
      </el-form>

      <div class="login-footer">
        <span>{{ registering ? '已有账号？' : '还没有账号？' }}</span>
        <el-link type="primary" @click="registering = !registering">{{ registering ? '返回登录' : '立即注册' }}</el-link>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { login, register } from '../api/auth'
import { useUserStore } from '../stores/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const username = ref('')
const password = ref('')
const loading = ref(false)
const registering = ref(false)

const handleSubmit = async () => {
  if (!username.value || !password.value || loading.value) return

  loading.value = true
  try {
    const res = registering.value
      ? await register(username.value, password.value)
      : await login(username.value, password.value)
    if (!res?.token) throw new Error('登录接口未返回令牌')

    userStore.setToken(res.token)
    userStore.setUser(res.user)
    ElMessage.success(registering.value ? '注册成功，已自动登录' : '登录成功')
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/chat'
    await router.replace(redirect)
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error.message || '登录失败，请检查后端服务')
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
