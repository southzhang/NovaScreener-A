#!/bin/bash
# V10 量化选股 — 启动脚本（Streamlit + 静态文件服务）
# 支持 PWA：manifest.json + service-worker.js + 图标

cd "$(dirname "$0")"

# 杀掉旧进程
lsof -ti :8501 | xargs kill -9 2>/dev/null
lsof -ti :8502 | xargs kill -9 2>/dev/null
sleep 1

echo "🚀 启动 V10 量化选股系统..."
echo "   Streamlit: http://localhost:8501"
echo "   静态文件:  http://localhost:8502"
echo ""

# 启动静态文件服务器（后台）
python3 -c "
import http.server, socketserver, os, threading
os.chdir('static')
handler = http.server.SimpleHTTPRequestHandler
handler.extensions_map.update({'.svg': 'image/svg+xml', '.json': 'application/json', '.js': 'application/javascript'})
with socketserver.TCPServer(('', 8502), handler) as httpd:
    httpd.serve_forever()
" &
STATIC_PID=$!
echo "  ✅ 静态文件服务 PID=$STATIC_PID"

# 启动 Streamlit（前台）
streamlit run app.py \
    --server.headless true \
    --server.port 8501 \
    --server.address 0.0.0.0

# 退出时清理
kill $STATIC_PID 2>/dev/null
