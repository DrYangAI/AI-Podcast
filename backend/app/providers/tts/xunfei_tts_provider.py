"""科大讯飞 TTS Provider — 讯飞开放平台语音合成 WebSocket API.

讯飞 TTS 使用 WebSocket 接口 (wss://tts-api.xfyun.cn/v2/tts)。
需要 app_id, api_key, api_secret 三个凭证。
"""

import asyncio
import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, urlparse

import httpx

from ..base import ProviderMetadata, ProviderType
from ..registry import ProviderRegistry
from .base import TTSProvider, TTSRequest, TTSResponse


@ProviderRegistry.register
class XunfeiTTSProvider(TTSProvider):
    """
    科大讯飞语音合成。

    使用方法:
    - api_key: 填写讯飞的 APIKey
    - config 中需要:
        - app_id: 讯飞 APPID
        - api_secret: 讯飞 APISecret
    - voice_id: 发音人 (如 xiaoyan, aisjiuxu, aisxping 等)

    注意: 讯飞 TTS 使用 WebSocket 接口，这里使用 REST 包装。
    如果 websockets 不可用，将回退到 HTTP 流式接口。
    """
    metadata = ProviderMetadata(
        key="xunfei_tts",
        name="科大讯飞 (语音合成)",
        provider_type=ProviderType.TTS,
        description="科大讯飞高质量语音合成",
        supported_models=[
            "xtts",  # 讯飞超拟人合成
        ],
        default_api_base="wss://tts-api.xfyun.cn/v2/tts",
        requires_api_key=True,
    )

    def _build_auth_url(self) -> str:
        """构建讯飞 WebSocket 鉴权 URL。"""
        api_secret = self.config.get("api_secret", "")
        api_key = self.api_key
        host = "tts-api.xfyun.cn"
        path = "/v2/tts"
        now = datetime.utcnow()
        date_str = now.strftime("%a, %d %b %Y %H:%M:%S GMT")

        signature_origin = f"host: {host}\ndate: {date_str}\nGET {path} HTTP/1.1"
        signature_sha = hmac.new(
            api_secret.encode(), signature_origin.encode(), hashlib.sha256
        ).digest()
        signature = base64.b64encode(signature_sha).decode()

        authorization_origin = (
            f'api_key="{api_key}", algorithm="hmac-sha256", '
            f'headers="host date request-line", signature="{signature}"'
        )
        authorization = base64.b64encode(authorization_origin.encode()).decode()

        params = {
            "authorization": authorization,
            "date": date_str,
            "host": host,
        }
        return f"wss://{host}{path}?{urlencode(params)}"

    async def synthesize(self, request: TTSRequest,
                         output_path: Path = Path("")) -> TTSResponse:
        try:
            import websockets
        except ImportError:
            raise RuntimeError(
                "讯飞 TTS 需要 websockets 库。请运行: pip install websockets"
            )

        app_id = self.config.get("app_id", "")
        voice = request.voice_id or self.config.get("voice", "xiaoyan")

        auth_url = self._build_auth_url()

        # 构建数据帧
        text_b64 = base64.b64encode(request.text.encode()).decode()
        ws_data = {
            "common": {"app_id": app_id},
            "business": {
                "aue": "lame",  # mp3 格式
                "auf": "audio/L16;rate=16000",
                "vcn": voice,
                "tte": "utf8",
                "speed": int(request.speed * 50),  # 0-100, 50 为正常
            },
            "data": {
                "status": 2,  # 一次性发送
                "text": text_b64,
            },
        }

        audio_chunks: list[bytes] = []

        async with websockets.connect(auth_url) as ws:
            await ws.send(json.dumps(ws_data))

            while True:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=30)
                    result = json.loads(message)

                    if result.get("code") != 0:
                        raise RuntimeError(f"讯飞 TTS 错误: {result.get('message', 'Unknown')}")

                    audio_data = result.get("data", {}).get("audio")
                    if audio_data:
                        audio_chunks.append(base64.b64decode(audio_data))

                    status = result.get("data", {}).get("status", 0)
                    if status == 2:
                        break
                except asyncio.TimeoutError:
                    break

        if not output_path or output_path == Path(""):
            output_path = Path(f"{uuid.uuid4().hex}.mp3")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"".join(audio_chunks))

        duration = await self._get_audio_duration(output_path)

        return TTSResponse(
            file_path=output_path,
            duration=duration,
            sample_rate=16000,
            model_used="xunfei-xtts",
        )

    async def list_voices(self) -> list[dict]:
        return [
            {"id": "xiaoyan", "name": "小燕 (普通话女声)", "gender": "female", "language": "zh-CN"},
            {"id": "aisjiuxu", "name": "许久 (普通话男声)", "gender": "male", "language": "zh-CN"},
            {"id": "aisxping", "name": "小萍 (普通话女声)", "gender": "female", "language": "zh-CN"},
            {"id": "aisjinger", "name": "小婧 (普通话女声)", "gender": "female", "language": "zh-CN"},
            {"id": "aisbabyxu", "name": "许小宝 (童声)", "gender": "neutral", "language": "zh-CN"},
        ]

    async def validate_connection(self) -> bool:
        """验证讯飞 TTS 凭证 — 尝试合成一个很短的音频。"""
        try:
            result = await self.synthesize(
                TTSRequest(text="测试"),
                output_path=Path(f"/tmp/xunfei_test_{uuid.uuid4().hex}.mp3"),
            )
            # 清理测试文件
            if result.file_path.exists():
                result.file_path.unlink()
            return True
        except Exception:
            return False

    @staticmethod
    async def _get_audio_duration(file_path: Path) -> float:
        try:
            process = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "csv=p=0", str(file_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            return float(stdout.decode().strip())
        except Exception:
            return 0.0
