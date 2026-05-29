<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { ResolvedPromptConfig } from '../types/prompt'
import { promptsApi } from '../api/prompts'

const route = useRoute()
const projectId = computed(() => route.params.id as string)

const configs = ref<ResolvedPromptConfig[]>([])
const loading = ref(false)
const activeNames = ref<string[]>([])
const editForms = ref<Record<string, { system_prompt: string; user_prompt_template: string; temperature: number; max_tokens: number }>>({})
const saving = ref<string | null>(null)

const stepLabels: Record<string, string> = {
  article_generation: '文章生成',
  script_generation: '口播稿生成（整篇）',
  segmented_script_generation: '口播稿生成（分段）',
  image_prompt_generation: '图片提示词生成',
  publish_copy: '发布文案生成',
  cover_prompt: '封面提示词生成',
  content_splitting: '内容切分配置',
}

// Steps that don't have AI prompts
const nonPromptSteps = ['content_splitting']

onMounted(async () => {
  await loadConfigs()
})

async function loadConfigs() {
  loading.value = true
  try {
    const { data } = await promptsApi.getProjectConfig(projectId.value)
    configs.value = data
    for (const c of data) {
      editForms.value[c.step_name] = {
        system_prompt: c.system_prompt,
        user_prompt_template: c.user_prompt_template,
        temperature: c.temperature,
        max_tokens: c.max_tokens,
      }
    }
  } finally {
    loading.value = false
  }
}

async function handleSave(stepName: string) {
  saving.value = stepName
  try {
    const form = editForms.value[stepName]
    if (!form) return
    await promptsApi.updateProjectConfig(projectId.value, stepName, {
      system_prompt: form.system_prompt,
      user_prompt_template: form.user_prompt_template,
      temperature: form.temperature,
      max_tokens: form.max_tokens,
    })
    ElMessage.success('已保存项目级覆盖')
    await loadConfigs()
  } catch {
    ElMessage.error('保存失败')
  } finally {
    saving.value = null
  }
}

async function handleRevert(stepName: string) {
  try {
    await ElMessageBox.confirm('确定恢复为系统默认？将删除此步骤的项目级自定义配置。', '恢复默认', { type: 'warning' })
    await promptsApi.deleteProjectConfig(projectId.value, stepName)
    ElMessage.success('已恢复为系统默认')
    await loadConfigs()
  } catch {}
}

function getForm(stepName: string) {
  return editForms.value[stepName]!
}
</script>

<template>
  <div v-loading="loading">
    <div style="margin-bottom: 16px;">
      <el-alert type="info" :closable="false" show-icon>
        <template #title>
          在此页面可以为当前项目自定义各步骤的提示词。未自定义的步骤将使用系统默认模板。
        </template>
      </el-alert>
    </div>

    <el-collapse v-model="activeNames">
      <el-collapse-item v-for="c in configs" :key="c.step_name" :name="c.step_name">
        <template #title>
          <div style="display: flex; align-items: center; gap: 8px;">
            <span>{{ stepLabels[c.step_name] || c.description }}</span>
            <el-tag v-if="c.is_override" type="warning" size="small">已自定义</el-tag>
            <el-tag v-else type="info" size="small">系统默认</el-tag>
          </div>
        </template>
        <div v-if="editForms[c.step_name] && !nonPromptSteps.includes(c.step_name)" style="padding: 0 10px;">
          <div style="margin-bottom: 16px;">
            <div style="margin-bottom: 6px; font-weight: bold; color: #606266;">系统提示词 (System Prompt)</div>
            <el-input v-model="getForm(c.step_name).system_prompt" type="textarea"
              :autosize="{ minRows: 3, maxRows: 10 }" />
          </div>

          <div style="margin-bottom: 16px;">
            <div style="margin-bottom: 6px; font-weight: bold; color: #606266;">
              用户提示词模板 (User Prompt Template)
            </div>
            <div style="margin-bottom: 4px;">
              <el-tag v-for="v in c.variables" :key="v" size="small" type="info" style="margin-right: 4px;">
                {{'{'}}{{ v }}{{'}'}}
                <span v-if="c.variable_descriptions?.[v]" style="color: #909399; margin-left: 4px;">
                  {{ c.variable_descriptions[v] }}
                </span>
              </el-tag>
            </div>
            <el-input v-model="getForm(c.step_name).user_prompt_template" type="textarea"
              :autosize="{ minRows: 6, maxRows: 20 }" />
          </div>

          <el-row :gutter="20" style="margin-bottom: 16px;">
            <el-col :span="12">
              <div style="margin-bottom: 6px; font-weight: bold; color: #606266;">Temperature</div>
              <el-slider v-model="getForm(c.step_name).temperature" :min="0" :max="1" :step="0.1" show-input />
            </el-col>
            <el-col :span="12">
              <div style="margin-bottom: 6px; font-weight: bold; color: #606266;">Max Tokens</div>
              <el-input-number v-model="getForm(c.step_name).max_tokens" :min="512" :max="16384" :step="512" />
            </el-col>
          </el-row>

          <div style="display: flex; gap: 8px;">
            <el-button type="primary" @click="handleSave(c.step_name)" :loading="saving === c.step_name">
              保存为项目配置
            </el-button>
            <el-button v-if="c.is_override" @click="handleRevert(c.step_name)">
              恢复系统默认
            </el-button>
          </div>
        </div>
        <div v-else-if="nonPromptSteps.includes(c.step_name)" style="padding: 0 10px;">
          <el-text type="info">内容切分配置请在系统设置中修改。</el-text>
        </div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>
