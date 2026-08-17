# 本地 VoxCPM-0.5B TTS 服务

本地部署的 **VoxCPM-0.5B** 零样本声音克隆 TTS,给主程序做离线语音合成。
Apache-2.0,可商用。与主程序解耦:模型跑在这个独立 venv 的常驻 HTTP 服务里,
后端通过 `local_voxcpm` provider 调用(默认 `http://127.0.0.1:9530`)。

## 为什么用 0.5B(而不是 2B)

2B(VoxCPM2)音质更好(48kHz),但 float32 下需 ~20GB 内存,在 18GB Mac 上
会撑爆(崩溃/死机)。**0.5B 内存仅 ~3-5GB,RTF ~1.2-1.5(比实时还快)**,
音质经实测可接受(16kHz + 降噪)。要 2B 请上更大内存机器 / GPU。

## 一次性安装

```bash
cd /Users/mac/AI-Podcast
/opt/homebrew/bin/python3.12 -m venv local-tts/venv
local-tts/venv/bin/pip install -r local-tts/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 【必需】torchaudio.load 依赖 torchcodec,而 torchcodec 只支持到 FFmpeg 6。
# 系统若是 FFmpeg 7,必须装 ffmpeg@6 提供 libavutil.58:
brew install ffmpeg@6
```

模型首次运行从 **ModelScope** 自动下载:`OpenBMB/VoxCPM-0.5B`、whisper(转写)、
`iic/speech_zipenhancer`(降噪器)。

## 启动服务

```bash
bash local-tts/run.sh
# run.sh 会自动设好 DYLD_FALLBACK_LIBRARY_PATH 指向 ffmpeg@6,并预热。
```

`GET /health` 返回 `model_loaded:true` 即就绪(加载约 20-40s)。

## 工作原理

0.5B 走 **prompt 模式**克隆,需要参考音频的文字转写。服务自动处理:
1. **转写**:用 whisper(small)转写参考音频,按路径缓存;
2. **降噪**:参考音频用 zipenhancer **预降噪一次、落盘缓存**(`denoised_cache/`),
   之后合成用干净版 + `denoise=False`(否则每次请求重跑降噪器会固定加 ~150s);
3. **合成**:prompt 模式克隆,输出 16kHz。

首次注册一个新声音会有一次性开销(转写 ~3s + 降噪 ~160s),之后该声音每次
合成 RTF ~1.4。

## 接口

- `GET  /health`
- `POST /tts` `{text, reference_audio_path, reference_text?, speed?, normalize?, timesteps?, cfg_value?}`
  → `audio/wav`(16kHz)。`reference_text` 不传则服务自动转写。

## 环境变量

- `VOXCPM_MODEL_ID` 模型(默认 `OpenBMB/VoxCPM-0.5B`)
- `VOXCPM_WHISPER` 转写模型(默认 `small`)
- `VOXCPM_PORT` 端口(默认 9530)
- `DYLD_FALLBACK_LIBRARY_PATH` 指向 `/opt/homebrew/opt/ffmpeg@6/lib`(run.sh 自动设)
