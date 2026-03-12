<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { publishApi, type PublishAsset, type PublishAssetUpdate } from '../api/publish'
import { projectsApi } from '../api/projects'
import { pipelineApi } from '../api/pipeline'
import { useProjectStore } from '../stores/project'
import type { ImageAsset } from '../types/project'

const route = useRoute()
const store = useProjectStore()
const projectId = computed(() => route.params.id as string)

const assets = ref<PublishAsset[]>([])
const segments = ref<ImageAsset[]>([])
const activeTab = ref('weixin')
const loading = ref(false)
const saving = ref(false)

// Cover generation tracking (mirrors ImageGalleryView pattern)
const coverGenerating = ref(false)
let coverPollingTimer: ReturnType<typeof setInterval> | null = null

// Cover prompt editing dialog
const coverPromptDialog = ref(false)
const coverPromptText = ref('')
const coverPromptLoading = ref(false)

// Editable copies (keyed by platform) – pre-initialise so template never hits undefined
const editData = ref<Record<string, { title: string; description: string; tags: string }>>({
  weixin: { title: '', description: '', tags: '' },
  xiaohongshu: { title: '', description: '', tags: '' },
  douyin: { title: '', description: '', tags: '' },
  tencent_video: { title: '', description: '', tags: '' },
  toutiao: { title: '', description: '', tags: '' },
})

const platformLabels: Record<string, string> = {
  weixin: '视频号',
  xiaohongshu: '小红书',
  douyin: '抖音',
  tencent_video: '腾讯视频',
  toutiao: '今日头条',
}

const platformSpecs: Record<string, { titleMax: number; descMax: number; coverW: number; coverH: number }> = {
  weixin:        { titleMax: 30,  descMax: 1000, coverW: 1080, coverH: 1260 },
  xiaohongshu:   { titleMax: 20,  descMax: 1000, coverW: 1080, coverH: 1440 },
  douyin:        { titleMax: 30,  descMax: 300,  coverW: 1080, coverH: 1920 },
  tencent_video: { titleMax: 30,  descMax: 200,  coverW: 1280, coverH: 720 },
  toutiao:       { titleMax: 30,  descMax: 400,  coverW: 1280, coverH: 720 },
}

const platforms = ['weixin', 'xiaohongshu', 'douyin', 'tencent_video', 'toutiao']

const currentAsset = computed(() =>
  assets.value.find(a => a.platform === activeTab.value)
)

const currentEdit = computed(() =>
  editData.value[activeTab.value] || { title: '', description: '', tags: '' }
)

const currentSpec = computed(() =>
  platformSpecs[activeTab.value] || { titleMax: 30, descMax: 1000, coverW: 1080, coverH: 1440 }
)

const titleLen = computed(() => currentEdit.value.title.length)
const descLen = computed(() => currentEdit.value.description.length)
const titleOver = computed(() => titleLen.value > currentSpec.value.titleMax)
const descOver = computed(() => descLen.value > currentSpec.value.descMax)

const coverUrl = computed(() => {
  const asset = currentAsset.value
  if (!asset?.cover_path) return ''
  // Convert file path to /data URL
  const path = asset.cover_path
  const dataIdx = path.indexOf('data/')
  if (dataIdx >= 0) {
    return `/${path.substring(dataIdx)}`
  }
  return `/data/covers/${projectId.value}/${path.split('/').pop()}`
})

const coverAspect = computed(() => {
  const spec = currentSpec.value
  return spec.coverW / spec.coverH
})

// --- Lifecycle ---

onMounted(async () => {
  await loadAssets()
  await loadSegmentImages()
  // Resume polling if covers are currently generating
  const hasGenerating = assets.value.some(a => a.cover_status === 'generating')
  if (hasGenerating) {
    coverGenerating.value = true
    startCoverPolling()
  }
})

onUnmounted(() => {
  stopCoverPolling()
})

// --- Data loading ---

async function loadAssets() {
  loading.value = true
  try {
    const { data } = await publishApi.getAssets(projectId.value)
    assets.value = data

    // Initialize edit data
    const ed: Record<string, { title: string; description: string; tags: string }> = {}
    for (const asset of data) {
      ed[asset.platform] = {
        title: asset.title || '',
        description: asset.description || '',
        tags: asset.tags || '',
      }
    }
    // Ensure all platforms have entries
    for (const p of platforms) {
      if (!ed[p]) {
        ed[p] = { title: '', description: '', tags: '' }
      }
    }
    editData.value = ed
  } catch (e) {
    console.error('Failed to load publish assets:', e)
  } finally {
    loading.value = false
  }
}

async function loadSegmentImages() {
  try {
    const { data } = await projectsApi.getImages(projectId.value)
    segments.value = data.filter(img => img.status === 'completed' && img.file_path)
  } catch {
    // non-critical
  }
}

// --- Cover generation polling ---

function startCoverPolling() {
  if (coverPollingTimer) return
  coverPollingTimer = setInterval(async () => {
    await loadAssets()
    const stillGenerating = assets.value.some(a => a.cover_status === 'generating')
    if (!stillGenerating) {
      stopCoverPolling()
      coverGenerating.value = false
      const anyFailed = assets.value.some(a => a.cover_status === 'failed')
      if (anyFailed) {
        ElMessage.error('封面生成失败，请检查图片服务配置')
      } else {
        ElMessage.success('封面生成完成')
      }
    }
  }, 3000)
}

function stopCoverPolling() {
  if (coverPollingTimer) {
    clearInterval(coverPollingTimer)
    coverPollingTimer = null
  }
}

// --- Cover regeneration ---

async function handleRegenerateCover(prompt?: string) {
  coverGenerating.value = true
  try {
    await publishApi.regenerateCover(projectId.value, prompt)
    ElMessage.info('封面生成中...')
    startCoverPolling()
  } catch (e: any) {
    coverGenerating.value = false
    ElMessage.error(e?.response?.data?.detail || '封面生成失败')
  }
}

// --- Cover prompt dialog ---

async function openCoverPromptEditor() {
  coverPromptLoading.value = true
  coverPromptDialog.value = true
  try {
    const { data } = await publishApi.getCoverPrompt(projectId.value)
    coverPromptText.value = data.prompt || ''
  } catch {
    coverPromptText.value = ''
  } finally {
    coverPromptLoading.value = false
  }
}

async function saveCoverPromptOnly() {
  if (!coverPromptText.value.trim()) {
    ElMessage.warning('提示词不能为空')
    return
  }
  try {
    await publishApi.updateCoverPrompt(projectId.value, coverPromptText.value)
    ElMessage.success('提示词已保存')
    coverPromptDialog.value = false
  } catch {
    ElMessage.error('保存失败')
  }
}

async function saveCoverPromptAndRegenerate() {
  const prompt = coverPromptText.value.trim() || undefined
  coverPromptDialog.value = false
  await handleRegenerateCover(prompt)
}

// --- Cover upload ---

function beforeCoverUpload(file: File) {
  const allowed = ['image/png', 'image/jpeg', 'image/webp']
  if (!allowed.includes(file.type)) {
    ElMessage.error('仅支持 PNG、JPG、WebP 格式')
    return false
  }
  if (file.size > 20 * 1024 * 1024) {
    ElMessage.error('文件大小不能超过 20MB')
    return false
  }
  return true
}

async function handleUploadCover(file: File) {
  try {
    await publishApi.uploadCover(projectId.value, activeTab.value, file)
    ElMessage.success('封面上传成功')
    await loadAssets()
  } catch {
    ElMessage.error('上传失败')
  }
}

// --- Existing functions ---

async function saveCurrentPlatform() {
  const platform = activeTab.value
  const data = currentEdit.value
  saving.value = true
  try {
    const update: PublishAssetUpdate = {
      title: data.title,
      description: data.description,
      tags: data.tags,
    }
    const { data: updated } = await publishApi.updateAsset(projectId.value, platform, update)
    // Update local asset
    const idx = assets.value.findIndex(a => a.platform === platform)
    if (idx >= 0) {
      assets.value[idx] = updated
    }
    ElMessage.success('保存成功')
  } catch {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

async function runPublishStep() {
  try {
    await pipelineApi.runStep(projectId.value, 'publish_copy')
    ElMessage.success('发布素材生成已启动')
    store.startPolling(projectId.value)
  } catch {
    ElMessage.error('启动失败')
  }
}

async function useSegmentImage(segmentId: string) {
  coverGenerating.value = true
  try {
    await publishApi.useSegmentAsCover(projectId.value, segmentId)
    ElMessage.info('封面重新生成中...')
    startCoverPolling()
  } catch {
    coverGenerating.value = false
    ElMessage.error('操作失败')
  }
}

function copyToClipboard(text: string, label: string) {
  navigator.clipboard.writeText(text).then(() => {
    ElMessage.success(`${label}已复制`)
  }).catch(() => {
    ElMessage.error('复制失败')
  })
}

function downloadCover() {
  const url = coverUrl.value
  if (!url) {
    ElMessage.warning('暂无封面可下载')
    return
  }
  const a = document.createElement('a')
  a.href = url
  const platform = activeTab.value
  const spec = currentSpec.value
  a.download = `${platform}_${spec.coverW}x${spec.coverH}.png`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

function getSegmentImageUrl(img: ImageAsset): string {
  const path = img.file_path
  const dataIdx = path.indexOf('data/')
  if (dataIdx >= 0) {
    return `/${path.substring(dataIdx)}`
  }
  return path
}
</script>

<template>
  <div v-loading="loading">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
      <h3 style="margin: 0;">发布素材</h3>
      <el-button type="primary" @click="runPublishStep">
        <el-icon><RefreshRight /></el-icon> 重新生成全部
      </el-button>
    </div>

    <div v-if="!loading && assets.length === 0" style="text-align: center; padding: 60px 0;">
      <el-empty description="暂无发布素材，请先运行「发布素材」步骤">
        <el-button type="primary" @click="runPublishStep">生成发布素材</el-button>
      </el-empty>
    </div>

    <div v-else-if="assets.length > 0">
      <el-tabs v-model="activeTab" type="card">
        <el-tab-pane
          v-for="p in platforms"
          :key="p"
          :label="platformLabels[p]"
          :name="p"
        />
      </el-tabs>

      <el-row :gutter="24" style="margin-top: 16px;">
        <!-- Cover preview -->
        <el-col :span="8">
          <el-card shadow="never">
            <template #header>
              <span>封面预览 ({{ currentSpec.coverW }}×{{ currentSpec.coverH }})</span>
            </template>

            <!-- Cover image / generating state -->
            <div
              :style="{
                width: '100%',
                paddingBottom: (1 / coverAspect * 100) + '%',
                position: 'relative',
                backgroundColor: '#f5f7fa',
                borderRadius: '8px',
                overflow: 'hidden',
              }"
            >
              <!-- Generating spinner -->
              <div
                v-if="coverGenerating"
                style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center;"
              >
                <el-icon class="is-loading" :size="32" style="color: #e6a23c;"><Loading /></el-icon>
                <span style="font-size: 12px; color: #909399; margin-top: 8px;">AI 封面生成中...</span>
              </div>
              <!-- Cover image -->
              <img
                v-else-if="coverUrl"
                :src="coverUrl"
                :alt="platformLabels[activeTab] + '封面'"
                style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: cover;"
              />
              <!-- No cover placeholder -->
              <div
                v-else
                style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; color: #c0c4cc;"
              >
                暂无封面
              </div>
            </div>

            <!-- Action buttons -->
            <div style="margin-top: 12px; display: flex; gap: 8px; flex-wrap: wrap;">
              <el-button
                size="small"
                type="primary"
                :loading="coverGenerating"
                @click="handleRegenerateCover()"
              >
                <el-icon><RefreshRight /></el-icon>
                {{ coverUrl ? '重新生成' : '生成封面' }}
              </el-button>
              <el-button size="small" type="warning" @click="openCoverPromptEditor">
                <el-icon><EditPen /></el-icon> 提示词
              </el-button>
              <el-upload
                :show-file-list="false"
                :before-upload="(f: any) => beforeCoverUpload(f)"
                :http-request="(opt: any) => handleUploadCover(opt.file)"
                accept="image/png,image/jpeg,image/webp"
                style="display: inline-block;"
              >
                <el-button size="small" type="info">
                  <el-icon><Upload /></el-icon> 上传
                </el-button>
              </el-upload>
              <el-button size="small" @click="downloadCover" :disabled="!coverUrl">
                <el-icon><Download /></el-icon> 下载
              </el-button>
            </div>

            <!-- Use segment image -->
            <div v-if="segments.length > 0" style="margin-top: 16px;">
              <el-text type="info" size="small" style="display: block; margin-bottom: 8px;">使用段落图片作为封面：</el-text>
              <div style="display: flex; gap: 6px; flex-wrap: wrap;">
                <div
                  v-for="(img, idx) in segments"
                  :key="img.id"
                  style="width: 48px; height: 48px; border-radius: 4px; overflow: hidden; cursor: pointer; border: 2px solid transparent;"
                  class="segment-thumb"
                  @click="useSegmentImage(img.segment_id)"
                  :title="'使用第' + (idx + 1) + '张图片'"
                >
                  <img :src="getSegmentImageUrl(img)" style="width: 100%; height: 100%; object-fit: cover;" />
                </div>
              </div>
            </div>
          </el-card>
        </el-col>

        <!-- Copy editor -->
        <el-col :span="16">
          <el-card shadow="never">
            <template #header>
              <span>{{ platformLabels[activeTab] }} 文案</span>
            </template>

            <!-- Title -->
            <div style="margin-bottom: 20px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <el-text tag="b">标题</el-text>
                <el-text :type="titleOver ? 'danger' : 'info'" size="small">
                  {{ titleLen }}/{{ currentSpec.titleMax }}字
                </el-text>
              </div>
              <el-input
                v-model="editData[activeTab].title"
                placeholder="输入标题"
                :class="{ 'is-over': titleOver }"
              />
              <el-button
                text size="small" style="margin-top: 4px;"
                @click="copyToClipboard(currentEdit.title, '标题')"
              >
                <el-icon><DocumentCopy /></el-icon> 复制标题
              </el-button>
            </div>

            <!-- Description -->
            <div style="margin-bottom: 20px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <el-text tag="b">摘要</el-text>
                <el-text :type="descOver ? 'danger' : 'info'" size="small">
                  {{ descLen }}/{{ currentSpec.descMax }}字
                </el-text>
              </div>
              <el-input
                v-model="editData[activeTab].description"
                type="textarea"
                :rows="6"
                placeholder="输入摘要"
                :class="{ 'is-over': descOver }"
              />
              <el-button
                text size="small" style="margin-top: 4px;"
                @click="copyToClipboard(currentEdit.description, '摘要')"
              >
                <el-icon><DocumentCopy /></el-icon> 复制摘要
              </el-button>
            </div>

            <!-- Tags -->
            <div style="margin-bottom: 20px;">
              <el-text tag="b" style="display: block; margin-bottom: 6px;">标签</el-text>
              <el-input
                v-model="editData[activeTab].tags"
                placeholder="#标签1 #标签2 #标签3"
              />
              <el-button
                text size="small" style="margin-top: 4px;"
                @click="copyToClipboard(currentEdit.tags, '标签')"
              >
                <el-icon><DocumentCopy /></el-icon> 复制标签
              </el-button>
            </div>

            <!-- Copy all -->
            <div style="margin-bottom: 16px;">
              <el-button
                text type="primary" size="small"
                @click="copyToClipboard(
                  currentEdit.title + '\n\n' + currentEdit.description + '\n\n' + currentEdit.tags,
                  '全部内容'
                )"
              >
                <el-icon><DocumentCopy /></el-icon> 一键复制全部
              </el-button>
            </div>

            <div style="text-align: right;">
              <el-button type="primary" :loading="saving" @click="saveCurrentPlatform">
                保存修改
              </el-button>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </div>

    <!-- Cover prompt editing dialog -->
    <el-dialog
      v-model="coverPromptDialog"
      title="修改封面提示词"
      width="600px"
    >
      <div v-loading="coverPromptLoading">
        <el-input
          v-model="coverPromptText"
          type="textarea"
          :rows="6"
          placeholder="输入封面图片生成提示词（英文效果更佳）"
        />
        <div style="margin-top: 8px; font-size: 12px; color: #909399;">
          "保存"仅保存提示词不生成封面；"保存并生成"会使用新提示词重新生成所有平台封面（消耗额度）。
        </div>
      </div>
      <template #footer>
        <el-button @click="coverPromptDialog = false">取消</el-button>
        <el-button @click="saveCoverPromptOnly">保存</el-button>
        <el-button type="primary" @click="saveCoverPromptAndRegenerate">
          <el-icon><RefreshRight /></el-icon> 保存并生成
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.is-over :deep(.el-input__inner),
.is-over :deep(.el-textarea__inner) {
  border-color: #f56c6c;
}

.segment-thumb:hover {
  border-color: #409eff !important;
}
</style>
