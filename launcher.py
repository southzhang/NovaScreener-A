#!/usr/bin/env python3
"""量化盯盘选股 V10 — 桌面版启动器

直接在当前进程运行 Streamlit。
"""
import os
import sys
import time
import webbrowser
import socket
import threading

PORT = 8501
HOST = "127.0.0.1"

# 禁用 Streamlit 开发模式
os.environ["STREAMLIT_ENV"] = "production"
os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"

def get_base_dir():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

def get_app_dir():
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.path.expanduser("~/.config")
    app_dir = os.path.join(base, "QuantWatchdog")
    os.makedirs(app_dir, exist_ok=True)
    return app_dir

def is_server_running(port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect((HOST, port))
            return True
    except (ConnectionRefusedError, socket.timeout, OSError):
        return False

def open_browser(port):
    time.sleep(5)
    webbrowser.open(f"http://{HOST}:{port}")

def main():
    base_dir = get_base_dir()
    app_dir = get_app_dir()
    
    if is_server_running(PORT):
        print(f"服务已在运行，打开浏览器...")
        webbrowser.open(f"http://{HOST}:{PORT}")
        return
    
    # 初始化数据目录
    app_py = os.path.join(app_dir, "app.py")
    if not os.path.exists(app_py):
        import shutil
        print(f"📁 初始化数据目录: {app_dir}")
        for item in ["app.py", "core", "pages", "static"]:
            src = os.path.join(base_dir, item)
            dst = os.path.join(app_dir, item)
            if os.path.isdir(src):
                if not os.path.exists(dst):
                    shutil.copytree(src, dst)
            else:
                if not os.path.exists(dst):
                    shutil.copy2(src, dst)
    
    # ★ 关键：把数据目录加入 sys.path，让 app.py 能找到 core.*
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    
    # 后台打开浏览器
    threading.Thread(target=open_browser, args=(PORT,), daemon=True).start()
    
    print(f"🚀 启动量化盯盘选股 V10...")
    print(f"📊 访问地址: http://{HOST}:{PORT}")
    print(f"📁 数据目录: {app_dir}")
    print(f"按 Ctrl+C 退出")
    
    try:
        os.environ["STREAMLIT_SERVER_PORT"] = str(PORT)
        os.environ["STREAMLIT_SERVER_ADDRESS"] = HOST
        os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
        os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
        os.environ["STREAMLIT_ENV"] = "production"
        os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"
        
        sys.argv = [
            "streamlit", "run", app_py,
            "--server.port", str(PORT),
            "--server.address", HOST,
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
            "--global.developmentMode", "false",
        ]
        
        from streamlit.web.cli import main as st_main
        st_main()
    except KeyboardInterrupt:
        print("\n👋 已退出")
    except Exception as e:
        print(f"❌ 启动失败: {e}")
        import traceback
        traceback.print_exc()
        input("按回车键退出...")

if __name__ == "__main__":
    main()
