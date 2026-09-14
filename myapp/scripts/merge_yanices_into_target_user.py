#!/usr/bin/env python3
"""将用户 yanices (id=100000) 的业务引用合并到「不是鱼子酱」(id=100001)，并弃用 yanices 账号。

覆盖库：
  - user_latest.sqlite（账号弃用；本脚本不改动主键 id）
  - board_games.sqlite（owner / current_holder 用户名）
  - events.sqlite（组织者、报名、分桌 host/owner/holder/player 用户名）
  - wechat_qr_income.sqlite（redeemed_by，若有）

说明：
  - 业务表大多存「用户名」而非数字 id；数字 id 主要出现在头像文件名 {id}.jpg。
  - 同活动/同桌若两边都有报名记录，保留目标用户记录，删除旧用户重复行。
  - 默认 dry-run；加 --apply 才写入。弃用账号会备份 sqlite 后再改。

用法（在 myapp 目录）：
    python3 scripts/merge_yanices_into_target_user.py
    python3 scripts/merge_yanices_into_target_user.py --apply
    python3 scripts/merge_yanices_into_target_user.py --apply \\
        --old-name yanices --old-id 100000 \\
        --new-name 不是鱼子酱 --new-id 100001
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.chdir(ROOT)

from app.models.config import get_config  # noqa: E402
from app.models.usericon import ICON_PATH, icon_init  # noqa: E402


def _db_base() -> Path:
    if get_config("development"):
        return Path(get_config("database_path_dev"))
    return Path(get_config("database_path"))


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _count(conn: sqlite3.Connection, sql: str, params=()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def _backup_file(path: Path, stamp: str) -> Optional[Path]:
    if not path.is_file():
        return None
    dest = path.with_name(f"{path.name}.pre_merge_yanices_{stamp}")
    shutil.copy2(path, dest)
    return dest


def _update_username_column(conn, table, column, old_name, new_name, apply: bool) -> int:
    if not _table_exists(conn, table):
        return 0
    n = _count(
        conn,
        f'SELECT COUNT(*) FROM "{table}" WHERE "{column}" = ?',
        (old_name,),
    )
    if apply and n:
        conn.execute(
            f'UPDATE "{table}" SET "{column}" = ? WHERE "{column}" = ?',
            (new_name, old_name),
        )
    return n


def _merge_unique_player_rows(
    conn,
    table: str,
    player_col: str,
    group_cols: list[str],
    old_name: str,
    new_name: str,
    apply: bool,
) -> tuple[int, int]:
    """将 player 从 old→new；若同组已有 new，则删除 old 行。返回 (renamed, deleted_dup)。"""
    if not _table_exists(conn, table):
        return 0, 0
    old_rows = conn.execute(
        f'SELECT * FROM "{table}" WHERE "{player_col}" = ?',
        (old_name,),
    ).fetchall()
    renamed = 0
    deleted = 0
    for row in old_rows:
        row = dict(row)
        where = " AND ".join(f'"{c}" = ?' for c in group_cols)
        params = [row[c] for c in group_cols] + [new_name]
        exists = conn.execute(
            f'SELECT 1 FROM "{table}" WHERE {where} AND "{player_col}" = ?',
            params,
        ).fetchone()
        # 定位旧行：优先用常见主键列
        pk = None
        for candidate in ("entryid", "id"):
            if candidate in row:
                pk = candidate
                break
        if exists:
            deleted += 1
            if apply:
                if pk:
                    conn.execute(f'DELETE FROM "{table}" WHERE "{pk}" = ?', (row[pk],))
                else:
                    conn.execute(
                        f'DELETE FROM "{table}" WHERE {where} AND "{player_col}" = ?',
                        [row[c] for c in group_cols] + [old_name],
                    )
        else:
            renamed += 1
            if apply:
                if pk:
                    conn.execute(
                        f'UPDATE "{table}" SET "{player_col}" = ? WHERE "{pk}" = ?',
                        (new_name, row[pk]),
                    )
                else:
                    conn.execute(
                        f'UPDATE "{table}" SET "{player_col}" = ? WHERE {where} AND "{player_col}" = ?',
                        [new_name] + [row[c] for c in group_cols] + [old_name],
                    )
    return renamed, deleted


def plan_and_apply(args) -> int:
    old_name = args.old_name
    new_name = args.new_name
    old_id = int(args.old_id)
    new_id = int(args.new_id)
    apply = bool(args.apply)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    base = _db_base()
    user_db = base / "user_latest.sqlite"
    board_db = base / "board_games.sqlite"
    events_db = base / "events.sqlite"
    wechat_db = base / "wechat_qr_income.sqlite"

    print(f"模式: {'APPLY（将写入）' if apply else 'DRY-RUN（仅预览）'}")
    print(f"库目录: {base.resolve()}")
    print(f"旧用户: {old_name!r} (id={old_id}) → 新用户: {new_name!r} (id={new_id})")
    print()

    if not user_db.is_file():
        print(f"找不到用户库：{user_db}", file=sys.stderr)
        return 1

    uconn = _connect(user_db)
    old_user = uconn.execute(
        "SELECT * FROM user_info WHERE id = ? OR name = ?",
        (old_id, old_name),
    ).fetchall()
    new_user = uconn.execute(
        "SELECT * FROM user_info WHERE id = ? OR name = ?",
        (new_id, new_name),
    ).fetchall()

    old_by_id = uconn.execute("SELECT * FROM user_info WHERE id = ?", (old_id,)).fetchone()
    old_by_name = uconn.execute("SELECT * FROM user_info WHERE name = ?", (old_name,)).fetchone()
    new_by_id = uconn.execute("SELECT * FROM user_info WHERE id = ?", (new_id,)).fetchone()
    new_by_name = uconn.execute("SELECT * FROM user_info WHERE name = ?", (new_name,)).fetchone()

    print("=== user_latest.sqlite ===")
    print(f"  按 id={old_id}: {dict(old_by_id) if old_by_id else None}")
    print(f"  按 name={old_name!r}: {dict(old_by_name) if old_by_name else None}")
    print(f"  按 id={new_id}: {dict(new_by_id) if new_by_id else None}")
    print(f"  按 name={new_name!r}: {dict(new_by_name) if new_by_name else None}")

    if not old_by_id and not old_by_name:
        print("未找到旧用户，退出。", file=sys.stderr)
        uconn.close()
        return 1
    if old_by_id and old_by_name and old_by_id["id"] != old_by_name["id"]:
        print("警告：旧 id 与旧用户名指向不同行，请人工确认。", file=sys.stderr)
    if not new_by_id:
        print(f"未找到目标用户 id={new_id}，退出。", file=sys.stderr)
        uconn.close()
        return 1
    if new_by_name and int(new_by_name["id"]) != new_id:
        print(
            f"目标用户名 {new_name!r} 已存在但 id={new_by_name['id']} ≠ {new_id}，退出。",
            file=sys.stderr,
        )
        uconn.close()
        return 1
    if (new_by_id["name"] or "") != new_name:
        print(
            f"注意：id={new_id} 当前用户名为 {new_by_id['name']!r}，"
            f"脚本将在 APPLY 时改名为 {new_name!r}。"
        )

    # --- board games ---
    board_changes = {}
    if board_db.is_file():
        bconn = _connect(board_db)
        print("\n=== board_games.sqlite ===")
        for col in ("owner", "current_holder"):
            n = _update_username_column(bconn, "registered_board_games", col, old_name, new_name, False)
            board_changes[col] = n
            print(f"  registered_board_games.{col}: {n} 行")
        if apply:
            _backup_file(board_db, stamp)
            for col in ("owner", "current_holder"):
                _update_username_column(bconn, "registered_board_games", col, old_name, new_name, True)
            bconn.commit()
        bconn.close()
    else:
        print(f"\n跳过桌游库（不存在）：{board_db}")

    # --- events ---
    event_report = {}
    if events_db.is_file():
        econn = _connect(events_db)
        print("\n=== events.sqlite ===")
        simple = [
            ("events", "inviter"),
            ("fixed_events", "inviter"),
            ("fixed_tables", "host"),
            ("fixed_tables", "owner_name"),
            ("fixed_tables", "holder_name"),
            ("attendrecord", "player"),
        ]
        for table, col in simple:
            n = _update_username_column(econn, table, col, old_name, new_name, False)
            event_report[f"{table}.{col}"] = {"update": n}
            print(f"  {table}.{col}: {n} 行将改名")

        for table, player_col, groups in (
            ("attendinfo", "player", ["eventid"]),
            ("fixed_table_attend", "player", ["fixed_event_id", "table_id"]),
        ):
            renamed, deleted = _merge_unique_player_rows(
                econn, table, player_col, groups, old_name, new_name, False
            )
            event_report[f"{table}.{player_col}"] = {"rename": renamed, "delete_dup": deleted}
            print(f"  {table}.{player_col}: 改名 {renamed}，删重复 {deleted}")

        if apply:
            _backup_file(events_db, stamp)
            for table, col in simple:
                _update_username_column(econn, table, col, old_name, new_name, True)
            for table, player_col, groups in (
                ("attendinfo", "player", ["eventid"]),
                ("fixed_table_attend", "player", ["fixed_event_id", "table_id"]),
            ):
                _merge_unique_player_rows(
                    econn, table, player_col, groups, old_name, new_name, True
                )
            econn.commit()
        econn.close()
    else:
        print(f"\n跳过活动库（不存在）：{events_db}")

    # --- wechat ---
    if wechat_db.is_file():
        wconn = _connect(wechat_db)
        print("\n=== wechat_qr_income.sqlite ===")
        n = _update_username_column(wconn, "wechat_qr_income", "redeemed_by", old_name, new_name, False)
        print(f"  redeemed_by: {n} 行")
        if apply and n:
            _backup_file(wechat_db, stamp)
            _update_username_column(wconn, "wechat_qr_income", "redeemed_by", old_name, new_name, True)
            wconn.commit()
        wconn.close()

    # --- icons ---
    icon_init()
    from app.models import usericon as usericon_mod

    icon_dir = Path(usericon_mod.ICON_PATH) if usericon_mod.ICON_PATH else None
    old_icon = icon_dir / f"{old_id}.jpg" if icon_dir else None
    new_icon = icon_dir / f"{new_id}.jpg" if icon_dir else None
    print("\n=== 头像文件 ===")
    print(f"  目录: {icon_dir}")
    print(f"  旧: {old_icon} exists={old_icon.is_file() if old_icon else False}")
    print(f"  新: {new_icon} exists={new_icon.is_file() if new_icon else False}")
    if apply and old_icon and old_icon.is_file():
        if new_icon and not new_icon.is_file():
            shutil.copy2(old_icon, new_icon)
            print(f"  已复制头像 → {new_icon}")
        else:
            print("  目标头像已存在或路径无效，不覆盖。")
        deprecated_icon = icon_dir / f"{old_id}.deprecated_{stamp}.jpg"
        shutil.move(str(old_icon), str(deprecated_icon))
        print(f"  旧头像已挪到 {deprecated_icon.name}")

    # --- deprecate old user account ---
    print("\n=== 弃用旧账号 ===")
    deprecated_name = f"{old_name}__deprecated_{stamp}"
    print(f"  将把旧账号改名为 {deprecated_name!r}，并清空 password_hash")
    if (new_by_id["name"] or "") != new_name:
        print(f"  并将 id={new_id} 的 name 改为 {new_name!r}")

    if apply:
        _backup_file(user_db, stamp)
        # 确保目标用户名正确
        if (new_by_id["name"] or "") != new_name:
            conflict = uconn.execute(
                "SELECT id FROM user_info WHERE name = ? AND id != ?",
                (new_name, new_id),
            ).fetchone()
            if conflict:
                print(f"无法改名：{new_name!r} 已被 id={conflict['id']} 占用", file=sys.stderr)
                uconn.close()
                return 1
            uconn.execute(
                "UPDATE user_info SET name = ? WHERE id = ?",
                (new_name, new_id),
            )
        # 弃用旧账号（按 id 优先）
        target_old_id = int(old_by_id["id"]) if old_by_id else int(old_by_name["id"])
        uconn.execute(
            """
            UPDATE user_info
            SET name = ?, password_hash = '', email = NULL, email_verified = 0
            WHERE id = ?
            """,
            (deprecated_name, target_old_id),
        )
        uconn.commit()
        print(f"  已弃用 id={target_old_id}")
    else:
        print("  （dry-run，未改 user_info）")

    uconn.close()
    print("\n完成。" + ("" if apply else " 确认无误后请加 --apply 执行。"))
    return 0


def main():
    parser = argparse.ArgumentParser(description="合并/弃用 yanices → 不是鱼子酱")
    parser.add_argument("--apply", action="store_true", help="实际写入（默认仅预览）")
    parser.add_argument("--old-name", default="yanices")
    parser.add_argument("--old-id", default="100000")
    parser.add_argument("--new-name", default="不是鱼子酱")
    parser.add_argument("--new-id", default="100001")
    args = parser.parse_args()

    # 触发 config / ICON_PATH
    from app import create_app

    app = create_app()
    with app.app_context():
        raise SystemExit(plan_and_apply(args))


if __name__ == "__main__":
    main()
