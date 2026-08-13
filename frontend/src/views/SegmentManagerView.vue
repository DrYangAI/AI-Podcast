<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, reactive } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
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
const editScript = ref('')
const splitting = ref(false)
const generatingTitles = ref(false)
const generatingScriptSet = ref<Set<string>>(new Set())
const deletingSet = ref<Set<string>>(new Set())
let pollTimer: ReturnType<typeof setInterval> | null = null

// --- Manual add-segment dialog ---
const addDialogVisible = ref(false)
const adding = ref(false)
// Target segment_order for the new segment; null = append at end.
const addPosition = ref<number | null>(null)
const addForm = reactive({
  content: '',
  chapter_title: '',
  image_prompt: '',
  script_text: '',
})

function openAddDialog(position: number | null = null) {
  addPosition.value = position
  addForm.content = ''
  addForm.chapter_title = ''
  addForm.image_prompt = ''
  addForm.script_text = ''
  addDialogVisible.value = true
}

async function submitAdd() {
  if (!addForm.content.trim()) {
    ElMessage.warning('请填写段落内容')
    return
  }
  adding.value = true
  try {
    await projectsApi.createSegment(projectId.value, {
      content: addForm.content,
      chapter_title: addForm.chapter_title || undefined,
      image_prompt: addForm.image_prompt || undefined,
      script_text: addForm.script_text || undefined,
      position: addPosition.value ?? undefined,
    })
    addDialogVisible.value = false
    await store.loadSegments(projectId.value)
    ElMessage.success('段落已新增')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '新增失败')
  } finally {
    adding.value = false
  }
}

async function handleDelete(segment: any) {
  try {
    await ElMessageBox.confirm(
      `确定删除段落 ${segment.segment_order + 1} 吗？对应的图片也会一并删除。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  deletingSet.value = new Set(deletingSet.value).add(segment.id)
  try {
    await projectsApi.deleteSegment(projectId.value, segment.id)
    await store.loadSegments(projectId.value)
    ElMessage.success('段落已删除')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  } finally {
    const next = new Set(deletingSet.value)
    next.delete(segment.id)
    deletingSet.value = next
  }
}

async function handleGenerateScript(segmentId: string) {
  generatingScriptSet.value = new Set(generatingScriptSet.value).add(segmentId)
  try {
    await projectsApi.regenerateSegmentScript(projectId.value, segmentId)
    await store.loadSegments(projectId.value)
    ElMessage.success('口播稿已生成')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '生成失败')
  } finally {
    const next = new Set(generatingScriptSet.value)
    next.delete(segmentId)
    generatingScriptSet.value = next
  }
}

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
  editScript.value = segment.script_text || ''
}

async function saveEdit(segmentId: string) {
  try {
    await projectsApi.updateSegment(projectId.value, segmentId, {
      content: editContent.value,
      image_prompt: editPrompt.value || undefined,
      chapter_title: editChapterTitle.value || undefined,
      script_text: editScript.value || undefined,
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
        <el-button @click="openAddDialog()" type="primary">
          <el-icon><Plus /></el-icon> 新增段落
        </el-button>
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
            <el-button
              v-if="editingId !== segment.id"
              text size="small" type="danger"
              :loading="deletingSet.has(segment.id)"
              @click="handleDelete(segment)"
            >
              <el-icon><Delete /></el-icon> 删除
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
        <el-input v-model="editScript" type="textarea" :rows="4" style="margin-top: 8px;" placeholder="口播稿 (可选，可点「AI 生成口播稿」自动生成)" />
      </template>
      <template v-else>
        <p style="margin: 0; white-space: pre-wrap;">{{ segment.content }}</p>
        <el-text v-if="segment.image_prompt" type="info" size="small" style="margin-top: 8px; display: block;">
          图片提示词: {{ segment.image_prompt }}
        </el-text>
        <div v-if="segment.script_text" class="script-block">
          <div class="script-label">口播稿</div>
          <p style="margin: 0; white-space: pre-wrap;">{{ segment.script_text }}</p>
        </div>
        <div class="segment-actions">
          <el-button
            text type="primary" size="small"
            :loading="generatingScriptSet.has(segment.id)"
            @click="handleGenerateScript(segment.id)"
          >
            <el-icon><MagicStick /></el-icon> {{ segment.script_text ? '重新生成口播稿' : 'AI 生成口播稿' }}
          </el-button>
          <el-button text size="small" @click="openAddDialog(segment.segment_order + 1)">
            <el-icon><Plus /></el-icon> 在此后插入段落
          </el-button>
        </div>
      </template>
    </el-card>

    <el-dialog v-model="addDialogVisible" :title="addPosition === null ? '新增段落（末尾）' : `在第 ${addPosition} 段后插入新段落`" width="600px">
      <el-input v-model="addForm.chapter_title" style="margin-bottom: 8px;" placeholder="章节标题（可选，用于视频章节导航）" maxlength="20" show-word-limit />
      <el-input v-model="addForm.content" type="textarea" :rows="5" placeholder="段落内容（必填）" />
      <el-input v-model="addForm.image_prompt" style="margin-top: 8px;" placeholder="图片提示词（可选，留空可稍后在图片库生成）" />
      <el-input v-model="addForm.script_text" type="textarea" :rows="4" style="margin-top: 8px;" placeholder="口播稿（可选，留空可新增后点「AI 生成口播稿」）" />
      <template #footer>
        <el-button @click="addDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="adding" @click="submitAdd">确定新增</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.segment-card { margin-bottom: 12px; }
.script-block {
  margin-top: 10px;
  padding: 8px 12px;
  background: #f5f7fa;
  border-radius: 4px;
  font-size: 13px;
  color: #606266;
}
.script-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}
.segment-actions {
  display: flex;
  gap: 4px;
  margin-top: 8px;
  flex-wrap: wrap;
}
.chapter-tag {
  cursor: pointer;
  transition: all 0.2s;
}
.chapter-tag:hover {
  transform: scale(1.05);
  box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}
</style>
