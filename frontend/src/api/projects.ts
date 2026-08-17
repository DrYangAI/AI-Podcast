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

  create(data: { title: string; topic: string; aspect_ratio?: string; video_template?: string; image_prompt_language?: string; reference_content?: string; source_type?: string; source_url?: string }) {
    return apiClient.post<Project>('/projects', data)
  },

  importPpt(file: File, opts: { title: string; aspect_ratio?: string; video_template?: string; subtitle_enabled?: boolean }) {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('title', opts.title)
    if (opts.aspect_ratio) formData.append('aspect_ratio', opts.aspect_ratio)
    if (opts.video_template) formData.append('video_template', opts.video_template)
    if (opts.subtitle_enabled !== undefined) formData.append('subtitle_enabled', String(opts.subtitle_enabled))
    return apiClient.post<Project>('/projects/import-ppt', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
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
  updateSegment(projectId: string, segmentId: string, data: { content?: string; image_prompt?: string; chapter_title?: string; script_text?: string }) {
    return apiClient.put<Segment>(`/projects/${projectId}/segments/${segmentId}`, data)
  },
  createSegment(projectId: string, data: { content: string; image_prompt?: string; chapter_title?: string; script_text?: string; position?: number }) {
    return apiClient.post<Segment>(`/projects/${projectId}/segments`, data)
  },
  deleteSegment(projectId: string, segmentId: string) {
    return apiClient.delete(`/projects/${projectId}/segments/${segmentId}`)
  },
  regenerateSegmentScript(projectId: string, segmentId: string) {
    return apiClient.post<Segment>(`/projects/${projectId}/segments/${segmentId}/script/regenerate`, null, {
      timeout: 60000,
    })
  },
  generateChapterTitles(projectId: string) {
    return apiClient.post<Segment[]>(`/projects/${projectId}/segments/generate-chapter-titles`, null, {
      timeout: 60000,
    })
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
  getAudioChunks(id: string) {
    return apiClient.get<any>(`/projects/${id}/audio/chunks`)
  },
  getTtsProgress(id: string) {
    return apiClient.get<{ total: number; done: number; status: string; segments: { order: number; url: string }[] }>(
      `/projects/${id}/audio/tts-progress`
    )
  },
  regenerateAudioChunk(id: string, chunkIndex: number) {
    return apiClient.post<any>(`/projects/${id}/audio/chunks/${chunkIndex}/regenerate`)
  },
  concatenateAudioChunks(id: string) {
    return apiClient.post<any>(`/projects/${id}/audio/concatenate`)
  },

  // Videos
  getVideos(id: string) {
    return apiClient.get<VideoOutput[]>(`/projects/${id}/videos`)
  },
  deleteVideo(projectId: string, videoId: string) {
    return apiClient.delete(`/projects/${projectId}/videos/${videoId}`)
  },
}
