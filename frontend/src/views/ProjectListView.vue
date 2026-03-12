<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { Project } from '../types/project'
import { projectsApi } from '../api/projects'
import { formatDateTime } from '../utils/date'

const router = useRouter()
const projects = ref<Project[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)

onMounted(() => loadProjects())

async function loadProjects() {
  loading.value = true
  try {
    const { data } = await projectsApi.list(page.value, 20)
    projects.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

async function handleDelete(id: string) {
  await ElMessageBox.confirm('确定要删除这个项目吗？所有相关数据将被删除。', '确认删除', { type: 'warning' })
  await projectsApi.delete(id)
  ElMessage.success('已删除')
  loadProjects()
}

async function handleDuplicate(id: string) {
  const { data } = await projectsApi.duplicate(id)
  ElMessage.success('已复制')
  router.push(`/projects/${data.id}`)
}

function getStatusType(s: string) {
  return ({ draft: 'info', processing: 'warning', completed: 'success', failed: 'danger' } as any)[s] || 'info'
}
function getStatusLabel(s: string) {
  return ({ draft: '草稿', processing: '处理中', completed: '已完成', failed: '失败' } as any)[s] || s
}
</script>

<template>
  <div style="max-width: 1200px; margin: 0 auto;">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
      <h2 style="margin: 0;">项目列表</h2>
      <el-button type="primary" @click="router.push('/')">
        <el-icon><Plus /></el-icon> 新建项目
      </el-button>
    </div>
    <el-table :data="projects" v-loading="loading" stripe>
      <el-table-column prop="title" label="标题" min-width="180">
        <template #default="{ row }">
          <el-link @click="router.push(`/projects/${row.id}`)">{{ row.title }}</el-link>
        </template>
      </el-table-column>
      <el-table-column prop="topic" label="话题" min-width="200" show-overflow-tooltip />
      <el-table-column prop="aspect_ratio" label="比例" width="80" />
      <el-table-column prop="video_template" label="模板" width="100" />
      <el-table-column prop="status" label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="getStatusType(row.status)" size="small">{{ getStatusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="170">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button text size="small" @click="handleDuplicate(row.id)">复制</el-button>
          <el-button text size="small" type="danger" @click="handleDelete(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination v-if="total > 20" :total="total" v-model:current-page="page"
      :page-size="20" layout="prev, pager, next" @current-change="loadProjects"
      style="margin-top: 16px; justify-content: center;" />
  </div>
</template>
