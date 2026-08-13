#!/usr/bin/env bash
# 启动本地 VoxCPM2 TTS 服务(常驻)。
# 用法: bash local-tts/run.sh
set -e
cd "$(dirname "$0")/.."

# 预热参考:存在则设,预编译 MPS 内核,让首个真实请求更快。
WARMUP="$PWD/local-tts/ref_yangyisheng_18s.wav"
if [ -f "$WARMUP" ]; then
  export VOXCPM_WARMUP_REF="$WARMUP"
fi

exec local-tts/venv/bin/python local-tts/server.py
