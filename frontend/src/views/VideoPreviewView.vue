<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { projectsApi } from '../api/projects'
import { pipelineApi } from '../api/pipeline'
import { utilsApi } from '../api/utils'
import { useProjectStore } from '../stores/project'
import { settingsApi } from '../api/settings'
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
  portrait_title_color: '#FFFFFF',
  portrait_title_outline_color: '#000000',
  portrait_title_outline_width: 2,
  portrait_title_shadow_enabled: true,
  portrait_title_shadow_color: '#000000',
  portrait_title_shadow_opacity: 0.5,
  portrait_title_shadow_x: 2,
  portrait_title_shadow_y: 2,
  portrait_sub_title_text: '',
  portrait_sub_title_font_size: 24,
  portrait_sub_title_color: '#CCCCCC',
  portrait_sub_title_y: 130,
  portrait_title_bg_enabled: false,
  portrait_title_bg_color: '#000000',
  portrait_title_bg_opacity: 0.5,
  portrait_title_bg_padding: 20,
  portrait_title_bg_shape: 'rect',
  portrait_title_bg_radius: 16,
  portrait_title_bg_skew: 10,
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

const previewSubTitleText = computed(() =>
  portraitSettings.portrait_sub_title_text?.trim() || ''
)

// 字幕示例句子取真实长度(一句口播稿的量级),这样调字号时能直接看出会折几行
const previewSubtitleSample = '这些判断都基于一个前提，骨头应该匀速成熟，一年长一岁。'

// 背景条为非矩形时，后端走 Pillow overlay(title_overlay.py)：主副标题被画进
// 同一个形状里，副标题紧跟主标题下方，portrait_sub_title_y 完全不起作用。
// 预览必须跟着这么排，否则副标题会按自己的 Y 跑到主标题上面，和成片对不上。
const titleOverlayMode = computed(() =>
  portraitSettings.portrait_title_bg_enabled &&
  portraitSettings.portrait_title_bg_shape !== 'rect'
)

// 矩形/无底条走后端 drawtext,长标题会按字号折行(portrait_service._wrap_cjk +
// chars_per_line)。预览用同样的规则折,才能如实反映成片会折成几行。
const SUBTITLE_SIDE_MARGIN = 40
const LEADING_PUNCT = '，。！？、；：,.!?;:…）】」》'

function charsPerLine(fontSize: number): number {
  const usable = Math.max(PORTRAIT_FULL_W - SUBTITLE_SIDE_MARGIN * 2, fontSize)
  return Math.max(4, Math.floor(usable / Math.max(fontSize, 1)))
}

function wrapCjk(text: string, maxChars: number, maxLines: number): string[] {
  const t = (text || '').trim()
  if (!t) return []
  if (maxChars <= 0) return [t]
  const chars = Array.from(t)
  const lines: string[] = []
  let cur = ''
  let n = 0
  for (const ch of chars) {
    cur += ch
    n++
    if (n >= maxChars) { lines.push(cur); cur = ''; n = 0 }
  }
  if (cur) lines.push(cur)
  const fixed: string[] = []
  for (let ln of lines) {
    while (ln && LEADING_PUNCT.includes(ln[0]) && fixed.length) {
      fixed[fixed.length - 1] += ln[0]
      ln = ln.slice(1)
    }
    if (ln) fixed.push(ln)
  }
  let out = fixed.length ? fixed : [t]
  if (out.length > maxLines) {
    out = out.slice(0, maxLines)
    out[maxLines - 1] = out[maxLines - 1].slice(0, Math.max(1, maxChars - 1)) + '…'
  }
  return out
}

// overlay(平行四边形)模式后端按像素折成最多两行,预览用 CSS 自然换行即可;
// 矩形模式才需要按字号显式折行。用 \n 连接 + white-space:pre-line 渲染。
const previewTitleDisplay = computed(() => {
  if (titleOverlayMode.value) return previewTitleText.value
  const cpl = charsPerLine(portraitSettings.portrait_title_font_size)
  return wrapCjk(previewTitleText.value, cpl, 3).join('\n')
})

const previewSubTitleDisplay = computed(() => {
  if (titleOverlayMode.value) return previewSubTitleText.value
  const cpl = charsPerLine(portraitSettings.portrait_sub_title_font_size)
  return wrapCjk(previewSubTitleText.value, cpl, 2).join('\n')
})

// 兼容 #RGB 简写；认不出来的值（空串、rgba(...) 等）原样返回，
// 总比拼出 rgba(NaN,NaN,NaN) 让浏览器整条丢弃、预览里底条凭空消失强
function hexToRgba(hex: string, alpha: number): string {
  let h = (hex || '').trim().replace('#', '')
  if (h.length === 3) h = h.split('').map(c => c + c).join('')
  if (!/^[0-9a-fA-F]{6}$/.test(h)) return hex
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

const previewStyles = computed(() => {
  const s = PREVIEW_SCALE
  const ps = portraitSettings

  // Build title text-shadow
  const shadowParts: string[] = []
  if (ps.portrait_title_shadow_enabled) {
    const sx = Math.max(1, Math.round(ps.portrait_title_shadow_x * s))
    const sy = Math.max(1, Math.round(ps.portrait_title_shadow_y * s))
    shadowParts.push(`${sx}px ${sy}px 2px ${ps.portrait_title_shadow_color}`)
  }
  // Outline simulation via text-shadow (4 directions)
  if (ps.portrait_title_outline_width > 0) {
    const ow = Math.max(1, Math.round(ps.portrait_title_outline_width * s))
    const oc = ps.portrait_title_outline_color
    shadowParts.push(`${ow}px 0 0 ${oc}`, `-${ow}px 0 0 ${oc}`, `0 ${ow}px 0 ${oc}`, `0 -${ow}px 0 ${oc}`)
  }

  // Title background decoration (applied as inline background on title text)
  const isParallelogram = ps.portrait_title_bg_shape === 'parallelogram'
  const skew = ps.portrait_title_bg_enabled && isParallelogram ? ps.portrait_title_bg_skew : 0
  const titleBgInline: Record<string, string> = {}
  if (ps.portrait_title_bg_enabled) {
    const pad = Math.max(2, Math.round(ps.portrait_title_bg_padding * s))
    Object.assign(titleBgInline, {
      // 透明度只作用于底色：后端只给填充色带 alpha，文字始终不透明
      backgroundColor: hexToRgba(ps.portrait_title_bg_color, ps.portrait_title_bg_opacity),
      padding: `${pad}px ${pad * 2}px`,
      borderRadius: Math.round(ps.portrait_title_bg_radius * s) + 'px',
      display: 'inline-block',
      transform: skew ? `skewX(-${skew}deg)` : 'none',
    })
  }
  // 后端只把背景画成平行四边形，文字是正的；预览里把文字反向斜回来对齐
  const counterSkew = skew ? { display: 'inline-block', transform: `skewX(${skew}deg)` } : {}

  return {
    canvas: {
      width: PREVIEW_W + 'px',
      height: PREVIEW_H + 'px',
      backgroundColor: ps.portrait_bg_color,
      position: 'relative' as const,
      overflow: 'hidden',
      borderRadius: '8px',
      border: '1px solid #dcdfe6',
      flexShrink: 0,
    },
    titleBgInline,
    titleTextInline: counterSkew,
    // overlay 模式下副标题画在标题底条里，紧跟标题下方(后端 gap=12px)
    subInBar: {
      // counterSkew 先展开：它带的 display:inline-block 会被下面的 block 覆盖，
      // 副标题必须自成一行落在标题下方(顺序反了就并排显示)
      ...counterSkew,
      display: 'block',
      marginTop: Math.max(1, Math.round(12 * s)) + 'px',
      fontSize: Math.max(7, Math.round(ps.portrait_sub_title_font_size * s)) + 'px',
      color: ps.portrait_sub_title_color,
      fontWeight: 'normal' as const,
      lineHeight: '1.3',
    },
    title: {
      position: 'absolute' as const,
      top: Math.round(ps.portrait_title_y * s) + 'px',
      left: '0',
      right: '0',
      textAlign: 'center' as const,
      fontSize: Math.max(8, Math.round(ps.portrait_title_font_size * s)) + 'px',
      color: ps.portrait_title_color,
      fontWeight: 'bold' as const,
      textShadow: shadowParts.join(', ') || 'none',
      padding: '0 6px',
      lineHeight: '1.3',
      // overlay 模式后端按像素折行,预览用 CSS 自然换行(normal);矩形/无底条走
      // drawtext,已在 previewTitleDisplay 里按字号显式折好。用 pre(而非 pre-line):
      // 只按显式换行渲染、不再按宽度二次折,和后端 drawtext"照给定行渲染、超宽才裁"
      // 一致 —— pre-line 会把标点回拉后略超条宽的那行再折一次,比成片多一行
      whiteSpace: (ps.portrait_title_bg_enabled && isParallelogram ? 'normal' : 'pre') as const,
      overflow: 'hidden',
    },
    subTitle: {
      position: 'absolute' as const,
      top: Math.round(ps.portrait_sub_title_y * s) + 'px',
      left: '0',
      right: '0',
      textAlign: 'center' as const,
      fontSize: Math.max(7, Math.round(ps.portrait_sub_title_font_size * s)) + 'px',
      color: ps.portrait_sub_title_color,
      padding: '0 6px',
      lineHeight: '1.3',
      // 副标题后端也会按字号折行(最多两行),预览用 pre 只按显式换行渲染
      whiteSpace: 'pre' as const,
      overflow: 'hidden',
    },
    video: {
      position: 'absolute' as const,
      top: Math.round(ps.portrait_video_y * s) + 'px',
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
      bottom: Math.round(ps.portrait_subtitle_margin_v * s) + 'px',
      left: '0',
      right: '0',
      textAlign: 'center' as const,
      fontSize: Math.max(7, Math.round(ps.portrait_subtitle_font_size * s)) + 'px',
      color: '#FFFFFF',
      textShadow: '1px 1px 2px rgba(0,0,0,0.8)',
      // 左右留白和成片一致(portrait_service.SUBTITLE_SIDE_MARGIN = 40)
      padding: `0 ${Math.max(2, Math.round(40 * s))}px`,
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
    portraitSettings.portrait_title_color = store.currentProject.portrait_title_color ?? '#FFFFFF'
    portraitSettings.portrait_title_outline_color = store.currentProject.portrait_title_outline_color ?? '#000000'
    portraitSettings.portrait_title_outline_width = store.currentProject.portrait_title_outline_width ?? 2
    portraitSettings.portrait_title_shadow_enabled = store.currentProject.portrait_title_shadow_enabled ?? true
    portraitSettings.portrait_title_shadow_color = store.currentProject.portrait_title_shadow_color ?? '#000000'
    portraitSettings.portrait_title_shadow_opacity = store.currentProject.portrait_title_shadow_opacity ?? 0.5
    portraitSettings.portrait_title_shadow_x = store.currentProject.portrait_title_shadow_x ?? 2
    portraitSettings.portrait_title_shadow_y = store.currentProject.portrait_title_shadow_y ?? 2
    portraitSettings.portrait_sub_title_text = store.currentProject.portrait_sub_title_text ?? ''
    portraitSettings.portrait_sub_title_font_size = store.currentProject.portrait_sub_title_font_size ?? 24
    portraitSettings.portrait_sub_title_color = store.currentProject.portrait_sub_title_color ?? '#CCCCCC'
    portraitSettings.portrait_sub_title_y = store.currentProject.portrait_sub_title_y ?? 130
    portraitSettings.portrait_title_bg_enabled = store.currentProject.portrait_title_bg_enabled ?? false
    portraitSettings.portrait_title_bg_color = store.currentProject.portrait_title_bg_color ?? '#000000'
    portraitSettings.portrait_title_bg_opacity = store.currentProject.portrait_title_bg_opacity ?? 0.5
    portraitSettings.portrait_title_bg_padding = store.currentProject.portrait_title_bg_padding ?? 20
    portraitSettings.portrait_title_bg_shape = store.currentProject.portrait_title_bg_shape ?? 'rect'
    portraitSettings.portrait_title_bg_radius = store.currentProject.portrait_title_bg_radius ?? 16
    portraitSettings.portrait_title_bg_skew = store.currentProject.portrait_title_bg_skew ?? 10
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
  const stepName = type === 'portrait' ? 'portrait_composite' : 'video_composition'
  pollTimer = setInterval(async () => {
    try {
      const { data: steps } = await pipelineApi.getStatus(projectId.value)
      const step = steps.find((s: any) => s.step_name === stepName)
      if (!step) return

      if (step.status === 'completed') {
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
        await fetchVideos()
        const targetVideos = type === 'portrait' ? portraitVideos.value : standardVideos.value
        const latest = targetVideos[targetVideos.length - 1]
        if (latest) {
          activeTab.value = type
          activeVideoId.value = latest.id
        }
        cacheBuster.value = Date.now()
        if (type === 'portrait') {
          portraitLoading.value = false
        } else {
          loading.value = false
        }
        ElMessage.success(type === 'portrait' ? '竖屏合成完成' : '视频合成完成')
      } else if (step.status === 'failed') {
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
        if (type === 'portrait') {
          portraitLoading.value = false
        } else {
          loading.value = false
        }
        ElMessage.error(step.error_message || (type === 'portrait' ? '竖屏合成失败' : '视频合成失败'))
      }
    } catch {
      // Ignore polling errors
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

function getPortraitPayload() {
  return {
    portrait_bg_color: portraitSettings.portrait_bg_color,
    portrait_title_text: portraitSettings.portrait_title_text || null,
    portrait_title_font_size: portraitSettings.portrait_title_font_size,
    portrait_title_y: portraitSettings.portrait_title_y,
    portrait_video_y: portraitSettings.portrait_video_y,
    portrait_subtitle_font_size: portraitSettings.portrait_subtitle_font_size,
    portrait_subtitle_margin_v: portraitSettings.portrait_subtitle_margin_v,
    portrait_title_color: portraitSettings.portrait_title_color,
    portrait_title_outline_color: portraitSettings.portrait_title_outline_color,
    portrait_title_outline_width: portraitSettings.portrait_title_outline_width,
    portrait_title_shadow_enabled: portraitSettings.portrait_title_shadow_enabled,
    portrait_title_shadow_color: portraitSettings.portrait_title_shadow_color,
    portrait_title_shadow_opacity: portraitSettings.portrait_title_shadow_opacity,
    portrait_title_shadow_x: portraitSettings.portrait_title_shadow_x,
    portrait_title_shadow_y: portraitSettings.portrait_title_shadow_y,
    portrait_sub_title_text: portraitSettings.portrait_sub_title_text || null,
    portrait_sub_title_font_size: portraitSettings.portrait_sub_title_font_size,
    portrait_sub_title_color: portraitSettings.portrait_sub_title_color,
    portrait_sub_title_y: portraitSettings.portrait_sub_title_y,
    portrait_title_bg_enabled: portraitSettings.portrait_title_bg_enabled,
    portrait_title_bg_color: portraitSettings.portrait_title_bg_color,
    portrait_title_bg_opacity: portraitSettings.portrait_title_bg_opacity,
    portrait_title_bg_padding: portraitSettings.portrait_title_bg_padding,
    portrait_title_bg_shape: portraitSettings.portrait_title_bg_shape,
    portrait_title_bg_radius: portraitSettings.portrait_title_bg_radius,
    portrait_title_bg_skew: portraitSettings.portrait_title_bg_skew,
  }
}

async function savePortraitSettings() {
  try {
    await projectsApi.update(projectId.value, getPortraitPayload() as any)
    ElMessage.success('竖屏设置已保存')
    portraitDialogVisible.value = false
    await store.loadProject(projectId.value)
  } catch {
    ElMessage.error('保存失败')
  }
}

async function savePortraitAsGlobal() {
  try {
    const payload = getPortraitPayload()
    await Promise.all([
      projectsApi.update(projectId.value, payload as any),
      settingsApi.setDefaults('portrait', {
        portrait_composite_enabled: store.currentProject?.portrait_composite_enabled ?? true,
        ...payload,
      }),
    ])
    await store.loadProject(projectId.value)
    ElMessage.success('已保存当前项目，并设为新项目的全局默认')
  } catch {
    ElMessage.error('保存全局默认失败')
  }
}

function selectVideo(videoId: string) {
  activeVideoId.value = videoId
  cacheBuster.value = Date.now()
}

async function handleDeleteVideo(videoId: string) {
  try {
    await projectsApi.deleteVideo(projectId.value, videoId)
    // Reset active selection so it falls back to latest
    if (activeVideoId.value === videoId) {
      activeVideoId.value = null
    }
    ElMessage.success('已删除')
    await fetchVideos()
    cacheBuster.value = Date.now()
  } catch {
    ElMessage.error('删除失败')
  }
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
        <el-button v-if="videos.length > 0 && videos[0]?.file_path" @click="utilsApi.openFolder(videos[0]!.file_path)" size="small">
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
        <el-table-column label="" width="120">
          <template #default="{ row }">
            <div style="display: flex; align-items: center; gap: 4px;">
              <el-tag v-if="activeVideo?.id === row.id" type="primary" size="small">当前</el-tag>
              <el-popconfirm
                v-if="activeVideo?.id !== row.id"
                title="确定删除这个历史版本？"
                confirm-button-text="删除"
                cancel-button-text="取消"
                @confirm="handleDeleteVideo(row.id)"
              >
                <template #reference>
                  <el-button text size="small" type="danger" @click.stop>
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </template>
              </el-popconfirm>
            </div>
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
              <el-slider v-model="subtitleSettings.subtitle_font_size" :min="12" :max="96" :step="1" style="flex: 1;" />
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
    <el-dialog v-model="portraitDialogVisible" title="竖屏合成设置" width="920px">
      <div style="display: flex; gap: 24px;">
        <!-- 左侧：实时预览 -->
        <div style="display: flex; flex-direction: column; align-items: center; gap: 8px;">
          <div :style="previewStyles.canvas">
            <!-- 主标题（背景装饰自动包裹文字） -->
            <div :style="previewStyles.title">
              <span :style="previewStyles.titleBgInline">
                <span :style="previewStyles.titleTextInline">{{ previewTitleDisplay }}</span>
                <!-- 平行四边形底条：副标题和主标题共用一个形状，就画在标题下方 -->
                <span v-if="titleOverlayMode && previewSubTitleText" :style="previewStyles.subInBar">{{ previewSubTitleText }}</span>
              </span>
            </div>
            <!-- 副标题（矩形/无底条时各自绝对定位） -->
            <div v-if="!titleOverlayMode && previewSubTitleText" :style="previewStyles.subTitle">
              {{ previewSubTitleDisplay }}
            </div>
            <!-- 16:9 视频占位 -->
            <div :style="previewStyles.video">
              <span>16:9 视频画面</span>
            </div>
            <!-- 字幕示例 -->
            <div :style="previewStyles.subtitle">{{ previewSubtitleSample }}</div>
          </div>
          <span style="font-size: 11px; color: #909399;">实时布局预览 (1080x1920)</span>
        </div>

        <!-- 右侧：控件（可滚动） -->
        <div style="flex: 1; min-width: 0; max-height: 520px; overflow-y: auto; padding-right: 8px;">
          <el-form label-width="110px" label-position="left">
            <el-form-item label="背景颜色">
              <el-color-picker v-model="portraitSettings.portrait_bg_color" />
              <span style="margin-left: 8px; font-size: 13px; color: #909399;">{{ portraitSettings.portrait_bg_color }}</span>
            </el-form-item>

            <el-divider content-position="left">主标题</el-divider>
            <el-form-item label="标题文本">
              <el-input v-model="portraitSettings.portrait_title_text"
                placeholder="留空则使用项目标题"
                maxlength="30" show-word-limit />
            </el-form-item>
            <el-form-item label="标题字号">
              <div style="width: 100%; display: flex; align-items: center; gap: 12px;">
                <el-slider v-model="portraitSettings.portrait_title_font_size" :min="20" :max="160" :step="1" style="flex: 1;" />
                <span style="min-width: 42px; text-align: right; font-size: 13px; color: #606266;">{{ portraitSettings.portrait_title_font_size }}px</span>
              </div>
            </el-form-item>
            <el-form-item label="标题 Y 位置">
              <div style="width: 100%; display: flex; align-items: center; gap: 12px;">
                <el-slider v-model="portraitSettings.portrait_title_y" :min="0" :max="400" :step="5" style="flex: 1;" />
                <span style="min-width: 42px; text-align: right; font-size: 13px; color: #606266;">{{ portraitSettings.portrait_title_y }}px</span>
              </div>
            </el-form-item>
            <el-form-item label="文字颜色">
              <el-color-picker v-model="portraitSettings.portrait_title_color" />
              <span style="margin-left: 8px; font-size: 13px; color: #909399;">{{ portraitSettings.portrait_title_color }}</span>
            </el-form-item>
            <el-form-item label="描边颜色">
              <div style="display: flex; align-items: center; gap: 12px;">
                <el-color-picker v-model="portraitSettings.portrait_title_outline_color" />
                <span style="font-size: 13px; color: #909399;">宽度</span>
                <el-slider v-model="portraitSettings.portrait_title_outline_width" :min="0" :max="6" :step="1" style="width: 120px;" />
                <span style="font-size: 13px; color: #606266;">{{ portraitSettings.portrait_title_outline_width }}px</span>
              </div>
            </el-form-item>
            <el-form-item label="文字阴影">
              <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                <el-switch v-model="portraitSettings.portrait_title_shadow_enabled" />
                <template v-if="portraitSettings.portrait_title_shadow_enabled">
                  <el-color-picker v-model="portraitSettings.portrait_title_shadow_color" size="small" />
                  <span style="font-size: 12px; color: #909399;">透明度</span>
                  <el-slider v-model="portraitSettings.portrait_title_shadow_opacity" :min="0.1" :max="1" :step="0.1" style="width: 80px;" />
                  <span style="font-size: 12px; color: #909399;">X</span>
                  <el-input-number v-model="portraitSettings.portrait_title_shadow_x" :min="0" :max="10" size="small" style="width: 70px;" />
                  <span style="font-size: 12px; color: #909399;">Y</span>
                  <el-input-number v-model="portraitSettings.portrait_title_shadow_y" :min="0" :max="10" size="small" style="width: 70px;" />
                </template>
              </div>
            </el-form-item>

            <el-form-item label="背景条">
              <div style="display: flex; align-items: center; gap: 10px;">
                <el-switch v-model="portraitSettings.portrait_title_bg_enabled" />
                <span style="font-size: 12px; color: #909399;">给标题文字加一条底色；有副标题时副标题也会套用同一套背景</span>
              </div>
            </el-form-item>
            <template v-if="portraitSettings.portrait_title_bg_enabled">
              <el-form-item label="背景条颜色">
                <el-color-picker v-model="portraitSettings.portrait_title_bg_color" />
                <span style="margin-left: 8px; font-size: 13px; color: #909399;">{{ portraitSettings.portrait_title_bg_color }}</span>
              </el-form-item>
              <el-form-item label="背景条透明度">
                <div style="width: 100%; display: flex; align-items: center; gap: 12px;">
                  <el-slider v-model="portraitSettings.portrait_title_bg_opacity" :min="0.1" :max="1" :step="0.05" style="flex: 1;" />
                  <span style="min-width: 42px; text-align: right; font-size: 13px; color: #606266;">{{ (portraitSettings.portrait_title_bg_opacity * 100).toFixed(0) }}%</span>
                </div>
              </el-form-item>
              <el-form-item label="背景条内边距">
                <div style="width: 100%; display: flex; align-items: center; gap: 12px;">
                  <el-slider v-model="portraitSettings.portrait_title_bg_padding" :min="0" :max="60" :step="2" style="flex: 1;" />
                  <span style="min-width: 42px; text-align: right; font-size: 13px; color: #606266;">{{ portraitSettings.portrait_title_bg_padding }}px</span>
                </div>
              </el-form-item>
              <el-form-item label="背景形状">
                <el-radio-group v-model="portraitSettings.portrait_title_bg_shape">
                  <el-radio-button value="rect">矩形</el-radio-button>
                  <el-radio-button value="parallelogram">平行四边形</el-radio-button>
                </el-radio-group>
              </el-form-item>
              <el-form-item label="圆角半径">
                <div style="width: 100%; display: flex; align-items: center; gap: 12px;">
                  <el-slider v-model="portraitSettings.portrait_title_bg_radius" :min="0" :max="40" :step="2" style="flex: 1;" />
                  <span style="min-width: 42px; text-align: right; font-size: 13px; color: #606266;">{{ portraitSettings.portrait_title_bg_radius }}px</span>
                </div>
              </el-form-item>
              <el-form-item v-if="portraitSettings.portrait_title_bg_shape === 'parallelogram'" label="倾斜角度">
                <div style="width: 100%; display: flex; align-items: center; gap: 12px;">
                  <el-slider v-model="portraitSettings.portrait_title_bg_skew" :min="0" :max="20" :step="1" style="flex: 1;" />
                  <span style="min-width: 42px; text-align: right; font-size: 13px; color: #606266;">{{ portraitSettings.portrait_title_bg_skew }}°</span>
                </div>
              </el-form-item>
            </template>

            <el-divider content-position="left">副标题</el-divider>
            <el-form-item label="副标题文本">
              <el-input v-model="portraitSettings.portrait_sub_title_text"
                placeholder="留空则不显示副标题"
                maxlength="40" show-word-limit />
            </el-form-item>
            <el-form-item label="副标题字号">
              <div style="width: 100%; display: flex; align-items: center; gap: 12px;">
                <el-slider v-model="portraitSettings.portrait_sub_title_font_size" :min="14" :max="120" :step="1" style="flex: 1;" />
                <span style="min-width: 42px; text-align: right; font-size: 13px; color: #606266;">{{ portraitSettings.portrait_sub_title_font_size }}px</span>
              </div>
            </el-form-item>
            <el-form-item label="副标题颜色">
              <el-color-picker v-model="portraitSettings.portrait_sub_title_color" />
              <span style="margin-left: 8px; font-size: 13px; color: #909399;">{{ portraitSettings.portrait_sub_title_color }}</span>
            </el-form-item>
            <el-form-item label="副标题 Y 位置">
              <div style="width: 100%;">
                <div style="display: flex; align-items: center; gap: 12px;">
                  <el-slider v-model="portraitSettings.portrait_sub_title_y" :min="0" :max="400" :step="5"
                    :disabled="titleOverlayMode" style="flex: 1;" />
                  <span style="min-width: 42px; text-align: right; font-size: 13px; color: #606266;">{{ portraitSettings.portrait_sub_title_y }}px</span>
                </div>
                <div v-if="titleOverlayMode" style="font-size: 12px; color: #e6a23c; line-height: 1.5;">
                  背景形状为平行四边形时，副标题会和主标题画进同一个底条、紧跟标题下方，此项不生效
                </div>
              </div>
            </el-form-item>

            <el-divider content-position="left">视频位置</el-divider>
            <el-form-item label="视频 Y 位置">
              <div style="width: 100%; display: flex; align-items: center; gap: 12px;">
                <el-slider v-model="portraitSettings.portrait_video_y" :min="200" :max="800" :step="10" style="flex: 1;" />
                <span style="min-width: 42px; text-align: right; font-size: 13px; color: #606266;">{{ portraitSettings.portrait_video_y }}px</span>
              </div>
            </el-form-item>

            <el-divider content-position="left">字幕布局</el-divider>
            <el-form-item label="字幕字号">
              <div style="width: 100%; display: flex; align-items: center; gap: 12px;">
                <el-slider v-model="portraitSettings.portrait_subtitle_font_size" :min="20" :max="160" :step="1" style="flex: 1;" />
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
        <div style="display: flex; justify-content: space-between; width: 100%;">
          <el-button type="success" plain @click="savePortraitAsGlobal">保存为全局默认</el-button>
          <div>
            <el-button @click="portraitDialogVisible = false">取消</el-button>
            <el-button type="primary" @click="savePortraitSettings">保存</el-button>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>
