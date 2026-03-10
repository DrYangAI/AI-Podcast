import apiClient from './client'
import type { Project, ProjectDetail, PaginatedResponse, Article, Segment, Script, AudioAsset, VideoOutput, ImageAsset } from '../types/project'

export const projectsApi = {
  list(page = 1, pageSize = 20, status?: string) {
    return apiClient.get<PaginatedResponse<Project>>('/projects', {
      params: { page, page_size: pageSize, status },
    })
  },

  get(id: string) {
    return apiClient.get<ProjectDetail>(`/projects/${id}`)
  },

  create(data: { title: string; topic: string; aspect_ratio?: string; video_template?: string; image_prompt_language?: string }) {
    return apiClient.post<Project>('/projects', data)
  },

  update(id: string, data: Partial<Project>) {
    return apiClient.put<Project>(`/projects/${id}`, data)
  },

  delete(id: string) {
    return apiClient.delete(`/projects/${id}`)
  },

  duplicate(id: string) {
    return apiClient.post<Project>(`/projects/${id}/duplicate`)
  },

  // Article
  getArticle(id: string) {
    return apiClient.get<Article>(`/projects/${id}/article`)
  },
  updateArticle(id: string, data: { title?: string; content?: string }) {
    return apiClient.put<Article>(`/projects/${id}/article`, data)
  },

  // Segments
  getSegments(id: string) {
    return apiClient.get<Segment[]>(`/projects/${id}/segments`)
  },
  updateSegment(projectId: string, segmentId: string, data: { content?: string; image_prompt?: string }) {
    return apiClient.put<Segment>(`/projects/${projectId}/segments/${segmentId}`, data)
  },

  // Images
  getImages(id: string) {
    return apiClient.get<ImageAsset[]>(`/projects/${id}/images`)
  },
  generatePrompts(id: string) {
    return apiClient.post(`/projects/${id}/generate-prompts`, null, {
      timeout: 180000,  // 提示词生成需要调用 LLM，耗时较长，设置 3 分钟超时
    })
  },
  regenerateSegmentImage(projectId: string, segmentId: string, prompt?: string) {
    return apiClient.post<ImageAsset>(`/projects/${projectId}/segments/${segmentId}/image/regenerate`,
      prompt !== undefined ? { prompt } : null)
  },
  uploadSegmentImage(projectId: string, segmentId: string, file: File) {
    const formData = new FormData()
    formData.append('file', file)
    return apiClient.post<ImageAsset>(`/projects/${projectId}/segments/${segmentId}/image/upload`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  // Script
  getScript(id: string) {
    return apiClient.get<Script>(`/projects/${id}/script`)
  },
  updateScript(id: string, data: { content?: string; style?: string }) {
    return apiClient.put<Script>(`/projects/${id}/script`, data)
  },

  // Audio
  getAudio(id: string) {
    return apiClient.get<AudioAsset>(`/projects/${id}/audio`)
  },

  // Videos
  getVideos(id: string) {
    return apiClient.get<VideoOutput[]>(`/projects/${id}/videos`)
  },
}
