<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useProjectStore } from '../stores/project'
import { pipelineApi } from '../api/pipeline'
import { providersApi } from '../api/providers'
import type { ProviderConfig } from '../types/provider'

const route = useRoute()
const router = useRouter()
const store = useProjectStore()

const projectId = computed(() => route.params.id as string)
const providers = ref<ProviderConfig[]>([])
const selectedProviders = ref<Record<string, string>>({})

const stepLabels: Record<string, string> = {
  topic_input: '话题输入',
  article_generation: '文章生成',
  content_splitting: '内容拆分',
  image_generation: '图片生成',
  script_generation: '口播稿生成',
  tts_audio: '语音合成',
  video_composition: '视频合成',
}

const stepRoutes: Record<string, string> = {
  article_generation: 'project-article',
  content_splitting: 'project-segments',
  image_generation: 'project-images',
  script_generation: 'project-script',
  tts_audio: 'project-audio',
  video_composition: 'project-video',
}

const stepProviderType: Record<string, string> = {
  article_generation: 'text',
  image_generation: 'image',
  script_generation: 'text',
  tts_audio: 'tts',
}

function getStepColor(status: string) {
  switch (status) {
    case 'completed': return '#67c23a'
    case 'in_progress': return '#e6a23c'
    case 'failed': return '#f56c6c'
    default: return '#c0c4cc'
  }
}

function getProvidersForStep(stepName: string): ProviderConfig[] {
  const type = stepProviderType[stepName]
  if (!type) return []
  return providers.value.filter(p => p.provider_type === type)
}

onMounted(async () => {
  try {
    const { data } = await providersApi.list()
    providers.value = data
  } catch {
    // non-critical
  }
})

async function runAll() {
  try {
    const overrides = buildOverrides()
    await pipelineApi.runPipeline(projectId.value, undefined, overrides)
    ElMessage.success('流水线已启动')
    store.startPolling(projectId.value)
  } catch {
    ElMessage.error('启动失败')
  }
}

async function runStep(stepName: string) {
  try {
    const overrides = buildOverrides()
    if (Object.keys(overrides).length > 0) {
      await pipelineApi.runPipeline(projectId.value, stepName, overrides)
    } else {
      await pipelineApi.runStep(projectId.value, stepName)
    }
    ElMessage.success(`步骤 "${stepLabels[stepName]}" 已启动`)
    store.startPolling(projectId.value)
  } catch {
    ElMessage.error('启动失败')
  }
}

async function retryStep(stepName: string) {
  try {
    await pipelineApi.retryStep(projectId.value, stepName)
    ElMessage.success('正在重试')
    store.startPolling(projectId.value)
  } catch {
    ElMessage.error('重试失败')
  }
}

function goToStep(stepName: string) {
  const routeName = stepRoutes[stepName]
  if (routeName) {
    router.push({ name: routeName, params: { id: projectId.value } })
  }
}

function buildOverrides(): Record<string, string> {
  const overrides: Record<string, string> = {}
  for (const [stepName, providerId] of Object.entries(selectedProviders.value)) {
    const providerType = stepProviderType[stepName]
    if (providerType && providerId) {
      overrides[providerType] = providerId
    }
  }
  return overrides
}
</script>

<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px;">
      <h3 style="margin: 0;">生产流水线</h3>
      <el-button type="primary" @click="runAll">
        <el-icon><VideoPlay /></el-icon> 运行全部
      </el-button>
    </div>

    <el-timeline>
      <el-timeline-item
        v-for="step in store.pipelineSteps"
        :key="step.id"
        :color="getStepColor(step.status)"
        :hollow="step.status === 'pending'"
        size="large"
      >
        <el-card shadow="hover" class="step-card">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <div style="flex: 1;">
              <strong>{{ stepLabels[step.step_name] || step.step_name }}</strong>
              <el-tag
                :type="step.status === 'completed' ? 'success' : step.status === 'failed' ? 'danger' : step.status === 'in_progress' ? 'warning' : 'info'"
                size="small" style="margin-left: 8px;"
              >
                {{ step.status === 'completed' ? '已完成' : step.status === 'in_progress' ? '进行中' : step.status === 'failed' ? '失败' : '待执行' }}
              </el-tag>
              <div v-if="step.error_message" style="margin-top: 4px;">
                <el-text type="danger" size="small">{{ step.error_message }}</el-text>
              </div>
            </div>
            <div style="display: flex; align-items: center; gap: 8px;">
              <el-select
                v-if="getProvidersForStep(step.step_name).length > 0"
                v-model="selectedProviders[step.step_name]"
                placeholder="默认 Provider"
                size="small"
                clearable
                style="width: 160px;"
              >
                <el-option
                  v-for="p in getProvidersForStep(step.step_name)"
                  :key="p.id"
                  :label="`${p.name} (${p.model_id || p.provider_key})`"
                  :value="p.id"
                />
              </el-select>

              <el-button v-if="step.status === 'completed' && stepRoutes[step.step_name]"
                text size="small" @click="goToStep(step.step_name)">
                <el-icon><View /></el-icon> 查看
              </el-button>
              <el-button v-if="step.status === 'completed' && step.step_name !== 'topic_input'"
                text type="primary" size="small" @click="runStep(step.step_name)">
                <el-icon><RefreshRight /></el-icon> 重新运行
              </el-button>
              <el-button v-if="step.status === 'pending' && step.step_name !== 'topic_input'"
                text type="primary" size="small" @click="runStep(step.step_name)">
                <el-icon><VideoPlay /></el-icon> 运行
              </el-button>
              <el-button v-if="step.status === 'failed'"
                text type="warning" size="small" @click="retryStep(step.step_name)">
                <el-icon><RefreshRight /></el-icon> 重试
              </el-button>
            </div>
          </div>
        </el-card>
      </el-timeline-item>
    </el-timeline>
  </div>
</template>

<style scoped>
.step-card { margin-bottom: 4px; }
</style>
