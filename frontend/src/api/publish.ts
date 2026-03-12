import apiClient from './client'

export interface PublishAsset {
  id: string
  platform: string
  cover_path: string | null
  cover_width: number | null
  cover_height: number | null
  cover_status: string
  title: string
  description: string
  tags: string | null
  status: string
  created_at: string
}

export interface PublishAssetUpdate {
  title?: string
  description?: string
  tags?: string
}

export interface CoverPrompt {
  prompt: string | null
}

export const publishApi = {
  getAssets(projectId: string) {
    return apiClient.get<PublishAsset[]>(`/projects/${projectId}/publish-assets`)
  },

  updateAsset(projectId: string, platform: string, data: PublishAssetUpdate) {
    return apiClient.put<PublishAsset>(`/projects/${projectId}/publish-assets/${platform}`, data)
  },

  useSegmentAsCover(projectId: string, segmentId: string) {
    return apiClient.post(`/projects/${projectId}/publish-assets/from-segment/${segmentId}`)
  },

  regenerateCover(projectId: string, prompt?: string) {
    return apiClient.post(`/projects/${projectId}/publish-assets/regenerate-cover`,
      prompt !== undefined ? { prompt } : null)
  },

  uploadCover(projectId: string, platform: string, file: File) {
    const formData = new FormData()
    formData.append('file', file)
    return apiClient.post<PublishAsset>(
      `/projects/${projectId}/publish-assets/${platform}/upload-cover`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    )
  },

  getCoverPrompt(projectId: string) {
    return apiClient.get<CoverPrompt>(`/projects/${projectId}/publish-assets/cover-prompt`)
  },

  updateCoverPrompt(projectId: string, prompt: string) {
    return apiClient.put<CoverPrompt>(`/projects/${projectId}/publish-assets/cover-prompt`, { prompt })
  },
}
