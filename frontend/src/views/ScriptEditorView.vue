<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { projectsApi } from '../api/projects'
import { pipelineApi } from '../api/pipeline'
import type { Script } from '../types/project'

const route = useRoute()
const projectId = computed(() => route.params.id as string)
const script = ref<Script | null>(null)
const content = ref('')
const loading = ref(false)
const saving = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

async function fetchScript() {
  try {
    const { data } = await projectsApi.getScript(projectId.value)
    script.value = data
    content.value = data.content
  } catch {
    // Script may not exist yet
  }
}

onMounted(async () => {
  loading.value = true
  await fetchScript()
  loading.value = false
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

async function handleSave() {
  saving.value = true
  try {
    await projectsApi.updateScript(projectId.value, { content: content.value })
    ElMessage.success('口播稿已保存')
  } catch {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

async function handleGenerate() {
  loading.value = true
  try {
    await pipelineApi.runStep(projectId.value, 'script_generation')
    ElMessage.success('口播稿生成已启动，请稍候...')

    pollTimer = setInterval(async () => {
      const oldVersion = script.value?.version
      await fetchScript()
      if (script.value && script.value.version !== oldVersion && script.value.content) {
        loading.value = false
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
        ElMessage.success('口播稿生成完成')
      }
    }, 3000)

    setTimeout(() => {
      if (pollTimer) {
        clearInterval(pollTimer)
        pollTimer = null
        loading.value = false
      }
    }, 120000)
  } catch {
    ElMessage.error('启动失败')
    loading.value = false
  }
}
</script>

<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <h3 style="margin: 0;">口播稿编辑</h3>
      <div>
        <el-button @click="handleGenerate" :loading="loading">
          <el-icon><MagicStick /></el-icon> {{ script ? '重新生成' : 'AI 生成' }}
        </el-button>
        <el-button type="primary" @click="handleSave" :loading="saving">
          <el-icon><Check /></el-icon> 保存
        </el-button>
      </div>
    </div>
    <div v-if="script" style="margin-bottom: 8px;">
      <el-text type="info" size="small">
        版本 {{ script.version }} | 风格: {{ script.style || '对话式' }}
        | {{ script.is_manual ? '手动编辑' : 'AI 生成' }}
      </el-text>
    </div>
    <el-input
      v-model="content"
      type="textarea"
      :rows="25"
      placeholder="口播稿内容将在这里显示..."
      style="font-size: 15px; line-height: 1.8;"
    />
  </div>
</template>
