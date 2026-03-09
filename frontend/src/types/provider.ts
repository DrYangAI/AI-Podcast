export interface ProviderConfig {
  id: string
  name: string
  provider_type: string
  provider_key: string
  api_base_url: string | null
  model_id: string | null
  config: Record<string, any> | null
  is_default: boolean
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface ProviderTypeInfo {
  key: string
  name: string
  provider_type: string
  description: string
  supported_models: string[]
  requires_api_key: boolean
}
