export interface PromptTemplate {
  id: string
  step_name: string
  description: string
  system_prompt: string
  user_prompt_template: string
  temperature: number
  max_tokens: number
  variables: string[]
  variable_descriptions: Record<string, string>
  extra_config: Record<string, any> | null
  updated_at: string
  created_at: string
}

export interface PromptTemplateUpdate {
  system_prompt?: string
  user_prompt_template?: string
  temperature?: number
  max_tokens?: number
  extra_config?: Record<string, any>
}

export interface PromptTemplateHistory {
  id: string
  template_id: string
  step_name: string
  version: number
  system_prompt: string
  user_prompt_template: string
  temperature: number
  max_tokens: number
  extra_config: Record<string, any> | null
  change_source: string
  created_at: string
}

export interface ResolvedPromptConfig {
  step_name: string
  description: string
  system_prompt: string
  user_prompt_template: string
  temperature: number
  max_tokens: number
  variables: string[]
  variable_descriptions: Record<string, string>
  is_override: boolean
}

export interface ProjectPromptOverride {
  system_prompt?: string
  user_prompt_template?: string
  temperature?: number
  max_tokens?: number
}
