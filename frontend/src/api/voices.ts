import apiClient from './client'
import type { VoiceClone, VoicePreviewResponse } from '../types/voice'

export const voicesApi = {
  list() {
    return apiClient.get<VoiceClone[]>('/voices')
  },

  get(id: string) {
    return apiClient.get<VoiceClone>(`/voices/${id}`)
  },

  clone(formData: FormData) {
    return apiClient.post<VoiceClone>('/voices/clone', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  update(id: string, data: { name?: string; reference_text?: string; is_default?: boolean }) {
    return apiClient.put<VoiceClone>(`/voices/${id}`, data)
  },

  delete(id: string) {
    return apiClient.delete(`/voices/${id}`)
  },

  preview(id: string) {
    return apiClient.post<VoicePreviewResponse>(`/voices/${id}/preview`, null, {
      // 本地 VoxCPM(2B/MPS)在内存吃紧时合成较慢,放宽到 5 分钟避免前端先超时
      timeout: 300000,
    })
  },

  refreshStatus(id: string) {
    return apiClient.post<VoiceClone>(`/voices/${id}/refresh-status`)
  },
}
