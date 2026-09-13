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
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os

os.chdir(ROOT)

from app.models.wechat_bills import (
    connect_wechat,
    extract_qr_income_rows,
    insert_qr_income_rows,
    list_qr_income_rows,
    row_from_db,
    wechat_db_path,
    write_qr_income_exports,
)

DEFAULT_DIR = ROOT / "database"
DEFAULT_CSV = DEFAULT_DIR / "wechat_qr_income.csv"
DEFAULT_JSON = DEFAULT_DIR / "wechat_qr_income.json"
DEFAULT_DB = Path(wechat_db_path())

ENCODINGS = ("utf-8-sig", "gb18030", "gbk")
LIST_FIELDS = ("订单号", "交易对方", "备注", "核销")


def decode_text(path: Path) -> str:
    raw = path.read_bytes()
    last_error = None
    for enc in ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise last_error


def print_rows(rows):
    writer = csv.DictWriter(sys.stdout, fieldnames=list(LIST_FIELDS), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)


def import_bill(args):
    if not args.csv.is_file():
        print(f"找不到文件：{args.csv}", file=sys.stderr)
        sys.exit(1)

    # 允许从任意 cwd 传入相对路径；脚本已 chdir 到 myapp
    csv_path = args.csv if args.csv.is_absolute() else (Path.cwd() / args.csv)
    if not csv_path.is_file():
        # 兼容在 scripts/ 下传文件名：回退到 scripts/<name>
        alt = ROOT / "scripts" / args.csv.name
        if alt.is_file():
            csv_path = alt
        else:
            print(f"找不到文件：{args.csv}", file=sys.stderr)
            sys.exit(1)

    rows = extract_qr_income_rows(decode_text(csv_path))
    out_csv = args.output or DEFAULT_CSV
    out_json = args.json or DEFAULT_JSON

    inserted, skipped, all_rows = insert_qr_income_rows(
        rows,
        source_label=str(csv_path.resolve()),
        sync_exports=False,
    )
    write_qr_income_exports(all_rows, csv_path=out_csv, json_path=out_json)

    print(f"本文件 {len(rows)} 条，新写入 {len(inserted)} 条，跳过重复 {skipped} 条。")
    print(f"库中现有 {len(all_rows)} 条：")
    print(f"  SQLite  {args.db or DEFAULT_DB}")
    print(f"  CSV     {out_csv}")
    print(f"  JSON    {out_json}")
    print("查询：python3 scripts/extract_wechat_qr_income.py --check 订单号")


def check_orders(args):
    db_path = args.db or DEFAULT_DB
    if not db_path.is_file():
        print(f"还没有导入记录：{db_path}", file=sys.stderr)
        sys.exit(1)

    found = []
    missing = []
    conn = connect_wechat(str(db_path))
    try:
        for order_no in args.check:
            order_no = order_no.strip()
            record = conn.execute(
                "SELECT * FROM wechat_qr_income WHERE order_no = ?",
                (order_no,),
            ).fetchone()
            if record:
                found.append(row_from_db(record))
            else:
                missing.append(order_no)
    finally:
        conn.close()

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
        rows = list_qr_income_rows()
        # 列表按导入时间倒序更适合 CLI 浏览
        rows = list(reversed(rows))
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
