<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { projectsApi } from '../api/projects'
import { pipelineApi } from '../api/pipeline'
import { utilsApi } from '../api/utils'
import type { AudioAsset } from '../types/project'

const route = useRoute()
const projectId = computed(() => route.params.id as string)
const audio = ref<AudioAsset | null>(null)
const loading = ref(false)
const cacheBuster = ref(Date.now())
let pollTimer: ReturnType<typeof setInterval> | null = null

const audioSrc = computed(() => {
  if (!audio.value?.file_path) return ''
  return '/' + audio.value.file_path + '?t=' + cacheBuster.value
})

async function fetchAudio() {
  try {
    const { data } = await projectsApi.getAudio(projectId.value)
    audio.value = data
  } catch {
    // No audio yet
  }
}

onMounted(fetchAudio)

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

async function handleGenerateTTS() {
  loading.value = true
  try {
    await pipelineApi.runStep(projectId.value, 'tts_audio')
    ElMessage.success('TTS 语音合成已启动，请稍候...')

    // Poll for completion
    pollTimer = setInterval(async () => {
      await fetchAudio()
      if (audio.value && audio.value.status === 'completed') {
        cacheBuster.value = Date.now()
        loading.value = false
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
        ElMessage.success('语音合成完成')
      } else if (audio.value && audio.value.status === 'failed') {
        loading.value = false
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
        ElMessage.error('语音合成失败')
      }
    }, 3000)
  } catch {
    ElMessage.error('启动失败')
    loading.value = false
  }
}

function formatDuration(seconds: number | null) {
  if (!seconds) return '--'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}
</script>

<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <h3 style="margin: 0;">音频管理</h3>
      <div>
        <el-button v-if="audio?.file_path" @click="utilsApi.openFolder(audio.file_path)" size="small">
          <el-icon><FolderOpened /></el-icon> 打开目录
        </el-button>
        <el-button type="primary" @click="handleGenerateTTS" :loading="loading">
          <el-icon><Microphone /></el-icon> {{ audio ? '重新生成语音' : '生成 TTS 语音' }}
        </el-button>
      </div>
    </div>

    <el-card v-if="audio">
      <el-descriptions :column="2" border>
        <el-descriptions-item label="状态">
          <el-tag :type="audio.status === 'completed' ? 'success' : audio.status === 'generating' ? 'warning' : 'info'">
            {{ audio.status === 'completed' ? '已完成' : audio.status === 'generating' ? '生成中' : audio.status }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="时长">{{ formatDuration(audio.duration) }}</el-descriptions-item>
        <el-descriptions-item label="声音">{{ audio.voice_id || '--' }}</el-descriptions-item>
        <el-descriptions-item label="来源">{{ audio.is_manual ? '手动上传' : 'TTS 生成' }}</el-descriptions-item>
      </el-descriptions>

      <div v-if="audio.status === 'completed' && audio.file_path" style="margin-top: 16px;">
        <p style="margin: 0 0 8px; font-weight: 500;">音频预览</p>
        <audio controls style="width: 100%;" :src="audioSrc" :key="cacheBuster"></audio>
      </div>
    </el-card>
    <el-empty v-else description="暂无音频，请先生成口播稿后生成 TTS 语音" />
  </div>
</template>
