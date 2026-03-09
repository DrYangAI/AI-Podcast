<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import type { ProviderConfig, ProviderTypeInfo } from '../types/provider'
import { providersApi } from '../api/providers'

const providers = ref<ProviderConfig[]>([])
const availableTypes = ref<ProviderTypeInfo[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const dialogMode = ref<'add' | 'edit'>('add')
const editingId = ref<string | null>(null)
const testing = ref<string | null>(null)

const form = ref({
  name: '',
  provider_type: 'text',
  provider_key: '',
  api_key: '',
  api_base_url: '',
  model_id: '',
  is_default: false,
  config: {} as Record<string, string>,
})

onMounted(async () => {
  await loadAll()
})

async function loadAll() {
  loading.value = true
  try {
    const [providersRes, typesRes] = await Promise.all([
      providersApi.list(),
      providersApi.listTypes(),
    ])
    providers.value = providersRes.data
    availableTypes.value = typesRes.data
  } finally {
    loading.value = false
  }
}

const filteredTypes = computed(() =>
  availableTypes.value.filter(t => t.provider_type === form.value.provider_type)
)

function openAdd() {
  form.value = { name: '', provider_type: 'text', provider_key: '', api_key: '', api_base_url: '', model_id: '', is_default: false, config: {} }
  dialogMode.value = 'add'
  editingId.value = null
  dialogVisible.value = true
}

function openEdit(row: ProviderConfig) {
  form.value = {
    name: row.name,
    provider_type: row.provider_type,
    provider_key: row.provider_key,
    api_key: '',  // Don't show existing API key for security
    api_base_url: row.api_base_url || '',
    model_id: row.model_id || '',
    is_default: row.is_default,
    config: (row as any).config || {},
  }
  dialogMode.value = 'edit'
  editingId.value = row.id
  dialogVisible.value = true
}

async function handleSave() {
  if (!form.value.name || !form.value.provider_key) {
    ElMessage.warning('请填写名称和提供商')
    return
  }
  try {
    const data = {
      ...form.value,
      config: form.value.config,
    }
    if (dialogMode.value === 'add') {
      await providersApi.create(data)
      ElMessage.success('已添加')
    } else if (editingId.value) {
      // Only send fields that have values (don't send empty api_key for security)
      const updateData: any = {
        name: form.value.name,
        api_base_url: form.value.api_base_url,
        model_id: form.value.model_id,
        is_default: form.value.is_default,
        config: form.value.config,
      }
      // Only include api_key if user entered a new one
      if (form.value.api_key) {
        updateData.api_key = form.value.api_key
      }
      await providersApi.update(editingId.value, updateData)
      ElMessage.success('已更新')
    }
    dialogVisible.value = false
    await loadAll()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function handleTest(id: string) {
  testing.value = id
  try {
    const { data } = await providersApi.test(id)
    if (data.success) {
      ElMessage.success('连接成功')
    } else {
      ElMessage.error(`连接失败: ${data.message}`)
    }
  } catch {
    ElMessage.error('测试失败')
  } finally {
    testing.value = null
  }
}

async function handleDelete(id: string) {
  await providersApi.delete(id)
  ElMessage.success('已删除')
  await loadAll()
}

function getTypeLabel(t: string) {
  return ({ text: '文字生成', image: '图片生成', tts: '语音合成', video: '视频生成' } as any)[t] || t
}
</script>

<template>
  <div style="max-width: 1000px; margin: 0 auto;">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
      <h2 style="margin: 0;">AI 模型配置</h2>
      <el-button type="primary" @click="openAdd">
        <el-icon><Plus /></el-icon> 添加模型
      </el-button>
    </div>

    <el-table :data="providers" v-loading="loading" stripe>
      <el-table-column prop="name" label="名称" width="160" />
      <el-table-column prop="provider_type" label="类型" width="100">
        <template #default="{ row }">{{ getTypeLabel(row.provider_type) }}</template>
      </el-table-column>
      <el-table-column prop="provider_key" label="提供商" width="120" />
      <el-table-column prop="model_id" label="模型" width="180" />
      <el-table-column label="默认" width="70">
        <template #default="{ row }">
          <el-tag v-if="row.is_default" type="success" size="small">是</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220">
        <template #default="{ row }">
          <el-button text size="small" type="primary" @click="openEdit(row)">
            编辑
          </el-button>
          <el-button text size="small" type="primary" :loading="testing === row.id" @click="handleTest(row.id)">
            测试
          </el-button>
          <el-button text size="small" type="danger" @click="handleDelete(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- Add/Edit Dialog -->
    <el-dialog v-model="dialogVisible" :title="dialogMode === 'add' ? '添加 AI 模型' : '编辑 AI 模型'" width="500px">
      <el-form label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="如: Claude Sonnet" />
        </el-form-item>
        <template v-if="dialogMode === 'add'">
          <el-form-item label="类型">
            <el-select v-model="form.provider_type">
              <el-option label="文字生成" value="text" />
              <el-option label="图片生成" value="image" />
              <el-option label="语音合成" value="tts" />
            </el-select>
          </el-form-item>
          <el-form-item label="提供商">
            <el-select v-model="form.provider_key" placeholder="选择提供商">
              <el-option v-for="t in filteredTypes" :key="t.key" :label="t.name" :value="t.key" />
            </el-select>
          </el-form-item>
        </template>
        <template v-else>
          <el-form-item label="类型">
            <el-input :model-value="getTypeLabel(form.provider_type)" disabled />
          </el-form-item>
          <el-form-item label="提供商">
            <el-input :model-value="form.provider_key" disabled />
          </el-form-item>
        </template>
        <el-form-item label="API Key">
          <el-input v-model="form.api_key" type="password" show-password
            :placeholder="dialogMode === 'edit' ? '已保存 (留空则保持不变)' : '输入 API Key'" />
        </el-form-item>
        <el-form-item label="API 地址">
          <el-input v-model="form.api_base_url" placeholder="自定义 API 地址 (可选)" />
        </el-form-item>
        <el-form-item label="模型 ID">
          <el-input v-model="form.model_id" placeholder="如: claude-sonnet-4-20250514" />
        </el-form-item>
        <el-form-item label="endpoint_id" v-if="form.provider_key === 'doubao_seedream'">
          <el-input v-model="form.config.endpoint_id" placeholder="推理接入点 ID (可选)" />
        </el-form-item>
        <el-form-item label="APP ID" v-if="form.provider_key === 'doubao_tts'">
          <el-input v-model="form.config.app_id" placeholder="火山引擎 APP ID" />
        </el-form-item>
        <el-form-item label="资源 ID" v-if="form.provider_key === 'doubao_tts'">
          <el-select v-model="form.config.resource_id" placeholder="选择资源 ID">
            <el-option label="seed-tts-1.0 (语音合成1.0)" value="seed-tts-1.0" />
            <el-option label="seed-tts-2.0 (语音合成2.0)" value="seed-tts-2.0" />
            <el-option label="seed-icl-1.0 (声音复刻1.0)" value="seed-icl-1.0" />
            <el-option label="seed-icl-2.0 (声音复刻2.0)" value="seed-icl-2.0" />
          </el-select>
        </el-form-item>
        <el-form-item label="设为默认">
          <el-switch v-model="form.is_default" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
