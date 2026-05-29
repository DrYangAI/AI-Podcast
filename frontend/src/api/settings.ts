import apiClient from './client'

export const settingsApi = {
  getDefaults(category: string) {
    return apiClient.get<Record<string, any>>(`/settings/defaults/${category}`)
  },

  setDefaults(category: string, data: Record<string, any>) {
    return apiClient.put<Record<string, any>>(`/settings/defaults/${category}`, data)
  },
}
