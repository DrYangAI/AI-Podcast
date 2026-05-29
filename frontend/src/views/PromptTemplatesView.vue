<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { PromptTemplate, PromptTemplateHistory } from '../types/prompt'
import { promptsApi } from '../api/prompts'

const templates = ref<PromptTemplate[]>([])
const loading = ref(false)
const activeNames = ref<string[]>([])
const editForms = ref<Record<string, { system_prompt: string; user_prompt_template: string; temperature: number; max_tokens: number; extra_config: Record<string, any> | null }>>({})
const historyMap = ref<Record<string, PromptTemplateHistory[]>>({})
const showHistory = ref<Record<string, boolean>>({})
const saving = ref<string | null>(null)

const stepLabels: Record<string, string> = {
  article_generation: '文章生成',
  script_generation: '口播稿生成（整篇）',
  segmented_script_generation: '口播稿生成（分段）',
  image_prompt_generation: '图片提示词生成',
  publish_copy: '发布文案生成',
  cover_prompt: '封面提示词生成',
  content_splitting: '内容切分配置',
  hotlist_filtering: '热榜健康话题筛选',
  psychology_filtering: '热榜心理健康话题筛选',
}

onMounted(async () => {
  await loadTemplates()
})

async function loadTemplates() {
  loading.value = true
  try {
    const { data } = await promptsApi.listTemplates()
    templates.value = data
    for (const t of data) {
      editForms.value[t.step_name] = {
        system_prompt: t.system_prompt,
        user_prompt_template: t.user_prompt_template,
        temperature: t.temperature,
        max_tokens: t.max_tokens,
        extra_config: t.extra_config,
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
    await promptsApi.updateTemplate(stepName, {
      system_prompt: form.system_prompt,
      user_prompt_template: form.user_prompt_template,
      temperature: form.temperature,
      max_tokens: form.max_tokens,
      extra_config: form.extra_config || undefined,
    })
    ElMessage.success('已保存')
    await loadTemplates()
  } catch {
    ElMessage.error('保存失败')
  } finally {
    saving.value = null
  }
}

async function handleReset(stepName: string) {
  try {
    await ElMessageBox.confirm('确定恢复为系统默认模板？当前修改将被保存到版本历史中。', '恢复默认', { type: 'warning' })
    await promptsApi.resetTemplate(stepName)
    ElMessage.success('已恢复默认')
    await loadTemplates()
  } catch {}
}

async function toggleHistory(stepName: string) {
  if (showHistory.value[stepName]) {
    showHistory.value[stepName] = false
    return
  }
  try {
    const { data } = await promptsApi.getHistory(stepName)
    historyMap.value[stepName] = data
    showHistory.value[stepName] = true
  } catch {
    ElMessage.error('加载历史失败')
  }
}

async function restoreVersion(stepName: string, versionId: string) {
  try {
    await ElMessageBox.confirm('确定恢复此历史版本？', '恢复版本', { type: 'warning' })
    await promptsApi.restoreVersion(stepName, versionId)
    ElMessage.success('已恢复')
    showHistory.value[stepName] = false
    await loadTemplates()
  } catch {}
}

function isContentSplitting(stepName: string) {
  return stepName === 'content_splitting'
}

function getForm(stepName: string) {
  return editForms.value[stepName]!
}

function formatDate(dateStr: string) {
  return new Date(dateStr).toLocaleString('zh-CN')
}
</script>

<template>
  <div style="max-width: 1000px; margin: 0 auto;" v-loading="loading">
    <h2 style="margin-bottom: 20px;">提示词模板管理</h2>
    <p style="color: #909399; margin-bottom: 20px;">
      管理各流水线步骤的系统默认提示词模板。修改后将影响所有未设置项目级覆盖的项目。
    </p>

    <el-collapse v-model="activeNames">
      <el-collapse-item v-for="t in templates" :key="t.step_name" :name="t.step_name"
        :title="stepLabels[t.step_name] || t.description">
        <div v-if="editForms[t.step_name]" style="padding: 0 10px;">
          <template v-if="!isContentSplitting(t.step_name)">
            <div style="margin-bottom: 16px;">
              <div style="margin-bottom: 6px; font-weight: bold; color: #606266;">系统提示词 (System Prompt)</div>
              <el-input v-model="getForm(t.step_name).system_prompt" type="textarea"
                :autosize="{ minRows: 3, maxRows: 10 }" />
            </div>

            <div style="margin-bottom: 16px;">
              <div style="margin-bottom: 6px; font-weight: bold; color: #606266;">
                用户提示词模板 (User Prompt Template)
              </div>
              <div style="margin-bottom: 4px;">
                <el-tag v-for="v in t.variables" :key="v" size="small" type="info" style="margin-right: 4px;">
                  {{'{'}}{{ v }}{{'}'}}
                  <span v-if="t.variable_descriptions?.[v]" style="color: #909399; margin-left: 4px;">
                    {{ t.variable_descriptions[v] }}
                  </span>
                </el-tag>
              </div>
              <el-input v-model="getForm(t.step_name).user_prompt_template" type="textarea"
                :autosize="{ minRows: 6, maxRows: 20 }" />
            </div>

            <el-row :gutter="20" style="margin-bottom: 16px;">
              <el-col :span="12">
                <div style="margin-bottom: 6px; font-weight: bold; color: #606266;">Temperature</div>
                <el-slider v-model="getForm(t.step_name).temperature" :min="0" :max="1" :step="0.1" show-input />
              </el-col>
              <el-col :span="12">
                <div style="margin-bottom: 6px; font-weight: bold; color: #606266;">Max Tokens</div>
                <el-input-number v-model="getForm(t.step_name).max_tokens" :min="512" :max="16384" :step="512" />
              </el-col>
            </el-row>
          </template>

          <template v-else>
            <div style="margin-bottom: 16px;">
              <div style="margin-bottom: 6px; font-weight: bold; color: #606266;">切分方法</div>
              <el-input :model-value="getForm(t.step_name).extra_config?.split_method || 'paragraph'" disabled />
            </div>
            <div style="margin-bottom: 16px;">
              <div style="margin-bottom: 6px; font-weight: bold; color: #606266;">最小段落长度（字符）</div>
              <el-input-number
                :model-value="getForm(t.step_name).extra_config?.min_paragraph_length || 10"
                @update:model-value="(v: number) => { const f = getForm(t.step_name); if (!f.extra_config) f.extra_config = {}; f.extra_config!.min_paragraph_length = v }"
                :min="1" :max="100" />
            </div>
          </template>

          <div style="display: flex; gap: 8px; margin-bottom: 12px;">
            <el-button type="primary" @click="handleSave(t.step_name)" :loading="saving === t.step_name">保存</el-button>
            <el-button @click="handleReset(t.step_name)">恢复默认</el-button>
            <el-button text type="info" @click="toggleHistory(t.step_name)">
              {{ showHistory[t.step_name] ? '隐藏历史' : '版本历史' }}
            </el-button>
          </div>

          <!-- Version History -->
          <div v-if="showHistory[t.step_name] && historyMap[t.step_name]?.length">
            <el-table :data="historyMap[t.step_name]" size="small" stripe style="margin-bottom: 12px;">
              <el-table-column prop="version" label="版本" width="70" />
              <el-table-column prop="change_source" label="来源" width="120" />
              <el-table-column label="时间" width="180">
                <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="80">
                <template #default="{ row }">
                  <el-button text size="small" type="primary" @click="restoreVersion(t.step_name, row.id)">恢复</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <div v-else-if="showHistory[t.step_name]">
            <el-empty description="暂无版本历史" :image-size="40" />
          </div>
        </div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>
