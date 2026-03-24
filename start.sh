#!/bin/bash

# 投資系統啟動腳本 - 同時啟動前後端

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=================================================="
echo "  投資系統 v2.0 啟動中..."
echo "=================================================="

# 啟動後端 (Flask)
echo "[後端] 啟動 Flask API on http://localhost:18900"
cd "$BASE_DIR"
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate venv
python3 webapp.py &
BACKEND_PID=$!

# 等待後端啟動
sleep 2

# 啟動前端 (Vite)
echo "[前端] 啟動 Vite Dev Server"
cd "$BASE_DIR/web"
bun dev &
FRONTEND_PID=$!

echo ""
echo "=================================================="
echo "  後端: http://localhost:18900"
echo "  前端: http://localhost:5173"
echo "  按 Ctrl+C 停止所有服務"
echo "=================================================="

# 捕捉 Ctrl+C，同時關閉前後端
trap "echo ''; echo '正在關閉服務...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT TERM

# 等待所有背景程序
wait $BACKEND_PID $FRONTEND_PID
