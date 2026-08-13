"""本地 VoxCPM2 TTS 常驻服务.

启动时加载一次 VoxCPM2 并常驻内存(保持 MPS 内核热 → 稳态 RTF ~2.4)。
app 后端通过 HTTP 调用它做零样本声音克隆,与主进程解耦。

零样本克隆:给一段参考音频(reference_audio_path)即可克隆该音色,无需训练。
运行:
    local-tts/venv/bin/python local-tts/server.py
环境变量:
    VOXCPM_MODEL_DIR   模型目录(默认 ModelScope 缓存)
    VOXCPM_PORT        监听端口(默认 9530)
    VOXCPM_WARMUP_REF  预热用参考音频路径(可选,预编译 MPS 内核)
"""

import io
import os
import time
import logging

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import librosa
import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("voxcpm-server")

MODEL_DIR = os.environ.get(
    "VOXCPM_MODEL_DIR",
    os.path.expanduser("~/.cache/modelscope/models/OpenBMB--VoxCPM2/snapshots/master"),
)
PORT = int(os.environ.get("VOXCPM_PORT", "9530"))
WARMUP_REF = os.environ.get("VOXCPM_WARMUP_REF", "")

# 全局单例:模型只加载一次
_model = None
_sample_rate = None


def get_model():
    global _model, _sample_rate
    if _model is None:
        from voxcpm import VoxCPM
        logger.info("Loading VoxCPM2 from %s ...", MODEL_DIR)
        t0 = time.time()
        _model = VoxCPM.from_pretrained(
            MODEL_DIR, load_denoiser=False, optimize=False,
            device="mps", local_files_only=True,
        )
        _sample_rate = _model.tts_model.sample_rate
        logger.info("Model ready in %.1fs (sample_rate=%s)", time.time() - t0, _sample_rate)
    return _model


class TTSRequest(BaseModel):
    text: str
    reference_audio_path: str = Field(..., description="克隆参考音频的绝对路径")
    reference_text: str | None = Field(None, description="参考音频转写(可选,保真更高)")
    speed: float = Field(1.0, gt=0.3, le=2.0, description="语速倍率,<1 更慢(保音调)")
    normalize: bool = Field(True, description="文本归一化(数字/单位/符号)")
    timesteps: int = Field(15, ge=4, le=40, description="推理步数,越大越稳越慢")
    cfg_value: float = Field(2.0, ge=1.0, le=4.0)


app = FastAPI(title="VoxCPM2 Local TTS")


@app.on_event("startup")
def _startup():
    get_model()  # 加载模型
    if WARMUP_REF and os.path.exists(WARMUP_REF):
        logger.info("Warming up (pre-compiling MPS kernels) ...")
        try:
            t0 = time.time()
            get_model().generate(
                text="预热。", reference_wav_path=WARMUP_REF,
                cfg_value=2.0, inference_timesteps=10, normalize=False,
            )
            logger.info("Warmup done in %.1fs", time.time() - t0)
        except Exception as e:
            logger.warning("Warmup failed (non-fatal): %s", e)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_loaded": _model is not None,
        "sample_rate": _sample_rate,
        "device": "mps",
        "model_dir": MODEL_DIR,
    }


@app.post("/tts")
def tts(req: TTSRequest):
    if not os.path.exists(req.reference_audio_path):
        raise HTTPException(status_code=400,
                            detail=f"参考音频不存在: {req.reference_audio_path}")
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text 不能为空")

    model = get_model()
    t0 = time.time()
    kwargs = dict(
        text=req.text,
        reference_wav_path=req.reference_audio_path,
        cfg_value=req.cfg_value,
        inference_timesteps=req.timesteps,
        normalize=req.normalize,
    )
    # 有参考文本时用 prompt 模式(保真更高)
    if req.reference_text:
        kwargs["prompt_wav_path"] = req.reference_audio_path
        kwargs["prompt_text"] = req.reference_text
    wav = model.generate(**kwargs)

    # 语速微调(保音调的时间伸缩)
    if abs(req.speed - 1.0) > 1e-3:
        wav = librosa.effects.time_stretch(wav, rate=req.speed)

    gen = time.time() - t0
    dur = len(wav) / _sample_rate
    logger.info("tts: %d 字 -> %.1fs 音频, 用时 %.1fs, RTF=%.1f",
                len(req.text), dur, gen, gen / max(dur, 0.01))

    buf = io.BytesIO()
    sf.write(buf, wav, _sample_rate, format="WAV")
    buf.seek(0)
    return Response(
        content=buf.read(),
        media_type="audio/wav",
        headers={
            "X-Audio-Duration": f"{dur:.3f}",
            "X-Sample-Rate": str(_sample_rate),
            "X-Generate-Seconds": f"{gen:.1f}",
        },
    )


if __name__ == "__main__":
    import uvicorn
    # 仅本机访问(与 app 的 loopback 安全策略一致)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
