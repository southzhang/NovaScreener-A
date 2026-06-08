#!/usr/bin/env python3
"""
飞书直接推送脚本 — 绕过 cron delivery，直接调用飞书 API 发送消息。
用法: python3 feishu_direct_push.py "消息内容"
      echo "消息内容" | python3 feishu_direct_push.py

环境变量（从 ~/.hermes/.env 自动读取）:
  FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_HOME_CHANNEL
"""

import os
import sys
import json
import urllib.request
import urllib.error

def load_env():
    """从 ~/.hermes/.env 加载环境变量"""
    env_path = os.path.expanduser("~/.hermes/.env")
    env = {}
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    env[key.strip()] = val.strip()
    except FileNotFoundError:
        pass
    return env

def get_tenant_access_token(app_id, app_secret):
    """获取飞书 tenant_access_token"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    data = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json; charset=utf-8"
    })
    resp = urllib.request.urlopen(req, timeout=10)
    result = json.loads(resp.read())
    if result.get("code") != 0:
        raise Exception(f"获取token失败: {result}")
    return result["tenant_access_token"]

def send_message(token, chat_id, text):
    """发送飞书文本消息"""
    url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
    payload = {
        "receive_id": chat_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}, ensure_ascii=False)
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8"
    })
    resp = urllib.request.urlopen(req, timeout=15)
    result = json.loads(resp.read())
    if result.get("code") != 0:
        raise Exception(f"发送失败: {result}")
    return result

def main():
    # 读取消息内容（命令行参数或stdin）
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
    else:
        text = sys.stdin.read().strip()
    
    if not text:
        print("错误: 没有消息内容", file=sys.stderr)
        sys.exit(1)
    
    # 加载配置
    env = load_env()
    app_id = os.environ.get("FEISHU_APP_ID") or env.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET") or env.get("FEISHU_APP_SECRET")
    chat_id = os.environ.get("FEISHU_HOME_CHANNEL") or env.get("FEISHU_HOME_CHANNEL")
    
    if not all([app_id, app_secret, chat_id]):
        print(f"错误: 缺少配置 (app_id={bool(app_id)}, app_secret={bool(app_secret)}, chat_id={bool(chat_id)})", file=sys.stderr)
        sys.exit(1)
    
    # 发送
    try:
        token = get_tenant_access_token(app_id, app_secret)
        result = send_message(token, chat_id, text)
        msg_id = result.get("data", {}).get("message_id", "unknown")
        print(f"✅ 已发送 (message_id: {msg_id})")
    except Exception as e:
        print(f"❌ 发送失败: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
