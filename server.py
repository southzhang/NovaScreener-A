"""
V10 量化选股 — 统一入口
同时服务 Streamlit + 静态文件（PWA manifest/service-worker/icons）
用法: python server.py
"""
import http.server
import socketserver
import threading
import subprocess
import os
import sys
import signal
import time

STATIC_PORT = 8502
STREAMLIT_PORT = 8501
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    """静态文件服务（支持 PWA 所需的 manifest/sw/icons）"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".svg": "image/svg+xml",
        ".json": "application/json",
        ".js": "application/javascript",
        ".webmanifest": "application/manifest+json",
    }

    def log_message(self, format, *args):
        pass  # 静默日志


def start_static_server():
    """后台启动静态文件服务器"""
    with socketserver.TCPServer(("", STATIC_PORT), StaticHandler) as httpd:
        httpd.serve_forever()


def main():
    print("🚀 V10 量化选股系统启动中...")
    print(f"   📊 Streamlit: http://localhost:{STREAMLIT_PORT}")
    print(f"   📦 静态文件:  http://localhost:{STATIC_PORT}")
    print(f"   📱 PWA Manifest: http://localhost:{STATIC_PORT}/manifest.json")
    print()

    # 启动静态文件服务（后台线程）
    static_thread = threading.Thread(target=start_static_server, daemon=True)
    static_thread.start()
    print(f"  ✅ 静态文件服务已启动 (:{STATIC_PORT})")

    # 启动 Streamlit（前台进程）
    print(f"  ✅ 启动 Streamlit (:{STREAMLIT_PORT})...")
    try:
        proc = subprocess.run(
            [
                os.path.expanduser("~/.hermes/hermes-agent/venv/bin/python3"), "-m", "streamlit", "run",
                os.path.join(os.path.dirname(__file__), "app.py"),
                "--server.headless", "true",
                "--server.port", str(STREAMLIT_PORT),
                "--server.address", "0.0.0.0",
                "--browser.gatherUsageStats", "false",
            ],
            cwd=os.path.dirname(__file__),
        )
    except KeyboardInterrupt:
        print("\n👋 已停止")


if __name__ == "__main__":
    main()
