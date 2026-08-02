<template>
  <div class="login-view">
    <div class="login-card">
      <div class="login-header">
        <span class="logo-icon">🛡️</span>
        <h1>JobGuard</h1>
        <p>求职卫士 - 智能岗位筛选与简历优化</p>
      </div>

      <el-form>
        <el-form-item>
          <el-input placeholder="用户名" v-model="username" :prefix-icon="User" />
        </el-form-item>
        <el-form-item>
          <el-input placeholder="密码" type="password" v-model="password" :prefix-icon="Lock" show-password />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" style="width: 100%" :disabled="!username || !password">
            登录
          </el-button>
        </el-form-item>
      </el-form>

      <div class="login-footer">
        <span>还没有账号？</span>
        <el-link type="primary">立即注册</el-link>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const username = ref('')
const password = ref('')
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
