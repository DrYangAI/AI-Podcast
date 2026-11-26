import apiClient from './client'

export interface PricingEntry {
  provider_type: string
  provider_key: string
  model_id: string
  unit: string              // image / char / token_in / token_out
  price: number             // 元/张 | 元/万字 | 元/百万token
  note: string
}

export interface UsageSummary {
  total_cost: number
  currency: string
  record_count: number
  by_type: { provider_type: string; type_name: string; cost: number }[]
  by_model: {
    provider_type: string; type_name: string; provider_key: string
    model_id: string; unit: string; quantity: number; cost: number
  }[]
  by_day: { day: string; cost: number }[]
  by_project: Record<string, number>
}

export const usageApi = {
  getSummary(params: { project_id?: string; days?: number } = {}) {
    return apiClient.get<UsageSummary>('/usage/summary', { params })
  },
  getPricing() {
    return apiClient.get<{ entries: PricingEntry[] }>('/usage/pricing')
  },
  savePricing(entries: PricingEntry[]) {
    return apiClient.put<{ entries: PricingEntry[] }>('/usage/pricing', { entries })
  },
}
