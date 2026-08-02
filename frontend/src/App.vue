<template>
  <div id="app" class="app-container">
    <!-- 左侧导航 -->
    <aside class="sidebar" v-if="!isLoginPage">
      <div class="logo">
        <span class="logo-icon">🛡️</span>
        <span class="logo-text">JobGuard</span>
      </div>
      <el-menu
        :default-active="activeMenu"
        router
        class="sidebar-menu"
        background-color="transparent"
      >
        <el-menu-item index="/chat">
          <el-icon><ChatDotRound /></el-icon>
          <span>对话助手</span>
        </el-menu-item>
        <el-menu-item index="/jobs">
          <el-icon><Briefcase /></el-icon>
          <span>岗位推荐</span>
        </el-menu-item>
        <el-menu-item index="/jobs/analysis">
          <el-icon><Warning /></el-icon>
          <span>岗位分析</span>
        </el-menu-item>
        <el-menu-item index="/resume">
          <el-icon><Document /></el-icon>
          <span>简历管理</span>
        </el-menu-item>
        <el-menu-item index="/profile">
          <el-icon><User /></el-icon>
          <span>我的画像</span>
        </el-menu-item>
      </el-menu>
      <div class="sidebar-footer">
        <span class="version">v0.1.0</span>
      </div>
    </aside>

    <!-- 主内容区 -->
    <main class="main-content" :class="{ 'full-width': isLoginPage }">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const isLoginPage = computed(() => route.name === 'Login')
const activeMenu = computed(() => route.path)
</script>

<style scoped>
.app-container {
  display: flex;
  height: 100vh;
  background: #f5f7fa;
}

.sidebar {
  width: 220px;
  background: #1a1a2e;
  color: #fff;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.logo {
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.logo-icon {
  font-size: 24px;
}

.logo-text {
  font-size: 18px;
  font-weight: 700;
  color: #e0e0ff;
}

.sidebar-menu {
  flex: 1;
  border-right: none;
}

.sidebar-menu .el-menu-item {
  color: rgba(255, 255, 255, 0.7);
}

.sidebar-menu .el-menu-item:hover,
.sidebar-menu .el-menu-item.is-active {
  color: #fff;
  background: rgba(255, 255, 255, 0.1);
}

.sidebar-footer {
  padding: 16px 20px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.version {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.4);
}

.main-content {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

.main-content.full-width {
  padding: 0;
}
</style>
