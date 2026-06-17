import sqlite3
import os
import uuid
import hashlib
from datetime import datetime

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "drawer.db")


def get_conn():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_conn()
    # ── 用户表 ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    # ── 会话表 ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    # ── 物品表（兼容旧表） ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 0,
            drawer TEXT NOT NULL,
            item TEXT NOT NULL,
            expiry TEXT DEFAULT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    # 兼容旧表：如果 user_id 列不存在则添加
    try:
        conn.execute("ALTER TABLE items ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_drawer ON items(drawer)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_item ON items(item)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_user ON items(user_id)")
    # ── 查询日志表 ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS query_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 0,
            query_text TEXT NOT NULL,
            intent TEXT DEFAULT '',
            result_summary TEXT DEFAULT '',
            result_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    try:
        conn.execute("ALTER TABLE query_log ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════
#  用户认证
# ══════════════════════════════════════════════════════

def _hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def register_user(username: str, password: str) -> dict | None:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username.strip(), _hash_pw(password))
        )
        conn.commit()
        row = conn.execute("SELECT id, username, created_at FROM users WHERE id = ?",
                           (cur.lastrowid,)).fetchone()
        conn.close()
        return dict(row) if row else None
    except sqlite3.IntegrityError:
        conn.close()
        return None  # 用户名已存在


def login_user(username: str, password: str) -> str | None:
    """验证成功返回 token，失败返回 None"""
    conn = get_conn()
    row = conn.execute(
        "SELECT id, password_hash FROM users WHERE username = ?",
        (username.strip(),)
    ).fetchone()
    if not row or row["password_hash"] != _hash_pw(password):
        conn.close()
        return None
    token = uuid.uuid4().hex
    conn.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, row["id"]))
    conn.commit()
    conn.close()
    return token


def logout_user(token: str):
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()


def get_user_by_token(token: str) -> int | None:
    """从 token 取 user_id，无效返回 None"""
    conn = get_conn()
    row = conn.execute("SELECT user_id FROM sessions WHERE token = ?", (token,)).fetchone()
    conn.close()
    return row["user_id"] if row else None


# ══════════════════════════════════════════════════════
#  物品 CRUD（全部带 user_id 隔离）
# ══════════════════════════════════════════════════════

def add_item(user_id: int, drawer: str, item: str, expiry: str | None = None) -> dict:
    conn = get_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        "INSERT INTO items (user_id, drawer, item, expiry, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, drawer.strip(), item.strip(), expiry, now, now)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM items WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


def query_item(user_id: int, item: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM items WHERE user_id = ? AND item LIKE ? ORDER BY updated_at DESC",
        (user_id, f"%{item.strip()}%")
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_item_in_drawer(user_id: int, drawer: str, item: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM items WHERE user_id = ? AND drawer LIKE ? AND item LIKE ? ORDER BY updated_at DESC",
        (user_id, f"%{drawer.strip()}%", f"%{item.strip()}%")
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_drawer(user_id: int, drawer: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM items WHERE user_id = ? AND drawer LIKE ? ORDER BY item ASC",
        (user_id, f"%{drawer.strip()}%")
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_item(user_id: int, item_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM items WHERE id = ? AND user_id = ?", (item_id, user_id))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def move_item(user_id: int, item_id: int, new_drawer: str) -> dict | None:
    conn = get_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        "UPDATE items SET drawer = ?, updated_at = ? WHERE id = ? AND user_id = ?",
        (new_drawer.strip(), now, item_id, user_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_all(user_id: int, limit: int = 50) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM items WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_drawers(user_id: int) -> list[str]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT drawer FROM items WHERE user_id = ? ORDER BY drawer ASC",
        (user_id,)
    ).fetchall()
    conn.close()
    return [r["drawer"] for r in rows]


def search_all(user_id: int, keyword: str) -> list[dict]:
    conn = get_conn()
    kw = f"%{keyword.strip()}%"
    rows = conn.execute(
        "SELECT * FROM items WHERE user_id = ? AND (item LIKE ? OR drawer LIKE ?) ORDER BY updated_at DESC LIMIT 50",
        (user_id, kw, kw)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def rename_drawer(user_id: int, old_name: str, new_name: str) -> int:
    conn = get_conn()
    cur = conn.execute(
        "UPDATE items SET drawer = ?, updated_at = ? WHERE user_id = ? AND drawer = ?",
        (new_name.strip(), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id, old_name.strip())
    )
    conn.commit()
    count = cur.rowcount
    conn.close()
    return count


def delete_drawer_items(user_id: int, name: str) -> int:
    conn = get_conn()
    cur = conn.execute("DELETE FROM items WHERE user_id = ? AND drawer = ?", (user_id, name.strip()))
    conn.commit()
    count = cur.rowcount
    conn.close()
    return count


# ══════════════════════════════════════════════════════
#  查询日志
# ══════════════════════════════════════════════════════

def log_query(user_id: int, query_text: str, intent: str = '', result_summary: str = '', result_count: int = 0):
    conn = get_conn()
    conn.execute(
        "INSERT INTO query_log (user_id, query_text, intent, result_summary, result_count) VALUES (?, ?, ?, ?, ?)",
        (user_id, query_text, intent, result_summary, result_count)
    )
    conn.commit()
    conn.close()


def get_query_logs(user_id: int, limit: int = 50) -> list:
    conn = get_conn()
    cur = conn.execute(
        "SELECT id, query_text, intent, result_summary, result_count, created_at FROM query_log WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def check_expiring(user_id: int, days: int = 90) -> list:
    """返回 user_id 下 expiry 在 days 天内的物品，按到期日升序"""
    conn = get_conn()
    cur = conn.execute(
        """SELECT id, user_id, drawer, item, expiry, created_at, updated_at
           FROM items
           WHERE user_id = ? AND expiry IS NOT NULL AND expiry != ''
             AND date(expiry) BETWEEN date('now','localtime') AND date('now','localtime','+' || ? || ' days')
           ORDER BY expiry ASC""",
        (user_id, days)
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]
