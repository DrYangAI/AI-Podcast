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
from ..video.subtitle_renderer import SubtitleRenderer, chars_per_line, SUBTITLE_SIDE_MARGIN
from ..video.composer import calculate_segment_durations, _hex_color_to_ass
from .audio_service import clean_script_for_tts, uses_per_segment_tts

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

# 折行时不让标点落在行首(会另起一行只剩一个逗号很难看)
_LEADING_PUNCT = "，。！？、；：,.!?;:…）】」》"


def _wrap_cjk(text: str, max_chars: int, max_lines: int = 3) -> list[str]:
    """把标题/副标题折成多行。

    优先尊重用户在标题文本里手动敲的回车(\\n):先按手动换行分段,每段再按每行
    max_chars 个字自动折(防止某一段仍然过长顶出画面)。drawtext 自己不换行,所以
    折行必须在送进 ffmpeg 之前做好。中文是方块字,按字数折足够准;标点尽量收在行尾、
    不落在行首。总行数超过 max_lines 则截断,末行以 … 收尾。
    """
    if not (text or "").strip():
        return []

    lines: list[str] = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue  # 跳过空行(连按两次回车不产生空白行)
        if max_chars <= 0:
            lines.append(para)
            continue

        # 段内按字数贪心折
        chunks: list[str] = []
        cur = ""
        for ch in para:
            cur += ch
            if len(cur) >= max_chars:
                chunks.append(cur)
                cur = ""
        if cur:
            chunks.append(cur)

        # 把落在行首的标点挪回上一行末尾(仅在本段内,不跨手动换行)
        fixed: list[str] = []
        for ln in chunks:
            while ln and ln[0] in _LEADING_PUNCT and fixed:
                fixed[-1] += ln[0]
                ln = ln[1:]
            if ln:
                fixed.append(ln)
        lines.extend(fixed or [para])

    if not lines:
        return [text.strip()]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        if max_chars > 0:
            lines[-1] = lines[-1][: max(1, max_chars - 1)] + "…"
        else:
            lines[-1] = lines[-1] + "…"
    return lines


def _escape_drawtext(s: str) -> str:
    """转义 drawtext text 里的特殊字符。"""
    return s.replace("\\", "\\\\").replace("'", "'\\''").replace(":", "\\:")


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
                "title_color": getattr(project, "portrait_title_color", "#FFFFFF"),
                "title_outline_color": getattr(project, "portrait_title_outline_color", "#000000"),
                "title_outline_width": getattr(project, "portrait_title_outline_width", 2),
                "title_shadow_enabled": getattr(project, "portrait_title_shadow_enabled", True),
                "title_shadow_color": getattr(project, "portrait_title_shadow_color", "#000000"),
                "title_shadow_opacity": getattr(project, "portrait_title_shadow_opacity", 0.5),
                "title_shadow_x": getattr(project, "portrait_title_shadow_x", 2),
                "title_shadow_y": getattr(project, "portrait_title_shadow_y", 2),
                "sub_title_text": getattr(project, "portrait_sub_title_text", None),
                "sub_title_font_size": getattr(project, "portrait_sub_title_font_size", 24),
                "sub_title_color": getattr(project, "portrait_sub_title_color", "#CCCCCC"),
                "sub_title_y": getattr(project, "portrait_sub_title_y", 130),
                "title_bg_enabled": getattr(project, "portrait_title_bg_enabled", False),
                "title_bg_color": getattr(project, "portrait_title_bg_color", "#000000"),
                "title_bg_opacity": getattr(project, "portrait_title_bg_opacity", 0.5),
                "title_bg_padding": getattr(project, "portrait_title_bg_padding", 20),
                "title_bg_shape": getattr(project, "portrait_title_bg_shape", "rect"),
                "title_bg_radius": getattr(project, "portrait_title_bg_radius", 16),
                "title_bg_skew": getattr(project, "portrait_title_bg_skew", 10),
            }

            # Generate title overlay PNG if using non-rect background shape
            title_overlay_path = None
            title_bg_shape = portrait_layout.get("title_bg_shape", "rect")
            if portrait_layout.get("title_bg_enabled") and title_bg_shape != "rect":
                from ..utils.title_overlay import generate_title_overlay
                title_overlay_path = output_dir / f"_title_overlay_{project_id}.png"
                generate_title_overlay(
                    title=title_text,
                    sub_title=portrait_layout.get("sub_title_text"),
                    canvas_width=PORTRAIT_WIDTH,
                    bg_color=portrait_layout.get("title_bg_color", "#FFD700"),
                    bg_opacity=portrait_layout.get("title_bg_opacity", 0.9),
                    bg_shape=title_bg_shape,
                    bg_radius=portrait_layout.get("title_bg_radius", 16),
                    bg_skew=portrait_layout.get("title_bg_skew", 10),
                    title_font_size=portrait_layout.get("title_font_size", 52),
                    title_color=portrait_layout.get("title_color", "#000000"),
                    title_outline_width=portrait_layout.get("title_outline_width", 0),
                    title_outline_color=portrait_layout.get("title_outline_color", "#000000"),
                    sub_title_font_size=portrait_layout.get("sub_title_font_size", 24),
                    sub_title_color=portrait_layout.get("sub_title_color", "#333333"),
                    padding=portrait_layout.get("title_bg_padding", 30),
                    output_path=title_overlay_path,
                )
                logger.info("Generated title overlay: %s", title_overlay_path)

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
                title_overlay_path=title_overlay_path,
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
        title_overlay_path: Path | None = None,
    ) -> list[str]:
        """Build the FFmpeg command for portrait compositing.

        Filter chain:
        ① color background canvas (1080x1920)
        ② scale input 16:9 video to 1080x608
        ③ overlay video onto canvas at y=video_y
        ④ drawtext for title
        ⑤ subtitles in bottom area
        """
        # 标题的折行/转义放到 drawtext 分支里做(overlay 模式用 PNG,不需要),
        # 因为要用到下面读出来的 title_font_size 才能算每行放几个字。

        # 从布局配置读取（可在前端调整）
        title_font_size = portrait_layout.get("title_font_size", 36)
        title_y = portrait_layout.get("title_y", 82)
        video_y = portrait_layout.get("video_y", VIDEO_Y_OFFSET)
        portrait_font_size = portrait_layout.get("subtitle_font_size", 38)
        subtitle_margin_v = portrait_layout.get("subtitle_margin_v", 550)

        # 标题样式
        title_color = portrait_layout.get("title_color", "#FFFFFF")
        title_outline_color = portrait_layout.get("title_outline_color", "#000000")
        title_outline_w = portrait_layout.get("title_outline_width", 2)
        title_shadow_enabled = portrait_layout.get("title_shadow_enabled", True)
        title_shadow_color = portrait_layout.get("title_shadow_color", "#000000")
        title_shadow_opacity = portrait_layout.get("title_shadow_opacity", 0.5)
        title_shadow_x = portrait_layout.get("title_shadow_x", 2)
        title_shadow_y = portrait_layout.get("title_shadow_y", 2)

        # 副标题
        sub_title_text = portrait_layout.get("sub_title_text")
        sub_title_font_size = portrait_layout.get("sub_title_font_size", 24)
        sub_title_color = portrait_layout.get("sub_title_color", "#CCCCCC")
        sub_title_y = portrait_layout.get("sub_title_y", 130)

        # 标题背景装饰
        title_bg_enabled = portrait_layout.get("title_bg_enabled", False)
        title_bg_color = portrait_layout.get("title_bg_color", "#000000")
        title_bg_opacity = portrait_layout.get("title_bg_opacity", 0.5)
        title_bg_padding = portrait_layout.get("title_bg_padding", 20)

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

        # ④ 标题渲染
        font_file = "/System/Library/Fonts/STHeiti Medium.ttc"
        current_label = "canvas"
        # Input index: 0=video, 1=title_overlay (if used)
        overlay_input_idx = 1

        if title_overlay_path and title_overlay_path.exists():
            # ── Overlay mode: Pillow PNG contains background + text together ──
            filter_parts.append(
                f"[{current_label}][{overlay_input_idx}:v]overlay=(W-w)/2:{title_y}[titled]"
            )
            current_label = "titled"
        else:
            # ── Drawtext mode ──
            # Build common parts
            shadow_part = ""
            if title_shadow_enabled:
                shadow_part = (
                    f":shadowcolor={title_shadow_color}@{title_shadow_opacity}"
                    f":shadowx={title_shadow_x}:shadowy={title_shadow_y}"
                )

            # Box background (auto-wraps text, stays coupled)
            box_part = ""
            if title_bg_enabled:
                box_part = (
                    f":box=1:boxcolor={title_bg_color}@{title_bg_opacity}"
                    f":boxborderw={title_bg_padding}"
                )

            # 长标题按字号折行(drawtext 自己不换行,超宽会被裁);多行用真实换行符
            # 连接,text_align=C 让每行在底条内居中。
            title_cpl = chars_per_line(title_font_size, PORTRAIT_WIDTH)
            title_lines = _wrap_cjk(title_text, title_cpl, max_lines=3)
            safe_title = "\n".join(_escape_drawtext(l) for l in title_lines)

            filter_parts.append(
                f"[{current_label}]drawtext="
                f"text='{safe_title}':"
                f"fontfile='{font_file}':"
                f"fontsize={title_font_size}:"
                f"fontcolor={title_color}:"
                f"borderw={title_outline_w}:bordercolor={title_outline_color}:"
                f"text_align=C:"
                f"x=(w-text_w)/2:"
                f"y={title_y}"
                f"{shadow_part}{box_part}"
                f"[titled]"
            )
            current_label = "titled"

            # 副标题
            if sub_title_text and sub_title_text.strip():
                sub_cpl = chars_per_line(sub_title_font_size, PORTRAIT_WIDTH)
                sub_lines = _wrap_cjk(sub_title_text, sub_cpl, max_lines=2)
                safe_sub = "\n".join(_escape_drawtext(l) for l in sub_lines)
                sub_box_part = ""
                if title_bg_enabled:
                    sub_box_part = (
                        f":box=1:boxcolor={title_bg_color}@{title_bg_opacity}"
                        f":boxborderw={title_bg_padding}"
                    )
                filter_parts.append(
                    f"[titled]drawtext="
                    f"text='{safe_sub}':"
                    f"fontfile='{font_file}':"
                    f"fontsize={sub_title_font_size}:"
                    f"fontcolor={sub_title_color}:"
                    f"text_align=C:"
                    f"x=(w-text_w)/2:"
                    f"y={sub_title_y}"
                    f"{sub_box_part}"
                    f"[subtitled]"
                )
                current_label = "subtitled"

        # ⑤ 添加字幕（使用可配置的 portrait_font_size 和 subtitle_margin_v）
        final_label = current_label
        if srt_path and srt_path.exists():
            safe_srt = str(srt_path).replace("\\", "/").replace(":", "\\\\:")
            pc = _hex_color_to_ass(font_color)
            oc = _hex_color_to_ass("#000000")
            filter_parts.append(
                f"[{current_label}]subtitles='{safe_srt}':force_style="
                f"'FontName=PingFang SC,"
                f"FontSize={portrait_font_size},"
                f"PrimaryColour={pc},"
                f"OutlineColour={oc},"
                f"Outline={outline_width},"
                f"MarginV={subtitle_margin_v},"
                # WrapStyle=0 是 libass 的智能折行(两行尽量等长);配上左右留白,
                # 太长的句子会在画面内折成多行,而不是横着顶出去被裁掉。
                f"WrapStyle=0,"
                f"MarginL={SUBTITLE_SIDE_MARGIN},"
                f"MarginR={SUBTITLE_SIDE_MARGIN},"
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
        ]
        if title_overlay_path and title_overlay_path.exists():
            args.extend(["-i", str(title_overlay_path)])
        args.extend([
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
        ])
        return args

    async def _spoken_texts(self, db, project_id: str) -> list[str]:
        """TTS 实际念出来的文字,按播放顺序:片头 + 各段口播稿 + 片尾。

        和 audio_service 合成语音时的顺序一致,这样才能拿它去对齐 ASR 的时间轴。
        段落没有单独口播稿时退回整篇稿子按段切分。
        """
        project = await db.get(Project, project_id)
        result = await db.execute(
            select(Segment)
            .where(Segment.project_id == project_id)
            .order_by(Segment.segment_order)
        )
        segments = list(result.scalars().all())
        if not segments:
            return []

        # 判断口径必须和 audio_service 合成语音时一致,否则参考文本和音频对不上,
        # 对齐命中率跌破阈值就静默退回原始识别文本(同音词错误照旧)
        per_segment = uses_per_segment_tts(project, segments)
        if per_segment:
            body = [s.script_text or "" for s in segments]
        else:
            result = await db.execute(
                select(Script).where(Script.project_id == project_id)
            )
            script = result.scalar_one_or_none()
            from .video_service import _split_script_to_paragraphs
            paragraphs = _split_script_to_paragraphs(script, len(segments)) if script else None
            body = paragraphs[:len(segments)] if paragraphs else [s.content for s in segments]

        # 片头/片尾只有逐段模式才会被合成进 speech.mp3(见 audio_service),
        # 整篇模式下音频里根本没有,算进参考文本只会凭空多出一段对不上的字。
        texts = []
        intro = getattr(project, "intro_text", None) if project else None
        if per_segment and intro and intro.strip():
            texts.append(intro)
        texts.extend(body)
        outro = getattr(project, "outro_text", None) if project else None
        if per_segment and outro and outro.strip():
            texts.append(outro)

        cleaned = [clean_script_for_tts(t or "") for t in texts]
        return [t for t in cleaned if t.strip()]

    async def _generate_srt(self, project_id: str, settings) -> Path | None:
        """Generate SRT file for portrait subtitles.

        Priority: ASR (precise timing) → proportional fallback.
        """
        async with async_session_factory() as db:
            result = await db.execute(
                select(AudioAsset).where(AudioAsset.project_id == project_id)
            )
            audio = result.scalar_one_or_none()
            if not audio or not audio.file_path:
                return None

            srt_dir = Path(settings.storage.base_dir) / "subtitles" / project_id
            srt_dir.mkdir(parents=True, exist_ok=True)
            srt_path = srt_dir / "portrait_subtitles.srt"

            # 每行字数按字号算,不能写死:字号越大一行放得下的字越少。再乘上允许
            # 的行数作为单条字幕的上限,超出的部分交给 libass 自动折行(见
            # _build_ffmpeg_command 里的 WrapStyle)。
            project = await db.get(Project, project_id)
            font_size = getattr(project, "portrait_subtitle_font_size", 38) if project else 38
            per_line = chars_per_line(font_size, PORTRAIT_WIDTH, SUBTITLE_SIDE_MARGIN)
            max_lines = max(1, settings.subtitles.max_lines)
            # 留 2 个字的余量:切行时会把句末标点收进本行(见 asr_service._line_ranges),
            # 不预留的话这一两个标点会把整条挤到多出一行,末行只剩一个句号。
            chunk_chars = max(per_line, per_line * max_lines - 2)

            # Try ASR-based precise subtitles.
            # 字幕文字用口播稿(TTS 念的原文),ASR 只提供时间轴 —— 否则 Whisper
            # 的同音词错误(骨龄→古灵)会直接烧进成片。见 asr_service 模块说明。
            spoken_texts = await self._spoken_texts(db, project_id)

            from .asr_service import transcribe_and_generate_srt
            asr_result = await transcribe_and_generate_srt(
                audio_path=Path(audio.file_path),
                output_path=srt_path,
                max_chars_per_line=chunk_chars,
                reference_texts=spoken_texts,
            )
            if asr_result:
                return asr_result

            # Fallback: proportional timing from script text
            if not audio.duration:
                return None

            result = await db.execute(
                select(Segment)
                .where(Segment.project_id == project_id)
                .order_by(Segment.segment_order)
            )
            segments = list(result.scalars().all())
            if not segments:
                return None

            result = await db.execute(
                select(Script).where(Script.project_id == project_id)
            )
            script = result.scalar_one_or_none()

            from .video_service import _split_script_to_paragraphs
            script_paragraphs = _split_script_to_paragraphs(script, len(segments)) if script else None

            if script_paragraphs and len(script_paragraphs) >= len(segments):
                segment_texts = script_paragraphs[:len(segments)]
            else:
                segment_texts = [s.content for s in segments]

            durations = calculate_segment_durations(segment_texts, audio.duration)

            renderer = SubtitleRenderer()
            renderer.generate_srt(
                segments=segment_texts,
                durations=durations,
                output_path=srt_path,
                max_chars_per_line=per_line,
                max_lines=max_lines,
            )
            return srt_path
