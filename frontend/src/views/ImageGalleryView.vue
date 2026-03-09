<script setup lang="ts">
import { onMounted, computed, ref, reactive } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useProjectStore } from '../stores/project'
import { pipelineApi } from '../api/pipeline'
import { projectsApi } from '../api/projects'
import { utilsApi } from '../api/utils'

const route = useRoute()
const store = useProjectStore()
const projectId = computed(() => route.params.id as string)
const generating = ref<string | null>(null)
const settingsVisible = ref(false)

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
  { label: '1024 × 1024', width: 1024, height: 1024 },
  { label: '1920 × 1080', width: 1920, height: 1080 },
  { label: '1080 × 1920', width: 1080, height: 1920 },
  { label: '2560 × 1440', width: 2560, height: 1440 },
  { label: '1440 × 2560', width: 1440, height: 2560 },
  { label: '1920 × 1920', width: 1920, height: 1920 },
]

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
})

function getImageForSegment(segmentId: string) {
  return store.images.find(img => img.segment_id === segmentId)
}

async function handleGenerateAll() {
  try {
    await pipelineApi.runStep(projectId.value, 'image_generation')
    ElMessage.success('图片生成已启动')
    store.startPolling(projectId.value)
  } catch {
    ElMessage.error('启动失败')
  }
}

async function handleRegenerateOne(segmentId: string, customPrompt?: string) {
  generating.value = segmentId
  try {
    await projectsApi.regenerateSegmentImage(projectId.value, segmentId, customPrompt)
    ElMessage.success('图片重新生成已启动')
    store.startPolling(projectId.value)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '生成失败')
  } finally {
    generating.value = null
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

async function saveSettings() {
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
          <div v-if="getImageForSegment(segment.id)" style="text-align: center;">
            <el-image
              v-if="getImageForSegment(segment.id)?.status === 'completed'"
              :src="'/' + getImageForSegment(segment.id)?.file_path"
              :preview-src-list="['/' + getImageForSegment(segment.id)?.file_path]"
              fit="cover"
              style="width: 100%; height: 150px; border-radius: 4px; margin-bottom: 8px;"
            />
            <div v-else-if="getImageForSegment(segment.id)?.status === 'generating'" style="height: 150px; display: flex; align-items: center; justify-content: center;">
              <el-icon class="is-loading" :size="32" style="color: #e6a23c;"><Loading /></el-icon>
            </div>
            <el-tag v-if="getImageForSegment(segment.id)?.status === 'completed'" type="success" size="small">
              已生成
            </el-tag>
            <el-tag v-else-if="getImageForSegment(segment.id)?.status === 'generating'" type="warning" size="small">
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
              :loading="generating === segment.id"
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
          <el-text size="small" style="display: block; margin-top: 8px;" :line-clamp="2">
            {{ segment.content.substring(0, 60) }}...
          </el-text>
          <el-text v-if="segment.image_prompt || getImageForSegment(segment.id)?.prompt_used" type="info" size="small" style="display: block; margin-top: 4px;">
            Prompt: {{ (segment.image_prompt || getImageForSegment(segment.id)?.prompt_used)?.substring(0, 80) }}...
          </el-text>
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
          <div style="font-size: 12px; color: #909399; margin-top: 4px;">
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
