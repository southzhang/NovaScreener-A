"""V10 量化盯盘选股 — 版本管理"""
from __future__ import annotations
VERSION = "v1.15.2"
REPO_OWNER = "southzhang"
REPO_NAME = "NovaScreener-A"

_GITHUB_HEADERS = {
    "User-Agent": "NovaScreener-A/1.1.0",
    "Accept": "application/vnd.github.v3+json",
}


def _get_github_token() -> str | None:
    """优先从环境变量获取 GitHub Token，避免限流"""
    import os
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    # 也尝试从 gh CLI 缓存读取
    if not token:
        try:
            import subprocess
            token = subprocess.run(
                ["gh", "auth", "token"], capture_output=True, text=True, timeout=5
            ).stdout.strip()
        except Exception:
            pass
    return token


def get_latest_release() -> dict | None:
    """从 GitHub API 获取最新 release 信息"""
    import requests
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
    headers = dict(_GITHUB_HEADERS)
    token = _get_github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = requests.get(url, timeout=5, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "tag_name": data.get("tag_name", ""),
                "name": data.get("name", ""),
                "body": data.get("body", ""),
                "published_at": data.get("published_at", ""),
                "html_url": data.get("html_url", ""),
            }
    except Exception:
        pass
    return None


def check_update(current: str = VERSION) -> dict:
    """检查更新，返回 {'has_update': bool, 'latest': ..., 'current': ..., 'info': ...}"""
    result = {
        "has_update": False,
        "current": current,
        "latest": current,
        "info": None,
        "error": None,
    }

    release = get_latest_release()
    if release is None:
        result["error"] = "无法连接 GitHub"
        return result

    latest_tag = release["tag_name"]
    result["latest"] = latest_tag
    result["info"] = release

    # 版本比较：去掉 v 前缀后拆数字
    def _parse_ver(t: str) -> tuple:
        try:
            parts = t.lstrip("v").split(".")
            return tuple(int(p) for p in parts)
        except (ValueError, AttributeError):
            return (0, 0, 0)

    if _parse_ver(latest_tag) > _parse_ver(current):
        result["has_update"] = True

    return result
