#!/usr/bin/env bash
# 启动本地 VoxCPM2 TTS 服务(常驻)。
# 用法: bash local-tts/run.sh
set -e
cd "$(dirname "$0")/.."

# torchaudio.load 依赖 torchcodec + ffmpeg@6 的库;必须在进程启动前设好。
if [ -d "/opt/homebrew/opt/ffmpeg@6/lib" ]; then
  export DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/opt/ffmpeg@6/lib:${DYLD_FALLBACK_LIBRARY_PATH}"
fi

# 预热参考:存在则设,预编译 MPS 内核,让首个真实请求更快。
WARMUP="$PWD/local-tts/ref_yangyisheng_18s.wav"
if [ -f "$WARMUP" ]; then
  export VOXCPM_WARMUP_REF="$WARMUP"
fi

exec local-tts/venv/bin/python local-tts/server.py
