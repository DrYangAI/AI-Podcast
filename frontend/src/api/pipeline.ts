import apiClient from './client'
import type { PipelineStep } from '../types/project'

export const pipelineApi = {
  getStatus(projectId: string) {
    return apiClient.get<PipelineStep[]>(`/projects/${projectId}/pipeline`)
  },

  runPipeline(projectId: string, fromStep?: string, providerOverrides?: Record<string, string>) {
    return apiClient.post(`/projects/${projectId}/pipeline/run`, {
      from_step: fromStep,
      provider_overrides: providerOverrides,
    })
  },

  runStep(projectId: string, stepName: string) {
    return apiClient.post(`/projects/${projectId}/pipeline/steps/${stepName}/run`)
  },

  retryStep(projectId: string, stepName: string) {
    return apiClient.post(`/projects/${projectId}/pipeline/steps/${stepName}/retry`)
  },
}
