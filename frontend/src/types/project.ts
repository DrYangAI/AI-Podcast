export interface Project {
  id: string
  title: string
  topic: string
  source_type: string
  source_url: string | null
  aspect_ratio: string
  video_template: string
  image_prompt_language: string
  output_format: string
  image_width: number | null
  image_height: number | null
  image_quality: string
  image_style: string
  image_negative_prompt: string | null
  subtitle_enabled: boolean
  subtitle_font_size: number
  subtitle_font_color: string
  subtitle_outline_width: number
  subtitle_position: string
  subtitle_margin_bottom: number
  portrait_composite_enabled: boolean
  portrait_bg_color: string
  portrait_title_text: string | null
  portrait_title_font_size: number
  portrait_title_y: number
  portrait_video_y: number
  portrait_subtitle_font_size: number
  portrait_subtitle_margin_v: number
  tts_voice_id: string | null
  tts_voice_clone_id: string | null
  status: string
  created_at: string
  updated_at: string
}

export interface PipelineStep {
  id: string
  step_name: string
  step_order: number
  status: string
  error_message: string | null
  started_at: string | null
  completed_at: string | null
}

export interface Article {
  id: string
  title: string
  content: string
  word_count: number | null
  language: string
  is_manual: boolean
  version: number
  created_at: string
}

export interface Segment {
  id: string
  segment_order: number
  content: string
  image_prompt: string | null
  duration_hint: number | null
}

export interface ImageAsset {
  id: string
  segment_id: string
  file_path: string
  prompt_used: string | null
  width: number | null
  height: number | null
  is_manual: boolean
  status: string
  created_at: string
}

export interface Script {
  id: string
  content: string
  style: string | null
  is_manual: boolean
  version: number
  created_at: string
}

export interface AudioAsset {
  id: string
  file_path: string
  duration: number | null
  voice_id: string | null
  is_manual: boolean
  status: string
  created_at: string
}

export interface VideoOutput {
  id: string
  file_path: string
  file_name: string
  aspect_ratio: string
  template_used: string
  duration: number | null
  resolution: string | null
  file_size: number | null
  has_subtitles: boolean
  video_type: string
  status: string
  created_at: string
}

export interface ProjectDetail extends Project {
  pipeline_steps: PipelineStep[]
  article: Article | null
  script: Script | null
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}
