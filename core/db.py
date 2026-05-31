"""数据库模块 - SQLite 存储自选股、策略配置、信号记录"""
import sqlite3
import json
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent.parent / "data" / "quant.db"


def _ensure_db_dir():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def get_db():
    """数据库上下文管理器"""
    _ensure_db_dir()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """初始化数据库表"""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS watchlist (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                "group" TEXT DEFAULT '默认',
                added_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
            CREATE TABLE IF NOT EXISTS strategies (
                name TEXT PRIMARY KEY,
                params_json TEXT DEFAULT '{}',
                enabled INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                name TEXT,
                strategy TEXT NOT NULL,
                price REAL,
                detail TEXT,
                triggered_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                message TEXT,
                sent_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
        """)


# ===== 自选股操作 =====

def add_watchlist(code: str, name: str, group: str = "默认"):
    """添加自选股"""
    with get_db() as conn:
        conn.execute(
            'INSERT OR REPLACE INTO watchlist (code, name, "group") VALUES (?, ?, ?)',
            (code, name, group)
        )


def remove_watchlist(code: str):
    """删除自选股"""
    with get_db() as conn:
        conn.execute("DELETE FROM watchlist WHERE code = ?", (code,))


def get_watchlist(group: str = None) -> list[dict]:
    """获取自选股列表"""
    with get_db() as conn:
        if group:
            rows = conn.execute(
                'SELECT * FROM watchlist WHERE "group" = ? ORDER BY added_at DESC', (group,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM watchlist ORDER BY added_at DESC").fetchall()
        return [dict(r) for r in rows]


def get_watchlist_groups() -> list[str]:
    """获取所有分组"""
    with get_db() as conn:
        rows = conn.execute('SELECT DISTINCT "group" FROM watchlist').fetchall()
        return [r["group"] for r in rows]


# ===== 策略操作 =====

def save_strategy(name: str, params: dict, enabled: bool = True):
    """保存策略配置"""
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO strategies (name, params_json, enabled) VALUES (?, ?, ?)",
            (name, json.dumps(params, ensure_ascii=False), int(enabled))
        )


def get_strategies(enabled_only: bool = False) -> list[dict]:
    """获取策略列表"""
    with get_db() as conn:
        if enabled_only:
            rows = conn.execute("SELECT * FROM strategies WHERE enabled = 1").fetchall()
        else:
            rows = conn.execute("SELECT * FROM strategies").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["params"] = json.loads(d.pop("params_json", "{}"))
            result.append(d)
        return result


# ===== 信号记录 =====

def save_signal(code: str, name: str, strategy: str, price: float, detail: str = ""):
    """保存策略触发信号"""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO signals (code, name, strategy, price, detail) VALUES (?, ?, ?, ?, ?)",
            (code, name, strategy, price, detail)
        )


def get_signals(limit: int = 100, strategy: str = None) -> list[dict]:
    """获取信号记录"""
    with get_db() as conn:
        if strategy:
            rows = conn.execute(
                "SELECT * FROM signals WHERE strategy = ? ORDER BY triggered_at DESC LIMIT ?",
                (strategy, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM signals ORDER BY triggered_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


# ===== 预警记录 =====

def save_alert(code: str, alert_type: str, message: str):
    """保存预警记录"""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO alerts (code, alert_type, message) VALUES (?, ?, ?)",
            (code, alert_type, message)
        )
