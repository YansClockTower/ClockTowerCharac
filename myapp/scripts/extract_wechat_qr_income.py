#!/usr/bin/env python3
"""从微信账单 CSV 的正表中提取「二维码收款」的订单号、交易对方、备注。

账单写入独立库 database/wechat_qr_income.sqlite（与活动库分开）。
相同订单号只保留首次导入，重复记录跳过。同时同步 CSV / JSON。

导入：
    python3 scripts/extract_wechat_qr_income.py 微信支付账单流水文件(...).csv

查询：
    python3 scripts/extract_wechat_qr_income.py --check 1000107301...
    python3 scripts/extract_wechat_qr_income.py --list
"""

import argparse
import csv
import io
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# config.txt 相对路径：从 myapp 目录加载
import os

os.chdir(ROOT)

from app.models.wechat_bills import connect_wechat, wechat_db_path

DEFAULT_DIR = ROOT / "database"
DEFAULT_CSV = DEFAULT_DIR / "wechat_qr_income.csv"
DEFAULT_JSON = DEFAULT_DIR / "wechat_qr_income.json"
DEFAULT_DB = Path(wechat_db_path())

ENCODINGS = ("utf-8-sig", "gb18030", "gbk")
TABLE_MARKERS = ("微信支付账单明细列表", "微信账单明细列表")
TYPE_NAME = "二维码收款"
FIELDS = ("订单号", "交易对方", "备注")
LIST_FIELDS = ("订单号", "交易对方", "备注", "核销")
HEADER_ORDER_KEYS = ("订单号", "交易单号")
HEADER_PEER = "交易对方"
HEADER_NOTE = "备注"
HEADER_TYPE = "交易类型"

def decode_text(path: Path) -> str:
    raw = path.read_bytes()
    last_error = None
    for enc in ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise last_error


def find_table(text: str):
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


def pick_column(fieldnames, *candidates):
    for name in candidates:
        if name in fieldnames:
            return name
    raise KeyError("缺少列：" + " / ".join(candidates))


def extract_rows(text: str):
    table_lines = find_table(text)
    reader = csv.DictReader(io.StringIO("\n".join(table_lines)))
    if not reader.fieldnames:
        raise ValueError("正表没有表头")

    type_col = pick_column(reader.fieldnames, HEADER_TYPE)
    order_col = pick_column(reader.fieldnames, *HEADER_ORDER_KEYS)
    peer_col = pick_column(reader.fieldnames, HEADER_PEER)
    note_col = pick_column(reader.fieldnames, HEADER_NOTE)

    rows = []
    for row in reader:
        if (row.get(type_col) or "").strip() != TYPE_NAME:
            continue
        note = (row.get(note_col) or "").strip()
        if note == "/":
            note = ""
        order_no = (row.get(order_col) or "").strip()
        if not order_no:
            continue
        rows.append({
            "订单号": order_no,
            "交易对方": (row.get(peer_col) or "").strip(),
            "备注": note,
        })
    return rows


def write_csv(rows, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(FIELDS), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(rows, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(
            [{key: row[key] for key in FIELDS} for row in rows],
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def connect_db(db_path: Path):
    return connect_wechat(str(db_path))


def dedupe_rows(rows):
    unique = {}
    for row in rows:
        unique.setdefault(row["订单号"], row)
    return list(unique.values())


def insert_new_rows(rows, db_path: Path, source_file: str = ""):
    """只插入尚未存在的订单号，已有记录保持不变。"""
    unique_rows = dedupe_rows(rows)
    conn = connect_db(db_path)
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
            (row["订单号"], row["交易对方"], row["备注"], source_file, imported_at)
            for row in new_rows
        ],
    )
    conn.commit()
    all_rows = [row_from_db(record) for record in conn.execute(
        "SELECT * FROM wechat_qr_income ORDER BY imported_at, order_no"
    ).fetchall()]
    conn.close()
    skipped = len(rows) - len(new_rows)
    return new_rows, skipped, all_rows


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


def lookup_order(order_no: str, db_path: Path):
    conn = connect_db(db_path)
    record = conn.execute(
        "SELECT * FROM wechat_qr_income WHERE order_no = ?",
        (order_no.strip(),),
    ).fetchone()
    conn.close()
    return row_from_db(record) if record else None


def list_orders(db_path: Path):
    conn = connect_db(db_path)
    records = conn.execute(
        "SELECT * FROM wechat_qr_income ORDER BY imported_at DESC, order_no"
    ).fetchall()
    conn.close()
    return [row_from_db(record) for record in records]


def print_rows(rows):
    writer = csv.DictWriter(sys.stdout, fieldnames=list(LIST_FIELDS), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)


def import_bill(args):
    if not args.csv.is_file():
        print(f"找不到文件：{args.csv}", file=sys.stderr)
        sys.exit(1)

    rows = extract_rows(decode_text(args.csv))
    csv_path = args.output or DEFAULT_CSV
    json_path = args.json or DEFAULT_JSON
    db_path = args.db or DEFAULT_DB

    inserted, skipped, all_rows = insert_new_rows(
        rows, db_path, source_file=str(args.csv.resolve())
    )
    write_csv(all_rows, csv_path)
    write_json(all_rows, json_path)

    print(f"本文件 {len(rows)} 条，新写入 {len(inserted)} 条，跳过重复 {skipped} 条。")
    print(f"库中现有 {len(all_rows)} 条：")
    print(f"  SQLite  {db_path}")
    print(f"  CSV     {csv_path}")
    print(f"  JSON    {json_path}")
    print("查询：python3 scripts/extract_wechat_qr_income.py --check 订单号")


def check_orders(args):
    db_path = args.db or DEFAULT_DB
    if not db_path.is_file():
        print(f"还没有导入记录：{db_path}", file=sys.stderr)
        sys.exit(1)

    found = []
    missing = []
    for order_no in args.check:
        order_no = order_no.strip()
        row = lookup_order(order_no, db_path)
        if row:
            found.append(row)
        else:
            missing.append(order_no)

    if found:
        print("命中：")
        print_rows(found)
    if missing:
        print("未找到：")
        for order_no in missing:
            print(order_no)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="提取并保存微信账单中二维码收款的订单号、交易对方、备注"
    )
    parser.add_argument("csv", nargs="?", type=Path, help="微信导出的账单 CSV")
    parser.add_argument("-o", "--output", type=Path, help=f"输出 CSV（默认 {DEFAULT_CSV}）")
    parser.add_argument("--json", type=Path, help=f"输出 JSON（默认 {DEFAULT_JSON}）")
    parser.add_argument("--db", type=Path, help=f"SQLite 路径（默认 {DEFAULT_DB}）")
    parser.add_argument(
        "--check",
        nargs="+",
        metavar="订单号",
        help="按订单号查询是否已导入",
    )
    parser.add_argument("--list", action="store_true", help="列出库中已导入的全部记录")
    args = parser.parse_args()

    if args.list:
        rows = list_orders(args.db or DEFAULT_DB)
        print_rows(rows)
        print(f"# 共 {len(rows)} 条", file=sys.stderr)
        return

    if args.check:
        check_orders(args)
        return

    if not args.csv:
        parser.error("请提供账单 CSV，或使用 --check / --list")

    import_bill(args)


if __name__ == "__main__":
    main()
