import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ProjectDetail, PipelineStep, Segment, ImageAsset } from '../types/project'
import { projectsApi } from '../api/projects'
import { pipelineApi } from '../api/pipeline'

export const useProjectStore = defineStore('project', () => {
  const currentProject = ref<ProjectDetail | null>(null)
  const pipelineSteps = ref<PipelineStep[]>([])
  const segments = ref<Segment[]>([])
  const images = ref<ImageAsset[]>([])
  const loading = ref(false)
  const pollingTimer = ref<number | null>(null)

  async function loadProject(id: string) {
    loading.value = true
    try {
      const { data } = await projectsApi.get(id)
      currentProject.value = data
      pipelineSteps.value = data.pipeline_steps || []
    } finally {
      loading.value = false
    }
  }

  async function loadSegments(projectId: string) {
    const { data } = await projectsApi.getSegments(projectId)
    segments.value = data
  }

  async function loadImages(projectId: string) {
    const { data } = await projectsApi.getImages(projectId)
    images.value = data
  }

  async function refreshPipeline(projectId: string) {
    const { data } = await pipelineApi.getStatus(projectId)
    pipelineSteps.value = data
  }

  function startPolling(projectId: string, interval = 3000) {
    stopPolling()
    pollingTimer.value = window.setInterval(() => {
      refreshPipeline(projectId)
    }, interval)
  }

  function stopPolling() {
    if (pollingTimer.value) {
      clearInterval(pollingTimer.value)
      pollingTimer.value = null
    }
  }

  return {
    currentProject,
    pipelineSteps,
    segments,
    images,
    loading,
    loadProject,
    loadSegments,
    loadImages,
    refreshPipeline,
    startPolling,
    stopPolling,
  }
})
