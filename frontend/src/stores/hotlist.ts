import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { sourcesApi } from '../api/sources'
import type { HotTopicItem } from '../types/source'

export const useHotlistStore = defineStore('hotlist', () => {
  const topics = ref<HotTopicItem[]>([])
  const totalScraped = ref(0)
  const loading = ref(false)
  const selectedSources = ref<string[]>(['weibo', 'baidu', 'toutiao', 'tencent'])
  const activeCategory = ref('all')

  const categories = computed(() => {
    const cats = new Set(topics.value.map(t => t.category).filter(Boolean))
    return ['all', ...Array.from(cats)]
  })

  const filteredTopics = computed(() => {
    if (activeCategory.value === 'all') return topics.value
    return topics.value.filter(t => t.category === activeCategory.value)
  })

  async function fetchRecommendations() {
    loading.value = true
    try {
      const { data } = await sourcesApi.getHotRecommendations(selectedSources.value)
      topics.value = data.items
      totalScraped.value = data.total_scraped
      return data
    } finally {
      loading.value = false
    }
  }

  return {
    topics,
    totalScraped,
    loading,
    selectedSources,
    activeCategory,
    categories,
    filteredTopics,
    fetchRecommendations,
  }
})
