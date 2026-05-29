<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { Project } from '../types/project'
import { projectsApi } from '../api/projects'
import { sourcesApi } from '../api/sources'
import { formatDateTime } from '../utils/date'

const router = useRouter()
const recentProjects = ref<Project[]>([])
const loading = ref(false)
const createDialogVisible = ref(false)
const createMode = ref<'manual' | 'url' | 'pdf' | 'ppt'>('manual')
const newProject = ref({ title: '', topic: '', aspect_ratio: '16:9', video_template: 'slideshow', image_prompt_language: 'zh', reference_content: '', source_type: 'manual', source_url: '' })

// URL import
const importUrl = ref('')
const extracting = ref(false)

// PDF import
const pdfFile = ref<File | null>(null)
const pdfExtracting = ref(false)

// PPT import
const pptFile = ref<File | null>(null)
const pptImporting = ref(false)

onMounted(async () => {
  await loadProjects()
})

async function loadProjects() {
  loading.value = true
  try {
    const { data } = await projectsApi.list(1, 10)
    recentProjects.value = data.items
  } catch {
    ElMessage.error('Failed to load projects')
  } finally {
    loading.value = false
  }
}

async function handleCreate() {
  if (!newProject.value.title || !newProject.value.topic) {
    ElMessage.warning('请填写标题和话题')
    return
  }
  try {
    const { data } = await projectsApi.create(newProject.value)
    createDialogVisible.value = false
    newProject.value = { title: '', topic: '', aspect_ratio: '16:9', video_template: 'slideshow', image_prompt_language: 'zh', reference_content: '', source_type: 'manual', source_url: '' }
    router.push(`/projects/${data.id}`)
  } catch {
    ElMessage.error('创建失败')
  }
}

async function handleExtractUrl() {
  if (!importUrl.value) {
    ElMessage.warning('请输入 URL')
    return
  }
  extracting.value = true
  try {
    const { data } = await sourcesApi.extractUrl(importUrl.value)
    newProject.value.title = data.title || ''
    newProject.value.topic = data.title || ''
    newProject.value.reference_content = data.content
    newProject.value.source_type = 'url'
    newProject.value.source_url = importUrl.value
    createMode.value = 'manual'
    ElMessage.success('内容提取成功，请检查并创建项目')
  } catch {
    ElMessage.error('内容提取失败，请检查 URL')
  } finally {
    extracting.value = false
  }
}

function handlePdfChange(file: any) {
  pdfFile.value = file.raw
}

async function handleExtractPdf() {
  if (!pdfFile.value) {
    ElMessage.warning('请选择 PDF 文件')
    return
  }
  pdfExtracting.value = true
  try {
    const { data } = await sourcesApi.extractPdf(pdfFile.value)
    newProject.value.title = data.title || ''
    newProject.value.topic = data.title || ''
    newProject.value.reference_content = data.content
    newProject.value.source_type = 'pdf'
    newProject.value.source_url = ''
    createMode.value = 'manual'
    ElMessage.success('PDF 内容提取成功，请检查并创建项目')
  } catch {
    ElMessage.error('PDF 内容提取失败，请确认文件格式正确')
  } finally {
    pdfExtracting.value = false
  }
}

function handlePptChange(file: any) {
  pptFile.value = file.raw
  // Pre-fill the title from the filename if the user hasn't typed one.
  if (!newProject.value.title && file.name) {
    newProject.value.title = file.name.replace(/\.(pptx?|PPTX?)$/, '')
  }
}

async function handlePptImport() {
  if (!pptFile.value) {
    ElMessage.warning('请选择 PPT 文件')
    return
  }
  if (!newProject.value.title) {
    ElMessage.warning('请填写标题')
    return
  }
  pptImporting.value = true
  try {
    const { data } = await projectsApi.importPpt(pptFile.value, {
      title: newProject.value.title,
      aspect_ratio: newProject.value.aspect_ratio,
      video_template: newProject.value.video_template,
    })
    createDialogVisible.value = false
    pptFile.value = null
    ElMessage.success('PPT 导入中：幻灯片转为画面、备注转为口播稿，稍候即可生成音频和视频')
    router.push(`/projects/${data.id}`)
  } catch {
    ElMessage.error('PPT 导入失败，请确认文件格式正确并已安装 LibreOffice')
  } finally {
    pptImporting.value = false
  }
}

function getStatusType(status: string) {
  const map: Record<string, string> = {
    draft: 'info', processing: 'warning', completed: 'success', failed: 'danger',
  }
  return map[status] || 'info'
}

function getStatusLabel(status: string) {
  const map: Record<string, string> = {
    draft: '草稿', processing: '处理中', completed: '已完成', failed: '失败',
  }
  return map[status] || status
}
</script>

<template>
  <div class="dashboard">
    <div class="dashboard-header">
      <h1>AI Podcast 控制台</h1>
      <el-button type="primary" size="large" @click="createDialogVisible = true">
        <el-icon><Plus /></el-icon> 新建项目
      </el-button>
    </div>

    <el-row :gutter="20" class="stats-row">
      <el-col :span="8">
        <el-card shadow="hover">
          <el-statistic title="总项目数" :value="recentProjects.length" />
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover">
          <el-statistic title="已完成" :value="recentProjects.filter(p => p.status === 'completed').length" />
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover">
          <el-statistic title="处理中" :value="recentProjects.filter(p => p.status === 'processing').length" />
        </el-card>
      </el-col>
    </el-row>

    <el-card class="recent-card">
      <template #header>
        <div class="card-header">
          <span>最近项目</span>
          <el-button text @click="router.push('/projects')">查看全部</el-button>
        </div>
      </template>
      <el-table :data="recentProjects" v-loading="loading" stripe>
        <el-table-column prop="title" label="标题" min-width="200">
          <template #default="{ row }">
            <el-link @click="router.push(`/projects/${row.id}`)">{{ row.title }}</el-link>
          </template>
        </el-table-column>
        <el-table-column prop="topic" label="话题" min-width="200" show-overflow-tooltip />
        <el-table-column prop="aspect_ratio" label="比例" width="80" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" size="small">{{ getStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Create Dialog -->
    <el-dialog v-model="createDialogVisible" title="新建项目" width="540px">
      <el-tabs v-model="createMode">
        <el-tab-pane label="手动输入" name="manual" />
        <el-tab-pane label="从 URL 导入" name="url" />
        <el-tab-pane label="PDF 论文导入" name="pdf" />
        <el-tab-pane label="从 PPT 导入" name="ppt" />
      </el-tabs>

      <!-- PPT 导入 -->
      <div v-if="createMode === 'ppt'" style="margin-bottom: 16px;">
        <el-upload
          :auto-upload="false"
          accept=".pptx,.ppt"
          :limit="1"
          :on-change="handlePptChange"
          :on-exceed="() => ElMessage.warning('只能上传一个 PPT 文件')"
          drag
        >
          <el-icon style="font-size: 40px; color: #909399;"><UploadFilled /></el-icon>
          <div style="margin-top: 8px;">将 PPT 文件拖到此处，或<em>点击上传</em></div>
        </el-upload>
        <el-text type="info" size="small" style="display: block; margin-top: 4px;">
          每页幻灯片作为一段画面，对应的备注作为该段口播稿（建议 .pptx，备注更可靠）。
          导入后可直接生成音频与视频。
        </el-text>
      </div>

      <!-- URL 导入 -->
      <div v-if="createMode === 'url'" style="margin-bottom: 16px;">
        <el-input
          v-model="importUrl"
          placeholder="输入文章 URL，自动提取标题和内容"
          @keyup.enter="handleExtractUrl"
        >
          <template #append>
            <el-button :loading="extracting" @click="handleExtractUrl">提取</el-button>
          </template>
        </el-input>
        <el-text type="info" size="small" style="display: block; margin-top: 4px;">
          输入健康文章的网页地址，自动提取标题和正文作为话题
        </el-text>
      </div>

      <!-- PDF 导入 -->
      <div v-if="createMode === 'pdf'" style="margin-bottom: 16px;">
        <el-upload
          :auto-upload="false"
          accept=".pdf"
          :limit="1"
          :on-change="handlePdfChange"
          :on-exceed="() => ElMessage.warning('只能上传一个 PDF 文件')"
          drag
        >
          <el-icon style="font-size: 40px; color: #909399;"><UploadFilled /></el-icon>
          <div style="margin-top: 8px;">将 PDF 文件拖到此处，或<em>点击上传</em></div>
        </el-upload>
        <el-button
          type="primary"
          :loading="pdfExtracting"
          :disabled="!pdfFile"
          style="margin-top: 12px; width: 100%;"
          @click="handleExtractPdf"
        >提取论文内容</el-button>
        <el-text type="info" size="small" style="display: block; margin-top: 4px;">
          上传学术论文 PDF，自动提取标题和正文作为话题和参考资料
        </el-text>
      </div>

      <el-form label-width="80px">
        <el-form-item label="标题">
          <el-input v-model="newProject.title" placeholder="输入项目标题" />
        </el-form-item>
        <el-form-item v-if="createMode !== 'ppt'" label="话题">
          <el-input v-model="newProject.topic" type="textarea" :rows="3" placeholder="输入健康科普话题" />
        </el-form-item>
        <el-form-item v-if="newProject.reference_content" label="参考资料">
          <el-input
            v-model="newProject.reference_content"
            type="textarea"
            :rows="6"
            placeholder="从 URL/PDF 提取的参考资料内容"
          />
          <el-text type="info" size="small" style="display: block; margin-top: 4px;">
            AI 生成文章时将严格参考以上内容的核心观点
          </el-text>
        </el-form-item>
        <el-form-item label="画面比例">
          <el-radio-group v-model="newProject.aspect_ratio">
            <el-radio-button value="16:9">横屏 16:9</el-radio-button>
            <el-radio-button value="9:16">竖屏 9:16</el-radio-button>
            <el-radio-button value="1:1">方形 1:1</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="视频模板">
          <el-select v-model="newProject.video_template">
            <el-option label="幻灯片" value="slideshow" />
            <el-option label="Ken Burns" value="kenburns" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="createMode !== 'ppt'" label="图片文字">
          <el-radio-group v-model="newProject.image_prompt_language">
            <el-radio-button value="zh">中文</el-radio-button>
            <el-radio-button value="en">英文</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button
          v-if="createMode === 'ppt'"
          type="primary"
          :loading="pptImporting"
          @click="handlePptImport"
        >导入并创建</el-button>
        <el-button v-else type="primary" @click="handleCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.dashboard { max-width: 1200px; margin: 0 auto; }
.dashboard-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.dashboard-header h1 { margin: 0; font-size: 24px; }
.stats-row { margin-bottom: 24px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.recent-card { margin-bottom: 24px; }
</style>
