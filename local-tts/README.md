# 本地 VoxCPM2 TTS 服务

本地部署的 VoxCPM2 **零样本声音克隆** TTS,给主程序做离线语音合成。
Apache-2.0,可商用。与主程序解耦:模型跑在这个独立 venv 的常驻 HTTP 服务里,
后端通过 `local_voxcpm` provider 调用(默认 `http://127.0.0.1:9530`)。

## 为什么独立

torch 等依赖有 2-3GB,且需要 Python 3.10–3.12(系统 python3 可能是 3.14),
不能混进后端 venv。因此本目录自带独立 venv;`venv/`、模型、`*.wav`、`*.log`
都被 gitignore,只有服务代码进 git。

## 一次性安装

```bash
cd /Users/mac/AI-Podcast
/opt/homebrew/bin/python3.12 -m venv local-tts/venv
local-tts/venv/bin/pip install -r local-tts/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

模型首次运行会从 **ModelScope** 自动下载 `OpenBMB/VoxCPM2`(约 5GB,国内快;
HF/hf-mirror 实测缺文件不可靠)。

## 启动服务

```bash
local-tts/venv/bin/python local-tts/server.py
# 或用启动脚本(带预热参考,预编译 MPS 内核):
bash local-tts/run.sh
```

启动约需 40–90s 加载模型;`GET /health` 返回 `model_loaded:true` 即就绪。

## 接口

- `GET  /health` → 状态、采样率(48000)、设备
- `POST /tts` `{text, reference_audio_path, speed?, normalize?, timesteps?, cfg_value?}`
  → 返回 `audio/wav`(48kHz)。零样本克隆:`reference_audio_path` 指向要克隆的
  人声样本(几十秒干净音频即可)。

## 性能(M3 Pro / 18GB / MPS)

- 首次推理含一次性 MPS 内核编译,较慢;**稳态 RTF ~3-3.7x**(现实长度 chunk)。
- 一条 3-4 分钟口播约 10-12 分钟合成完,适合本地后台批量。
- 提速方向:量化 Metal(llama.cpp-omni RTF~1.76)、或 N 卡/云 GPU(RTF~0.3)。

## 环境变量

- `VOXCPM_MODEL_DIR` 模型目录(默认 ModelScope 缓存)
- `VOXCPM_PORT` 端口(默认 9530)
- `VOXCPM_WARMUP_REF` 预热参考音频(可选,预编译内核让首个真实请求更快)
