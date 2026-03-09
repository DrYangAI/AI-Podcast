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
const splitting = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

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
}

async function saveEdit(segmentId: string) {
  try {
    await projectsApi.updateSegment(projectId.value, segmentId, {
      content: editContent.value,
      image_prompt: editPrompt.value || undefined,
    })
    editingId.value = null
    await store.loadSegments(projectId.value)
    ElMessage.success('已保存')
  } catch {
    ElMessage.error('保存失败')
  }
}

async function handleSplit() {
  splitting.value = true
  try {
    const oldCount = store.segments.length
    await pipelineApi.runStep(projectId.value, 'content_splitting')
    ElMessage.success('内容拆分已启动，请稍候...')

    pollTimer = setInterval(async () => {
      await store.loadSegments(projectId.value)
      if (store.segments.length > 0 && store.segments.length !== oldCount) {
        splitting.value = false
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
        ElMessage.success('内容拆分完成')
      }
    }, 2000)

    setTimeout(() => {
      if (pollTimer) {
        clearInterval(pollTimer)
        pollTimer = null
        splitting.value = false
        // Final load attempt
        store.loadSegments(projectId.value)
      }
    }, 30000)
  } catch {
    ElMessage.error('拆分失败')
    splitting.value = false
  }
}
</script>

<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <h3 style="margin: 0;">段落管理 ({{ store.segments.length }} 段)</h3>
      <el-button @click="handleSplit" :loading="splitting">
        <el-icon><ScaleToOriginal /></el-icon> 重新拆分
      </el-button>
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
          <span>段落 {{ segment.segment_order + 1 }}</span>
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
</style>
