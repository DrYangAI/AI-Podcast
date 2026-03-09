import apiClient from './client'
import type { ContentSource, FetchedTopic, HotTopicResponse } from '../types/source'
import type { Project } from '../types/project'

export const sourcesApi = {
  list() {
    return apiClient.get<ContentSource[]>('/sources')
  },

  create(data: { name: string; source_type: string; url: string; category?: string; fetch_interval?: number }) {
    return apiClient.post<ContentSource>('/sources', data)
  },

  update(id: string, data: Partial<ContentSource>) {
    return apiClient.put<ContentSource>(`/sources/${id}`, data)
  },

  delete(id: string) {
    return apiClient.delete(`/sources/${id}`)
  },

  getTopics(sourceId: string) {
    return apiClient.get<FetchedTopic[]>(`/sources/${sourceId}/topics`)
  },

  fetch(sourceId: string) {
    return apiClient.post<FetchedTopic[]>(`/sources/${sourceId}/fetch`)
  },

  createProjectFromTopic(topicId: string) {
    return apiClient.post<Project>(`/sources/topics/${topicId}/create-project`)
  },

  extractUrl(url: string) {
    return apiClient.post<{ title: string; content: string; url: string }>('/sources/extract-url', { url })
  },

  getHotRecommendations(sources?: string[], maxResults?: number) {
    return apiClient.post<HotTopicResponse>('/sources/hotlist/recommend', {
      sources,
      max_results: maxResults || 15,
    })
  },

  createProjectFromHotTopic(data: { title: string; health_angle?: string; source_url?: string }) {
    return apiClient.post<Project>('/sources/hotlist/create-project', data)
  },
}
