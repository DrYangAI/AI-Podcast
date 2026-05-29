<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { projectsApi } from '../api/projects'
import { useProjectStore } from '../stores/project'

const route = useRoute()
const store = useProjectStore()
const projectId = computed(() => route.params.id as string)

const introText = ref('')
const outroText = ref('')
const referenceContent = ref('')
const useReferenceContent = ref(true)
const userNotes = ref('')
const saving = ref(false)

onMounted(() => {
  if (store.currentProject) {
    introText.value = store.currentProject.intro_text || ''
    outroText.value = store.currentProject.outro_text || ''
    referenceContent.value = store.currentProject.reference_content || ''
    useReferenceContent.value = store.currentProject.use_reference_content ?? true
    userNotes.value = store.currentProject.user_notes || ''
  }
})

async function handleSave() {
  saving.value = true
  try {
    await projectsApi.update(projectId.value, {
      intro_text: introText.value || null,
      outro_text: outroText.value || null,
      reference_content: referenceContent.value || null,
      use_reference_content: useReferenceContent.value,
      user_notes: userNotes.value || null,
    })
    if (store.currentProject) {
      store.currentProject.intro_text = introText.value || null
      store.currentProject.outro_text = outroText.value || null
      store.currentProject.reference_content = referenceContent.value || null
      store.currentProject.use_reference_content = useReferenceContent.value
      store.currentProject.user_notes = userNotes.value || null
    }
    ElMessage.success('已保存')
  } catch {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div style="max-width: 800px;">
    <h3 style="margin-top: 0; margin-bottom: 20px;">项目设置</h3>

    <el-card shadow="never" style="margin-bottom: 20px;">
      <template #header>
        <div style="display: flex; align-items: center; justify-content: space-between;">
          <div style="display: flex; align-items: center; gap: 8px;">
            <el-icon><Document /></el-icon>
            <span style="font-weight: bold;">参考资料</span>
          </div>
          <el-switch
            v-model="useReferenceContent"
            active-text="启用"
            inactive-text="关闭"
            style="--el-switch-on-color: #409eff;"
          />
        </div>
      </template>

      <el-alert :type="useReferenceContent ? 'info' : 'warning'" :closable="false" show-icon style="margin-bottom: 16px;">
        <template #title>
          {{ useReferenceContent ? '已启用：AI生成文章时会参考以下内容。' : '已关闭：AI生成文章时不会使用参考资料，仅根据话题创作。' }}
        </template>
      </el-alert>

      <div style="margin-bottom: 16px;">
        <el-input
          v-model="referenceContent"
          type="textarea"
          :autosize="{ minRows: 4, maxRows: 15 }"
          placeholder="粘贴参考文章内容..."
        />
        <div style="margin-top: 4px; color: #909399; font-size: 12px;">
          字数：{{ referenceContent.length }}
        </div>
      </div>
    </el-card>

    <el-card shadow="never" style="margin-bottom: 20px;">
      <template #header>
        <div style="display: flex; align-items: center; gap: 8px;">
          <el-icon><EditPen /></el-icon>
          <span style="font-weight: bold;">创作要求</span>
        </div>
      </template>

      <el-alert type="info" :closable="false" show-icon style="margin-bottom: 16px;">
        <template #title>
          您可以在此添加自己的观点、角度或特殊要求，AI生成文章时会融入这些内容。
        </template>
      </el-alert>

      <div style="margin-bottom: 16px;">
        <el-input
          v-model="userNotes"
          type="textarea"
          :autosize="{ minRows: 3, maxRows: 10 }"
          placeholder="例如：重点强调预防的重要性，从中医角度分析..."
        />
      </div>
    </el-card>

    <el-card shadow="never" style="margin-bottom: 20px;">
      <template #header>
        <div style="display: flex; align-items: center; gap: 8px;">
          <el-icon><VideoCamera /></el-icon>
          <span style="font-weight: bold;">片头片尾</span>
        </div>
      </template>

      <el-alert type="info" :closable="false" show-icon style="margin-bottom: 16px;">
        <template #title>
          设置固定的开场白和结束语。TTS 会将文字合成语音，分别添加到视频的开头和结尾。留空则不添加。
        </template>
      </el-alert>

      <div style="margin-bottom: 16px;">
        <div style="margin-bottom: 6px; font-weight: bold; color: #606266;">
          片头文案 (开场白)
        </div>
        <el-input
          v-model="introText"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 6 }"
          placeholder="例如：大家好，欢迎来到健康科普频道，我是你们的AI主播。今天我们来聊一聊..."
        />
      </div>

      <div style="margin-bottom: 16px;">
        <div style="margin-bottom: 6px; font-weight: bold; color: #606266;">
          片尾文案 (结束语)
        </div>
        <el-input
          v-model="outroText"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 6 }"
          placeholder="例如：感谢大家的收看，如果觉得有用，请点赞关注。我们下期再见！"
        />
      </div>

      <el-button type="primary" @click="handleSave" :loading="saving">
        保存
      </el-button>
    </el-card>
  </div>
</template>
