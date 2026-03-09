<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { sourcesApi } from '../api/sources'
import type { ContentSource, FetchedTopic } from '../types/source'

const router = useRouter()
const sources = ref<ContentSource[]>([])
const topics = ref<FetchedTopic[]>([])
const activeSourceId = ref<string | null>(null)
const loading = ref(false)
const fetchingId = ref<string | null>(null)

// Add source dialog
const addDialogVisible = ref(false)
const addForm = ref({
  name: '',
  source_type: 'rss',
  url: '',
  category: '',
  fetch_interval: 3600,
})

onMounted(loadSources)

async function loadSources() {
  loading.value = true
  try {
    const { data } = await sourcesApi.list()
    sources.value = data
  } finally {
    loading.value = false
  }
}

async function handleAddSource() {
  if (!addForm.value.name || !addForm.value.url) {
    ElMessage.warning('请填写名称和 URL')
    return
  }
  try {
    await sourcesApi.create({
      name: addForm.value.name,
      source_type: addForm.value.source_type,
      url: addForm.value.url,
      category: addForm.value.category || undefined,
      fetch_interval: addForm.value.fetch_interval,
    })
    ElMessage.success('添加成功')
    addDialogVisible.value = false
    addForm.value = { name: '', source_type: 'rss', url: '', category: '', fetch_interval: 3600 }
    await loadSources()
  } catch {
    ElMessage.error('添加失败')
  }
}

async function handleDeleteSource(id: string) {
  try {
    await ElMessageBox.confirm('确定删除该订阅源？', '确认')
    await sourcesApi.delete(id)
    ElMessage.success('已删除')
    if (activeSourceId.value === id) {
      activeSourceId.value = null
      topics.value = []
    }
    await loadSources()
  } catch {
    // cancelled or error
  }
}

async function handleToggleActive(source: ContentSource) {
  try {
    await sourcesApi.update(source.id, { is_active: !source.is_active } as any)
    source.is_active = !source.is_active
  } catch {
    ElMessage.error('更新失败')
  }
}

async function handleFetch(sourceId: string) {
  fetchingId.value = sourceId
  try {
    const { data } = await sourcesApi.fetch(sourceId)
    ElMessage.success(`抓取完成，新增 ${data.length} 条话题`)
    await loadSources()
    if (activeSourceId.value === sourceId) {
      await loadTopics(sourceId)
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '抓取失败')
  } finally {
    fetchingId.value = null
  }
}

async function loadTopics(sourceId: string) {
  activeSourceId.value = sourceId
  try {
    const { data } = await sourcesApi.getTopics(sourceId)
    topics.value = data
  } catch {
    topics.value = []
  }
}

async function handleCreateProject(topicId: string) {
  try {
    const { data } = await sourcesApi.createProjectFromTopic(topicId)
    ElMessage.success('项目已创建')
    // Mark topic as used locally
    const topic = topics.value.find(t => t.id === topicId)
    if (topic) topic.is_used = true
    router.push(`/projects/${data.id}`)
  } catch {
    ElMessage.error('创建失败')
  }
}

function formatTime(dateStr: string | null) {
  if (!dateStr) return '从未'
  return new Date(dateStr).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

function activeSourceName() {
  const s = sources.value.find(s => s.id === activeSourceId.value)
  return s ? s.name : ''
}
</script>

<template>
  <div style="max-width: 1200px; margin: 0 auto;">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <h2 style="margin: 0;">内容源管理</h2>
      <el-button type="primary" @click="addDialogVisible = true">
        <el-icon><Plus /></el-icon> 添加订阅源
      </el-button>
    </div>

    <el-row :gutter="16">
      <!-- 左侧：订阅源列表 -->
      <el-col :span="10">
        <el-card shadow="never">
          <template #header>
            <span>RSS 订阅源 ({{ sources.length }})</span>
          </template>
          <el-empty v-if="sources.length === 0" description="暂无订阅源" />
          <div v-for="source in sources" :key="source.id" style="margin-bottom: 12px;">
            <el-card
              shadow="hover"
              :class="{ 'active-source': activeSourceId === source.id }"
              style="cursor: pointer;"
              @click="loadTopics(source.id)"
            >
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <div style="flex: 1; min-width: 0;">
                  <div style="display: flex; align-items: center; gap: 6px;">
                    <strong style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{{ source.name }}</strong>
                    <el-tag size="small" :type="source.is_active ? 'success' : 'info'">
                      {{ source.is_active ? '启用' : '停用' }}
                    </el-tag>
                    <el-tag size="small" type="info">{{ source.source_type }}</el-tag>
                  </div>
                  <el-text type="info" size="small" style="display: block; margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                    {{ source.url }}
                  </el-text>
                  <el-text type="info" size="small" style="display: block; margin-top: 2px;">
                    上次抓取: {{ formatTime(source.last_fetched_at) }}
                  </el-text>
                </div>
                <div style="display: flex; gap: 4px; margin-left: 8px;" @click.stop>
                  <el-button
                    text size="small" type="primary"
                    :loading="fetchingId === source.id"
                    @click="handleFetch(source.id)"
                  >
                    抓取
                  </el-button>
                  <el-button text size="small" @click="handleToggleActive(source)">
                    {{ source.is_active ? '停用' : '启用' }}
                  </el-button>
                  <el-button text size="small" type="danger" @click="handleDeleteSource(source.id)">
                    删除
                  </el-button>
                </div>
              </div>
            </el-card>
          </div>
        </el-card>
      </el-col>

      <!-- 右侧：话题列表 -->
      <el-col :span="14">
        <el-card shadow="never">
          <template #header>
            <span>{{ activeSourceId ? `话题 - ${activeSourceName()}` : '选择订阅源查看话题' }}</span>
          </template>
          <el-empty v-if="!activeSourceId" description="点击左侧订阅源查看话题" />
          <el-empty v-else-if="topics.length === 0" description="暂无话题，请点击抓取" />
          <el-table v-else :data="topics" size="small">
            <el-table-column label="标题" min-width="200">
              <template #default="{ row }">
                <div>
                  <span>{{ row.title }}</span>
                  <el-tag v-if="row.is_used" type="success" size="small" style="margin-left: 4px;">已用</el-tag>
                </div>
                <el-text v-if="row.summary" type="info" size="small" :line-clamp="2" style="display: block; margin-top: 2px;">
                  {{ row.summary }}
                </el-text>
              </template>
            </el-table-column>
            <el-table-column label="抓取时间" width="110">
              <template #default="{ row }">
                <el-text size="small">{{ formatTime(row.fetched_at) }}</el-text>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button
                  v-if="!row.is_used"
                  text size="small" type="primary"
                  @click="handleCreateProject(row.id)"
                >
                  创建项目
                </el-button>
                <el-link
                  v-if="row.url"
                  :href="row.url" target="_blank"
                  type="info" :underline="false"
                  style="font-size: 12px; margin-left: 4px;"
                >
                  原文
                </el-link>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <!-- 添加订阅源对话框 -->
    <el-dialog v-model="addDialogVisible" title="添加订阅源" width="480px">
      <el-form label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="addForm.name" placeholder="如：丁香医生" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="addForm.source_type" style="width: 100%;">
            <el-option label="RSS 订阅" value="rss" />
            <el-option label="网页抓取" value="scrape" />
          </el-select>
        </el-form-item>
        <el-form-item label="URL">
          <el-input v-model="addForm.url" placeholder="RSS 订阅地址" />
        </el-form-item>
        <el-form-item label="分类">
          <el-input v-model="addForm.category" placeholder="如：儿科、长寿医学（可选）" />
        </el-form-item>
        <el-form-item label="抓取间隔">
          <el-select v-model="addForm.fetch_interval" style="width: 100%;">
            <el-option label="每小时" :value="3600" />
            <el-option label="每 6 小时" :value="21600" />
            <el-option label="每 12 小时" :value="43200" />
            <el-option label="每天" :value="86400" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleAddSource">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.active-source {
  border-color: #409eff;
}
</style>
