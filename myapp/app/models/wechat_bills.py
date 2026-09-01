"""独立账单库 wechat_qr_income.sqlite：导入记录与订单号核销。"""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime

from app.models.config import get_config

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS wechat_qr_income (
    order_no TEXT PRIMARY KEY,
    peer TEXT NOT NULL,
    note TEXT,
    source_file TEXT,
    imported_at TEXT NOT NULL,
    redeemed INTEGER DEFAULT 0,
    redeemed_by TEXT,
    redeemed_at TEXT
)
"""

ORDER_RE = re.compile(r"^[A-Za-z0-9]{10,40}$")


def wechat_db_path() -> str:
    if get_config("development"):
        base = get_config("database_path_dev")
    else:
        base = get_config("database_path")
    return os.path.join(base, "wechat_qr_income.sqlite")


def normalize_order_no(value) -> str:
    return re.sub(r"\s+", "", (value or "").strip())


def is_valid_order_no(value) -> bool:
    return bool(ORDER_RE.match(value or ""))


def ensure_wechat_schema(conn) -> None:
    conn.execute(CREATE_TABLE_SQL)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(wechat_qr_income)")}
    for name, decl in (
        ("redeemed", "INTEGER DEFAULT 0"),
        ("redeemed_by", "TEXT"),
        ("redeemed_at", "TEXT"),
    ):
        if name not in cols:
            conn.execute(f"ALTER TABLE wechat_qr_income ADD COLUMN {name} {decl}")
    conn.commit()


def connect_wechat(path=None):
    db_path = path or wechat_db_path()
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_wechat_schema(conn)
    return conn


def find_income_order(conn, order_no):
    order_no = normalize_order_no(order_no)
    if not order_no:
        return None
    return conn.execute(
        "SELECT * FROM wechat_qr_income WHERE order_no = ?",
        (order_no,),
    ).fetchone()


def redeem_income_order(conn, order_no, username):
    """将未核销订单标为已核销。返回 ok / missing / used。"""
    order_no = normalize_order_no(order_no)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor = conn.execute(
        """
        UPDATE wechat_qr_income
        SET redeemed = 1, redeemed_by = ?, redeemed_at = ?
        WHERE order_no = ? AND IFNULL(redeemed, 0) = 0
        """,
        (username, now, order_no),
    )
    conn.commit()
    if cursor.rowcount == 1:
        return "ok"
    row = find_income_order(conn, order_no)
    if row is None:
        return "missing"
    if row["redeemed"] and (row["redeemed_by"] or "") == username:
        return "ok"
    return "used"
