"""本地 VoxCPM2 TTS Provider — 调用常驻的 local-tts 服务做零样本声音克隆.

架构:模型运行在独立 venv 的常驻 HTTP 服务里(默认 127.0.0.1:9530),
本 provider 通过 HTTP 调用它,与主进程解耦。零样本克隆,无需训练。

声音选择:audio_service 会把所选克隆声音的【参考音频绝对路径】放进
TTSRequest.voice_id 传进来,provider 转发给服务。
"""

import asyncio
import logging
import uuid
from pathlib import Path

import httpx

from ..base import ProviderMetadata, ProviderType
from ..registry import ProviderRegistry
from .base import TTSProvider, TTSRequest, TTSResponse

logger = logging.getLogger(__name__)


@ProviderRegistry.register
class LocalVoxCPMProvider(TTSProvider):
    """本地 VoxCPM2 零样本声音克隆(离线、Apache-2.0 可商用)。

    使用前需启动本地服务:
        local-tts/venv/bin/python local-tts/server.py
    config 可选:
        - timesteps: 推理步数(默认 15,越大越稳越慢)
        - cfg_value: 默认 2.0
    """
    metadata = ProviderMetadata(
        key="local_voxcpm",
        name="本地 VoxCPM (声音克隆)",
        provider_type=ProviderType.TTS,
        description="本地部署的 VoxCPM2 零样本声音克隆,离线运行、可商用。需先启动 local-tts 服务。",
        supported_models=["voxcpm2"],
        default_api_base="http://127.0.0.1:9530",
        requires_api_key=False,
    )

    async def synthesize(self, request: TTSRequest,
                         output_path: Path = Path("")) -> TTSResponse:
        ref_path = request.voice_id
        if not ref_path:
            raise RuntimeError(
                "本地 VoxCPM 需要参考音频。请为项目选择一个克隆声音(带参考音频)。"
            )
        if not Path(ref_path).exists():
            raise RuntimeError(f"参考音频不存在: {ref_path}")

        payload = {
            "text": request.text,
            "reference_audio_path": ref_path,
            "speed": request.speed,
            "normalize": True,
            "timesteps": int(self.config.get("timesteps", 15)),
            "cfg_value": float(self.config.get("cfg_value", 2.0)),
        }

        # trust_env=False:本机服务,不走任何环境代理(避免 SOCKS/HTTP 代理干扰)
        async with httpx.AsyncClient(timeout=600.0, trust_env=False) as client:
            try:
                resp = await client.post(f"{self.api_base_url}/tts", json=payload)
            except httpx.ConnectError as exc:
                raise RuntimeError(
                    f"连不上本地 VoxCPM 服务({self.api_base_url})。"
                    f"请先启动 local-tts/server.py。原始错误: {exc}"
                ) from exc
            if resp.status_code != 200:
                raise RuntimeError(
                    f"本地 VoxCPM 服务返回错误({resp.status_code}): {resp.text[:200]}"
                )
            wav_bytes = resp.content
            sample_rate = int(resp.headers.get("X-Sample-Rate", "48000"))

        if not output_path or output_path == Path(""):
            output_path = Path(f"{uuid.uuid4().hex}.mp3")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 服务返回 WAV;基类分块/拼接按 mp3 处理,这里转成 mp3
        tmp_wav = output_path.with_suffix(".voxcpm.wav")
        tmp_wav.write_bytes(wav_bytes)
        try:
            await self._wav_to_mp3(tmp_wav, output_path)
        finally:
            tmp_wav.unlink(missing_ok=True)

        duration = await self._probe_duration(output_path)
        return TTSResponse(
            file_path=output_path,
            duration=duration,
            sample_rate=sample_rate,
            model_used="voxcpm2",
        )

    async def validate_connection(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
                r = await client.get(f"{self.api_base_url}/health")
                return r.status_code == 200 and bool(r.json().get("model_loaded"))
        except Exception:
            return False

    async def list_voices(self) -> list[dict]:
        # 本地克隆的"声音"由项目的 voice_clones(参考音频)决定,无预置发音人
        return []

    @staticmethod
    async def _wav_to_mp3(wav_path: Path, mp3_path: Path) -> None:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", str(wav_path.resolve()),
            "-c:a", "libmp3lame", "-q:a", "2", str(mp3_path.resolve()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"wav->mp3 转码失败: {stderr.decode(errors='replace')[-200:]}"
            )
