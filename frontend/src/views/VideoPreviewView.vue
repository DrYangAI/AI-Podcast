<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { projectsApi } from '../api/projects'
import { pipelineApi } from '../api/pipeline'
import { utilsApi } from '../api/utils'
import { useProjectStore } from '../stores/project'
import type { VideoOutput } from '../types/project'
import { formatDateTime } from '../utils/date'

const route = useRoute()
const store = useProjectStore()
const projectId = computed(() => route.params.id as string)
const videos = ref<VideoOutput[]>([])
const loading = ref(false)
const portraitLoading = ref(false)
const cacheBuster = ref(Date.now())
const activeVideoId = ref<string | null>(null)
const activeTab = ref('standard')
const subtitleDialogVisible = ref(false)
const portraitDialogVisible = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

const subtitleSettings = reactive({
  subtitle_enabled: true,
  subtitle_font_size: 18,
  subtitle_font_color: '#FFFFFF',
  subtitle_outline_width: 1,
  subtitle_margin_bottom: 30,
})

const portraitSettings = reactive({
  portrait_bg_color: '#1A1A2E',
  portrait_title_text: '',
  portrait_title_font_size: 36,
  portrait_title_y: 82,
  portrait_video_y: 480,
  portrait_subtitle_font_size: 38,
  portrait_subtitle_margin_v: 550,
})

// 按 video_type 过滤视频
const standardVideos = computed(() =>
  videos.value.filter(v => (v.video_type || 'standard') === 'standard')
)
const portraitVideos = computed(() =>
  videos.value.filter(v => v.video_type === 'portrait')
)

const currentTabVideos = computed(() =>
  activeTab.value === 'portrait' ? portraitVideos.value : standardVideos.value
)

const activeVideo = computed(() => {
  const tabVideos = currentTabVideos.value
  if (activeVideoId.value) {
    const found = tabVideos.find(v => v.id === activeVideoId.value)
    if (found) return found
  }
  const completed = tabVideos.filter(v => v.status === 'completed')
  return completed.length > 0 ? completed[completed.length - 1] : null
})

const videoSrc = computed(() => {
  const v = activeVideo.value
  if (!v?.file_path || v.status !== 'completed') return ''
  return '/' + v.file_path + '?t=' + cacheBuster.value
})

const portraitEnabled = computed(() =>
  store.currentProject?.portrait_composite_enabled ?? true
)

// ── 竖屏预览相关 ──
const PORTRAIT_FULL_W = 1080
const PORTRAIT_FULL_H = 1920
const VIDEO_FULL_H = 608  // 1080 * 9/16 ≈ 608
const PREVIEW_H = 400
const PREVIEW_SCALE = PREVIEW_H / PORTRAIT_FULL_H  // ≈ 0.2083
const PREVIEW_W = Math.round(PORTRAIT_FULL_W * PREVIEW_SCALE)  // ≈ 225

const previewTitleText = computed(() =>
  portraitSettings.portrait_title_text || store.currentProject?.title || '项目标题'
)

const previewStyles = computed(() => {
  const s = PREVIEW_SCALE
  return {
    canvas: {
      width: PREVIEW_W + 'px',
      height: PREVIEW_H + 'px',
      backgroundColor: portraitSettings.portrait_bg_color,
      position: 'relative' as const,
      overflow: 'hidden',
      borderRadius: '8px',
      border: '1px solid #dcdfe6',
      flexShrink: 0,
    },
    title: {
      position: 'absolute' as const,
      top: Math.round(portraitSettings.portrait_title_y * s) + 'px',
      left: '0',
      right: '0',
      textAlign: 'center' as const,
      fontSize: Math.max(8, Math.round(portraitSettings.portrait_title_font_size * s)) + 'px',
      color: '#FFFFFF',
      fontWeight: 'bold' as const,
      textShadow: '1px 1px 2px rgba(0,0,0,0.5)',
      padding: '0 6px',
      lineHeight: '1.3',
      whiteSpace: 'nowrap' as const,
      overflow: 'hidden',
      textOverflow: 'ellipsis',
    },
    video: {
      position: 'absolute' as const,
      top: Math.round(portraitSettings.portrait_video_y * s) + 'px',
      left: '0',
      width: '100%',
      height: Math.round(VIDEO_FULL_H * s) + 'px',
      backgroundColor: '#374151',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: '#9ca3af',
      fontSize: '11px',
    },
    subtitle: {
      position: 'absolute' as const,
      bottom: Math.round(portraitSettings.portrait_subtitle_margin_v * s) + 'px',
      left: '0',
      right: '0',
      textAlign: 'center' as const,
      fontSize: Math.max(7, Math.round(portraitSettings.portrait_subtitle_font_size * s)) + 'px',
      color: '#FFFFFF',
      textShadow: '1px 1px 2px rgba(0,0,0,0.8)',
      padding: '0 8px',
      lineHeight: '1.4',
    },
  }
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
    portraitSettings.portrait_bg_color = store.currentProject.portrait_bg_color ?? '#1A1A2E'
    portraitSettings.portrait_title_text = store.currentProject.portrait_title_text ?? ''
    portraitSettings.portrait_title_font_size = store.currentProject.portrait_title_font_size ?? 36
    portraitSettings.portrait_title_y = store.currentProject.portrait_title_y ?? 82
    portraitSettings.portrait_video_y = store.currentProject.portrait_video_y ?? 480
    portraitSettings.portrait_subtitle_font_size = store.currentProject.portrait_subtitle_font_size ?? 38
    portraitSettings.portrait_subtitle_margin_v = store.currentProject.portrait_subtitle_margin_v ?? 550
  }
  // 如果有竖屏视频，默认切到竖屏 Tab
  if (portraitVideos.value.length > 0) {
    activeTab.value = 'portrait'
  }
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

function onTabChange() {
  activeVideoId.value = null
  cacheBuster.value = Date.now()
}

async function handleCompose() {
  loading.value = true
  try {
    await pipelineApi.runStep(projectId.value, 'video_composition')
    ElMessage.success('视频合成已启动，请稍候...')
    startComposePolling('standard')
  } catch {
    ElMessage.error('启动失败')
    loading.value = false
  }
}

async function handlePortraitCompose() {
  portraitLoading.value = true
  try {
    await pipelineApi.runStep(projectId.value, 'portrait_composite')
    ElMessage.success('竖屏合成已启动，请稍候...')
    startComposePolling('portrait')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '启动失败')
    portraitLoading.value = false
  }
}

function startComposePolling(type: 'standard' | 'portrait') {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    await fetchVideos()
    const targetVideos = type === 'portrait' ? portraitVideos.value : standardVideos.value
    const latest = targetVideos[targetVideos.length - 1]
    if (latest && latest.status === 'completed') {
      activeTab.value = type
      activeVideoId.value = latest.id
      cacheBuster.value = Date.now()
      if (type === 'portrait') {
        portraitLoading.value = false
      } else {
        loading.value = false
      }
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
      ElMessage.success(type === 'portrait' ? '竖屏合成完成' : '视频合成完成')
    } else if (latest && latest.status === 'failed') {
      if (type === 'portrait') {
        portraitLoading.value = false
      } else {
        loading.value = false
      }
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
      ElMessage.error(type === 'portrait' ? '竖屏合成失败' : '视频合成失败')
    }
  }, 3000)
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

async function savePortraitSettings() {
  try {
    await projectsApi.update(projectId.value, {
      portrait_bg_color: portraitSettings.portrait_bg_color,
      portrait_title_text: portraitSettings.portrait_title_text || null,
      portrait_title_font_size: portraitSettings.portrait_title_font_size,
      portrait_title_y: portraitSettings.portrait_title_y,
      portrait_video_y: portraitSettings.portrait_video_y,
      portrait_subtitle_font_size: portraitSettings.portrait_subtitle_font_size,
      portrait_subtitle_margin_v: portraitSettings.portrait_subtitle_margin_v,
    } as any)
    ElMessage.success('竖屏设置已保存')
    portraitDialogVisible.value = false
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

// formatTime removed — use shared formatDateTime from utils/date
</script>

<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <h3 style="margin: 0;">视频预览</h3>
      <div style="display: flex; gap: 8px;">
        <template v-if="activeTab === 'standard'">
          <el-button @click="subtitleDialogVisible = true" size="small">
            <el-icon><Setting /></el-icon> 字幕设置
          </el-button>
          <el-button type="primary" @click="handleCompose" :loading="loading">
            <el-icon><VideoCamera /></el-icon> {{ standardVideos.length > 0 ? '重新合成' : '合成视频' }}
          </el-button>
        </template>
        <template v-if="activeTab === 'portrait'">
          <el-button @click="portraitDialogVisible = true" size="small">
            <el-icon><Setting /></el-icon> 竖屏设置
          </el-button>
          <el-button type="primary" @click="handlePortraitCompose" :loading="portraitLoading"
            :disabled="!portraitEnabled">
            <el-icon><VideoCamera /></el-icon> {{ portraitVideos.length > 0 ? '重新合成' : '合成竖屏' }}
          </el-button>
        </template>
        <el-button v-if="videos.length > 0 && videos[0].file_path" @click="utilsApi.openFolder(videos[0].file_path)" size="small">
          <el-icon><FolderOpened /></el-icon> 打开目录
        </el-button>
      </div>
    </div>

    <!-- Tab 切换 -->
    <el-tabs v-model="activeTab" @tab-change="onTabChange" style="margin-bottom: 16px;">
      <el-tab-pane name="standard">
        <template #label>
          <span>横屏视频
            <el-badge v-if="standardVideos.filter(v => v.status === 'completed').length > 0"
              :value="standardVideos.filter(v => v.status === 'completed').length"
              type="info" style="margin-left: 4px;" />
          </span>
        </template>
      </el-tab-pane>
      <el-tab-pane name="portrait">
        <template #label>
          <span>竖屏视频
            <el-badge v-if="portraitVideos.filter(v => v.status === 'completed').length > 0"
              :value="portraitVideos.filter(v => v.status === 'completed').length"
              type="info" style="margin-left: 4px;" />
          </span>
        </template>
      </el-tab-pane>
    </el-tabs>

    <!-- 竖屏未启用提示 -->
    <el-alert
      v-if="activeTab === 'portrait' && !portraitEnabled"
      title="竖屏合成已禁用"
      description="请在流水线页面启用「竖屏合成」步骤后再合成竖屏视频"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 16px;"
    />

    <!-- 视频播放区 -->
    <el-card v-if="activeVideo && activeVideo.status === 'completed'" style="margin-bottom: 16px;">
      <video controls
        :style="activeTab === 'portrait'
          ? 'width: auto; max-width: 100%; max-height: 600px; display: block; margin: 0 auto; background: #000;'
          : 'width: 100%; max-height: 540px; background: #000;'"
        :src="videoSrc" :key="cacheBuster + activeTab"></video>
      <el-descriptions :column="4" border size="small" style="margin-top: 12px;">
        <el-descriptions-item label="文件名">{{ activeVideo.file_name }}</el-descriptions-item>
        <el-descriptions-item label="分辨率">{{ activeVideo.resolution || '--' }}</el-descriptions-item>
        <el-descriptions-item label="时长">{{ formatDuration(activeVideo.duration) }}</el-descriptions-item>
        <el-descriptions-item label="大小">{{ formatSize(activeVideo.file_size) }}</el-descriptions-item>
        <el-descriptions-item label="比例">{{ activeVideo.aspect_ratio }}</el-descriptions-item>
        <el-descriptions-item label="模板">{{ activeVideo.template_used }}</el-descriptions-item>
        <el-descriptions-item label="字幕">{{ activeVideo.has_subtitles ? '有' : '无' }}</el-descriptions-item>
        <el-descriptions-item label="生成时间">{{ formatDateTime(activeVideo.created_at) }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 版本历史列表 -->
    <div v-if="currentTabVideos.length > 1" style="margin-bottom: 16px;">
      <h4 style="margin: 0 0 8px 0; color: #606266;">历史版本 ({{ currentTabVideos.length }})</h4>
      <el-table :data="[...currentTabVideos].reverse()" size="small" highlight-current-row
        @row-click="(row: VideoOutput) => selectVideo(row.id)"
        style="cursor: pointer;">
        <el-table-column label="版本" width="60">
          <template #default="{ $index }">
            #{{ currentTabVideos.length - $index }}
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
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="" width="60">
          <template #default="{ row }">
            <el-tag v-if="activeVideo?.id === row.id" type="primary" size="small">当前</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- Loading -->
    <div v-if="(activeTab === 'standard' && loading && standardVideos.length === 0) ||
               (activeTab === 'portrait' && portraitLoading && portraitVideos.length === 0)"
      style="text-align: center; padding: 40px;">
      <el-icon class="is-loading" :size="32"><Loading /></el-icon>
      <p>{{ activeTab === 'portrait' ? '竖屏合成中，请稍候...' : '视频合成中，请稍候...' }}</p>
    </div>

    <!-- 空状态 -->
    <el-empty
      v-if="!loading && !portraitLoading && currentTabVideos.length === 0 && (activeTab !== 'portrait' || portraitEnabled)"
      :description="activeTab === 'portrait'
        ? '暂无竖屏视频，请先完成横屏视频合成后再合成竖屏'
        : '暂无视频，请先完成前面的步骤后合成视频'"
    />

    <!-- 字幕设置对话框 -->
    <el-dialog v-model="subtitleDialogVisible" title="字幕设置" width="480px">
      <el-form label-width="100px" label-position="left">
        <el-form-item label="显示字幕">
          <el-switch v-model="subtitleSettings.subtitle_enabled" />
        </el-form-item>
        <template v-if="subtitleSettings.subtitle_enabled">
          <el-form-item label="字号">
            <div style="width: 100%; display: flex; align-items: center; gap: 12px;">
              <el-slider v-model="subtitleSettings.subtitle_font_size" :min="12" :max="48" :step="1" style="flex: 1;" />
              <span style="min-width: 36px; text-align: right; font-size: 13px; color: #606266;">{{ subtitleSettings.subtitle_font_size }}px</span>
            </div>
          </el-form-item>
          <el-form-item label="字体颜色">
            <el-color-picker v-model="subtitleSettings.subtitle_font_color" />
            <span style="margin-left: 8px; font-size: 13px; color: #909399;">{{ subtitleSettings.subtitle_font_color }}</span>
          </el-form-item>
          <el-form-item label="描边宽度">
            <div style="width: 100%; display: flex; align-items: center; gap: 12px;">
              <el-slider v-model="subtitleSettings.subtitle_outline_width" :min="0" :max="4" :step="1" style="flex: 1;" />
              <span style="min-width: 36px; text-align: right; font-size: 13px; color: #606266;">{{ subtitleSettings.subtitle_outline_width }}px</span>
            </div>
          </el-form-item>
          <el-form-item label="底部边距">
            <div style="width: 100%; display: flex; align-items: center; gap: 12px;">
              <el-slider v-model="subtitleSettings.subtitle_margin_bottom" :min="10" :max="200" :step="5" style="flex: 1;" />
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

    <!-- 竖屏设置对话框 -->
    <el-dialog v-model="portraitDialogVisible" title="竖屏合成设置" width="880px">
      <div style="display: flex; gap: 24px;">
        <!-- 左侧：实时预览 -->
        <div style="display: flex; flex-direction: column; align-items: center; gap: 8px;">
          <div :style="previewStyles.canvas">
            <!-- 标题 -->
            <div :style="previewStyles.title">{{ previewTitleText }}</div>
            <!-- 16:9 视频占位 -->
            <div :style="previewStyles.video">
              <span>16:9 视频画面</span>
            </div>
            <!-- 字幕示例 -->
            <div :style="previewStyles.subtitle">这里是字幕示例文本</div>
          </div>
          <span style="font-size: 11px; color: #909399;">实时布局预览 (1080×1920)</span>
        </div>

        <!-- 右侧：控件 -->
        <div style="flex: 1; min-width: 0;">
          <el-form label-width="110px" label-position="left">
            <el-form-item label="背景颜色">
              <el-color-picker v-model="portraitSettings.portrait_bg_color" />
              <span style="margin-left: 8px; font-size: 13px; color: #909399;">{{ portraitSettings.portrait_bg_color }}</span>
            </el-form-item>
            <el-form-item label="标题文本">
              <el-input v-model="portraitSettings.portrait_title_text"
                placeholder="留空则使用项目标题"
                maxlength="30" show-word-limit />
            </el-form-item>

            <el-divider content-position="left">标题布局</el-divider>
            <el-form-item label="标题字号">
              <div style="width: 100%; display: flex; align-items: center; gap: 12px;">
                <el-slider v-model="portraitSettings.portrait_title_font_size" :min="20" :max="60" :step="1" style="flex: 1;" />
                <span style="min-width: 42px; text-align: right; font-size: 13px; color: #606266;">{{ portraitSettings.portrait_title_font_size }}px</span>
              </div>
            </el-form-item>
            <el-form-item label="标题 Y 位置">
              <div style="width: 100%; display: flex; align-items: center; gap: 12px;">
                <el-slider v-model="portraitSettings.portrait_title_y" :min="0" :max="400" :step="5" style="flex: 1;" />
                <span style="min-width: 42px; text-align: right; font-size: 13px; color: #606266;">{{ portraitSettings.portrait_title_y }}px</span>
              </div>
              <div style="font-size: 11px; color: #C0C4CC; margin-top: 2px;">值越大标题越往下</div>
            </el-form-item>

            <el-divider content-position="left">视频位置</el-divider>
            <el-form-item label="视频 Y 位置">
              <div style="width: 100%; display: flex; align-items: center; gap: 12px;">
                <el-slider v-model="portraitSettings.portrait_video_y" :min="200" :max="800" :step="10" style="flex: 1;" />
                <span style="min-width: 42px; text-align: right; font-size: 13px; color: #606266;">{{ portraitSettings.portrait_video_y }}px</span>
              </div>
              <div style="font-size: 11px; color: #C0C4CC; margin-top: 2px;">控制 16:9 画面在竖屏中的起始位置，减小可让标题和字幕更贴近画面</div>
            </el-form-item>

            <el-divider content-position="left">字幕布局</el-divider>
            <el-form-item label="字幕字号">
              <div style="width: 100%; display: flex; align-items: center; gap: 12px;">
                <el-slider v-model="portraitSettings.portrait_subtitle_font_size" :min="20" :max="60" :step="1" style="flex: 1;" />
                <span style="min-width: 42px; text-align: right; font-size: 13px; color: #606266;">{{ portraitSettings.portrait_subtitle_font_size }}px</span>
              </div>
            </el-form-item>
            <el-form-item label="字幕距底边距">
              <div style="width: 100%; display: flex; align-items: center; gap: 12px;">
                <el-slider v-model="portraitSettings.portrait_subtitle_margin_v" :min="100" :max="800" :step="10" style="flex: 1;" />
                <span style="min-width: 42px; text-align: right; font-size: 13px; color: #606266;">{{ portraitSettings.portrait_subtitle_margin_v }}px</span>
              </div>
              <div style="font-size: 11px; color: #C0C4CC; margin-top: 2px;">值越大字幕越靠上（越接近视频画面）</div>
            </el-form-item>
          </el-form>
          <div style="font-size: 12px; color: #909399; margin-top: 8px;">
            拖动滑块可实时预览布局效果，保存后需重新合成才会应用到视频。
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="portraitDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="savePortraitSettings">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
