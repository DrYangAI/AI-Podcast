<script setup lang="ts">
</script>

<template>
  <el-container class="app-container">
    <el-aside width="220px" class="app-aside">
      <div class="logo">
        <el-icon size="24"><VideoCamera /></el-icon>
        <span>AI Podcast</span>
      </div>
      <el-menu
        :router="true"
        :default-active="$route.path"
        class="sidebar-menu"
      >
        <el-menu-item index="/">
          <el-icon><HomeFilled /></el-icon>
          <span>仪表盘</span>
        </el-menu-item>
        <el-menu-item index="/projects">
          <el-icon><FolderOpened /></el-icon>
          <span>项目列表</span>
        </el-menu-item>
        <el-menu-item index="/sources">
          <el-icon><Connection /></el-icon>
          <span>内容源</span>
        </el-menu-item>
        <el-menu-item index="/hotlist">
          <el-icon><TrendCharts /></el-icon>
          <span>热门推荐</span>
        </el-menu-item>
        <el-menu-item index="/settings/providers">
          <el-icon><Setting /></el-icon>
          <span>模型配置</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style>
html, body, #app {
  margin: 0;
  padding: 0;
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

.app-container {
  height: 100vh;
}

.app-aside {
  background: #1d1e1f;
  border-right: 1px solid #e4e7ed;
  overflow-y: auto;
}

.logo {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 20px 16px;
  font-size: 18px;
  font-weight: 700;
  color: #fff;
}

.sidebar-menu {
  border-right: none;
  background: #1d1e1f;
}

.sidebar-menu .el-menu-item {
  color: #bbb;
}

.sidebar-menu .el-menu-item:hover,
.sidebar-menu .el-menu-item.is-active {
  background: #2d2e2f;
  color: #409eff;
}

.app-main {
  background: #f5f7fa;
  min-height: 100vh;
}
</style>
