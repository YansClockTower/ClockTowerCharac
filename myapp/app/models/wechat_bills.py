"""独立账单库 wechat_qr_income.sqlite：导入记录与订单号核销。"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

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


# ----- 微信账单 CSV 提取与导入 -----

TABLE_MARKERS = ("微信支付账单明细列表", "微信账单明细列表")
TYPE_NAME = "二维码收款"
EXPORT_FIELDS = ("订单号", "交易对方", "备注")
HEADER_ORDER_KEYS = ("订单号", "交易单号")
HEADER_PEER = "交易对方"
HEADER_NOTE = "备注"
HEADER_TYPE = "交易类型"


def export_csv_path() -> Path:
    return Path(wechat_db_path()).with_name("wechat_qr_income.csv")


def export_json_path() -> Path:
    return Path(wechat_db_path()).with_name("wechat_qr_income.json")


def _pick_column(fieldnames, *candidates):
    for name in candidates:
        if name in fieldnames:
            return name
    raise KeyError("缺少列：" + " / ".join(candidates))


def find_bill_table_lines(text: str):
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if any(mark in line for mark in TABLE_MARKERS):
            start = i + 1
            break
    if start is None:
        for i, line in enumerate(lines):
            if HEADER_TYPE in line and HEADER_PEER in line:
                start = i
                break
    if start is None or start >= len(lines):
        raise ValueError("未找到正表（微信支付账单明细列表）")
    return lines[start:]


def extract_qr_income_rows(text: str):
    """从微信账单 CSV 文本中提取「二维码收款」记录。"""
    table_lines = find_bill_table_lines(text)
    reader = csv.DictReader(io.StringIO("\n".join(table_lines)))
    if not reader.fieldnames:
        raise ValueError("正表没有表头")

    type_col = _pick_column(reader.fieldnames, HEADER_TYPE)
    order_col = _pick_column(reader.fieldnames, *HEADER_ORDER_KEYS)
    peer_col = _pick_column(reader.fieldnames, HEADER_PEER)
    note_col = _pick_column(reader.fieldnames, HEADER_NOTE)

    rows = []
    for row in reader:
        if (row.get(type_col) or "").strip() != TYPE_NAME:
            continue
        note = (row.get(note_col) or "").strip()
        if note == "/":
            note = ""
        order_no = normalize_order_no(row.get(order_col) or "")
        if not order_no:
            continue
        rows.append({
            "订单号": order_no,
            "交易对方": (row.get(peer_col) or "").strip(),
            "备注": note,
        })
    return rows


def dedupe_qr_income_rows(rows):
    unique = {}
    for row in rows:
        unique.setdefault(row["订单号"], row)
    return list(unique.values())


def row_from_db(record):
    redeemed = 0
    try:
        redeemed = record["redeemed"]
    except (IndexError, KeyError):
        pass
    return {
        "订单号": record["order_no"],
        "交易对方": record["peer"],
        "备注": record["note"] or "",
        "核销": "是" if redeemed else "否",
    }


def list_qr_income_rows(conn=None):
    own_conn = conn is None
    if own_conn:
        conn = connect_wechat()
    try:
        records = conn.execute(
            "SELECT * FROM wechat_qr_income ORDER BY imported_at, order_no"
        ).fetchall()
        return [row_from_db(record) for record in records]
    finally:
        if own_conn:
            conn.close()


def write_qr_income_exports(rows, csv_path=None, json_path=None):
    csv_dest = Path(csv_path) if csv_path else export_csv_path()
    json_dest = Path(json_path) if json_path else export_json_path()
    csv_dest.parent.mkdir(parents=True, exist_ok=True)
    json_dest.parent.mkdir(parents=True, exist_ok=True)
    with csv_dest.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(EXPORT_FIELDS), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    json_dest.write_text(
        json.dumps(
            [{key: row[key] for key in EXPORT_FIELDS} for row in rows],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return csv_dest, json_dest


def insert_qr_income_rows(rows, source_label: str = "", sync_exports: bool = True):
    """只插入尚未存在的订单号。返回 (new_rows, skipped_count, all_rows)。"""
    unique_rows = dedupe_qr_income_rows(rows)
    conn = connect_wechat()
    try:
        existing = {
            record["order_no"]
            for record in conn.execute("SELECT order_no FROM wechat_qr_income").fetchall()
        }
        imported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_rows = [row for row in unique_rows if row["订单号"] not in existing]
        conn.executemany(
            """
            INSERT OR IGNORE INTO wechat_qr_income
                (order_no, peer, note, source_file, imported_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (row["订单号"], row["交易对方"], row["备注"], source_label, imported_at)
                for row in new_rows
            ],
        )
        conn.commit()
        all_rows = list_qr_income_rows(conn)
    finally:
        conn.close()

    skipped = len(rows) - len(new_rows)
    if sync_exports:
        write_qr_income_exports(all_rows)
    return new_rows, skipped, all_rows


def insert_manual_qr_income(
    order_no: str,
    peer: str,
    note: str = "",
    source_label: str = "manual",
    sync_exports: bool = True,
):
    """
    手动写入一条二维码收款记录。
    返回 (status, detail)：
      ok — 已写入；detail 为新行 dict
      duplicate — 订单号已存在；detail 为已有行
      invalid — 参数不合法；detail 为错误说明
    """
    order_no = normalize_order_no(order_no)
    peer = (peer or "").strip()
    note = (note or "").strip()
    if note == "/":
        note = ""

    if not order_no:
        return "invalid", "请填写订单号。"
    if not is_valid_order_no(order_no):
        return "invalid", "订单号格式无效（应为 10–40 位字母或数字）。"
    if not peer:
        return "invalid", "请填写用户名（交易对方）。"

    conn = connect_wechat()
    try:
        existing = find_income_order(conn, order_no)
        if existing is not None:
            return "duplicate", row_from_db(existing)

        imported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """
            INSERT INTO wechat_qr_income
                (order_no, peer, note, source_file, imported_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (order_no, peer, note, source_label, imported_at),
        )
        conn.commit()
        row = row_from_db(find_income_order(conn, order_no))
        all_rows = list_qr_income_rows(conn)
    finally:
        conn.close()

    if sync_exports:
        write_qr_income_exports(all_rows)
    return "ok", row


def import_qr_income_from_text(text: str, source_label: str = "web_paste"):
    """解析粘贴/文件文本并去重导入。返回统计 dict。"""
    rows = extract_qr_income_rows(text)
    inserted, skipped, all_rows = insert_qr_income_rows(rows, source_label=source_label)
    return {
        "parsed": len(rows),
        "inserted": len(inserted),
        "skipped": skipped,
        "total": len(all_rows),
        "new_rows": inserted,
    }
