<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { Project } from '../types/project'
import { projectsApi } from '../api/projects'
import { sourcesApi } from '../api/sources'
import { formatDateTime } from '../utils/date'

const router = useRouter()
const recentProjects = ref<Project[]>([])
const loading = ref(false)
const createDialogVisible = ref(false)
const createMode = ref<'manual' | 'url'>('manual')
const newProject = ref({ title: '', topic: '', aspect_ratio: '16:9', video_template: 'slideshow', image_prompt_language: 'zh' })

// URL import
const importUrl = ref('')
const extracting = ref(false)

onMounted(async () => {
  await loadProjects()
})

async function loadProjects() {
  loading.value = true
  try {
    const { data } = await projectsApi.list(1, 10)
    recentProjects.value = data.items
  } catch {
    ElMessage.error('Failed to load projects')
  } finally {
    loading.value = false
  }
}

async function handleCreate() {
  if (!newProject.value.title || !newProject.value.topic) {
    ElMessage.warning('请填写标题和话题')
    return
  }
  try {
    const { data } = await projectsApi.create(newProject.value)
    createDialogVisible.value = false
    newProject.value = { title: '', topic: '', aspect_ratio: '16:9', video_template: 'slideshow', image_prompt_language: 'zh' }
    router.push(`/projects/${data.id}`)
  } catch {
    ElMessage.error('创建失败')
  }
}

async function handleExtractUrl() {
  if (!importUrl.value) {
    ElMessage.warning('请输入 URL')
    return
  }
  extracting.value = true
  try {
    const { data } = await sourcesApi.extractUrl(importUrl.value)
    newProject.value.title = data.title || ''
    newProject.value.topic = data.content.substring(0, 500)
    createMode.value = 'manual'
    ElMessage.success('内容提取成功，请检查并创建项目')
  } catch {
    ElMessage.error('内容提取失败，请检查 URL')
  } finally {
    extracting.value = false
  }
}

function getStatusType(status: string) {
  const map: Record<string, string> = {
    draft: 'info', processing: 'warning', completed: 'success', failed: 'danger',
  }
  return map[status] || 'info'
}

function getStatusLabel(status: string) {
  const map: Record<string, string> = {
    draft: '草稿', processing: '处理中', completed: '已完成', failed: '失败',
  }
  return map[status] || status
}
</script>

<template>
  <div class="dashboard">
    <div class="dashboard-header">
      <h1>AI Podcast 控制台</h1>
      <el-button type="primary" size="large" @click="createDialogVisible = true">
        <el-icon><Plus /></el-icon> 新建项目
      </el-button>
    </div>

    <el-row :gutter="20" class="stats-row">
      <el-col :span="8">
        <el-card shadow="hover">
          <el-statistic title="总项目数" :value="recentProjects.length" />
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover">
          <el-statistic title="已完成" :value="recentProjects.filter(p => p.status === 'completed').length" />
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover">
          <el-statistic title="处理中" :value="recentProjects.filter(p => p.status === 'processing').length" />
        </el-card>
      </el-col>
    </el-row>

    <el-card class="recent-card">
      <template #header>
        <div class="card-header">
          <span>最近项目</span>
          <el-button text @click="router.push('/projects')">查看全部</el-button>
        </div>
      </template>
      <el-table :data="recentProjects" v-loading="loading" stripe>
        <el-table-column prop="title" label="标题" min-width="200">
          <template #default="{ row }">
            <el-link @click="router.push(`/projects/${row.id}`)">{{ row.title }}</el-link>
          </template>
        </el-table-column>
        <el-table-column prop="topic" label="话题" min-width="200" show-overflow-tooltip />
        <el-table-column prop="aspect_ratio" label="比例" width="80" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" size="small">{{ getStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Create Dialog -->
    <el-dialog v-model="createDialogVisible" title="新建项目" width="540px">
      <el-tabs v-model="createMode">
        <el-tab-pane label="手动输入" name="manual" />
        <el-tab-pane label="从 URL 导入" name="url" />
      </el-tabs>

      <!-- URL 导入 -->
      <div v-if="createMode === 'url'" style="margin-bottom: 16px;">
        <el-input
          v-model="importUrl"
          placeholder="输入文章 URL，自动提取标题和内容"
          @keyup.enter="handleExtractUrl"
        >
          <template #append>
            <el-button :loading="extracting" @click="handleExtractUrl">提取</el-button>
          </template>
        </el-input>
        <el-text type="info" size="small" style="display: block; margin-top: 4px;">
          输入健康文章的网页地址，自动提取标题和正文作为话题
        </el-text>
      </div>

      <el-form label-width="80px">
        <el-form-item label="标题">
          <el-input v-model="newProject.title" placeholder="输入项目标题" />
        </el-form-item>
        <el-form-item label="话题">
          <el-input v-model="newProject.topic" type="textarea" :rows="3" placeholder="输入健康科普话题" />
        </el-form-item>
        <el-form-item label="画面比例">
          <el-radio-group v-model="newProject.aspect_ratio">
            <el-radio-button value="16:9">横屏 16:9</el-radio-button>
            <el-radio-button value="9:16">竖屏 9:16</el-radio-button>
            <el-radio-button value="1:1">方形 1:1</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="视频模板">
          <el-select v-model="newProject.video_template">
            <el-option label="幻灯片" value="slideshow" />
            <el-option label="Ken Burns" value="kenburns" />
          </el-select>
        </el-form-item>
        <el-form-item label="图片文字">
          <el-radio-group v-model="newProject.image_prompt_language">
            <el-radio-button value="zh">中文</el-radio-button>
            <el-radio-button value="en">英文</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.dashboard { max-width: 1200px; margin: 0 auto; }
.dashboard-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.dashboard-header h1 { margin: 0; font-size: 24px; }
.stats-row { margin-bottom: 24px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.recent-card { margin-bottom: 24px; }
</style>
