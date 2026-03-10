export interface VoiceClone {
  id: string
  name: string
  provider_key: string
  speaker_id: string
  reference_audio_path: string
  reference_text: string | null
  training_status: number  // 0=NotFound, 1=Training, 2=Success, 3=Failed, 4=Active
  is_default: boolean
  created_at: string
}

export interface PresetVoice {
  id: string
  name: string
  gender: string | null
  language: string | null
  provider_key: string | null
}

export interface VoicePreviewResponse {
  audio_path: string
  duration: number
}
