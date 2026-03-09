# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI Podcast - Health Science Video Generator. A system that converts health articles into oral broadcast videos using a 7-step pipeline.

## Commands

### Backend
```bash
cd /Users/mac/AI-Podcast/backend

# Install dependencies
pip install -r requirements.txt

# Run development server
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001

# Run with auto-reload
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

### Frontend
```bash
cd /Users/mac/AI-Podcast/frontend

# Install dependencies
npm install

# Run development server
npm run dev

# Build for production
npm run build
```

## Architecture

### 7-Step Pipeline
The system uses a pipeline with these steps:
1. `topic_input` - User input topic
2. `article_generation` - AI generates health article
3. `content_splitting` - Split article into segments
4. `image_generation` - Generate images for each segment
5. `script_generation` - Generate narration script
6. `tts_audio` - Text-to-speech synthesis
7. `video_composition` - Compose final video

### Backend Structure (`/backend/app/`)

- **`api/`** - FastAPI routes (projects, providers, pipeline, sources)
- **`models/`** - SQLAlchemy ORM models (project, segment, article, script, audio_asset, image_asset, video_output, provider_config)
- **`schemas/`** - Pydantic schemas for API request/response
- **`services/`** - Business logic (pipeline_service, audio_service, video_service, image_service, etc.)
- **`providers/`** - AI provider plugins with decorator-based registry
  - `text/` - Text generation (OpenAI, Claude, DeepSeek, Doubao, Qwen, Zhipu, MiniMax, etc.)
  - `image/` - Image generation (DALL-E, Stable Diffusion, Doubao Seedream, etc.)
  - `tts/` - Text-to-speech (OpenAI TTS, MiniMax, Doubao, CosyVoice)
  - `video/` - Video generation (experimental)
- **`video/`** - FFmpeg-based video composition
- **`utils/`** - Utilities (file_manager, text_splitter, rss_parser)

### Provider System
AI providers use a decorator-based registry:
```python
@ProviderRegistry.register
class MyProvider(TextProvider):
    metadata = ProviderMetadata(
        key="my_provider",
        name="My Provider",
        provider_type=ProviderType.TEXT,
        ...
    )
```

### Frontend Structure (`/frontend/src/`)

- **`views/`** - Page components (PipelineView, ImageGalleryView, VideoPreviewView, ProviderSettingsView)
- **`stores/`** - Pinia stores for state management
- **`api/`** - API client functions
- **`types/`** - TypeScript type definitions

## Key Configuration

- Backend config: `/backend/config.yaml`
- API runs on `http://localhost:8001`
- Frontend runs on `http://localhost:5173`
- Static files (images, audio) served from `/data` endpoint
- Database: SQLite at `./data/db/ai_podcast.db`

## API Endpoints

- `GET /api/v1/projects` - List projects
- `POST /api/v1/projects` - Create project
- `GET /api/v1/projects/{id}/pipeline` - Get pipeline status
- `POST /api/v1/projects/{id}/pipeline/run` - Run full pipeline
- `POST /api/v1/projects/{id}/pipeline/steps/{step}/run` - Run single step
- `POST /api/v1/projects/{id}/pipeline/steps/{step}/retry` - Retry failed step
- `GET /api/v1/providers` - List AI providers
- `POST /api/v1/providers` - Add provider
- `PUT /api/v1/providers/{id}` - Update provider

## Current Issues

- TTS (Doubao) requires a Volcano Engine TTS inference endpoint ID, not just model name
- Some providers need API keys configured via environment variables or UI settings
