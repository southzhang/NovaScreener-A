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
                score REAL DEFAULT 0,
                grade TEXT DEFAULT '',
                triggered_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                message TEXT,
                sent_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
            CREATE TABLE IF NOT EXISTS portfolio (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                buy_price REAL NOT NULL,
                quantity INTEGER NOT NULL,
                buy_date TEXT DEFAULT (date('now', 'localtime')),
                stop_loss REAL DEFAULT 0,
                target_price REAL DEFAULT 0,
                notes TEXT DEFAULT '',
                status TEXT DEFAULT 'holding',
                sell_price REAL DEFAULT 0,
                sell_date TEXT,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
        """)
        # 迁移：给signals表添加score和grade字段（如果不存在）
        try:
            conn.execute("ALTER TABLE signals ADD COLUMN score REAL DEFAULT 0")
        except:
            pass  # 字段已存在
        try:
            conn.execute("ALTER TABLE signals ADD COLUMN grade TEXT DEFAULT ''")
        except:
            pass  # 字段已存在


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

def save_signal(code: str, name: str, strategy: str, price: float, detail: str = "", score: float = 0, grade: str = ""):
    """保存策略触发信号"""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO signals (code, name, strategy, price, detail, score, grade) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (code, name, strategy, price, detail, score, grade)
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


# ===== 持仓管理 =====

def add_position(code: str, name: str, buy_price: float, quantity: int,
                 stop_loss: float = 0, target_price: float = 0, notes: str = "") -> int:
    """添加持仓"""
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO portfolio (code, name, buy_price, quantity, stop_loss, target_price, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (code, name, buy_price, quantity, stop_loss, target_price, notes)
        )
        return cursor.lastrowid


def update_position(position_id: int, **kwargs):
    """更新持仓信息"""
    allowed = {"buy_price", "quantity", "stop_loss", "target_price", "notes", "status",
               "sell_price", "sell_date"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [position_id]
    with get_db() as conn:
        conn.execute(f"UPDATE portfolio SET {set_clause} WHERE id = ?", values)


def sell_position(position_id: int, sell_price: float):
    """卖出持仓"""
    with get_db() as conn:
        conn.execute(
            "UPDATE portfolio SET status = 'sold', sell_price = ?, sell_date = date('now', 'localtime') WHERE id = ?",
            (sell_price, position_id)
        )


def delete_position(position_id: int):
    """删除持仓记录"""
    with get_db() as conn:
        conn.execute("DELETE FROM portfolio WHERE id = ?", (position_id,))


def add_to_position(code: str, add_price: float, add_quantity: int) -> int | None:
    """加仓：合并同一股票的持仓（加权平均买入价 + 累加数量）
    
    只合并 status='holding' 的记录。如果有多条 holding 记录，
    合并到最早的那条，删除其余条目。
    返回合并后的 position_id，无持仓返回 None。
    """
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, buy_price, quantity, stop_loss, target_price, notes "
            "FROM portfolio WHERE code = ? AND status = 'holding' ORDER BY created_at ASC",
            (code,)
        ).fetchall()
        
        if not rows:
            return None
        
        # 计算合并后的加权平均价和总数量
        total_cost = sum(r["buy_price"] * r["quantity"] for r in rows)
        total_quantity = sum(r["quantity"] for r in rows) + add_quantity
        total_cost += add_price * add_quantity
        avg_price = round(total_cost / total_quantity, 3)
        
        # 保留最早那条，更新价格和数量
        primary_id = rows[0]["id"]
        conn.execute(
            "UPDATE portfolio SET buy_price = ?, quantity = ? WHERE id = ?",
            (avg_price, total_quantity, primary_id)
        )
        
        # 删除其余重复记录
        for r in rows[1:]:
            conn.execute("DELETE FROM portfolio WHERE id = ?", (r["id"],))
        
        return primary_id


def get_position_by_code(code: str, status: str = "holding") -> dict | None:
    """按股票代码获取持仓（holding 状态取第一条）"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM portfolio WHERE code = ? AND status = ? ORDER BY created_at ASC LIMIT 1",
            (code, status)
        ).fetchone()
        return dict(row) if row else None


def get_positions(status: str = "holding") -> list[dict]:
    """获取持仓列表"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM portfolio WHERE status = ? ORDER BY created_at DESC",
            (status,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_positions() -> list[dict]:
    """获取所有持仓（含已卖出）"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM portfolio ORDER BY status ASC, created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
