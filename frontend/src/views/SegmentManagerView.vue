<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useProjectStore } from '../stores/project'
import { projectsApi } from '../api/projects'
import { pipelineApi } from '../api/pipeline'

const route = useRoute()
const store = useProjectStore()
const projectId = computed(() => route.params.id as string)
const editingId = ref<string | null>(null)
const editContent = ref('')
const editPrompt = ref('')
const editChapterTitle = ref('')
const splitting = ref(false)
const generatingTitles = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

const hasChapterTitles = computed(() =>
  store.segments.some(s => s.chapter_title)
)

// All chapter titles formatted for platform use (e.g. "00:00 标题")
const allChapterTitlesText = computed(() =>
  store.segments
    .filter(s => s.chapter_title)
    .map((s, i) => `${formatTimestamp(s, i)} ${s.chapter_title}`)
    .join('\n')
)

function formatTimestamp(_segment: any, index: number): string {
  // Estimate timestamp from cumulative duration hints
  let seconds = 0
  for (let i = 0; i < index; i++) {
    seconds += store.segments[i]?.duration_hint || 0
  }
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

onMounted(async () => {
  await store.loadSegments(projectId.value)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

function startEdit(segment: any) {
  editingId.value = segment.id
  editContent.value = segment.content
  editPrompt.value = segment.image_prompt || ''
  editChapterTitle.value = segment.chapter_title || ''
}

async function saveEdit(segmentId: string) {
  try {
    await projectsApi.updateSegment(projectId.value, segmentId, {
      content: editContent.value,
      image_prompt: editPrompt.value || undefined,
      chapter_title: editChapterTitle.value || undefined,
    })
    editingId.value = null
    await store.loadSegments(projectId.value)
    ElMessage.success('已保存')
  } catch {
    ElMessage.error('保存失败')
  }
}

function stopSplitPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  splitting.value = false
}

async function handleSplit() {
  splitting.value = true
  try {
    await pipelineApi.runStep(projectId.value, 'content_splitting')
    ElMessage.success('内容拆分已启动，请稍候...')

    // Poll the pipeline step status rather than comparing segment counts:
    // a re-split that yields the same number of segments would otherwise
    // never be detected and would just hang until timeout.
    const startTime = Date.now()
    const TIMEOUT = 120000 // long articles can take a while to split
    pollTimer = setInterval(async () => {
      let step
      try {
        const { data } = await pipelineApi.getStatus(projectId.value)
        step = data.find(s => s.step_name === 'content_splitting')
      } catch {
        return // transient error, keep polling
      }

      if (step?.status === 'completed') {
        stopSplitPolling()
        await store.loadSegments(projectId.value)
        ElMessage.success('内容拆分完成')
      } else if (step?.status === 'failed') {
        stopSplitPolling()
        await store.loadSegments(projectId.value)
        ElMessage.error(step.error_message || '拆分失败')
      } else if (Date.now() - startTime > TIMEOUT) {
        stopSplitPolling()
        await store.loadSegments(projectId.value)
        ElMessage.warning('拆分超时，请稍后刷新查看')
      }
    }, 2000)
  } catch {
    ElMessage.error('拆分失败')
    splitting.value = false
  }
}

async function handleGenerateTitles() {
  generatingTitles.value = true
  try {
    await projectsApi.generateChapterTitles(projectId.value)
    await store.loadSegments(projectId.value)
    ElMessage.success('章节标题已生成')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '生成失败')
  } finally {
    generatingTitles.value = false
  }
}

function copyTitle(title: string) {
  navigator.clipboard.writeText(title).then(() => {
    ElMessage.success('已复制: ' + title)
  }).catch(() => {
    ElMessage.error('复制失败')
  })
}

function copyAllTitles() {
  navigator.clipboard.writeText(allChapterTitlesText.value).then(() => {
    ElMessage.success('全部章节标题已复制')
  }).catch(() => {
    ElMessage.error('复制失败')
  })
}
</script>

<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <h3 style="margin: 0;">段落管理 ({{ store.segments.length }} 段)</h3>
      <div style="display: flex; gap: 8px;">
        <el-button @click="handleGenerateTitles" :loading="generatingTitles" type="primary" plain>
          <el-icon><MagicStick /></el-icon> AI 生成章节标题
        </el-button>
        <el-button v-if="hasChapterTitles" @click="copyAllTitles" type="success" plain>
          <el-icon><DocumentCopy /></el-icon> 复制全部标题
        </el-button>
        <el-button @click="handleSplit" :loading="splitting">
          <el-icon><ScaleToOriginal /></el-icon> 重新拆分
        </el-button>
      </div>
    </div>

    <div v-if="store.segments.length === 0 && !splitting" style="text-align: center; padding: 40px;">
      <el-empty description="暂无段落，请先生成文章并拆分" />
    </div>

    <div v-if="splitting && store.segments.length === 0" style="text-align: center; padding: 40px;">
      <el-icon class="is-loading" :size="32"><Loading /></el-icon>
      <p>正在拆分内容...</p>
    </div>

    <el-card v-for="segment in store.segments" :key="segment.id" class="segment-card" shadow="hover">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span>段落 {{ segment.segment_order + 1 }}</span>
            <el-tag
              v-if="segment.chapter_title && editingId !== segment.id"
              effect="plain"
              type="warning"
              class="chapter-tag"
              @click="copyTitle(formatTimestamp(segment, segment.segment_order) + ' ' + segment.chapter_title!)"
              :title="'点击复制: ' + formatTimestamp(segment, segment.segment_order) + ' ' + segment.chapter_title"
            >
              <el-icon style="margin-right: 2px;"><DocumentCopy /></el-icon>
              <span style="color: #909399; margin-right: 4px;">{{ formatTimestamp(segment, segment.segment_order) }}</span>
              {{ segment.chapter_title }}
            </el-tag>
          </div>
          <div>
            <el-button v-if="editingId !== segment.id" text size="small" @click="startEdit(segment)">
              <el-icon><Edit /></el-icon> 编辑
            </el-button>
            <template v-else>
              <el-button text size="small" type="primary" @click="saveEdit(segment.id)">保存</el-button>
              <el-button text size="small" @click="editingId = null">取消</el-button>
            </template>
          </div>
        </div>
      </template>

      <template v-if="editingId === segment.id">
        <el-input v-model="editChapterTitle" style="margin-bottom: 8px;" placeholder="章节标题（可选，用于视频章节导航）" maxlength="20" show-word-limit />
        <el-input v-model="editContent" type="textarea" :rows="4" placeholder="段落内容" />
        <el-input v-model="editPrompt" style="margin-top: 8px;" placeholder="图片提示词 (可选)" />
      </template>
      <template v-else>
        <p style="margin: 0; white-space: pre-wrap;">{{ segment.content }}</p>
        <el-text v-if="segment.image_prompt" type="info" size="small" style="margin-top: 8px; display: block;">
          图片提示词: {{ segment.image_prompt }}
        </el-text>
      </template>
    </el-card>
  </div>
</template>

<style scoped>
.segment-card { margin-bottom: 12px; }
.chapter-tag {
  cursor: pointer;
  transition: all 0.2s;
}
.chapter-tag:hover {
  transform: scale(1.05);
  box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}
</style>
