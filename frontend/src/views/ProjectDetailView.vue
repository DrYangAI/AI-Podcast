<script setup lang="ts">
import { onMounted, onUnmounted, computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useProjectStore } from '../stores/project'
import { projectsApi } from '../api/projects'

const route = useRoute()
const router = useRouter()
const store = useProjectStore()

const editingTitle = ref(false)
const editingTopic = ref(false)
const editTitle = ref('')
const editTopic = ref('')

async function updateProjectSetting(field: string, value: string) {
  if (!store.currentProject) return
  try {
    await projectsApi.update(store.currentProject.id, { [field]: value })
    ;(store.currentProject as any)[field] = value
  } catch {
    ElMessage.error('更新失败')
  }
}

function startEditTitle() {
  editTitle.value = store.currentProject?.title || ''
  editingTitle.value = true
}

async function saveTitle() {
  if (!editTitle.value.trim()) return
  await updateProjectSetting('title', editTitle.value.trim())
  editingTitle.value = false
}

function startEditTopic() {
  editTopic.value = store.currentProject?.topic || ''
  editingTopic.value = true
}

async function saveTopic() {
  if (!editTopic.value.trim()) return
  await updateProjectSetting('topic', editTopic.value.trim())
  editingTopic.value = false
}

const projectId = computed(() => route.params.id as string)

onMounted(async () => {
  await store.loadProject(projectId.value)
  if (store.currentProject?.status === 'processing') {
    store.startPolling(projectId.value)
  }
})

onUnmounted(() => {
  store.stopPolling()
})

const tabs = [
  { name: 'project-pipeline', label: '流水线', icon: 'Connection' },
  { name: 'project-article', label: '文章', icon: 'Document' },
  { name: 'project-segments', label: '段落', icon: 'List' },
  { name: 'project-images', label: '图片', icon: 'Picture' },
  { name: 'project-script', label: '口播稿', icon: 'Microphone' },
  { name: 'project-audio', label: '音频', icon: 'Headset' },
  { name: 'project-video', label: '视频', icon: 'VideoCamera' },
]
</script>

<template>
  <div v-if="store.currentProject" style="max-width: 1200px; margin: 0 auto;">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <div style="flex: 1; min-width: 0;">
        <el-button text @click="router.push('/projects')">
          <el-icon><ArrowLeft /></el-icon> 返回列表
        </el-button>
        <!-- 标题：可编辑 -->
        <div v-if="editingTitle" style="display: flex; align-items: center; gap: 8px; margin-top: 8px;">
          <el-input v-model="editTitle" @keyup.enter="saveTitle" autofocus style="max-width: 400px;" />
          <el-button type="primary" size="small" @click="saveTitle">保存</el-button>
          <el-button size="small" @click="editingTitle = false">取消</el-button>
        </div>
        <h2 v-else style="margin: 8px 0 0 0; cursor: pointer;" @click="startEditTitle">
          {{ store.currentProject.title }}
          <el-icon style="font-size: 14px; color: #909399; margin-left: 4px;"><Edit /></el-icon>
        </h2>
        <!-- 话题：可编辑 -->
        <div v-if="editingTopic" style="display: flex; align-items: center; gap: 8px; margin-top: 4px;">
          <el-input v-model="editTopic" type="textarea" :autosize="{ minRows: 1, maxRows: 4 }" style="max-width: 500px;" />
          <el-button type="primary" size="small" @click="saveTopic">保存</el-button>
          <el-button size="small" @click="editingTopic = false">取消</el-button>
        </div>
        <el-text v-else type="info" size="small" style="cursor: pointer;" @click="startEditTopic">
          {{ store.currentProject.topic }}
          <el-icon style="font-size: 12px; margin-left: 2px;"><Edit /></el-icon>
        </el-text>
      </div>
      <div style="display: flex; align-items: center; gap: 8px;">
        <el-tag>{{ store.currentProject.aspect_ratio }}</el-tag>
        <el-tag>{{ store.currentProject.video_template }}</el-tag>
        <el-dropdown @command="(v: string) => updateProjectSetting('image_prompt_language', v)">
          <el-tag :type="store.currentProject.image_prompt_language === 'zh' ? 'warning' : ''" style="cursor: pointer;">
            图片文字: {{ store.currentProject.image_prompt_language === 'zh' ? '中文' : '英文' }}
            <el-icon style="margin-left: 2px;"><ArrowDown /></el-icon>
          </el-tag>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="en" :disabled="store.currentProject.image_prompt_language === 'en'">英文 English</el-dropdown-item>
              <el-dropdown-item command="zh" :disabled="store.currentProject.image_prompt_language === 'zh'">中文 Chinese</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <el-tabs :model-value="route.name as string" @tab-change="(name: string) => router.push({ name, params: { id: projectId } })">
      <el-tab-pane v-for="tab in tabs" :key="tab.name" :name="tab.name" :label="tab.label" />
    </el-tabs>

    <div style="margin-top: 16px;">
      <router-view />
    </div>
  </div>
  <div v-else style="text-align: center; padding: 60px;">
    <el-icon :size="48" style="color: #c0c4cc;"><Loading /></el-icon>
    <p>加载中...</p>
  </div>
</template>
