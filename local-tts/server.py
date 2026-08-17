"""本地 VoxCPM-0.5B TTS 常驻服务(零样本声音克隆).

用 VoxCPM-0.5B:内存仅 ~3-5GB,适合 18GB Mac(2B 需 ~20GB 会撑爆内存)。
0.5B 走 prompt 模式克隆,需要参考音频的转写文本;服务内部用 whisper 转写
并按音频路径缓存,app 端只需传 reference_audio_path(无需关心转写)。

运行(务必带 DYLD 路径,否则 torchaudio.load 找不到 ffmpeg 库):
    DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/opt/ffmpeg@6/lib \
        local-tts/venv/bin/python local-tts/server.py
"""

import io
import os
import time
import hashlib
import logging
import threading

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
# 注意:torchaudio 2.x 的 load() 依赖 torchcodec,而 torchcodec 只支持到
# FFmpeg 6,系统若是 FFmpeg 7 会找不到 libavutil。DYLD_FALLBACK_LIBRARY_PATH
# 必须在【进程启动前】由 run.sh/restart.sh 设好,在这里设无效(dyld 只读启动时环境)。

import librosa
import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("voxcpm-server")

MODEL_ID = os.environ.get("VOXCPM_MODEL_ID", "OpenBMB/VoxCPM-0.5B")
WHISPER_MODEL = os.environ.get("VOXCPM_WHISPER", "small")
PORT = int(os.environ.get("VOXCPM_PORT", "9530"))
WARMUP_REF = os.environ.get("VOXCPM_WARMUP_REF", "")

# 单机单 MPS 设备:全局串行锁。本服务的 /tts 端点是 sync def,FastAPI 会把它丢进
# 线程池,多个请求会【同时】跑 model.generate() 抢同一块 MPS —— 实测并发会把 RTF
# 从 ~1.3 拖到 7+,单个请求耗时飙到 800s+ 触发客户端 600s 超时,进而重试叠加、雪崩。
# 加锁让并发请求排队(而非抢占),每个请求都在健康 RTF 下顺序完成。
_gen_lock = threading.Lock()

_model = None
_sample_rate = None
_whisper = None
_transcript_cache: dict[str, str] = {}
_denoised_cache: dict[str, str] = {}

DENOISE_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "denoised_cache")
os.makedirs(DENOISE_CACHE_DIR, exist_ok=True)


def get_model():
    global _model, _sample_rate
    if _model is None:
        from modelscope import snapshot_download
        from voxcpm import VoxCPM
        logger.info("Downloading/loading %s ...", MODEL_ID)
        t0 = time.time()
        local_dir = snapshot_download(MODEL_ID)
        _model = VoxCPM.from_pretrained(
            local_dir, load_denoiser=True, optimize=False, device="mps",
        )
        _sample_rate = _model.tts_model.sample_rate
        logger.info("Model ready in %.1fs (sample_rate=%s)", time.time() - t0, _sample_rate)
    return _model


def get_whisper():
    global _whisper
    if _whisper is None:
        import whisper
        logger.info("Loading whisper '%s' for reference transcription ...", WHISPER_MODEL)
        _whisper = whisper.load_model(WHISPER_MODEL)
    return _whisper


def transcribe_reference(ref_path: str) -> str:
    """转写参考音频(按路径缓存,每个声音只转一次)。"""
    if ref_path in _transcript_cache:
        return _transcript_cache[ref_path]
    t0 = time.time()
    result = get_whisper().transcribe(
        ref_path, language="zh", fp16=False,
        initial_prompt="以下是普通话医学科普。",
    )
    text = (result.get("text") or "").strip()
    _transcript_cache[ref_path] = text
    logger.info("Transcribed reference in %.1fs: %s", time.time() - t0, text[:40])
    return text


REF_MAX_SECONDS = float(os.environ.get("VOXCPM_REF_SECONDS", "20"))


def prepare_reference(ref_path: str, denoise: bool = True,
                      ref_seconds: float = REF_MAX_SECONDS) -> str:
    """把参考音频裁到前 N 秒(可选降噪)【一次】,落盘缓存。返回短参考的路径。

    克隆不需要长参考:十几秒干净片段又快又好。而降噪耗时与音频长度成正比,
    直接降噪一个 2 分钟的参考会卡十几分钟——裁到 20s 后只需 ~20s。
    合成时用这个短参考 + generate(denoise=False)。

    注意:zipenhancer 降噪器在某些音频上会把尾部语音"畸变/脑补"成糊话,
    这段被污染的参考尾巴会泄漏到每个合成片段的开头(听感是前缀杂音)。
    原始音频若本身较干净,建议 denoise=False。
    """
    # 缓存键要区分 降噪与否 + 裁剪时长,否则改参数取到旧缓存。
    key = hashlib.md5(f"{ref_path}|d{int(denoise)}|s{ref_seconds:g}".encode("utf-8")).hexdigest()[:12]
    out = os.path.join(DENOISE_CACHE_DIR, f"{key}.wav")
    if os.path.exists(out):  # 磁盘缓存:重启后仍有效
        _denoised_cache[ref_path] = out
        return out

    model = get_model()
    t0 = time.time()
    # 1) 裁剪到前 N 秒(16k 单声道)
    y, _ = librosa.load(ref_path, sr=16000, mono=True, duration=ref_seconds)
    trimmed = out + ".trim.wav"
    sf.write(trimmed, y, 16000)
    # 2) 可选降噪(若加载了降噪器)
    if denoise and getattr(model, "denoiser", None) is not None:
        model.denoiser.enhance(trimmed, output_path=out)
        os.remove(trimmed)
    else:
        os.replace(trimmed, out)
    _denoised_cache[ref_path] = out
    logger.info("Prepared reference (trim %.0fs, denoise=%s) in %.1fs -> %s",
                ref_seconds, denoise, time.time() - t0, out)
    return out


class TTSRequest(BaseModel):
    text: str
    reference_audio_path: str = Field(..., description="克隆参考音频的绝对路径")
    reference_text: str | None = Field(None, description="参考音频转写(不传则服务自动转写并缓存)")
    speed: float = Field(1.0, gt=0.3, le=2.0)
    normalize: bool = Field(True)
    timesteps: int = Field(15, ge=4, le=40)
    cfg_value: float = Field(2.0, ge=1.0, le=4.0)
    denoise_ref: bool = Field(True, description="是否对参考音频降噪(污染尾巴时设 False)")
    ref_seconds: float = Field(REF_MAX_SECONDS, gt=3, le=60, description="参考裁剪时长(秒)")


app = FastAPI(title="VoxCPM-0.5B Local TTS")


@app.on_event("startup")
def _startup():
    get_model()
    get_whisper()
    # 预热合成暂时禁用:在 uvicorn 启动上下文里跑 generate 会底层崩溃,
    # 改为首个真实请求时再编译内核(慢一点但不崩)。


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_loaded": _model is not None,
        "sample_rate": _sample_rate,
        "device": "mps",
        "model": MODEL_ID,
    }


@app.post("/tts")
def tts(req: TTSRequest):
    if not os.path.exists(req.reference_audio_path):
        raise HTTPException(status_code=400,
                            detail=f"参考音频不存在: {req.reference_audio_path}")
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text 不能为空")

    model = get_model()
    # 全局串行:并发请求在此排队,避免多生成同时抢 MPS 导致雪崩(见 _gen_lock 注释)。
    wait0 = time.time()
    with _gen_lock:
        waited = time.time() - wait0
        if waited > 1.0:
            logger.info("tts: 等待生成锁 %.1fs(前面有请求在跑)", waited)
        clean_ref = prepare_reference(req.reference_audio_path,
                                      denoise=req.denoise_ref,
                                      ref_seconds=req.ref_seconds)  # 裁剪(可选降噪)一次并缓存
        prompt_text = req.reference_text or transcribe_reference(clean_ref)  # 转写短参考

        t0 = time.time()
        wav = model.generate(
            text=req.text,
            prompt_wav_path=clean_ref,
            prompt_text=prompt_text,
            cfg_value=req.cfg_value,
            inference_timesteps=req.timesteps,
            normalize=req.normalize,
            denoise=False,  # 参考音频已预降噪,这里不再重跑降噪器
        )
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
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
