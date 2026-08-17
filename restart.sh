#!/bin/bash
# AI-Podcast 一键重启前后端服务
# 后端: 9527  前端: 9528

set -e

PROJ_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PORT=9527
FRONTEND_PORT=9528
TTS_PORT=9530
# 本地 VoxCPM TTS 服务较重(加载 2B 模型、约 8GB 内存、1-2 分钟)。
# 不需要本地声音克隆时,用 SKIP_TTS=1 bash restart.sh 跳过。
SKIP_TTS="${SKIP_TTS:-0}"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; }

kill_port() {
  local port=$1
  local pids
  pids=$(lsof -ti:"$port" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "$pids" | xargs kill -9 2>/dev/null || true
    warn "已终止端口 $port 上的进程"
  fi
}

echo ""
echo "==============================="
echo "  AI-Podcast 服务重启"
echo "==============================="
echo ""

# 1. 停止旧进程
kill_port $BACKEND_PORT
kill_port $FRONTEND_PORT
[ "$SKIP_TTS" != "1" ] && kill_port $TTS_PORT
sleep 1

# 2. 启动后端（使用 ARM 原生 Python venv）
log "启动后端 (端口 $BACKEND_PORT) ..."
cd "$PROJ_DIR/backend"
if [ -f "$PROJ_DIR/backend/venv/bin/activate" ]; then
  source "$PROJ_DIR/backend/venv/bin/activate"
  log "已激活 venv ($(python3 -c 'import platform; print(platform.machine())'))"
fi
# 本机伴侣无独立登录，必须只监听回环地址，禁止暴露到机构局域网。
nohup python3 -m uvicorn app.main:app --host 127.0.0.1 --port $BACKEND_PORT --reload \
  > "$PROJ_DIR/backend/.server.log" 2>&1 &
BACKEND_PID=$!

# 3. 启动前端
log "启动前端 (端口 $FRONTEND_PORT) ..."
cd "$PROJ_DIR/frontend"
nohup npx vite --port $FRONTEND_PORT \
  > "$PROJ_DIR/frontend/.server.log" 2>&1 &
FRONTEND_PID=$!

# 3b. 启动本地 VoxCPM TTS 服务(可选、加载慢,不阻塞前后端就绪判断)
TTS_PID=""
if [ "$SKIP_TTS" != "1" ]; then
  if [ -x "$PROJ_DIR/local-tts/venv/bin/python" ]; then
    log "启动本地 VoxCPM TTS 服务 (端口 $TTS_PORT, 加载模型约需 1-2 分钟) ..."
    WARMUP="$PROJ_DIR/local-tts/ref_yangyisheng_18s.wav"
    [ -f "$WARMUP" ] && export VOXCPM_WARMUP_REF="$WARMUP"
    # torchaudio.load 依赖 torchcodec + ffmpeg@6 的库
    [ -d "/opt/homebrew/opt/ffmpeg@6/lib" ] && \
      export DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/opt/ffmpeg@6/lib:${DYLD_FALLBACK_LIBRARY_PATH}"
    cd "$PROJ_DIR"
    nohup local-tts/venv/bin/python local-tts/server.py \
      > "$PROJ_DIR/local-tts/server.log" 2>&1 &
    TTS_PID=$!
  else
    warn "未找到 local-tts venv,跳过本地 TTS 服务(安装见 local-tts/README.md)"
  fi
fi

# 4. 等待服务就绪
echo ""
log "等待服务启动..."

ready=0
for i in $(seq 1 15); do
  sleep 1
  backend_ok=0
  frontend_ok=0
  curl -s -o /dev/null http://localhost:$BACKEND_PORT/api/v1/projects 2>/dev/null && backend_ok=1
  curl -s -o /dev/null http://localhost:$FRONTEND_PORT/ 2>/dev/null && frontend_ok=1

  if [ $backend_ok -eq 1 ] && [ $frontend_ok -eq 1 ]; then
    ready=1
    break
  fi
  printf "."
done
echo ""

if [ $ready -eq 1 ]; then
  echo ""
  log "后端就绪  http://localhost:$BACKEND_PORT  (PID: $BACKEND_PID)"
  log "前端就绪  http://localhost:$FRONTEND_PORT  (PID: $FRONTEND_PID)"
  echo ""
  echo -e "  ${GREEN}打开浏览器访问: http://localhost:$FRONTEND_PORT${NC}"
  echo ""
else
  # 部分启动也提示地址
  curl -s -o /dev/null http://localhost:$BACKEND_PORT/api/v1/projects 2>/dev/null \
    && log "后端就绪  http://localhost:$BACKEND_PORT" \
    || warn "后端尚未就绪，查看日志: $PROJ_DIR/backend/.server.log"

  curl -s -o /dev/null http://localhost:$FRONTEND_PORT/ 2>/dev/null \
    && log "前端就绪  http://localhost:$FRONTEND_PORT" \
    || warn "前端尚未就绪，查看日志: $PROJ_DIR/frontend/.server.log"
  echo ""
fi

# 5. 本地 TTS 状态(模型加载慢,通常此刻仍在预热,故单独报告、不阻塞)
if [ "$SKIP_TTS" = "1" ]; then
  warn "已跳过本地 VoxCPM TTS 服务 (SKIP_TTS=1)"
  echo ""
elif [ -n "$TTS_PID" ]; then
  if curl -s -o /dev/null --max-time 2 http://localhost:$TTS_PORT/health 2>/dev/null; then
    log "本地 TTS 就绪  http://localhost:$TTS_PORT  (PID: $TTS_PID)"
  else
    warn "本地 TTS 加载中(约 1-2 分钟);就绪前可先用豆包等其它 TTS"
    warn "  就绪检查: curl http://localhost:$TTS_PORT/health   日志: local-tts/server.log"
  fi
  echo ""
fi
