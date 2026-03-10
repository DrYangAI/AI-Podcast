"""豆包 TTS Provider — 火山引擎语音合成 WebSocket API.

基于官方文档: https://www.volcengine.com/docs/6561/1719100

接口说明:
- WebSocket 地址: wss://openspeech.bytedance.com/api/v3/tts/unidirectional/stream
- 使用二进制协议传输数据
- 支持豆包语音合成模型 1.0 / 2.0, 声音复刻 1.0 / 2.0

使用方法:
- app_id: 火山引擎控制台获取的 APP ID
- api_key: 火山引擎控制台获取的 Access Token
- resource_id: 资源 ID (seed-tts-1.0, seed-tts-2.0, seed-icl-1.0, seed-icl-2.0)
- voice_id: 发音人 ID (如 zh_female_shuangkuaisisi_moon_bigtts)
"""

import asyncio
import json
import struct
import uuid
from pathlib import Path
from typing import Any

import websockets

from ..base import ProviderMetadata, ProviderType
from ..registry import ProviderRegistry
from .base import TTSProvider, TTSRequest, TTSResponse


# 二进制协议常量
PROTOCOL_VERSION = 0b0001
HEADER_SIZE = 0b0001  # 4 bytes
MESSAGE_TYPE_TEXT = 0b001  # SendText
MESSAGE_TYPE_AUDIO = 0b1011  # Audio response
MESSAGE_TYPE_FULL = 0b1001  # Full response (with event number)
MESSAGE_TYPE_ERROR = 0b1111  # Error frame
SERIALIZATION_JSON = 0b0001
SERIALIZATION_RAW = 0b0000
COMPRESSION_NONE = 0b0000

# Event codes
EVENT_TTS_SENTENCE_START = 350
EVENT_TTS_SENTENCE_END = 351
EVENT_TTS_RESPONSE = 352
EVENT_SESSION_FINISHED = 152


@ProviderRegistry.register
class DoubaoTTSProvider(TTSProvider):
    """
    豆包语音合成 - 火山引擎 WebSocket API.

    使用方法:
    1. 登录火山引擎控制台 (https://console.volcengine.com/)
    2. 获取 APP ID 和 Access Token
    3. 选择模型版本 (seed-tts-1.0 / seed-tts-2.0 / seed-icl-1.0 / seed-icl-2.0)
    4. 选择发音人 (见 list_voices)

    配置参数 (config):
    - app_id: 火山引擎 APP ID
    - resource_id: 资源 ID (默认: seed-tts-1.0)
    - emotion: 情感设置 (可选, 部分音色支持)
    - emotion_scale: 情绪值 1-5 (默认 4)
    """
    metadata = ProviderMetadata(
        key="doubao_tts",
        name="豆包 (语音合成)",
        provider_type=ProviderType.TTS,
        description="字节跳动豆包语音合成,支持多语种、多方言、声音复刻",
        supported_models=[
            "seed-tts-1.0",
            "seed-tts-1.0-concurr",
            "seed-tts-2.0",
            "seed-icl-1.0",
            "seed-icl-1.0-concurr",
            "seed-icl-2.0",
        ],
        default_api_base="wss://openspeech.bytedance.com/api/v3/tts/unidirectional/stream",
        requires_api_key=True,
    )

    def __init__(self, api_key: str = "", api_base_url: str = "",
                 model_id: str = "", config: dict[str, Any] | None = None):
        super().__init__(api_key, api_base_url, model_id, config)
        self.app_id = self.config.get("app_id", "")
        self.resource_id = self.config.get("resource_id", "seed-tts-1.0")
        self.icl_resource_id = self.config.get("icl_resource_id", "")

    def _build_text_frame(self, payload: dict) -> bytes:
        """构建 SendText 二进制帧."""
        # 将 payload 序列化为 JSON
        payload_json = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        payload_length = len(payload_json)

        # 构建 header
        # Byte 0: Protocol version (4-bit) + Header size (4-bit)
        byte0 = (PROTOCOL_VERSION << 4) | HEADER_SIZE
        # Byte 1: Message type (4-bit) + Message type specific flags (4-bit)
        byte1 = (MESSAGE_TYPE_TEXT << 4) | 0b0000
        # Byte 2: Serialization method (4-bit) + Compression method (4-bit)
        byte2 = (SERIALIZATION_JSON << 4) | COMPRESSION_NONE
        # Byte 3: Reserved
        byte3 = 0b0000

        # 构建帧: header(4 bytes) + payload length(4 bytes) + payload
        frame = bytes([byte0, byte1, byte2, byte3])
        frame += struct.pack(">I", payload_length)  # 大端 uint32
        frame += payload_json

        return frame

    def _parse_response_frame(self, data: bytes) -> dict:
        """解析响应帧.

        V3 二进制协议格式:
        - [0-3]: header (protocol version, header size, message type, flags, serialization, compression, reserved)
        - 当 flags 包含 0b0100 (带 event number) 时:
            - [4-7]: event_type (uint32)
            - [8-11]: session_id_len (uint32)
            - [12 ~ 12+N]: session_id
            - [12+N ~ 16+N]: payload_len (uint32)
            - [16+N ~ ...]: payload_data
        - 当 flags 不包含 0b0100 时:
            - [4-7]: payload_len (uint32)
            - [8 ~ ...]: payload_data
        - 错误帧 (message_type=0b1111):
            - [4-7]: error_code (uint32)
            - [8 ~ ...]: error_message
        """
        if len(data) < 4:
            return {"type": "unknown", "data": data}

        # 解析 header
        byte1 = data[1]
        message_type = (byte1 >> 4) & 0x0F
        message_flags = byte1 & 0x0F
        has_event = (message_flags & 0b0100) != 0

        # 错误帧
        if message_type == MESSAGE_TYPE_ERROR:
            if len(data) >= 8:
                error_code = struct.unpack(">I", data[4:8])[0]
                error_msg = data[8:].decode('utf-8', errors='ignore')
                return {"type": "error", "code": error_code, "message": error_msg}
            return {"type": "error", "code": 0, "message": "Unknown error"}

        # 带 event number 的响应帧 (音频帧、全量帧)
        if has_event:
            if len(data) < 12:
                return {"type": "unknown", "data": data}

            event_type = struct.unpack(">I", data[4:8])[0]
            session_id_len = struct.unpack(">I", data[8:12])[0]
            offset = 12 + session_id_len

            # 解析 payload
            if len(data) >= offset + 4:
                payload_len = struct.unpack(">I", data[offset:offset + 4])[0]
                payload_data = data[offset + 4:offset + 4 + payload_len]
            else:
                payload_data = b""

            if event_type == EVENT_TTS_RESPONSE:
                return {"type": "audio", "data": payload_data}
            elif event_type == EVENT_SESSION_FINISHED:
                try:
                    meta = json.loads(payload_data.decode('utf-8'))
                    return {"type": "session_finished", "data": meta}
                except Exception:
                    return {"type": "session_finished", "data": {}}
            elif event_type == EVENT_TTS_SENTENCE_START:
                return {"type": "sentence_start", "data": payload_data}
            elif event_type == EVENT_TTS_SENTENCE_END:
                try:
                    text_data = json.loads(payload_data.decode('utf-8'))
                    return {"type": "sentence_end", "data": text_data}
                except Exception:
                    return {"type": "sentence_end", "data": payload_data}
            return {"type": "unknown_event", "event": event_type, "data": payload_data}

        # 不带 event number 的响应帧
        if len(data) >= 8:
            payload_length = struct.unpack(">I", data[4:8])[0]
            payload_data = data[8:8 + payload_length]
            return {"type": "payload", "data": payload_data}

        return {"type": "unknown", "data": data}

    async def synthesize(self, request: TTSRequest,
                         output_path: Path = Path("")) -> TTSResponse:
        """合成语音（支持标准模式和 ICL 声音复刻模式）.

        ICL 模式: 需要先通过 voice_clone 训练接口注册音色，获得 speaker_id，
        然后在此处通过 speaker_id + ICL resource_id 进行合成。
        """
        ws_url = self.api_base_url or self.metadata.default_api_base
        voice_id = request.voice_id or "zh_female_shuangkuaisisi_moon_bigtts"

        # 判断是否使用 ICL（声音复刻）模式
        use_icl = request.use_icl

        # 构建请求 headers — ICL 模式使用 ICL 资源 ID
        resource_id = self.resource_id
        if use_icl:
            if self.icl_resource_id:
                resource_id = self.icl_resource_id
            elif "icl" not in resource_id:
                resource_id = "seed-icl-1.0"

        headers = {
            "X-Api-App-Id": self.app_id,
            "X-Api-Access-Key": self.api_key,
            "X-Api-Resource-Id": resource_id,
            "X-Api-Request-Id": str(uuid.uuid4()),
        }

        # 构建请求 payload
        payload = {
            "user": {"uid": self.app_id or "anonymous"},
            "req_params": {
                "text": request.text,
                "speaker": voice_id,
                "audio_params": {
                    "format": request.output_format or "mp3",
                    "sample_rate": 24000,
                },
            }
        }

        # 添加语速设置
        if request.speed != 1.0:
            speech_rate = int((request.speed - 1.0) * 100)
            payload["req_params"]["audio_params"]["speech_rate"] = speech_rate

        # 添加情感设置 (仅标准模式)
        if not use_icl:
            emotion = self.config.get("emotion")
            if emotion:
                payload["req_params"]["audio_params"]["emotion"] = emotion
                emotion_scale = self.config.get("emotion_scale", 4)
                payload["req_params"]["audio_params"]["emotion_scale"] = emotion_scale

        audio_chunks: list[bytes] = []
        session_finished = False

        try:
            async with websockets.connect(ws_url, additional_headers=headers) as ws:
                # 发送文本帧
                text_frame = self._build_text_frame(payload)
                await ws.send(text_frame)

                # 接收响应
                while not session_finished:
                    try:
                        response = await asyncio.wait_for(ws.recv(), timeout=60)
                        result = self._parse_response_frame(response)

                        if result["type"] == "audio":
                            audio_chunks.append(result["data"])
                        elif result["type"] == "session_finished":
                            session_finished = True
                        elif result["type"] == "error":
                            raise RuntimeError(f"豆包 TTS 错误: {result.get('code')} - {result.get('message')}")

                    except asyncio.TimeoutError:
                        break

        except websockets.exceptions.WebSocketException as e:
            raise RuntimeError(f"WebSocket 连接错误: {str(e)}")

        if not audio_chunks:
            raise RuntimeError("未收到任何音频数据")

        if not output_path or output_path == Path(""):
            output_path = Path(f"{uuid.uuid4().hex}.{request.output_format or 'mp3'}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"".join(audio_chunks))

        duration = await self._get_audio_duration(output_path)

        return TTSResponse(
            file_path=output_path,
            duration=duration,
            sample_rate=24000,
            model_used=self.resource_id,
        )

    async def list_voices(self) -> list[dict]:
        """列出可用的发音人 (豆包语音合成模型1.0)."""
        return [
            # 女声
            {"id": "zh_female_shuangkuaisisi_moon_bigtts", "name": "爽快思思", "gender": "female", "language": "zh-CN", "model": "seed-tts-1.0"},
            {"id": "zh_female_wanwanxiaohe_moon_bigtts", "name": "弯弯小河", "gender": "female", "language": "zh-CN", "model": "seed-tts-1.0"},
            {"id": "zh_female_tianmeixiaoyuan_moon_bigtts", "name": "甜美小媛", "gender": "female", "language": "zh-CN", "model": "seed-tts-1.0"},
            {"id": "zh_female_cancan_mars_bigtts", "name": "灿灿mars", "gender": "female", "language": "zh-CN", "model": "seed-tts-1.0"},
            {"id": "zh_female_yujie_moon_bigtts", "name": "雨洁", "gender": "female", "language": "zh-CN", "model": "seed-tts-1.0"},
            {"id": "zh_female_aizhang_moon_bigtts", "name": "艾张", "gender": "female", "language": "zh-CN", "model": "seed-tts-1.0"},
            {"id": "zh_female_xiaoxia_moon_bigtts", "name": "小夏", "gender": "female", "language": "zh-CN", "model": "seed-tts-1.0"},
            {"id": "zh_female_xue_qing_vip", "name": "雪青(VIP)", "gender": "female", "language": "zh-CN", "model": "seed-tts-1.0"},
            # 男声
            {"id": "zh_male_chunhou_moon_bigtts", "name": "淳厚男声", "gender": "male", "language": "zh-CN", "model": "seed-tts-1.0"},
            {"id": "zh_male_yangguangqingnian_moon_bigtts", "name": "阳光青年", "gender": "male", "language": "zh-CN", "model": "seed-tts-1.0"},
            {"id": "zh_male_bvlazysheep", "name": "BV懒羊羊", "gender": "male", "language": "zh-CN", "model": "seed-tts-1.0"},
            {"id": "zh_male_ahu_conversation_wvae_bigtts", "name": "AHU对话", "gender": "male", "language": "zh-CN", "model": "seed-tts-1.0"},
            {"id": "zh_male_xiaoguang_vip", "name": "晓光(VIP)", "gender": "male", "language": "zh-CN", "model": "seed-tts-1.0"},
            # 情感音色 (支持 emotion 参数)
            {"id": "emotion_angry_sc", "name": "愤怒-川建国", "gender": "male", "language": "zh-CN", "model": "seed-tts-1.0", "emotion": True},
            {"id": "emotion_disgust_sc", "name": "厌恶-川建国", "gender": "male", "language": "zh-CN", "model": "seed-tts-1.0", "emotion": True},
            {"id": "emotion_fear_sc", "name": "害怕-川建国", "gender": "male", "language": "zh-CN", "model": "seed-tts-1.0", "emotion": True},
            {"id": "emotion_happy_sc", "name": "开心-川建国", "gender": "male", "language": "zh-CN", "model": "seed-tts-1.0", "emotion": True},
            {"id": "emotion_sad_sc", "name": "悲伤-川建国", "gender": "male", "language": "zh-CN", "model": "seed-tts-1.0", "emotion": True},
            {"id": "emotion_surprise_sc", "name": "惊讶-川建国", "gender": "male", "language": "zh-CN", "model": "seed-tts-1.0", "emotion": True},
        ]

    async def validate_connection(self) -> bool:
        """验证连接 - 尝试合成一个短音频."""
        try:
            result = await self.synthesize(
                TTSRequest(text="测试"),
                output_path=Path(f"/tmp/doubao_test_{uuid.uuid4().hex}.mp3"),
            )
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
