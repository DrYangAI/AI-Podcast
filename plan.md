Context
你是一位医生和诊所老板，希望每天将热门健康话题（儿科、生活方式医学、长寿医学、功能医学、医学科技前沿）制作成口播视频。系统需要支持：话题输入 → 文字科普 → 图片生成 → 口播稿 → TTS/录音 → 视频合成的完整流水线，并且每一步都可以配置不同的 AI 模型、可编辑、可重新生成。

技术选型
层技术理由后端Python + FastAPIAI 生态最佳，异步支持好前端Vue 3 + TypeScript + Element PlusElement Plus 中文支持优秀数据库SQLite (aiosqlite)单用户场景，免运维视频合成FFmpeg (subprocess)机器已安装 ffmpeg 7.0，性能优于 MoviePy任务队列Huey (SQLite backend)轻量，无需 Redis配置YAML支持多行 Prompt 模板

项目结构
AI-Podcast/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI 入口
│   │   ├── config.py                  # Pydantic Settings 配置加载
│   │   ├── database.py                # SQLAlchemy 引擎 + Session
│   │   ├── models/                    # ORM 模型
│   │   │   ├── project.py             # 项目（核心实体）
│   │   │   ├── pipeline_step.py       # 流水线步骤状态
│   │   │   ├── article.py             # 生成的文章
│   │   │   ├── segment.py             # 段落切片
│   │   │   ├── image_asset.py         # 图片资源
│   │   │   ├── script.py              # 口播稿
│   │   │   ├── audio_asset.py         # 音频资源
│   │   │   ├── video_output.py        # 视频输出
│   │   │   ├── provider_config.py     # AI 模型配置
│   │   │   └── content_source.py      # 内容来源（RSS/网站）
│   │   ├── schemas/                   # Pydantic 请求/响应 Schema
│   │   ├── api/                       # API 路由
│   │   │   ├── projects.py, pipeline.py, articles.py, segments.py
│   │   │   ├── images.py, scripts.py, audio.py, videos.py
│   │   │   ├── providers.py, sources.py, templates.py
│   │   │   └── router.py             # 路由汇总
│   │   ├── services/                  # 业务逻辑层
│   │   │   ├── pipeline_service.py    # 流水线编排（核心）
│   │   │   ├── article_service.py, segment_service.py
│   │   │   ├── image_service.py, script_service.py
│   │   │   ├── audio_service.py, video_service.py
│   │   │   ├── source_service.py, provider_service.py
│   │   ├── providers/                 # AI 模型插件系统
│   │   │   ├── base.py                # 抽象基类 + ProviderMetadata
│   │   │   ├── registry.py            # 插件注册中心
│   │   │   ├── text/                  # 文字生成: claude, openai, qwen, zhipu, wenxin
│   │   │   ├── image/                 # 图片生成: dalle, midjourney, flux, tongyi, zhipu
│   │   │   ├── tts/                   # 语音合成: openai_tts, elevenlabs, ali, xunfei
│   │   │   └── video/                 # 预留: 图生视频
│   │   ├── video/                     # 视频合成引擎
│   │   │   ├── composer.py            # 合成主控
│   │   │   ├── ffmpeg_builder.py      # FFmpeg 命令构建器
│   │   │   ├── subtitle_renderer.py   # SRT 字幕生成
│   │   │   ├── image_processor.py     # 图片缩放/裁切/填充
│   │   │   └── templates/             # 视频模板: slideshow, kenburns, transitions, minimal
│   │   ├── tasks/                     # Huey 后台任务
│   │   └── utils/                     # 工具: file_manager, text_splitter, rss_parser, web_scraper
│   ├── config.yaml                    # 主配置文件
│   ├── config.example.yaml
│   ├── requirements.txt
│   └── alembic/                       # 数据库迁移
├── frontend/
│   ├── src/
│   │   ├── views/                     # 页面
│   │   │   ├── DashboardView.vue      # 首页仪表盘
│   │   │   ├── ProjectListView.vue    # 项目列表
│   │   │   ├── PipelineView.vue       # 流水线控制台（核心页面）
│   │   │   ├── ArticleEditorView.vue  # 文章编辑器
│   │   │   ├── ImageGalleryView.vue   # 图片画廊
│   │   │   ├── ScriptEditorView.vue   # 口播稿编辑
│   │   │   ├── AudioManagerView.vue   # 音频管理
│   │   │   ├── VideoPreviewView.vue   # 视频预览
│   │   │   └── ProviderSettingsView.vue # 模型配置
│   │   ├── components/, stores/, api/, composables/, types/
│   │   └── router/
│   ├── package.json
│   └── vite.config.ts
└── docker-compose.yml

数据库设计 (SQLite)
核心实体关系: Project → Article → Segments[] → ImageAsset[] + Script → AudioAsset → VideoOutput
表作用关键字段projects项目（一个视频对应一个项目）title, topic, aspect_ratio, video_template, statuspipeline_steps7 个步骤的执行状态project_id, step_name, status, provider_id, error_messagearticlesAI 生成或手动输入的文章project_id, content, provider_id, is_manual, versionsegments按段落拆分的内容片段article_id, segment_order, content, image_promptimage_assets每段对应的图片segment_id, file_path, prompt_used, provider_id, is_manualscripts口播稿project_id, content, style, provider_idaudio_assetsTTS 或手动上传的音频project_id, file_path, duration, voice_id, is_manualvideo_outputs最终视频project_id, file_path, aspect_ratio, template_used, durationprovider_configsAI 模型配置provider_type, provider_key, api_key, model_id, is_defaultcontent_sourcesRSS/网站来源source_type, url, category, fetch_intervalfetched_topics自动抓取的话题source_id, title, url, is_used

AI 模型插件架构
采用 抽象基类 + 注册器 模式。每个 Provider 实现统一接口，通过 @ProviderRegistry.register 装饰器自动注册。
BaseProvider (ABC)
├── TextProvider → generate(prompt) → TextGenerationResponse
│   ├── ClaudeProvider
│   ├── OpenAIProvider
│   ├── QwenProvider, ZhipuProvider, WenxinProvider
├── ImageProvider → generate(prompt, size) → ImageGenerationResponse
│   ├── DalleProvider, FluxProvider
│   ├── TongyiWanxiangProvider, ZhipuImageProvider
├── TTSProvider → synthesize(text, voice) → TTSResponse
│   ├── OpenAITTSProvider, ElevenLabsProvider
│   ├── AliTTSProvider, XunfeiProvider
└── VideoProvider (预留)
启动时自动扫描 providers/*/ 目录下的模块，触发注册。用户在 Web UI 中配置 API Key 和默认模型。

核心流水线 (7 步)
1. 话题输入 → 2. 文章生成 → 3. 内容拆分 → 4. 图片生成 → 5. 口播稿生成 → 6. 音频(TTS/上传) → 7. 视频合成

每步独立可重跑，支持从任意步骤开始
每步修改后可从该步重新生成后续步骤
异步执行，WebSocket 推送实时进度
pipeline_service.py 负责编排，Huey 负责后台执行


视频合成引擎

使用 FFmpeg subprocess 直接调用
支持 4 种模板: 幻灯片(slideshow)、Ken Burns 缩放平移、过渡特效(transitions)、简约(minimal)
支持 3 种比例: 9:16 竖屏、16:9 横屏、1:1 方形
自动生成 SRT 字幕（中文每行 20 字，2 行）
图片自动缩放/裁切适配目标分辨率
段落时长按文字长度比例分配音频总时长


API 概要 (所有以 /api/v1/ 为前缀)

项目: CRUD /projects, 复制 /projects/{id}/duplicate
流水线: /projects/{id}/pipeline/run, /pipeline/steps/{step}/run, 支持 from_step 断点续跑
文章: 生成/编辑 /projects/{id}/article
段落: 拆分/排序/编辑 /projects/{id}/segments
图片: 生成/上传/编辑 Prompt /projects/{id}/images
口播稿: 生成/编辑 /projects/{id}/script
音频: TTS 生成/上传 /projects/{id}/audio
视频: 合成/预览/下载 /projects/{id}/video
模型配置: CRUD /providers, 连通性测试 /providers/{id}/test
内容来源: CRUD /sources, 立即抓取 /sources/{id}/fetch
异步任务: 状态查询 /tasks/{id}, WebSocket /ws/tasks/{id}


输出自定义

可配置输出目录
命名规则支持变量: {date}_{topic}_{aspect_ratio} 等
配置文件 config.yaml 中定义默认值，Web UI 可覆盖


实施顺序
阶段内容Phase 1: 基础项目脚手架、数据库模型、配置加载、Provider 基类和注册器Phase 2: 核心后端项目 CRUD、文章/段落/图片/口播稿/音频 Service + API，实现 Claude + DALL-E + OpenAI TTS 各一个参考 ProviderPhase 3: 视频引擎图片预处理、字幕渲染、FFmpeg 构建器、Slideshow + Ken Burns 模板Phase 4: 流水线编排Huey 集成、Pipeline 编排、WebSocket 实时更新、断点续跑Phase 5: 前端Vue 项目搭建、所有页面组件开发Phase 6: 扩展RSS/网站抓取、更多 AI Provider、更多视频模板Phase 7: 测试单元测试、集成测试、文档

验证方式

启动后端 uvicorn app.main:app --reload，检查 /docs Swagger UI 可用
在 Provider 设置页配置至少一个 Text/Image/TTS Provider 的 API Key
创建项目 → 输入话题 → 点击「运行流水线」→ 观察 7 步依次执行
验证每一步输出可编辑、可重新生成
最终生成的 MP4 视频可正常播放，包含图片轮播 + 字幕 + 音频
切换不同 Provider（如 Claude → GPT）重新生成文章，对比结果


关键依赖
后端: fastapi, uvicorn, sqlalchemy[asyncio], aiosqlite, pydantic-settings, alembic, Pillow, httpx, feedparser, beautifulsoup4, anthropic, openai, pyyaml, huey, python-multipart, cryptography
前端: vue 3, vite, vue-router, pinia, axios, element-plus, md-editor-v3, typescript