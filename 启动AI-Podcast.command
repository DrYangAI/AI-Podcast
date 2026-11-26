#!/bin/bash
# 双击此文件即可启动 AI-Podcast 前后端服务
# macOS Finder 会在「终端」中运行 .command 文件。
# 实际逻辑都在同目录的 restart.sh 里，这里只负责定位并调用它。

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

bash "$DIR/restart.sh"
status=$?

# 启动完成后自动在默认浏览器打开前端页面
FRONTEND_URL="http://localhost:9528"
echo ""
echo "正在打开浏览器: $FRONTEND_URL"
open "$FRONTEND_URL"

echo ""
echo "（服务已在后台运行。此窗口可以直接关闭。）"
echo "按回车键关闭本窗口 ..."
read -r _

exit $status
