<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { MdEditor } from 'md-editor-v3'
import 'md-editor-v3/lib/style.css'
import { projectsApi } from '../api/projects'
import { pipelineApi } from '../api/pipeline'
import type { Article } from '../types/project'

const route = useRoute()
const projectId = computed(() => route.params.id as string)
const article = ref<Article | null>(null)
const content = ref('')
const loading = ref(false)
const saving = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

async function fetchArticle() {
  try {
    const { data } = await projectsApi.getArticle(projectId.value)
    article.value = data
    content.value = data.content
  } catch {
    // Article may not exist yet
  }
}

onMounted(async () => {
  loading.value = true
  await fetchArticle()
  loading.value = false
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

async function handleSave() {
  saving.value = true
  try {
    await projectsApi.updateArticle(projectId.value, { content: content.value })
    ElMessage.success('文章已保存')
  } catch {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

async function handleGenerate() {
  loading.value = true
  try {
    await pipelineApi.runStep(projectId.value, 'article_generation')
    ElMessage.success('文章生成已启动，请稍候...')

    pollTimer = setInterval(async () => {
      const oldVersion = article.value?.version
      await fetchArticle()
      if (article.value && article.value.version !== oldVersion && article.value.content) {
        loading.value = false
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
        ElMessage.success('文章生成完成')
      }
    }, 3000)

    // Safety timeout: stop polling after 2 minutes
    setTimeout(() => {
      if (pollTimer) {
        clearInterval(pollTimer)
        pollTimer = null
        loading.value = false
      }
    }, 120000)
  } catch {
    ElMessage.error('启动文章生成失败')
    loading.value = false
  }
}
</script>

<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <h3 style="margin: 0;">文章编辑</h3>
      <div>
        <el-button @click="handleGenerate" :loading="loading">
          <el-icon><MagicStick /></el-icon> {{ article ? '重新生成' : 'AI 生成' }}
        </el-button>
        <el-button type="primary" @click="handleSave" :loading="saving">
          <el-icon><Check /></el-icon> 保存
        </el-button>
      </div>
    </div>
    <div v-if="article" style="margin-bottom: 8px;">
      <el-text type="info" size="small">
        版本 {{ article.version }} | {{ article.word_count || 0 }} 字
        | {{ article.is_manual ? '手动编辑' : 'AI 生成' }}
      </el-text>
    </div>
    <MdEditor v-model="content" language="zh-CN" :preview="true" style="height: 600px;" />
  </div>
</template>
