export interface ContentSource {
  id: string
  name: string
  source_type: string
  url: string
  category: string | null
  fetch_interval: number
  last_fetched_at: string | null
  is_active: boolean
  created_at: string
}

export interface FetchedTopic {
  id: string
  source_id: string
  title: string
  url: string | null
  summary: string | null
  fetched_at: string
  is_used: boolean
}

export interface HotTopicItem {
  title: string
  source: string
  source_name: string
  url: string | null
  rank: number
  heat: string
  relevance_score: number
  health_angle: string
  category: string
}

export interface HotTopicResponse {
  items: HotTopicItem[]
  total_scraped: number
  ai_filtered: number
}
