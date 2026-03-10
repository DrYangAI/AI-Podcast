"""Portrait composite service - converts 16:9 video to 9:16 portrait layout.

Layout (1080x1920):
┌──────────────────────┐
│      项目标题        │  ← 顶部标题区 (HEADER_HEIGHT px)
├──────────────────────┤
│                      │
│   16:9 核心画面      │  ← 视频区 (VIDEO_WIDTH x VIDEO_HEIGHT)
│                      │
├──────────────────────┤
│                      │
│    实时字幕区域      │  ← 底部字幕区 (剩余空间)
│                      │
└──────────────────────┘
"""

import logging
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from ..database import async_session_factory
from ..models import Project, Segment, Script, AudioAsset, VideoOutput
from ..config import get_settings
from ..video.ffmpeg_builder import FFmpegBuilder
from ..video.subtitle_renderer import SubtitleRenderer
from ..video.composer import calculate_segment_durations, _hex_color_to_ass
from .audio_service import clean_script_for_tts

logger = logging.getLogger(__name__)

# ── Layout constants for 1080x1920 portrait ──
PORTRAIT_WIDTH = 1080
PORTRAIT_HEIGHT = 1920
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 608  # 1080 * 9/16 ≈ 607.5 → 608
HEADER_HEIGHT = 200
# 视频放在中间偏上：标题下方留一段间距，视频不紧贴标题
VIDEO_Y_OFFSET = 480  # 标题(200) + 间距(280) → 视频从 480 开始
SUBTITLE_AREA_TOP = VIDEO_Y_OFFSET + VIDEO_HEIGHT  # = 1088


class PortraitCompositeService:
    """Composites a 16:9 video into a 9:16 portrait layout."""

    def __init__(self):
        self.ffmpeg = FFmpegBuilder()

    async def compose_portrait(self, project_id: str):
        settings = get_settings()

        async with async_session_factory() as db:
            project = await db.get(Project, project_id)
            if not project:
                raise ValueError(f"Project {project_id} not found")

            # 查找步骤 7 生成的横屏视频
            result = await db.execute(
                select(VideoOutput)
                .where(
                    VideoOutput.project_id == project_id,
                    VideoOutput.status == "completed",
                    VideoOutput.video_type == "standard",
                )
                .order_by(VideoOutput.created_at.desc())
            )
            landscape_video = result.scalars().first()
            if not landscape_video:
                raise ValueError("未找到已完成的横屏视频，请先运行视频合成步骤")

            input_path = Path(landscape_video.file_path)
            if not input_path.exists():
                raise ValueError(f"横屏视频文件不存在: {input_path}")

            # 始终重新生成 SRT，确保使用最新的口播稿内容
            srt_path = await self._generate_srt(project_id, settings)

            # 构建输出路径
            output_dir = Path(settings.storage.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_topic = re.sub(r'[<>:"/\\|?*\s]+', '_', project.topic[:30]).strip('_')
            output_filename = f"{timestamp}_{safe_topic}_9x16_portrait.mp4"
            output_path = output_dir / output_filename

            # 读取设置
            bg_color = getattr(project, "portrait_bg_color", "#1A1A2E")
            title_text = getattr(project, "portrait_title_text", None) or project.title

            # 读取竖屏布局设置（标题/字幕位置与大小）
            portrait_layout = {
                "title_font_size": getattr(project, "portrait_title_font_size", 36),
                "title_y": getattr(project, "portrait_title_y", 82),
                "video_y": getattr(project, "portrait_video_y", VIDEO_Y_OFFSET),
                "subtitle_font_size": getattr(project, "portrait_subtitle_font_size", 38),
                "subtitle_margin_v": getattr(project, "portrait_subtitle_margin_v", 550),
            }

            # 构建 FFmpeg 命令
            command = self._build_ffmpeg_command(
                input_video=input_path,
                srt_path=srt_path,
                output_path=output_path,
                bg_color=bg_color,
                title_text=title_text,
                portrait_layout=portrait_layout,
                subtitle_config={
                    "font_size": getattr(project, "subtitle_font_size", 24),
                    "font_color": getattr(project, "subtitle_font_color", "#FFFFFF"),
                    "outline_width": getattr(project, "subtitle_outline_width", 1),
                },
                video_quality={
                    "crf": settings.output.video_quality.crf,
                    "codec": settings.output.video_quality.codec,
                    "audio_codec": settings.output.video_quality.audio_codec,
                },
            )

            logger.info(f"Portrait composite FFmpeg command: {' '.join(command)}")

            # 执行 FFmpeg
            returncode, stdout, stderr = await self.ffmpeg.execute(command)
            if returncode != 0:
                logger.error(f"Portrait composite failed: {stderr[-1000:]}")
                raise RuntimeError(f"竖屏合成 FFmpeg 失败 (code {returncode}): {stderr[-500:]}")

            # 获取文件大小
            file_size = output_path.stat().st_size if output_path.exists() else 0

            # 保存竖屏视频记录
            video = VideoOutput(
                project_id=project_id,
                file_path=str(output_path),
                file_name=output_path.name,
                aspect_ratio="9:16",
                template_used=landscape_video.template_used,
                duration=landscape_video.duration,
                resolution=f"{PORTRAIT_WIDTH}x{PORTRAIT_HEIGHT}",
                file_size=file_size,
                has_subtitles=True,
                video_type="portrait",
                status="completed",
            )
            db.add(video)
            await db.commit()
            return video

    def _build_ffmpeg_command(
        self,
        input_video: Path,
        srt_path: Path | None,
        output_path: Path,
        bg_color: str,
        title_text: str,
        portrait_layout: dict,
        subtitle_config: dict,
        video_quality: dict,
    ) -> list[str]:
        """Build the FFmpeg command for portrait compositing.

        Filter chain:
        ① color background canvas (1080x1920)
        ② scale input 16:9 video to 1080x608
        ③ overlay video onto canvas at y=video_y
        ④ drawtext for title
        ⑤ subtitles in bottom area
        """
        # 转义标题中的特殊字符（FFmpeg drawtext 格式）
        safe_title = title_text.replace("\\", "\\\\").replace("'", "'\\''").replace(":", "\\:")
        # 截断过长标题
        if len(title_text) > 30:
            safe_title_display = title_text[:28] + "…"
            safe_title = safe_title_display.replace("\\", "\\\\").replace("'", "'\\''").replace(":", "\\:")

        # 从布局配置读取（可在前端调整）
        title_font_size = portrait_layout.get("title_font_size", 36)
        title_y = portrait_layout.get("title_y", 82)
        video_y = portrait_layout.get("video_y", VIDEO_Y_OFFSET)
        portrait_font_size = portrait_layout.get("subtitle_font_size", 38)
        subtitle_margin_v = portrait_layout.get("subtitle_margin_v", 550)

        font_color = subtitle_config.get("font_color", "#FFFFFF")
        outline_width = subtitle_config.get("outline_width", 2)

        filter_parts = []

        # ① 纯色背景画布
        filter_parts.append(
            f"color=c={bg_color}:s={PORTRAIT_WIDTH}x{PORTRAIT_HEIGHT}:r=25[bg]"
        )

        # ② 缩放输入视频
        filter_parts.append(
            f"[0:v]scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:"
            f"force_original_aspect_ratio=decrease,"
            f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color={bg_color}[vid]"
        )

        # ③ 叠加视频到画布（使用可配置的 video_y）
        filter_parts.append(
            f"[bg][vid]overlay=0:{video_y}:shortest=1[canvas]"
        )

        # ④ 绘制标题文本（使用可配置的 title_y 和 title_font_size）
        font_file = "/System/Library/Fonts/STHeiti Medium.ttc"

        filter_parts.append(
            f"[canvas]drawtext="
            f"text='{safe_title}':"
            f"fontfile='{font_file}':"
            f"fontsize={title_font_size}:"
            f"fontcolor=white:"
            f"x=(w-text_w)/2:"
            f"y={title_y}:"
            f"shadowcolor=black@0.5:shadowx=2:shadowy=2"
            f"[titled]"
        )

        # ⑤ 添加字幕（使用可配置的 portrait_font_size 和 subtitle_margin_v）
        final_label = "titled"
        if srt_path and srt_path.exists():
            safe_srt = str(srt_path).replace("\\", "/").replace(":", "\\\\:")
            pc = _hex_color_to_ass(font_color)
            oc = _hex_color_to_ass("#000000")
            filter_parts.append(
                f"[titled]subtitles='{safe_srt}':force_style="
                f"'FontName=PingFang SC,"
                f"FontSize={portrait_font_size},"
                f"PrimaryColour={pc},"
                f"OutlineColour={oc},"
                f"Outline={outline_width},"
                f"MarginV={subtitle_margin_v},"
                f"Alignment=2,"
                f"PlayResX={PORTRAIT_WIDTH},"
                f"PlayResY={PORTRAIT_HEIGHT}'"
                f"[final]"
            )
            final_label = "final"

        filter_complex = ";".join(filter_parts)

        codec = video_quality.get("codec", "libx264")
        crf = video_quality.get("crf", 23)
        audio_codec = video_quality.get("audio_codec", "aac")

        args = [
            "ffmpeg", "-y",
            "-i", str(input_video),
            "-filter_complex", filter_complex,
            "-map", f"[{final_label}]",
            "-map", "0:a",
            "-c:v", codec,
            "-crf", str(crf),
            "-preset", "medium",
            "-c:a", audio_codec,
            "-shortest",
            "-pix_fmt", "yuv420p",
            str(output_path),
        ]
        return args

    async def _generate_srt(self, project_id: str, settings) -> Path | None:
        """Generate SRT file if not available from step 7.

        Uses Script (口播稿) content for subtitles so they match the TTS narration.
        Falls back to Segment content if no script is available.
        """
        async with async_session_factory() as db:
            result = await db.execute(
                select(Segment)
                .where(Segment.project_id == project_id)
                .order_by(Segment.segment_order)
            )
            segments = list(result.scalars().all())

            result = await db.execute(
                select(AudioAsset).where(AudioAsset.project_id == project_id)
            )
            audio = result.scalar_one_or_none()

            if not segments or not audio or not audio.duration:
                return None

            # Try to use script (口播稿) content for subtitles
            result = await db.execute(
                select(Script).where(Script.project_id == project_id)
            )
            script = result.scalar_one_or_none()

            from .video_service import _split_script_to_paragraphs
            script_paragraphs = _split_script_to_paragraphs(script, len(segments)) if script else None

            if script_paragraphs and len(script_paragraphs) >= len(segments):
                segment_texts = script_paragraphs[:len(segments)]
            else:
                # Fallback to segment content
                segment_texts = [s.content for s in segments]

            durations = calculate_segment_durations(segment_texts, audio.duration)

            srt_dir = Path(settings.storage.base_dir) / "subtitles" / project_id
            srt_dir.mkdir(parents=True, exist_ok=True)
            srt_path = srt_dir / "portrait_subtitles.srt"

            renderer = SubtitleRenderer()
            renderer.generate_srt(
                segments=segment_texts,
                durations=durations,
                output_path=srt_path,
                max_chars_per_line=settings.subtitles.max_chars_per_line,
                max_lines=settings.subtitles.max_lines,
            )
            return srt_path
