<script setup lang="ts">
import { onMounted, onUnmounted, computed, ref, reactive } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useProjectStore } from '../stores/project'
import { pipelineApi } from '../api/pipeline'
import { projectsApi } from '../api/projects'
import { utilsApi } from '../api/utils'

const route = useRoute()
const store = useProjectStore()
const projectId = computed(() => route.params.id as string)
const generatingSet = ref<Set<string>>(new Set())
const settingsVisible = ref(false)
const generatingPrompts = ref(false)
let imagePollingTimer: ReturnType<typeof setInterval> | null = null

// Per-image prompt editing
const editingPrompt = ref<{ segmentId: string; prompt: string } | null>(null)

const imageSettings = reactive({
  image_width: null as number | null,
  image_height: null as number | null,
  image_quality: 'standard',
  image_style: 'natural',
  image_negative_prompt: '',
})

const resolutionPresets = [
  { label: '跟随宽高比（默认）', width: null, height: null },
  { label: '2560 × 1440（16:9）', width: 2560, height: 1440 },
  { label: '1440 × 2560（9:16）', width: 1440, height: 2560 },
  { label: '1920 × 1920（1:1）', width: 1920, height: 1920 },
]

const MIN_PIXELS = 3686400  // 豆包 Seedream 最低像素要求

const pixelCount = computed(() => {
  const w = imageSettings.image_width
  const h = imageSettings.image_height
  if (!w || !h) return null
  return w * h
})

const pixelWarning = computed(() => {
  if (pixelCount.value === null) return ''
  if (pixelCount.value < MIN_PIXELS) {
    return `当前 ${(pixelCount.value / 10000).toFixed(0)} 万像素，低于豆包 Seedream 最低要求 ${(MIN_PIXELS / 10000).toFixed(0)} 万像素，生成将失败`
  }
  return ''
})

const currentPreset = computed(() => {
  const w = imageSettings.image_width
  const h = imageSettings.image_height
  if (!w || !h) return '跟随宽高比（默认）'
  const found = resolutionPresets.find(p => p.width === w && p.height === h)
  return found ? found.label : '自定义'
})

onMounted(async () => {
  await Promise.all([
    store.loadProject(projectId.value),
    store.loadSegments(projectId.value),
    store.loadImages(projectId.value),
  ])
  // Load current settings from project
  if (store.currentProject) {
    imageSettings.image_width = store.currentProject.image_width ?? null
    imageSettings.image_height = store.currentProject.image_height ?? null
    imageSettings.image_quality = store.currentProject.image_quality || 'standard'
    imageSettings.image_style = store.currentProject.image_style || 'natural'
    imageSettings.image_negative_prompt = store.currentProject.image_negative_prompt || ''
  }
  // Resume polling if any images are in "generating" state
  const hasGenerating = store.images.some(img => img.status === 'generating')
  if (hasGenerating) {
    store.images.filter(img => img.status === 'generating').forEach(img => {
      generatingSet.value.add(img.segment_id)
    })
    startImagePolling()
  }
})

onUnmounted(() => {
  stopImagePolling()
})

function startImagePolling() {
  if (imagePollingTimer) return
  imagePollingTimer = setInterval(async () => {
    await store.loadImages(projectId.value)
    // Check each tracked segment
    const finished: string[] = []
    for (const segId of generatingSet.value) {
      const img = store.images.find(i => i.segment_id === segId)
      if (!img || img.status === 'completed') {
        finished.push(segId)
        const seg = store.segments.find(s => s.id === segId)
        const label = seg ? `段落 ${seg.segment_order + 1}` : ''
        ElMessage.success(`${label} 图片生成完成`)
      } else if (img.status === 'failed') {
        finished.push(segId)
        const seg = store.segments.find(s => s.id === segId)
        const label = seg ? `段落 ${seg.segment_order + 1}` : ''
        ElMessage.error(`${label} 图片生成失败`)
      }
    }
    finished.forEach(id => generatingSet.value.delete(id))
    if (generatingSet.value.size === 0) {
      stopImagePolling()
    }
  }, 3000)
}

function stopImagePolling() {
  if (imagePollingTimer) {
    clearInterval(imagePollingTimer)
    imagePollingTimer = null
  }
}

function getImageForSegment(segmentId: string) {
  return store.images.find(img => img.segment_id === segmentId)
}

async function handleGeneratePrompts() {
  generatingPrompts.value = true
  try {
    await projectsApi.generatePrompts(projectId.value)
    await store.loadSegments(projectId.value)
    ElMessage.success('提示词已生成，请检查后再生成图片')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '提示词生成失败')
  } finally {
    generatingPrompts.value = false
  }
}

async function handleGenerateAll() {
  try {
    await pipelineApi.runStep(projectId.value, 'image_generation')
    ElMessage.success('全部图片生成已启动')
    // Track all segments as generating
    store.segments.forEach(s => generatingSet.value.add(s.id))
    startImagePolling()
    store.startPolling(projectId.value)
  } catch {
    ElMessage.error('启动失败')
  }
}

async function handleRegenerateOne(segmentId: string, customPrompt?: string) {
  generatingSet.value.add(segmentId)
  try {
    await projectsApi.regenerateSegmentImage(projectId.value, segmentId, customPrompt)
    const seg = store.segments.find(s => s.id === segmentId)
    const label = seg ? `段落 ${seg.segment_order + 1}` : ''
    ElMessage.info(`${label} 图片生成中...`)
    startImagePolling()
  } catch (e: any) {
    generatingSet.value.delete(segmentId)
    ElMessage.error(e?.response?.data?.detail || '生成失败')
  }
}

function openPromptEditor(segmentId: string) {
  const segment = store.segments.find(s => s.id === segmentId)
  const image = getImageForSegment(segmentId)
  editingPrompt.value = {
    segmentId,
    prompt: segment?.image_prompt || image?.prompt_used || '',
  }
}

async function savePromptOnly() {
  if (!editingPrompt.value) return
  const { segmentId, prompt } = editingPrompt.value
  try {
    await projectsApi.updateSegment(projectId.value, segmentId, { image_prompt: prompt })
    ElMessage.success('提示词已保存')
    editingPrompt.value = null
    await store.loadSegments(projectId.value)
  } catch {
    ElMessage.error('保存失败')
  }
}

async function submitPromptAndRegenerate() {
  if (!editingPrompt.value) return
  const { segmentId, prompt } = editingPrompt.value
  editingPrompt.value = null
  await handleRegenerateOne(segmentId, prompt)
}

async function handleUploadImage(segmentId: string, file: File) {
  try {
    await projectsApi.uploadSegmentImage(projectId.value, segmentId, file)
    ElMessage.success('图片上传成功')
    await store.loadImages(projectId.value)
  } catch {
    ElMessage.error('上传失败')
  }
}

function beforeUpload(file: File) {
  const allowed = ['image/png', 'image/jpeg', 'image/webp', 'image/gif']
  if (!allowed.includes(file.type)) {
    ElMessage.error('仅支持 PNG、JPG、WebP、GIF 格式')
    return false
  }
  if (file.size > 20 * 1024 * 1024) {
    ElMessage.error('文件大小不能超过 20MB')
    return false
  }
  return true
}

function applyPreset(preset: typeof resolutionPresets[0]) {
  imageSettings.image_width = preset.width
  imageSettings.image_height = preset.height
}

async function doSaveSettings() {
  try {
    await projectsApi.update(projectId.value, {
      image_width: imageSettings.image_width,
      image_height: imageSettings.image_height,
      image_quality: imageSettings.image_quality,
      image_style: imageSettings.image_style,
      image_negative_prompt: imageSettings.image_negative_prompt || null,
    } as any)
    ElMessage.success('参数已保存')
    settingsVisible.value = false
    await store.loadProject(projectId.value)
  } catch {
    ElMessage.error('保存失败')
  }
}

async function saveSettings() {
  if (pixelWarning.value) {
    try {
      await ElMessageBox.confirm(
        pixelWarning.value + '。确定要保存吗？',
        '分辨率警告',
        { confirmButtonText: '仍然保存', cancelButtonText: '取消', type: 'warning' }
      )
      await doSaveSettings()
    } catch {
      // User cancelled
    }
  } else {
    await doSaveSettings()
  }
}
</script>

<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <h3 style="margin: 0;">图片画廊 ({{ store.images.length }} 张)</h3>
      <div>
        <el-button @click="settingsVisible = true" size="small">
          <el-icon><Setting /></el-icon> 参数设置
        </el-button>
        <el-button v-if="store.images.length > 0" @click="utilsApi.openFolder(store.images[0].file_path)" size="small">
          <el-icon><FolderOpened /></el-icon> 打开目录
        </el-button>
        <el-button @click="handleGeneratePrompts" :loading="generatingPrompts">
          <el-icon><MagicStick /></el-icon> {{ store.segments.some(s => s.image_prompt) ? '重新生成提示词' : '生成提示词' }}
        </el-button>
        <el-button type="primary" @click="handleGenerateAll">
          <el-icon><PictureFilled /></el-icon> {{ store.images.length > 0 ? '重新生成全部图片' : '生成全部图片' }}
        </el-button>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :span="8" v-for="segment in store.segments" :key="segment.id">
        <el-card shadow="hover" style="margin-bottom: 16px;">
          <template #header>
            <span>段落 {{ segment.segment_order + 1 }}</span>
          </template>
          <div v-if="getImageForSegment(segment.id) || generatingSet.has(segment.id)" style="text-align: center;">
            <el-image
              v-if="getImageForSegment(segment.id)?.status === 'completed' && !generatingSet.has(segment.id)"
              :src="'/' + getImageForSegment(segment.id)?.file_path"
              :preview-src-list="['/' + getImageForSegment(segment.id)?.file_path]"
              fit="cover"
              style="width: 100%; height: 150px; border-radius: 4px; margin-bottom: 8px;"
            />
            <div v-else-if="generatingSet.has(segment.id) || getImageForSegment(segment.id)?.status === 'generating'" style="height: 150px; display: flex; flex-direction: column; align-items: center; justify-content: center;">
              <el-icon class="is-loading" :size="32" style="color: #e6a23c;"><Loading /></el-icon>
              <span style="font-size: 12px; color: #909399; margin-top: 8px;">AI 生成中，请稍候...</span>
            </div>
            <el-tag v-if="getImageForSegment(segment.id)?.status === 'completed' && !generatingSet.has(segment.id)" type="success" size="small">
              已生成
            </el-tag>
            <el-tag v-else-if="generatingSet.has(segment.id) || getImageForSegment(segment.id)?.status === 'generating'" type="warning" size="small">
              生成中
            </el-tag>
            <el-tag v-else type="danger" size="small">失败</el-tag>
          </div>
          <div v-else style="text-align: center; padding: 20px;">
            <el-upload
              :show-file-list="false"
              :before-upload="(f: any) => beforeUpload(f)"
              :http-request="(opt: any) => handleUploadImage(segment.id, opt.file)"
              accept="image/*"
            >
              <el-icon :size="48" style="color: #dcdfe6; cursor: pointer;"><Upload /></el-icon>
              <p style="color: #909399; font-size: 12px;">点击上传或 AI 生成</p>
            </el-upload>
          </div>

          <!-- Action buttons -->
          <div style="display: flex; justify-content: center; gap: 4px; margin-top: 8px; flex-wrap: wrap;">
            <el-button
              text type="primary" size="small"
              :loading="generatingSet.has(segment.id)"
              @click="handleRegenerateOne(segment.id)"
            >
              <el-icon><RefreshRight /></el-icon> 重新生成
            </el-button>
            <el-button
              text type="warning" size="small"
              @click="openPromptEditor(segment.id)"
            >
              <el-icon><EditPen /></el-icon> 修改提示词
            </el-button>
            <el-upload
              :show-file-list="false"
              :before-upload="(f: any) => beforeUpload(f)"
              :http-request="(opt: any) => handleUploadImage(segment.id, opt.file)"
              accept="image/*"
              style="display: inline-block;"
            >
              <el-button text size="small" type="info">
                <el-icon><Upload /></el-icon> 替换
              </el-button>
            </el-upload>
          </div>

          <!-- Content preview -->
          <el-text size="small" style="display: block; margin-top: 8px; color: #606266;" :line-clamp="2">
            {{ segment.content.substring(0, 60) }}...
          </el-text>
          <div v-if="segment.image_prompt || getImageForSegment(segment.id)?.prompt_used"
            style="margin-top: 6px; padding: 6px 8px; background: #f0f9eb; border-radius: 4px; border-left: 3px solid #67c23a;">
            <el-text size="small" style="display: block; color: #67c23a; font-weight: 500; margin-bottom: 2px;">
              提示词
            </el-text>
            <el-text size="small" style="display: block; color: #606266;" :line-clamp="3">
              {{ segment.image_prompt || getImageForSegment(segment.id)?.prompt_used }}
            </el-text>
          </div>
          <div v-else style="margin-top: 6px; padding: 6px 8px; background: #fdf6ec; border-radius: 4px; border-left: 3px solid #e6a23c;">
            <el-text size="small" style="color: #e6a23c;">
              暂无提示词，点击上方"生成提示词"按钮
            </el-text>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-empty v-if="store.segments.length === 0" description="暂无段落，请先拆分文章" />

    <!-- Prompt editing dialog -->
    <el-dialog
      v-model="editingPrompt"
      title="修改图片提示词"
      width="600px"
      :before-close="() => editingPrompt = null"
    >
      <template v-if="editingPrompt">
        <el-input
          v-model="editingPrompt.prompt"
          type="textarea"
          :rows="6"
          placeholder="输入图片生成提示词，修改后点击'生成'将使用新提示词重新生成该图片"
        />
        <div style="margin-top: 8px; font-size: 12px; color: #909399;">
          "保存"仅保存提示词不生成图片；"保存并生成"会使用新提示词重新生成图片（消耗额度）。
        </div>
      </template>
      <template #footer>
        <el-button @click="editingPrompt = null">取消</el-button>
        <el-button @click="savePromptOnly">保存</el-button>
        <el-button type="primary" @click="submitPromptAndRegenerate">
          <el-icon><RefreshRight /></el-icon> 保存并生成
        </el-button>
      </template>
    </el-dialog>

    <!-- Settings dialog -->
    <el-dialog v-model="settingsVisible" title="图片生成参数" width="520px">
      <el-form label-width="100px" label-position="left">
        <el-form-item label="分辨率预设">
          <el-select :model-value="currentPreset" placeholder="选择预设" style="width: 100%;">
            <el-option
              v-for="preset in resolutionPresets"
              :key="preset.label"
              :label="preset.label"
              :value="preset.label"
              @click="applyPreset(preset)"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="自定义分辨率">
          <div style="display: flex; align-items: center; gap: 8px;">
            <el-input-number
              v-model="imageSettings.image_width"
              :min="256"
              :max="4096"
              :step="64"
              placeholder="宽度"
              style="flex: 1;"
            />
            <span>×</span>
            <el-input-number
              v-model="imageSettings.image_height"
              :min="256"
              :max="4096"
              :step="64"
              placeholder="高度"
              style="flex: 1;"
            />
          </div>
          <div v-if="pixelWarning" style="font-size: 12px; color: #f56c6c; margin-top: 4px;">
            {{ pixelWarning }}
          </div>
          <div v-else-if="pixelCount" style="font-size: 12px; color: #67c23a; margin-top: 4px;">
            当前 {{ (pixelCount / 10000).toFixed(0) }} 万像素 ✓
          </div>
          <div v-else style="font-size: 12px; color: #909399; margin-top: 4px;">
            留空则根据项目宽高比自动计算
          </div>
        </el-form-item>
        <el-form-item label="质量">
          <el-select v-model="imageSettings.image_quality" style="width: 100%;">
            <el-option label="标准 (standard)" value="standard" />
            <el-option label="高清 (hd)" value="hd" />
          </el-select>
        </el-form-item>
        <el-form-item label="风格">
          <el-select v-model="imageSettings.image_style" style="width: 100%;">
            <el-option label="自然 (natural)" value="natural" />
            <el-option label="生动 (vivid)" value="vivid" />
          </el-select>
        </el-form-item>
        <el-form-item label="负向提示词">
          <el-input
            v-model="imageSettings.image_negative_prompt"
            type="textarea"
            :rows="3"
            placeholder="描述不希望出现在图片中的内容（部分模型支持）"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="settingsVisible = false">取消</el-button>
        <el-button type="primary" @click="saveSettings">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
