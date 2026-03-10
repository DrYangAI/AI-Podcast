<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { projectsApi } from '../api/projects'
import { pipelineApi } from '../api/pipeline'
import { providersApi } from '../api/providers'
import { voicesApi } from '../api/voices'
import { utilsApi } from '../api/utils'
import type { AudioAsset, Project } from '../types/project'
import type { VoiceClone, PresetVoice } from '../types/voice'
import type { ProviderConfig } from '../types/provider'

const route = useRoute()
const projectId = computed(() => route.params.id as string)
const audio = ref<AudioAsset | null>(null)
const project = ref<Project | null>(null)
const loading = ref(false)
const cacheBuster = ref(Date.now())
let pollTimer: ReturnType<typeof setInterval> | null = null

// Voice selection state
const voiceMode = ref<'preset' | 'cloned'>('preset')
const presetVoices = ref<PresetVoice[]>([])
const clonedVoices = ref<VoiceClone[]>([])
const selectedPresetVoiceId = ref<string>('')
const selectedCloneId = ref<string>('')
const ttsProviders = ref<ProviderConfig[]>([])
const voicesLoading = ref(false)

// Clone dialog state
const cloneDialogVisible = ref(false)
const cloneForm = ref({
  name: '',
  speaker_id: '',
  reference_text: '',
  is_default: false,
})
const cloneFile = ref<File | null>(null)
const cloneUploading = ref(false)

// Preview state
const previewing = ref(false)
const previewAudioSrc = ref('')

const audioSrc = computed(() => {
  if (!audio.value?.file_path) return ''
  return '/' + audio.value.file_path + '?t=' + cacheBuster.value
})

function getTrainingStatusTag(status: number) {
  switch (status) {
    case 0: return { type: 'info' as const, text: '未训练' }
    case 1: return { type: 'warning' as const, text: '训练中' }
    case 2: return { type: 'success' as const, text: '训练完成' }
    case 3: return { type: 'danger' as const, text: '训练失败' }
    case 4: return { type: 'success' as const, text: '已激活' }
    default: return { type: 'info' as const, text: '未知' }
  }
}

async function fetchAudio() {
  try {
    const { data } = await projectsApi.getAudio(projectId.value)
    audio.value = data
  } catch {
    // No audio yet
  }
}

async function fetchProject() {
  try {
    const { data } = await projectsApi.get(projectId.value)
    project.value = data
    // Sync voice selection from project
    if (data.tts_voice_clone_id) {
      voiceMode.value = 'cloned'
      selectedCloneId.value = data.tts_voice_clone_id
    } else if (data.tts_voice_id) {
      voiceMode.value = 'preset'
      selectedPresetVoiceId.value = data.tts_voice_id
    }
  } catch {
    // ignore
  }
}

async function loadVoiceOptions() {
  voicesLoading.value = true
  try {
    // Load cloned voices
    const { data: clones } = await voicesApi.list()
    clonedVoices.value = clones

    // Load TTS providers
    const { data: providers } = await providersApi.list('tts')
    ttsProviders.value = providers

    // Load preset voices for the default TTS provider
    const defaultProvider = providers.find(p => p.is_default) || providers[0]
    if (defaultProvider) {
      try {
        const { data: voices } = await providersApi.listVoices(defaultProvider.id)
        presetVoices.value = voices
      } catch {
        presetVoices.value = []
      }
    }

    // If no project voice set but there's a default clone, show it
    if (!selectedCloneId.value && !selectedPresetVoiceId.value) {
      const defaultClone = clones.find(c => c.is_default)
      if (defaultClone) {
        voiceMode.value = 'cloned'
        selectedCloneId.value = defaultClone.id
      }
    }
  } catch {
    // non-critical
  } finally {
    voicesLoading.value = false
  }
}

onMounted(async () => {
  await Promise.all([fetchAudio(), fetchProject()])
  await loadVoiceOptions()
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

async function saveVoiceSelection() {
  try {
    if (voiceMode.value === 'cloned' && selectedCloneId.value) {
      await projectsApi.update(projectId.value, {
        tts_voice_clone_id: selectedCloneId.value,
        tts_voice_id: null,
      } as any)
    } else if (voiceMode.value === 'preset' && selectedPresetVoiceId.value) {
      await projectsApi.update(projectId.value, {
        tts_voice_id: selectedPresetVoiceId.value,
        tts_voice_clone_id: null,
      } as any)
    }
    ElMessage.success('声音设置已保存')
  } catch {
    ElMessage.error('保存声音设置失败')
  }
}

async function handleGenerateTTS() {
  // Save voice selection first
  await saveVoiceSelection()

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

// Clone voice handlers
function openCloneDialog() {
  cloneForm.value = { name: '', speaker_id: '', reference_text: '', is_default: false }
  cloneFile.value = null
  cloneDialogVisible.value = true
}

function handleCloneFileChange(file: any) {
  cloneFile.value = file.raw
}

async function handleCreateClone() {
  if (!cloneForm.value.name.trim()) {
    ElMessage.warning('请输入声音名称')
    return
  }
  if (!cloneForm.value.speaker_id.trim()) {
    ElMessage.warning('请输入火山引擎音色 ID (speaker_id)')
    return
  }
  if (!cloneFile.value) {
    ElMessage.warning('请上传参考音频文件')
    return
  }

  cloneUploading.value = true
  try {
    const formData = new FormData()
    formData.append('name', cloneForm.value.name.trim())
    formData.append('speaker_id', cloneForm.value.speaker_id.trim())
    formData.append('provider_key', 'doubao_tts')
    formData.append('audio_file', cloneFile.value)
    if (cloneForm.value.reference_text.trim()) {
      formData.append('reference_text', cloneForm.value.reference_text.trim())
    }
    formData.append('is_default', String(cloneForm.value.is_default))

    const { data } = await voicesApi.clone(formData)
    const statusInfo = getTrainingStatusTag(data.training_status)
    ElMessage.success(`声音 "${data.name}" 训练已提交（${statusInfo.text}）`)
    cloneDialogVisible.value = false

    // Reload voices and select the new one
    await loadVoiceOptions()
    voiceMode.value = 'cloned'
    selectedCloneId.value = data.id
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '创建克隆声音失败')
  } finally {
    cloneUploading.value = false
  }
}

async function handleRefreshStatus(cloneId: string) {
  try {
    const { data } = await voicesApi.refreshStatus(cloneId)
    // Update local state
    const idx = clonedVoices.value.findIndex(v => v.id === cloneId)
    if (idx >= 0) {
      clonedVoices.value[idx] = data
    }
    const statusInfo = getTrainingStatusTag(data.training_status)
    ElMessage.info(`训练状态: ${statusInfo.text}`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '刷新状态失败')
  }
}

async function handlePreviewClone(cloneId: string) {
  const clone = clonedVoices.value.find(v => v.id === cloneId)
  if (clone && clone.training_status !== 2 && clone.training_status !== 4) {
    ElMessage.warning('声音尚未训练完成，请先刷新状态确认训练已完成')
    return
  }

  previewing.value = true
  previewAudioSrc.value = ''
  try {
    const { data } = await voicesApi.preview(cloneId)
    previewAudioSrc.value = '/' + data.audio_path + '?t=' + Date.now()
    ElMessage.success('预览音频已生成')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '预览失败')
  } finally {
    previewing.value = false
  }
}

async function handleSetDefault(cloneId: string) {
  try {
    await voicesApi.update(cloneId, { is_default: true })
    await loadVoiceOptions()
    ElMessage.success('已设为默认声音')
  } catch {
    ElMessage.error('设置默认声音失败')
  }
}

async function handleDeleteClone(cloneId: string) {
  try {
    await voicesApi.delete(cloneId)
    if (selectedCloneId.value === cloneId) {
      selectedCloneId.value = ''
    }
    await loadVoiceOptions()
    ElMessage.success('已删除')
  } catch {
    ElMessage.error('删除失败')
  }
}

function formatDuration(seconds: number | null) {
  if (!seconds) return '--'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function getVoiceGenderLabel(gender: string | null) {
  if (gender === 'female') return '女'
  if (gender === 'male') return '男'
  return ''
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

    <!-- 声音设置 -->
    <el-card style="margin-bottom: 16px;">
      <template #header>
        <span style="font-weight: 500;">声音设置</span>
      </template>

      <el-radio-group v-model="voiceMode" style="margin-bottom: 16px;">
        <el-radio-button value="preset">预置声音</el-radio-button>
        <el-radio-button value="cloned">克隆声音</el-radio-button>
      </el-radio-group>

      <!-- 预置声音模式 -->
      <div v-if="voiceMode === 'preset'">
        <el-select
          v-model="selectedPresetVoiceId"
          placeholder="选择预置声音"
          style="width: 100%;"
          :loading="voicesLoading"
          filterable
        >
          <el-option
            v-for="v in presetVoices"
            :key="v.id"
            :label="`${v.name}${v.gender ? ' (' + getVoiceGenderLabel(v.gender) + ')' : ''}`"
            :value="v.id"
          />
        </el-select>
        <el-text v-if="presetVoices.length === 0 && !voicesLoading" type="info" size="small" style="margin-top: 8px; display: block;">
          未找到预置声音。请先在"AI 模型配置"中添加 TTS 提供商。
        </el-text>
      </div>

      <!-- 克隆声音模式 -->
      <div v-if="voiceMode === 'cloned'">
        <div style="display: flex; gap: 8px; align-items: center;">
          <el-select
            v-model="selectedCloneId"
            placeholder="选择克隆声音"
            style="flex: 1;"
            :loading="voicesLoading"
          >
            <el-option
              v-for="v in clonedVoices"
              :key="v.id"
              :value="v.id"
            >
              <span>{{ v.name }}{{ v.is_default ? ' ⭐默认' : '' }}</span>
              <el-tag :type="getTrainingStatusTag(v.training_status).type" size="small" style="margin-left: 8px;">
                {{ getTrainingStatusTag(v.training_status).text }}
              </el-tag>
            </el-option>
          </el-select>
          <el-button @click="openCloneDialog" type="primary" plain size="default">
            <el-icon><Plus /></el-icon> 添加
          </el-button>
        </div>

        <!-- 克隆声音操作 -->
        <div v-if="selectedCloneId" style="margin-top: 12px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
          <el-button
            size="small"
            @click="handleRefreshStatus(selectedCloneId)"
          >
            <el-icon><Refresh /></el-icon> 刷新状态
          </el-button>
          <el-button
            size="small"
            :loading="previewing"
            @click="handlePreviewClone(selectedCloneId)"
            :disabled="(() => { const c = clonedVoices.find(v => v.id === selectedCloneId); return c ? (c.training_status !== 2 && c.training_status !== 4) : true })()"
          >
            <el-icon><VideoPlay /></el-icon> 试听预览
          </el-button>
          <el-button
            size="small"
            @click="handleSetDefault(selectedCloneId)"
            :disabled="clonedVoices.find(v => v.id === selectedCloneId)?.is_default"
          >
            设为默认
          </el-button>
          <el-popconfirm title="确定删除此克隆声音？" @confirm="handleDeleteClone(selectedCloneId)">
            <template #reference>
              <el-button size="small" type="danger" text>删除</el-button>
            </template>
          </el-popconfirm>
        </div>

        <!-- 预览播放器 -->
        <div v-if="previewAudioSrc" style="margin-top: 12px;">
          <el-text size="small" type="info">预览音频：</el-text>
          <audio controls style="width: 100%; margin-top: 4px;" :src="previewAudioSrc"></audio>
        </div>

        <el-empty v-if="clonedVoices.length === 0 && !voicesLoading" :image-size="60" description="暂无克隆声音">
          <el-button type="primary" @click="openCloneDialog">
            <el-icon><Plus /></el-icon> 添加克隆声音
          </el-button>
        </el-empty>
      </div>
    </el-card>

    <!-- 音频信息 -->
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

    <!-- 添加克隆声音对话框 -->
    <el-dialog v-model="cloneDialogVisible" title="添加克隆声音" width="520px">
      <el-form label-width="110px">
        <el-form-item label="声音名称" required>
          <el-input v-model="cloneForm.name" placeholder="如：张老师的声音" />
        </el-form-item>
        <el-form-item label="音色 ID" required>
          <el-input v-model="cloneForm.speaker_id" placeholder="如：S_xxxxxxx（从火山引擎控制台获取）" />
          <el-text size="small" type="info" style="margin-top: 4px; display: block;">
            需要在火山引擎控制台购买声音复刻服务后获取 speaker_id
          </el-text>
        </el-form-item>
        <el-form-item label="参考音频" required>
          <el-upload
            :auto-upload="false"
            :limit="1"
            accept=".mp3,.wav,.ogg,.flac,.m4a,.aac,.pcm"
            :on-change="handleCloneFileChange"
          >
            <el-button type="primary" plain>
              <el-icon><Upload /></el-icon> 选择音频文件
            </el-button>
            <template #tip>
              <div class="el-upload__tip">支持 mp3/wav/ogg/flac/m4a 格式，建议 10~15 秒清晰单人语音</div>
            </template>
          </el-upload>
        </el-form-item>
        <el-form-item label="参考文本">
          <el-input
            v-model="cloneForm.reference_text"
            type="textarea"
            :rows="3"
            placeholder="（可选）参考音频中说的文字内容，填写后可提升克隆质量"
          />
        </el-form-item>
        <el-form-item label="设为默认">
          <el-switch v-model="cloneForm.is_default" />
          <el-text size="small" type="info" style="margin-left: 8px;">新项目将自动使用此声音</el-text>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="cloneDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleCreateClone" :loading="cloneUploading">
          提交训练
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>
