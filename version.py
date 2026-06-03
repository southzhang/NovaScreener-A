"""V10 量化盯盘选股 — 版本管理"""

VERSION = "v1.0.0"
REPO_OWNER = "southzhang"
REPO_NAME = "NovaScreener-A"

def get_latest_release() -> dict | None:
    """从 GitHub API 获取最新 release 信息"""
    import requests
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
    try:
        resp = requests.get(url, timeout=5)
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
