<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { projectsApi } from '../api/projects'
import { pipelineApi } from '../api/pipeline'
import { utilsApi } from '../api/utils'
import { useProjectStore } from '../stores/project'
import type { VideoOutput } from '../types/project'

const route = useRoute()
const store = useProjectStore()
const projectId = computed(() => route.params.id as string)
const videos = ref<VideoOutput[]>([])
const loading = ref(false)
const cacheBuster = ref(Date.now())
const activeVideoId = ref<string | null>(null)
const subtitleDialogVisible = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

const subtitleSettings = reactive({
  subtitle_enabled: true,
  subtitle_font_size: 18,
  subtitle_font_color: '#FFFFFF',
  subtitle_outline_width: 1,
  subtitle_margin_bottom: 30,
})

const activeVideo = computed(() => {
  if (activeVideoId.value) {
    return videos.value.find(v => v.id === activeVideoId.value) || null
  }
  const completed = videos.value.filter(v => v.status === 'completed')
  return completed.length > 0 ? completed[completed.length - 1] : null
})

const videoSrc = computed(() => {
  const v = activeVideo.value
  if (!v?.file_path || v.status !== 'completed') return ''
  return '/' + v.file_path + '?t=' + cacheBuster.value
})

async function fetchVideos() {
  try {
    const { data } = await projectsApi.getVideos(projectId.value)
    videos.value = data
  } catch {
    // No videos yet
  }
}

onMounted(async () => {
  await store.loadProject(projectId.value)
  await fetchVideos()
  // Load subtitle settings from project
  if (store.currentProject) {
    subtitleSettings.subtitle_enabled = store.currentProject.subtitle_enabled ?? true
    subtitleSettings.subtitle_font_size = store.currentProject.subtitle_font_size ?? 18
    subtitleSettings.subtitle_font_color = store.currentProject.subtitle_font_color ?? '#FFFFFF'
    subtitleSettings.subtitle_outline_width = store.currentProject.subtitle_outline_width ?? 1
    subtitleSettings.subtitle_margin_bottom = store.currentProject.subtitle_margin_bottom ?? 30
  }
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

async function handleCompose() {
  loading.value = true
  try {
    await pipelineApi.runStep(projectId.value, 'video_composition')
    ElMessage.success('视频合成已启动，请稍候...')

    pollTimer = setInterval(async () => {
      await fetchVideos()
      const latest = videos.value[videos.value.length - 1]
      if (latest && latest.status === 'completed') {
        activeVideoId.value = latest.id
        cacheBuster.value = Date.now()
        loading.value = false
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
        ElMessage.success('视频合成完成')
      } else if (latest && latest.status === 'failed') {
        loading.value = false
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
        ElMessage.error('视频合成失败')
      }
    }, 3000)
  } catch {
    ElMessage.error('启动失败')
    loading.value = false
  }
}

async function saveSubtitleSettings() {
  try {
    await projectsApi.update(projectId.value, {
      subtitle_enabled: subtitleSettings.subtitle_enabled,
      subtitle_font_size: subtitleSettings.subtitle_font_size,
      subtitle_font_color: subtitleSettings.subtitle_font_color,
      subtitle_outline_width: subtitleSettings.subtitle_outline_width,
      subtitle_margin_bottom: subtitleSettings.subtitle_margin_bottom,
    } as any)
    ElMessage.success('字幕设置已保存')
    subtitleDialogVisible.value = false
    await store.loadProject(projectId.value)
  } catch {
    ElMessage.error('保存失败')
  }
}

function selectVideo(videoId: string) {
  activeVideoId.value = videoId
  cacheBuster.value = Date.now()
}

function formatSize(bytes: number | null) {
  if (!bytes) return '--'
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatDuration(seconds: number | null) {
  if (!seconds) return '--'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function formatTime(dateStr: string) {
  return new Date(dateStr).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}
</script>

<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <h3 style="margin: 0;">视频预览</h3>
      <div>
        <el-button @click="subtitleDialogVisible = true" size="small">
          <el-icon><Setting /></el-icon> 字幕设置
        </el-button>
        <el-button v-if="videos.length > 0 && videos[0].file_path" @click="utilsApi.openFolder(videos[0].file_path)" size="small">
          <el-icon><FolderOpened /></el-icon> 打开目录
        </el-button>
        <el-button type="primary" @click="handleCompose" :loading="loading">
          <el-icon><VideoCamera /></el-icon> {{ videos.length > 0 ? '重新合成' : '合成视频' }}
        </el-button>
      </div>
    </div>

    <!-- 视频播放区 -->
    <el-card v-if="activeVideo && activeVideo.status === 'completed'" style="margin-bottom: 16px;">
      <video controls style="width: 100%; max-height: 540px; background: #000;" :src="videoSrc" :key="cacheBuster"></video>
      <el-descriptions :column="4" border size="small" style="margin-top: 12px;">
        <el-descriptions-item label="文件名">{{ activeVideo.file_name }}</el-descriptions-item>
        <el-descriptions-item label="分辨率">{{ activeVideo.resolution || '--' }}</el-descriptions-item>
        <el-descriptions-item label="时长">{{ formatDuration(activeVideo.duration) }}</el-descriptions-item>
        <el-descriptions-item label="大小">{{ formatSize(activeVideo.file_size) }}</el-descriptions-item>
        <el-descriptions-item label="比例">{{ activeVideo.aspect_ratio }}</el-descriptions-item>
        <el-descriptions-item label="模板">{{ activeVideo.template_used }}</el-descriptions-item>
        <el-descriptions-item label="字幕">{{ activeVideo.has_subtitles ? '有' : '无' }}</el-descriptions-item>
        <el-descriptions-item label="生成时间">{{ formatTime(activeVideo.created_at) }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 版本历史列表 -->
    <div v-if="videos.length > 1" style="margin-bottom: 16px;">
      <h4 style="margin: 0 0 8px 0; color: #606266;">历史版本 ({{ videos.length }})</h4>
      <el-table :data="[...videos].reverse()" size="small" highlight-current-row
        @row-click="(row: VideoOutput) => selectVideo(row.id)"
        style="cursor: pointer;">
        <el-table-column label="版本" width="60">
          <template #default="{ $index }">
            #{{ videos.length - $index }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.status === 'completed' ? 'success' : row.status === 'failed' ? 'danger' : 'warning'" size="small">
              {{ row.status === 'completed' ? '完成' : row.status === 'failed' ? '失败' : '进行中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="resolution" label="分辨率" width="100" />
        <el-table-column label="时长" width="80">
          <template #default="{ row }">{{ formatDuration(row.duration) }}</template>
        </el-table-column>
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column prop="template_used" label="模板" width="100" />
        <el-table-column label="生成时间">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="" width="60">
          <template #default="{ row }">
            <el-tag v-if="activeVideo?.id === row.id" type="primary" size="small">当前</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div v-if="loading && videos.length === 0" style="text-align: center; padding: 40px;">
      <el-icon class="is-loading" :size="32"><Loading /></el-icon>
      <p>视频合成中，请稍候...</p>
    </div>

    <el-empty v-if="!loading && videos.length === 0" description="暂无视频，请先完成前面的步骤后合成视频" />

    <!-- 字幕设置对话框 -->
    <el-dialog v-model="subtitleDialogVisible" title="字幕设置" width="480px">
      <el-form label-width="100px" label-position="left">
        <el-form-item label="显示字幕">
          <el-switch v-model="subtitleSettings.subtitle_enabled" />
        </el-form-item>
        <template v-if="subtitleSettings.subtitle_enabled">
          <el-form-item label="字号">
            <div style="width: 100%; display: flex; align-items: center; gap: 12px;">
              <el-slider
                v-model="subtitleSettings.subtitle_font_size"
                :min="12"
                :max="48"
                :step="1"
                style="flex: 1;"
              />
              <span style="min-width: 36px; text-align: right; font-size: 13px; color: #606266;">{{ subtitleSettings.subtitle_font_size }}px</span>
            </div>
          </el-form-item>
          <el-form-item label="字体颜色">
            <el-color-picker v-model="subtitleSettings.subtitle_font_color" />
            <span style="margin-left: 8px; font-size: 13px; color: #909399;">{{ subtitleSettings.subtitle_font_color }}</span>
          </el-form-item>
          <el-form-item label="描边宽度">
            <div style="width: 100%; display: flex; align-items: center; gap: 12px;">
              <el-slider
                v-model="subtitleSettings.subtitle_outline_width"
                :min="0"
                :max="4"
                :step="1"
                style="flex: 1;"
              />
              <span style="min-width: 36px; text-align: right; font-size: 13px; color: #606266;">{{ subtitleSettings.subtitle_outline_width }}px</span>
            </div>
          </el-form-item>
          <el-form-item label="底部边距">
            <div style="width: 100%; display: flex; align-items: center; gap: 12px;">
              <el-slider
                v-model="subtitleSettings.subtitle_margin_bottom"
                :min="10"
                :max="200"
                :step="5"
                style="flex: 1;"
              />
              <span style="min-width: 36px; text-align: right; font-size: 13px; color: #606266;">{{ subtitleSettings.subtitle_margin_bottom }}px</span>
            </div>
          </el-form-item>
        </template>
      </el-form>
      <div style="font-size: 12px; color: #909399; margin-top: 4px;">
        修改字幕设置后需要重新合成视频才会生效。
      </div>
      <template #footer>
        <el-button @click="subtitleDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveSubtitleSettings">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
