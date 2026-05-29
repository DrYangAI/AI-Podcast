import axios from 'axios'
import type { PromptTemplate, PromptTemplateUpdate, PromptTemplateHistory, ResolvedPromptConfig, ProjectPromptOverride } from '../types/prompt'

const API = axios.create({ baseURL: '/api/v1' })

export const promptsApi = {
  // System-level
  listTemplates: () => API.get<PromptTemplate[]>('/prompt-templates/'),
  getTemplate: (step: string) => API.get<PromptTemplate>(`/prompt-templates/${step}`),
  updateTemplate: (step: string, data: PromptTemplateUpdate) => API.put<PromptTemplate>(`/prompt-templates/${step}`, data),
  resetTemplate: (step: string) => API.post<PromptTemplate>(`/prompt-templates/${step}/reset`),
  getHistory: (step: string) => API.get<PromptTemplateHistory[]>(`/prompt-templates/${step}/history`),
  restoreVersion: (step: string, versionId: string) => API.post<PromptTemplate>(`/prompt-templates/${step}/restore/${versionId}`),

  // Project-level
  getProjectConfig: (projectId: string) => API.get<ResolvedPromptConfig[]>(`/projects/${projectId}/prompt-config`),
  getProjectConfigStep: (projectId: string, step: string) => API.get<ResolvedPromptConfig>(`/projects/${projectId}/prompt-config/${step}`),
  updateProjectConfig: (projectId: string, step: string, data: ProjectPromptOverride) => API.put(`/projects/${projectId}/prompt-config/${step}`, data),
  deleteProjectConfig: (projectId: string, step: string) => API.delete(`/projects/${projectId}/prompt-config/${step}`),
}
