"""Audio service - TTS generation and manual upload handling."""

import asyncio
import json
import logging
import re
from pathlib import Path

from sqlalchemy import select

from ..database import async_session_factory
from ..models import Project, Script, Segment, AudioAsset, ProviderConfig, VoiceClone
from ..providers.base import ProviderType
from ..providers.registry import ProviderRegistry
from ..providers.tts.base import TTSProvider
from ..config import get_settings
from ..utils.ppt_importer import DEFAULT_SILENT_SLIDE_SECONDS

logger = logging.getLogger(__name__)


async def _generate_silence(output_path: Path, seconds: float, sample_rate: int = 24000) -> None:
    """Write a silent MP3 of the given length (for slides with no speaker notes)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"anullsrc=channel_layout=mono:sample_rate={sample_rate}",
        "-t", f"{max(seconds, 0.1):.3f}",
        "-c:a", "libmp3lame", "-q:a", "9",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg silence generation failed: {stderr.decode(errors='replace')[-300:]}")


def clean_script_for_tts(text: str) -> str:
    """Remove annotations, markdown formatting, and other non-speech content
    from the script before sending to TTS.

    Cleans:
    - Stage direction annotations in Chinese parentheses: （轻松、亲切的开场）
    - Stage direction annotations in regular parentheses: (轻松开场)
    - Markdown bold/italic markers: **text** / *text*
    - Markdown headings: # / ## / ###
    - Extra whitespace and blank lines
    """
    # Remove annotations in Chinese parentheses （...）
    text = re.sub(r'[（(][^）)]*?[的地]?(?:开场白?|语气|口吻|过渡|结尾|总结|转折|停顿|感叹|强调)[^）)]*?[）)]', '', text)
    # Broader: remove any Chinese parenthetical that looks like a stage direction
    # (contains descriptive words like 轻松、亲切、认真 etc.)
    text = re.sub(r'[（(][\u4e00-\u9fff、，\s]{2,20}[）)]', '', text)

    # Remove markdown bold/italic markers (keep the text inside)
    text = re.sub(r'\*{1,3}(.+?)\*{1,3}', r'\1', text)

    # Remove markdown heading markers
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

    # Remove markdown bullet points (- or *)
    text = re.sub(r'^\s*[-*]\s+', '', text, flags=re.MULTILINE)

    # Clean up extra blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


# chunks.json 里 intro/outro 分段不对应任何 Segment,做下标换算时要跳过。
CHUNK_META_TYPES = ("intro", "outro")


def chunk_segment_index(chunks: list[dict], chunk_index: int) -> int | None:
    """chunks.json 下标 → segments(按 segment_order 排序)下标。

    intro/outro 分段不对应段落,返回 None。
    """
    if chunks[chunk_index].get("type") in CHUNK_META_TYPES:
        return None
    return chunk_index - sum(
        1 for c in chunks[:chunk_index] if c.get("type") in CHUNK_META_TYPES
    )


def chunks_align_with_segments(chunks: list[dict], segments: list) -> bool:
    """分段是否与段落一一对应。

    按段落合成时成立;旧的"整篇切块"模式下分段是按字数切的,和段落对不上,
    此时不能拿分段下标去改段落文字。
    """
    body = [c for c in chunks if c.get("type") not in CHUNK_META_TYPES]
    return bool(segments) and len(body) == len(segments)


def uses_per_segment_tts(project, segments: list) -> bool:
    """TTS 是不是按段落逐段合成的(而不是整篇一次合成)。

    这个判断决定了 speech.mp3 的构成:逐段模式下音频是「片头 + 各段 script_text
    + 片尾」拼起来的;整篇模式下只有 Script.content 一条,没有片头片尾。字幕要拿
    口播稿去对齐 ASR 的时间轴,参考文本必须和音频的构成一致,所以合成语音、横屏
    字幕、竖屏字幕三处必须用同一个判断 —— 各写各的就会对不上,而对不上只会静默
    退回原始识别文本(同音词错误照旧)。

    PPT 导入的项目即便有幻灯片没有备注也走逐段模式(空备注合成为静音),所以
    单独放行。
    """
    is_ppt = bool(project and getattr(project, "source_type", "") == "ppt")
    return bool(segments) and (is_ppt or all(s.script_text for s in segments))


def _shift_segment_audio_dirs(segments_dir: Path, removed_order: int) -> None:
    """段落音频目录整体前移一位,让 seg_XXX 重新对上 segment_order。

    目录名带着段落序号(seg_003),删掉中间一段后面每段都要往前挪。升序处理,
    目标目录总是刚被腾空的,不会撞名。
    """
    import shutil

    if not segments_dir.exists():
        return

    shutil.rmtree(segments_dir / f"seg_{removed_order:03d}", ignore_errors=True)
    later = sorted(
        (d for d in segments_dir.iterdir()
         if d.is_dir() and d.name.startswith("seg_") and d.name[4:].isdigit()
         and int(d.name[4:]) > removed_order),
        key=lambda d: int(d.name[4:]),
    )
    for d in later:
        d.replace(segments_dir / f"seg_{int(d.name[4:]) - 1:03d}")


def _renumber_chunks(chunks_dir: Path, chunks: list[dict]) -> None:
    """重新编号分段,让 index 和文件名 chunk_XXX.mp3 重新对齐。

    删掉一段后面每段都往前挪一位;升序处理,目标文件名总是刚被腾空的。
    """
    for i, chunk in enumerate(chunks):
        target = f"chunk_{i:03d}.mp3"
        if chunk["file"] != target:
            src = chunks_dir / chunk["file"]
            if src.exists():
                src.replace(chunks_dir / target)
            chunk["file"] = target
        chunk["index"] = i


async def _rebuild_script_after_removal(db, project_id: str, segments: list,
                                        removed_order: int, previous_count: int) -> bool | None:
    """把整篇口播稿里被删段落的那一段去掉。

    返回 True 表示已同步,False 表示对不上没敢动,None 表示还没生成口播稿、
    本来就没有要同步的东西。
    """
    result = await db.execute(select(Script).where(Script.project_id == project_id))
    script = result.scalar_one_or_none()
    if not script:
        return None

    if segments and all(s.script_text for s in segments):
        # 逐段模式:整篇稿本来就是各段拼回来的,重拼一次即可
        new_content = "\n\n".join(s.script_text for s in segments)
    else:
        # 整篇模式:段落没有各自的稿子,只能按空行切开删掉对应那一段。
        # 段数对不上说明稿子和段落早已不同步,这时宁可不动。
        paragraphs = [p.strip() for p in script.content.split("\n\n") if p.strip()]
        if len(paragraphs) != previous_count or not 0 <= removed_order < previous_count:
            logger.warning(
                "删除段落 %d 后未能同步口播稿:稿子有 %d 段,段落有 %d 个",
                removed_order, len(paragraphs), previous_count,
            )
            return False
        del paragraphs[removed_order]
        new_content = "\n\n".join(paragraphs)

    script.content = new_content
    script.is_manual = True
    script.version += 1
    return True


async def sync_after_segment_removed(db, project_id: str, removed_order: int,
                                     previous_count: int) -> dict:
    """段落被删除后,把口播稿和音频一并收拢干净。

    段落 / 口播稿 / 音频分段是同一份内容的三个视图(见 ``update_chunk_text``),
    删段落时三处都要跟着删,否则整篇口播稿和合成好的 speech.mp3 里还留着那段
    内容,而且分段数和段落数一对不上,分段改文字就再也同步不回段落了。

    调用方传入的 ``db`` 就是当前请求的会话,这里只写不提交(由调用方提交)。
    返回哪几处真的同步上了:``script_synced``(None 表示还没生成口播稿)、
    ``chunks_synced``、``audio_duration``(None 表示没能重新拼接)。
    """
    settings = get_settings()

    seg_result = await db.execute(
        select(Segment)
        .where(Segment.project_id == project_id)
        .order_by(Segment.segment_order)
    )
    segments = list(seg_result.scalars().all())

    script_synced = await _rebuild_script_after_removal(
        db, project_id, segments, removed_order, previous_count
    )
    no_audio = {"script_synced": script_synced, "chunks_synced": False,
                "audio_duration": None}

    # 先把该删哪一段判断清楚,再动盘上的东西。反过来做的话,"分段和段落对不上、
    # 不敢动"这条退路会在音频目录已经被删改之后才触发 —— 嘴上说没动,其实
    # 已经把一段音频永久删掉、后面每段的 audio_file 都指到了邻居的文件上。
    audio_dir = Path(settings.storage.base_dir) / "audio" / project_id
    chunks_dir = audio_dir / "chunks"
    meta = TTSProvider.load_chunks_json(chunks_dir)
    chunks = meta["chunks"] if meta else []
    drop_at = None
    if meta:
        body_indexes = [i for i, c in enumerate(chunks)
                        if c.get("type") not in CHUNK_META_TYPES]
        if len(body_indexes) != previous_count or not 0 <= removed_order < previous_count:
            # 分段和段落本来就对不上(旧的整篇切块模式),无从判断该删哪一段。
            # 这时连段落音频目录也不能碰:目录改名要配合 audio_file 一起改,
            # 而分段对不上说明这份音频的结构我们已经看不懂了。
            logger.warning(
                "删除段落 %d 后未能同步音频分段:分段有 %d 段,段落有 %d 个;"
                "盘上的音频保持原样", removed_order, len(body_indexes), previous_count,
            )
            return no_audio
        drop_at = body_indexes[removed_order]

    # DB 侧的改动先落一次,免得约束错误在文件已经删改之后才炸出来
    await db.flush()

    # 目录名带着段落序号,DB 里段落已经重排过了,盘上也要跟着挪
    _shift_segment_audio_dirs(audio_dir / "segments", removed_order)
    for seg in segments:
        if not seg.audio_file:
            continue
        moved = audio_dir / "segments" / f"seg_{seg.segment_order:03d}" / "speech.mp3"
        seg.audio_file = str(moved) if moved.exists() else None

    if drop_at is None:
        return no_audio

    dropped = chunks.pop(drop_at)
    (chunks_dir / dropped["file"]).unlink(missing_ok=True)
    _renumber_chunks(chunks_dir, chunks)
    TTSProvider._save_chunks_json(
        chunks_dir, chunks, meta.get("voice_id", ""), meta.get("use_icl", False),
        voice_display=meta.get("voice_display", ""),
    )

    try:
        duration = await _reconcat_after_removal(db, project_id, chunks_dir, chunks,
                                                 audio_dir / "speech.mp3")
    except Exception:
        # 分段已经删干净了,只是整段没拼成(ffmpeg 缺失/失败)。这一步失败不该
        # 连累前面已经写好的口播稿 —— 如实回报,让前端提示去音频页手动拼接。
        logger.exception("删除段落 %d 后重新拼接失败", removed_order)
        duration = None
    logger.info("删除段落 %d:口播稿同步=%s,剩余分段 %d,重新拼接=%s",
                removed_order, script_synced, len(chunks),
                f"{duration:.1f}s" if duration is not None else "跳过")
    return {"script_synced": script_synced, "chunks_synced": True,
            "audio_duration": duration}


async def _reconcat_after_removal(db, project_id: str, chunks_dir: Path,
                                  chunks: list[dict], output_path: Path) -> float | None:
    """把剩下的分段重新拼成整段音频,并更新 AudioAsset 的时长。

    缺分段音频时跳过(返回 None),让调用方提示用户自己去音频页重新拼接,
    总比拼出一段缺东少西的成品好。
    """
    chunk_paths = [chunks_dir / c["file"] for c in chunks]
    missing = [p.name for p in chunk_paths if not p.exists()]
    if not chunk_paths or missing:
        logger.warning("删除段落后跳过重新拼接:缺少分段音频 %s", missing or "(无分段)")
        return None

    duration = await TTSProvider._concat_audio(chunk_paths, output_path)

    result = await db.execute(
        select(AudioAsset).where(AudioAsset.project_id == project_id)
    )
    audio = result.scalar_one_or_none()
    if audio:
        audio.file_path = str(output_path)
        audio.duration = duration
        # 和 concatenate_chunks 保持一致:拼出来的就是完整可用的音频,
        # 状态还停在 failed/pending 的话视频合成会一直说"没有已完成的音频"
        audio.status = "completed"
    return duration


class AudioService:
    """Handles TTS audio generation and manual audio upload."""

    async def generate_tts(self, project_id: str,
                            provider_overrides: dict[str, str] | None = None):
        """Generate TTS audio from the project's script."""
        settings = get_settings()

        async with async_session_factory() as db:
            result = await db.execute(select(Script).where(Script.project_id == project_id))
            script = result.scalar_one_or_none()
            if not script:
                proj = await db.get(Project, project_id)
                if proj and getattr(proj, "source_type", "") == "ppt":
                    raise ValueError(
                        "PPT 导入尚未完成（或导入失败）。请等待流水线前面的步骤全部变为“已完成”"
                        "后再生成语音；大文件渲染可能需要 1–2 分钟。"
                    )
                raise ValueError(f"No script found for project {project_id}")

            # 先确定将要使用的克隆声音,据此选对 provider:本地克隆必须走
            # local_voxcpm(否则会用默认 TTS 提供商如豆包的默认音色)。
            project = await db.get(Project, project_id)
            effective_clone = None
            if project and getattr(project, "tts_voice_clone_id", None):
                effective_clone = await db.get(VoiceClone, project.tts_voice_clone_id)
            elif not (project and getattr(project, "tts_voice_id", None)):
                # 项目既未指定克隆声音也未指定预置声音 -> 看全局默认克隆
                _dc = await db.execute(
                    select(VoiceClone).where(VoiceClone.is_default == True)
                )
                effective_clone = _dc.scalar_one_or_none()

            force_local = bool(effective_clone and effective_clone.provider_key == "local_voxcpm")

            # Get TTS provider
            tts_config = await self._get_provider(db, "tts", provider_overrides)

            if force_local:
                # 选中本地克隆声音 -> 强制用本地 VoxCPM(零样本,无需凭据/ProviderConfig)
                tts_provider = ProviderRegistry.instantiate(
                    provider_type=ProviderType.TTS, key="local_voxcpm",
                    api_key="", api_base_url="", model_id="", config={},
                )
                provider_key_used = "local_voxcpm"
                extra_config = {}
                logger.info("Selected clone is local_voxcpm -> using local VoxCPM provider")
            else:
                # 非本地克隆:优先用与该克隆 provider_key 匹配的 provider 配置,而不是
                # 全局默认(默认现在可能是 local_voxcpm,拿它跑豆包 speaker_id 会出错)。
                provider_cfg = tts_config
                if effective_clone and effective_clone.provider_key:
                    pc_result = await db.execute(
                        select(ProviderConfig).where(
                            ProviderConfig.provider_type == "tts",
                            ProviderConfig.provider_key == effective_clone.provider_key,
                        )
                    )
                    matched = pc_result.scalar_one_or_none()
                    if matched:
                        provider_cfg = matched
                if not provider_cfg:
                    raise ValueError(
                        f"未配置 {effective_clone.provider_key if effective_clone else 'TTS'} provider")
                api_key = provider_cfg.api_key
                if not api_key:
                    key_map = {
                        "openai_tts": settings.openai_api_key,
                        "elevenlabs": settings.elevenlabs_api_key,
                        "doubao_tts": settings.doubao_api_key,
                        "minimax_tts": settings.minimax_api_key,
                    }
                    api_key = key_map.get(provider_cfg.provider_key, "")
                extra_config = json.loads(provider_cfg.config_json) if provider_cfg.config_json else None
                tts_provider = ProviderRegistry.instantiate(
                    provider_type=ProviderType.TTS,
                    key=provider_cfg.provider_key,
                    api_key=api_key,
                    api_base_url=provider_cfg.api_base_url or "",
                    model_id=provider_cfg.model_id or "",
                    config=extra_config,
                )
                provider_key_used = provider_cfg.provider_key

            # Generate audio
            output_dir = Path(settings.storage.base_dir) / "audio" / project_id
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / "speech.mp3"

            # --- 声音选择优先级：项目克隆声音 > 项目预置声音 > 全局默认克隆 > Provider 默认 ---
            voice_id = ""
            voice_display = ""
            use_icl = False

            is_local_voxcpm = provider_key_used == "local_voxcpm"

            def _resolve_clone(vc) -> str:
                """克隆声音 -> voice_id。本地 VoxCPM 用参考音频绝对路径(零样本、免训练);
                其它(如豆包 ICL)用训练后的 speaker_id。"""
                if is_local_voxcpm:
                    if vc.reference_audio_path:
                        ref = Path(vc.reference_audio_path)
                        ref = ref if ref.is_absolute() else ref.resolve()
                        if ref.exists():
                            return str(ref)
                    return ""
                if vc.speaker_id and vc.training_status in (2, 4):
                    return vc.speaker_id
                return ""

            if project and getattr(project, "tts_voice_clone_id", None):
                # 项目指定了克隆声音
                voice_clone = await db.get(VoiceClone, project.tts_voice_clone_id)
                if voice_clone:
                    resolved = _resolve_clone(voice_clone)
                    if resolved:
                        voice_id = resolved
                        use_icl = True
                        voice_display = f"clone:{voice_clone.name}"
                        logger.info("Using cloned voice: %s (project override)", voice_clone.name)

            if not voice_id and project and getattr(project, "tts_voice_id", None):
                # 项目指定了预置声音
                voice_id = project.tts_voice_id
                voice_display = voice_id
                logger.info("Using preset voice: %s (project override)", voice_id)

            if not voice_id:
                # 检查全局默认克隆声音
                result = await db.execute(
                    select(VoiceClone).where(VoiceClone.is_default == True)
                )
                default_clone = result.scalar_one_or_none()
                if default_clone:
                    resolved = _resolve_clone(default_clone)
                    if resolved:
                        voice_id = resolved
                        use_icl = True
                        voice_display = f"clone:{default_clone.name}"
                        logger.info("Using cloned voice: %s (global default)", default_clone.name)

            if not voice_id:
                # Provider 默认声音
                voice_id = extra_config.get("voice", "") if extra_config else ""
                voice_display = voice_id

            max_chunk = settings.tts.icl_max_chars if use_icl else settings.tts.standard_max_chars
            # 本地 VoxCPM:压小分块以抗长文本漂移(越说越快/越响)。见 config 注释。
            if provider_key_used == "local_voxcpm":
                max_chunk = min(max_chunk, settings.tts.local_voxcpm_max_chars)

            # Check if segments have per-segment script_text
            seg_result = await db.execute(
                select(Segment)
                .where(Segment.project_id == project_id)
                .order_by(Segment.segment_order)
            )
            segments = list(seg_result.scalars().all())
            # PPT-imported projects use the per-segment path even when some slides
            # have empty notes (those become silent still-frames below).
            has_segment_scripts = uses_per_segment_tts(project, segments)

            if has_segment_scripts:
                # === New path: per-segment TTS synthesis ===
                logger.info("Per-segment TTS: %d segments", len(segments))
                segment_audio_paths = []
                total_duration = 0.0

                # Synthesize intro if configured
                intro_audio_path = None
                intro_duration = 0.0
                intro_text_val = getattr(project, 'intro_text', None)
                if intro_text_val and intro_text_val.strip():
                    intro_clean = clean_script_for_tts(intro_text_val)
                    if intro_clean:
                        intro_dir = output_dir / "segments" / "seg_intro"
                        intro_dir.mkdir(parents=True, exist_ok=True)
                        intro_output = intro_dir / "speech.mp3"
                        logger.info("Synthesizing intro: %d chars", len(intro_clean))
                        intro_response = await tts_provider.synthesize_script(
                            script=intro_clean,
                            voice_id=voice_id,
                            output_path=intro_output,
                            use_icl=use_icl,
                            max_chunk_chars=max_chunk,
                        )
                        intro_audio_path = intro_output
                        intro_duration = intro_response.duration
                        total_duration += intro_duration
                        logger.info("Intro done: %.1fs", intro_duration)

                for seg in segments:
                    seg_text = clean_script_for_tts(seg.script_text or "")
                    seg_dir = output_dir / "segments" / f"seg_{seg.segment_order:03d}"
                    seg_dir.mkdir(parents=True, exist_ok=True)
                    seg_output = seg_dir / "speech.mp3"

                    if not seg_text.strip():
                        # Slide with no speaker notes: emit a silent still-frame
                        # clip so the segment keeps its place in the timeline.
                        silent_seconds = seg.duration_hint or DEFAULT_SILENT_SLIDE_SECONDS
                        await _generate_silence(seg_output, silent_seconds)
                        seg.audio_file = str(seg_output)
                        seg.duration_hint = silent_seconds
                        total_duration += silent_seconds
                        segment_audio_paths.append(seg_output)
                        logger.info("Segment %d empty note: %.1fs silence",
                                    seg.segment_order, silent_seconds)
                        continue

                    logger.info("Synthesizing segment %d: %d chars", seg.segment_order, len(seg_text))
                    seg_response = await tts_provider.synthesize_script(
                        script=seg_text,
                        voice_id=voice_id,
                        output_path=seg_output,
                        use_icl=use_icl,
                        max_chunk_chars=max_chunk,
                    )

                    seg.audio_file = str(seg_output)
                    seg.duration_hint = seg_response.duration
                    total_duration += seg_response.duration
                    segment_audio_paths.append(seg_output)
                    logger.info("Segment %d done: %.1fs", seg.segment_order, seg_response.duration)

                # Synthesize outro if configured
                outro_audio_path = None
                outro_duration = 0.0
                outro_text_val = getattr(project, 'outro_text', None)
                if outro_text_val and outro_text_val.strip():
                    outro_clean = clean_script_for_tts(outro_text_val)
                    if outro_clean:
                        outro_dir = output_dir / "segments" / "seg_outro"
                        outro_dir.mkdir(parents=True, exist_ok=True)
                        outro_output = outro_dir / "speech.mp3"
                        logger.info("Synthesizing outro: %d chars", len(outro_clean))
                        outro_response = await tts_provider.synthesize_script(
                            script=outro_clean,
                            voice_id=voice_id,
                            output_path=outro_output,
                            use_icl=use_icl,
                            max_chunk_chars=max_chunk,
                        )
                        outro_audio_path = outro_output
                        outro_duration = outro_response.duration
                        total_duration += outro_duration
                        logger.info("Outro done: %.1fs", outro_duration)

                # Build final audio path list: intro + segments + outro
                all_audio_paths = []
                if intro_audio_path:
                    all_audio_paths.append(intro_audio_path)
                all_audio_paths.extend(segment_audio_paths)
                if outro_audio_path:
                    all_audio_paths.append(outro_audio_path)

                # Concatenate all audio into final speech.mp3
                if len(all_audio_paths) > 1:
                    total_duration = await TTSProvider._concat_audio(
                        all_audio_paths, output_path
                    )
                elif all_audio_paths:
                    import shutil
                    shutil.copy2(all_audio_paths[0], output_path)

                # Write chunks.json for chunk management UI compatibility
                chunks_dir = output_dir / "chunks"
                chunks_dir.mkdir(parents=True, exist_ok=True)
                chunk_entries = []
                chunk_idx = 0

                # Intro chunk
                if intro_audio_path and intro_text_val:
                    intro_clean = clean_script_for_tts(intro_text_val)
                    chunk_file = f"chunk_{chunk_idx:03d}.mp3"
                    import shutil as _shutil
                    _shutil.copy2(intro_audio_path, chunks_dir / chunk_file)
                    chunk_entries.append({
                        "index": chunk_idx,
                        "text": intro_clean,
                        "file": chunk_file,
                        "duration": intro_duration,
                        "speed": len(intro_clean) / intro_duration if intro_duration else 0.0,
                        "chars": len(intro_clean),
                        "type": "intro",
                    })
                    chunk_idx += 1

                # Include every segment that produced audio (silent slides too).
                active_segments = [s for s in segments if s.audio_file]
                for seg in active_segments:
                    chunk_file = f"chunk_{chunk_idx:03d}.mp3"
                    seg_audio = Path(seg.audio_file) if seg.audio_file else None
                    if seg_audio and seg_audio.exists():
                        import shutil as _shutil
                        _shutil.copy2(seg_audio, chunks_dir / chunk_file)
                    seg_clean = clean_script_for_tts(seg.script_text or "")
                    chunk_entries.append({
                        "index": chunk_idx,
                        "text": seg_clean,
                        "file": chunk_file,
                        "duration": seg.duration_hint or 0.0,
                        "speed": len(seg_clean) / seg.duration_hint if seg.duration_hint else 0.0,
                        "chars": len(seg_clean),
                    })
                    chunk_idx += 1

                # Outro chunk
                if outro_audio_path and outro_text_val:
                    outro_clean = clean_script_for_tts(outro_text_val)
                    chunk_file = f"chunk_{chunk_idx:03d}.mp3"
                    import shutil as _shutil
                    _shutil.copy2(outro_audio_path, chunks_dir / chunk_file)
                    chunk_entries.append({
                        "index": chunk_idx,
                        "text": outro_clean,
                        "file": chunk_file,
                        "duration": outro_duration,
                        "speed": len(outro_clean) / outro_duration if outro_duration else 0.0,
                        "chars": len(outro_clean),
                        "type": "outro",
                    })
                    chunk_idx += 1
                TTSProvider._save_chunks_json(chunks_dir, chunk_entries, voice_id, use_icl,
                                              voice_display=voice_display or voice_id)
                logger.info("Wrote chunks.json with %d segment-based chunks", len(chunk_entries))

                sample_rate = 24000  # default
                logger.info("Per-segment TTS complete: %d segments, total %.1fs",
                            len(segment_audio_paths), total_duration)

            else:
                # === Legacy path: monolithic TTS synthesis ===
                clean_text = clean_script_for_tts(script.content)
                logger.info("Cleaned script for TTS: removed %d chars of annotations/formatting",
                            len(script.content) - len(clean_text))

                response = await tts_provider.synthesize_script(
                    script=clean_text,
                    voice_id=voice_id,
                    output_path=output_path,
                    use_icl=use_icl,
                    max_chunk_chars=max_chunk,
                )
                total_duration = response.duration
                sample_rate = response.sample_rate

            # Save or update audio asset
            result = await db.execute(select(AudioAsset).where(AudioAsset.project_id == project_id))
            audio = result.scalar_one_or_none()

            # force_local 且未配置默认 TTS provider 时 tts_config 可能为 None
            provider_id_used = tts_config.id if tts_config else None

            if audio:
                audio.file_path = str(output_path)
                audio.duration = total_duration
                audio.sample_rate = sample_rate
                audio.provider_id = provider_id_used
                audio.voice_id = voice_display or voice_id
                audio.is_manual = False
                audio.status = "completed"
            else:
                audio = AudioAsset(
                    project_id=project_id,
                    file_path=str(output_path),
                    duration=total_duration,
                    sample_rate=sample_rate,
                    provider_id=provider_id_used,
                    voice_id=voice_display or voice_id,
                    is_manual=False,
                    status="completed",
                )
                db.add(audio)

            await db.commit()
            return audio

    async def get_audio_chunks(self, project_id: str) -> dict | None:
        """Load chunks metadata for a project."""
        settings = get_settings()
        chunks_dir = Path(settings.storage.base_dir) / "audio" / project_id / "chunks"
        from ..providers.tts.base import TTSProvider
        return TTSProvider.load_chunks_json(chunks_dir)

    async def regenerate_chunk(self, project_id: str, chunk_index: int) -> dict:
        """Re-synthesize a single chunk and return updated chunk info."""
        settings = get_settings()
        chunks_dir = Path(settings.storage.base_dir) / "audio" / project_id / "chunks"

        from ..providers.tts.base import TTSProvider, TTSRequest
        meta = TTSProvider.load_chunks_json(chunks_dir)
        if not meta:
            raise ValueError("No chunks found for this project")

        chunks = meta["chunks"]
        if chunk_index < 0 or chunk_index >= len(chunks):
            raise ValueError(f"Chunk index {chunk_index} out of range (0-{len(chunks)-1})")

        chunk = chunks[chunk_index]
        voice_id = meta["voice_id"]
        voice_display = meta.get("voice_display", voice_id)
        use_icl = meta.get("use_icl", False)

        # Get TTS provider and refresh chunk text from database
        async with async_session_factory() as db:
            tts_config = await self._get_provider(db, "tts")

            # Refresh chunk text from database (in case script was edited)
            seg_result = await db.execute(
                select(Segment)
                .where(Segment.project_id == project_id)
                .order_by(Segment.segment_order)
            )
            segments = list(seg_result.scalars().all())
            aligned = chunks_align_with_segments(chunks, segments)
            seg_index = chunk_segment_index(chunks, chunk_index) if aligned else None
            if seg_index is not None and 0 <= seg_index < len(segments):
                if segments[seg_index].script_text:
                    fresh_text = clean_script_for_tts(segments[seg_index].script_text)
                    if fresh_text != chunk["text"]:
                        logger.info("Chunk %d text updated from database (was %d chars, now %d chars)",
                                    chunk_index, len(chunk["text"]), len(fresh_text))
                        chunk["text"] = fresh_text
                        chunk["chars"] = len(fresh_text)

            # 声音以【项目当前选择】为准重新解析,不信 chunks.json 里烙进去的旧
            # voice_id(否则切换声音后单段重生成仍用旧声音/旧参考)。逻辑与整步生成
            # 一致:先按当前克隆声音判定 provider(本地 VoxCPM / 豆包...),再解析 voice_id。
            cur_project = await db.get(Project, project_id)
            effective_clone = None
            if cur_project and cur_project.tts_voice_clone_id:
                effective_clone = await db.get(VoiceClone, cur_project.tts_voice_clone_id)
            elif not (cur_project and cur_project.tts_voice_id):
                # 项目没选任何声音 -> 看全局默认克隆
                _dc = await db.execute(
                    select(VoiceClone).where(VoiceClone.is_default == True)
                )
                effective_clone = _dc.scalar_one_or_none()

            force_local = bool(effective_clone and effective_clone.provider_key == "local_voxcpm")

            if effective_clone:
                if force_local:
                    if not effective_clone.reference_audio_path:
                        raise ValueError(f"本地克隆声音 '{effective_clone.name}' 缺少参考音频")
                    ref = Path(effective_clone.reference_audio_path)
                    ref = ref if ref.is_absolute() else ref.resolve()
                    if not ref.exists():
                        raise ValueError(f"本地克隆声音 '{effective_clone.name}' 参考音频不存在: {ref}")
                    new_voice_id = str(ref)
                else:
                    if not (effective_clone.speaker_id and effective_clone.training_status in (2, 4)):
                        raise ValueError(
                            f"克隆声音 '{effective_clone.name}' 不可用(缺 speaker_id 或未就绪)")
                    new_voice_id = effective_clone.speaker_id
                if new_voice_id != voice_id:
                    logger.info("Regenerate: 用项目当前声音覆盖旧声音 %s -> clone:%s",
                                voice_display, effective_clone.name)
                voice_id = new_voice_id
                use_icl = True
                voice_display = f"clone:{effective_clone.name}"
            elif cur_project and cur_project.tts_voice_id:
                voice_id = cur_project.tts_voice_id
                voice_display = voice_id
                use_icl = False
            # else: 项目未选声音,沿用 chunks.json 里的 voice_id/use_icl 作保底

            if force_local:
                tts_provider = ProviderRegistry.instantiate(
                    provider_type=ProviderType.TTS, key="local_voxcpm",
                    api_key="", api_base_url="", model_id="", config={},
                )
            else:
                # 非本地克隆:优先用与该克隆 provider_key 匹配的 provider 配置,而不是
                # 全局默认(默认现在可能是 local_voxcpm,拿它跑豆包 speaker_id 会出错)。
                provider_cfg = tts_config
                if effective_clone and effective_clone.provider_key:
                    pc_result = await db.execute(
                        select(ProviderConfig).where(
                            ProviderConfig.provider_type == "tts",
                            ProviderConfig.provider_key == effective_clone.provider_key,
                        )
                    )
                    matched = pc_result.scalar_one_or_none()
                    if matched:
                        provider_cfg = matched
                if not provider_cfg:
                    raise ValueError(
                        f"未配置 {effective_clone.provider_key if effective_clone else 'TTS'} provider")
                api_key = provider_cfg.api_key
                if not api_key:
                    key_map = {
                        "openai_tts": settings.openai_api_key,
                        "elevenlabs": settings.elevenlabs_api_key,
                        "doubao_tts": settings.doubao_api_key,
                        "minimax_tts": settings.minimax_api_key,
                    }
                    api_key = key_map.get(provider_cfg.provider_key, "")
                extra_config = json.loads(provider_cfg.config_json) if provider_cfg.config_json else None
                tts_provider = ProviderRegistry.instantiate(
                    provider_type=ProviderType.TTS,
                    key=provider_cfg.provider_key,
                    api_key=api_key,
                    api_base_url=provider_cfg.api_base_url or "",
                    model_id=provider_cfg.model_id or "",
                    config=extra_config,
                )
                provider_key_used = provider_cfg.provider_key

        # Re-synthesize the chunk
        chunk_path = chunks_dir / chunk["file"]
        logger.info("Regenerating chunk %d for project %s (%d chars)",
                    chunk_index, project_id, chunk["chars"])

        await tts_provider.synthesize(
            TTSRequest(text=chunk["text"], voice_id=voice_id, use_icl=use_icl),
            output_path=chunk_path,
        )

        # Update metadata
        dur = await TTSProvider._probe_duration(chunk_path)
        speed = len(chunk["text"]) / dur if dur > 0 else 0.0
        chunk["duration"] = dur
        chunk["speed"] = speed
        chunk["stale"] = False  # 音频已按当前文字重生成
        chunks[chunk_index] = chunk

        # Save updated chunks.json (preserve display name, store real speaker_id)
        TTSProvider._save_chunks_json(chunks_dir, chunks, voice_id, use_icl,
                                      voice_display=voice_display)

        # Sync back to segment if in per-segment mode
        if chunk.get("type") in CHUNK_META_TYPES:
            # 片头/片尾没有对应段落,但视频合成会读 seg_intro/seg_outro 的时长,
            # 这里也要覆盖,否则视频还按旧时长排版。
            meta_audio = (Path(settings.storage.base_dir) / "audio" / project_id
                          / "segments" / f"seg_{chunk['type']}" / "speech.mp3")
            if meta_audio.exists():
                import shutil as _shutil
                _shutil.copy2(chunk_path, meta_audio)
                logger.info("Synced regenerated %s chunk back to %s", chunk["type"], meta_audio.name)
        else:
            async with async_session_factory() as db:
                seg_result = await db.execute(
                    select(Segment)
                    .where(Segment.project_id == project_id)
                    .order_by(Segment.segment_order)
                )
                segments = list(seg_result.scalars().all())
                seg_index = (chunk_segment_index(chunks, chunk_index)
                             if chunks_align_with_segments(chunks, segments) else None)
                if seg_index is not None and 0 <= seg_index < len(segments):
                    seg = segments[seg_index]
                    if seg.script_text:
                        # Copy regenerated audio back to segment dir
                        seg_audio = Path(seg.audio_file) if seg.audio_file else None
                        if seg_audio:
                            import shutil as _shutil
                            _shutil.copy2(chunk_path, seg_audio)
                        seg.duration_hint = dur
                        await db.commit()
                        logger.info("Synced regenerated chunk %d back to segment %d",
                                    chunk_index, seg_index)

        return chunk

    async def update_chunk_text(self, project_id: str, chunk_index: int, text: str) -> dict:
        """改写单个分段的文字,并同步回口播稿。

        音频分段和口播稿是同一份内容的两个视图,所以一次改三处:chunks.json
        (TTS 实际要念的文本)、Segment.script_text、Script.content(整篇口播稿)。
        分段音频此时还是旧文字生成的,标记 ``stale``,待用户点"重新生成"。
        """
        settings = get_settings()
        chunks_dir = Path(settings.storage.base_dir) / "audio" / project_id / "chunks"

        meta = TTSProvider.load_chunks_json(chunks_dir)
        if not meta:
            raise ValueError("No chunks found for this project")

        chunks = meta["chunks"]
        if chunk_index < 0 or chunk_index >= len(chunks):
            raise ValueError(f"Chunk index {chunk_index} out of range (0-{len(chunks)-1})")

        raw_text = (text or "").strip()
        if not raw_text:
            raise ValueError("分段文字不能为空")
        clean_text = clean_script_for_tts(raw_text)
        if not clean_text:
            raise ValueError("分段文字清洗后为空,请检查内容")

        chunk = chunks[chunk_index]
        chunk_type = chunk.get("type")
        script_synced = False

        async with async_session_factory() as db:
            if chunk_type in CHUNK_META_TYPES:
                project = await db.get(Project, project_id)
                if project:
                    setattr(project, f"{chunk_type}_text", raw_text)
                    script_synced = True
            else:
                seg_result = await db.execute(
                    select(Segment)
                    .where(Segment.project_id == project_id)
                    .order_by(Segment.segment_order)
                )
                segments = list(seg_result.scalars().all())
                seg_index = (chunk_segment_index(chunks, chunk_index)
                             if chunks_align_with_segments(chunks, segments) else None)
                if seg_index is not None and 0 <= seg_index < len(segments):
                    segments[seg_index].script_text = raw_text
                    # 整篇口播稿由各段拼回,和 script_service 里的做法保持一致
                    full_script = "\n\n".join(
                        s.script_text for s in segments if s.script_text
                    )
                    script_result = await db.execute(
                        select(Script).where(Script.project_id == project_id)
                    )
                    script = script_result.scalar_one_or_none()
                    if script:
                        script.content = full_script
                        script.is_manual = True
                        script.version += 1
                    script_synced = True
            await db.commit()

        if not script_synced:
            logger.warning("Chunk %d text updated but not synced to script "
                           "(分段与段落不一一对应)", chunk_index)

        chunk["text"] = clean_text
        chunk["chars"] = len(clean_text)
        chunk["stale"] = True  # 文字已改,现有音频还是旧的
        chunks[chunk_index] = chunk
        TTSProvider._save_chunks_json(
            chunks_dir, chunks, meta.get("voice_id", ""), meta.get("use_icl", False),
            voice_display=meta.get("voice_display", ""),
        )
        logger.info("Chunk %d text updated (%d chars, script_synced=%s)",
                    chunk_index, len(clean_text), script_synced)

        return {**chunk, "script_synced": script_synced}

    async def concatenate_chunks(self, project_id: str) -> dict:
        """Re-concatenate all persisted chunks into final audio."""
        settings = get_settings()
        audio_dir = Path(settings.storage.base_dir) / "audio" / project_id
        chunks_dir = audio_dir / "chunks"
        output_path = audio_dir / "speech.mp3"

        from ..providers.tts.base import TTSProvider
        meta = TTSProvider.load_chunks_json(chunks_dir)
        if not meta:
            raise ValueError("No chunks found for this project")

        chunk_paths = [chunks_dir / c["file"] for c in meta["chunks"]]

        # Verify all chunks exist
        for p in chunk_paths:
            if not p.exists():
                raise ValueError(f"Chunk file missing: {p.name}")

        duration = await TTSProvider._concat_audio(chunk_paths, output_path)

        # Update AudioAsset and segment durations in database
        async with async_session_factory() as db:
            result = await db.execute(
                select(AudioAsset).where(AudioAsset.project_id == project_id)
            )
            audio = result.scalar_one_or_none()
            if audio:
                audio.file_path = str(output_path)
                audio.duration = duration
                audio.status = "completed"
            else:
                audio = AudioAsset(
                    project_id=project_id,
                    file_path=str(output_path),
                    duration=duration,
                    status="completed",
                )
                db.add(audio)

            # Sync chunk durations back to segments
            seg_result = await db.execute(
                select(Segment)
                .where(Segment.project_id == project_id)
                .order_by(Segment.segment_order)
            )
            segments = list(seg_result.scalars().all())
            # 分段下标 ≠ 段落下标:片头/片尾也占分段,要换算后再写回时长,
            # 否则有片头的项目每段都会拿到前一段的时长,视频排版整体错位。
            chunks = meta["chunks"]
            if chunks_align_with_segments(chunks, segments):
                for ci, chunk in enumerate(chunks):
                    seg_index = chunk_segment_index(chunks, ci)
                    if seg_index is not None and 0 <= seg_index < len(segments):
                        segments[seg_index].duration_hint = chunk.get("duration", 0)

            await db.commit()

        return {"file_path": str(output_path), "duration": duration}

    async def _get_provider(self, db, provider_type: str,
                             overrides: dict[str, str] | None = None) -> ProviderConfig | None:
        # Priority: 1. Override, 2. DB default, 3. Env var fallback, 4. First available
        if overrides and provider_type in overrides:
            result = await db.execute(
                select(ProviderConfig).where(ProviderConfig.id == overrides[provider_type])
            )
            return result.scalar_one_or_none()

        result = await db.execute(
            select(ProviderConfig)
            .where(ProviderConfig.provider_type == provider_type, ProviderConfig.is_default == True)
        )
        config = result.scalar_one_or_none()
        if config:
            return config

        # Fallback 1: try to create from environment variables
        from .provider_helper import get_provider_from_env
        config = await get_provider_from_env(db, provider_type)
        if config:
            return config

        # Fallback 2: get first available provider (for UI-added providers)
        from .provider_helper import get_first_provider
        return await get_first_provider(db, provider_type)
