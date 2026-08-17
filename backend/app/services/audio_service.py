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

            # Check if segments have per-segment script_text
            seg_result = await db.execute(
                select(Segment)
                .where(Segment.project_id == project_id)
                .order_by(Segment.segment_order)
            )
            segments = list(seg_result.scalars().all())
            # PPT-imported projects use the per-segment path even when some slides
            # have empty notes (those become silent still-frames below).
            is_ppt = bool(project and getattr(project, "source_type", "") == "ppt")
            has_segment_scripts = bool(segments) and (
                is_ppt or all(seg.script_text for seg in segments)
            )

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
            if segments and chunk.get("type") not in ("intro", "outro"):
                # Calculate segment index by skipping intro/outro chunks
                seg_index = chunk_index
                for i in range(chunk_index):
                    if chunks[i].get("type") in ("intro", "outro"):
                        seg_index -= 1
                if 0 <= seg_index < len(segments) and segments[seg_index].script_text:
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
        chunks[chunk_index] = chunk

        # Save updated chunks.json (preserve display name, store real speaker_id)
        TTSProvider._save_chunks_json(chunks_dir, chunks, voice_id, use_icl,
                                      voice_display=voice_display)

        # Sync back to segment if in per-segment mode
        async with async_session_factory() as db:
            seg_result = await db.execute(
                select(Segment)
                .where(Segment.project_id == project_id)
                .order_by(Segment.segment_order)
            )
            segments = list(seg_result.scalars().all())
            if segments and chunk_index < len(segments):
                seg = segments[chunk_index]
                if seg.script_text:
                    # Copy regenerated audio back to segment dir
                    seg_audio = Path(seg.audio_file) if seg.audio_file else None
                    if seg_audio:
                        import shutil as _shutil
                        _shutil.copy2(chunk_path, seg_audio)
                    seg.duration_hint = dur
                    await db.commit()
                    logger.info("Synced regenerated chunk %d back to segment", chunk_index)

        return chunk

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
            if segments and segments[0].script_text:
                for i, seg in enumerate(segments):
                    if i < len(meta["chunks"]):
                        seg.duration_hint = meta["chunks"][i].get("duration", 0)

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
