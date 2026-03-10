import apiClient from './client'
import type { ProviderConfig, ProviderTypeInfo } from '../types/provider'
import type { PresetVoice } from '../types/voice'

export const providersApi = {
  list(providerType?: string) {
    return apiClient.get<ProviderConfig[]>('/providers', {
      params: providerType ? { provider_type: providerType } : undefined,
    })
  },

  listTypes() {
    return apiClient.get<ProviderTypeInfo[]>('/providers/types')
  },

  create(data: {
    name: string
    provider_type: string
    provider_key: string
    api_key?: string
    api_base_url?: string
    model_id?: string
    config?: Record<string, any>
    is_default?: boolean
  }) {
    return apiClient.post<ProviderConfig>('/providers', data)
  },

  update(id: string, data: Partial<ProviderConfig & { api_key?: string }>) {
    return apiClient.put<ProviderConfig>(`/providers/${id}`, data)
  },

  delete(id: string) {
    return apiClient.delete(`/providers/${id}`)
  },

  test(id: string) {
    return apiClient.post<{ success: boolean; message: string }>(`/providers/${id}/test`)
  },

  listVoices(providerId: string) {
    return apiClient.get<PresetVoice[]>(`/providers/${providerId}/voices`)
  },
}
