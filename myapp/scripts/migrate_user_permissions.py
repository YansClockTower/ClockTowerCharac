#!/usr/bin/env python3
"""迁移 user_info 权限：单一 permission_script_bitmap，删除 permission_lightboard_bitmap。

- 旧 6 项布尔列 → script bitmap（说书人 / 染作者，「或」合并）
- 旧 permission_lightboard_bitmap → 合并进 script bitmap bit 4–7
- /user/me 不暴露原始 bitmap，仅 DB 存储

用法（在 myapp 目录）：
    python3 scripts/migrate_user_permissions.py --dry-run
    python3 scripts/migrate_user_permissions.py
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os

os.chdir(ROOT)

from app.identity.permissions import (  # noqa: E402
    ASSOCIATION_ROLE_COLUMN,
    ASSOCIATION_ROLE_RANK,
    ASSOCIATION_ROLE_VALUES,
    ADMIN_RANK,
    LEGACY_LIGHTBOARD_BITMAP_COLUMN,
    LEGACY_MANAGE_ACCOUNT_COLUMN,
    LEGACY_SCRIPT_COLUMNS,
    MANAGE_ACCOUNT_PERMISSION,
    PERMISSION_BOTC_EDITION_AUTHOR,
    PERMISSION_STORYTELLER,
    PERMISSION_TRPG_DM,
    PERMISSION_TRPG_MODULE_AUTHOR,
    SCRIPT_BITMAP_COLUMN,
    USER_PERMISSION_KEYS,
    _bool_like,
    _normalize_script_bitmap,
    enrich_user_permissions,
    ensure_user_permission_schema,
    get_permission_bitmap_config,
)

LEGACY_COLUMNS_TO_DROP = (
    LEGACY_MANAGE_ACCOUNT_COLUMN,
    LEGACY_LIGHTBOARD_BITMAP_COLUMN,
    *LEGACY_SCRIPT_COLUMNS,
)

TARGET_USER_INFO_DDL = """
CREATE TABLE user_info_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    password_hash TEXT,
    icon TEXT,
    title TEXT,
    permission_manage_account BOOLEAN DEFAULT 0,
    permission_script_bitmap INTEGER DEFAULT 0,
    association_role TEXT DEFAULT '普通玩家',
    social_role TEXT DEFAULT '保密',
    contact_info TEXT DEFAULT '保密',
    activity_organized_count INTEGER DEFAULT 0,
    activity_joined_count INTEGER DEFAULT 0,
    activity_absent_count INTEGER DEFAULT 0,
    email TEXT,
    email_verified INTEGER DEFAULT 0,
    member_order_no TEXT,
    member_review_note TEXT,
    lastLogin INTEGER
)
"""

INSERT_COLUMNS = (
    "id",
    "name",
    "password_hash",
    "icon",
    "title",
    MANAGE_ACCOUNT_PERMISSION,
    SCRIPT_BITMAP_COLUMN,
    ASSOCIATION_ROLE_COLUMN,
    "social_role",
    "contact_info",
    "activity_organized_count",
    "activity_joined_count",
    "activity_absent_count",
    "email",
    "email_verified",
    "member_order_no",
    "member_review_note",
    "lastLogin",
)


def default_db_path() -> Path:
    from app.models.config import get_config

    base = Path(get_config("database_path_dev") if get_config("development") else get_config("database_path"))
    if not base.is_absolute():
        base = ROOT / base
    return base / "user_latest.sqlite"


def _row_column_set(conn: sqlite3.Connection) -> set[str]:
    return {row[1] for row in conn.execute("PRAGMA table_info(user_info)").fetchall()}


def _resolve_association_role(row: Mapping[str, Any]) -> str:
    role = row.get(ASSOCIATION_ROLE_COLUMN) or "普通玩家"
    if role not in ASSOCIATION_ROLE_RANK:
        role = "普通玩家"

    legacy_admin = _bool_like(row.get(LEGACY_MANAGE_ACCOUNT_COLUMN)) or _bool_like(
        row.get(MANAGE_ACCOUNT_PERMISSION)
    )
    if legacy_admin and ASSOCIATION_ROLE_RANK.get(role, 0) < ADMIN_RANK:
        return ASSOCIATION_ROLE_VALUES[-1]
    return role


def migrate_row(row: Mapping[str, Any], config: Mapping[str, Mapping[str, int]]) -> dict[str, Any]:
    script_bitmap = _normalize_script_bitmap(row, config)
    enriched = enrich_user_permissions({**row, SCRIPT_BITMAP_COLUMN: script_bitmap})
    association_role = _resolve_association_role(row)
    is_admin = ASSOCIATION_ROLE_RANK.get(association_role, 0) == ADMIN_RANK

    return {
        SCRIPT_BITMAP_COLUMN: script_bitmap,
        ASSOCIATION_ROLE_COLUMN: association_role,
        MANAGE_ACCOUNT_PERMISSION: int(is_admin),
        PERMISSION_STORYTELLER: enriched[PERMISSION_STORYTELLER],
        PERMISSION_BOTC_EDITION_AUTHOR: enriched[PERMISSION_BOTC_EDITION_AUTHOR],
        PERMISSION_TRPG_DM: enriched[PERMISSION_TRPG_DM],
        PERMISSION_TRPG_MODULE_AUTHOR: enriched[PERMISSION_TRPG_MODULE_AUTHOR],
    }


def backup_database(db_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.with_name(f"{db_path.stem}.pre_permission_migrate_{stamp}{db_path.suffix}")
    shutil.copy2(db_path, backup_path)
    return backup_path


def load_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return list(conn.execute("SELECT * FROM user_info ORDER BY id"))


def print_preview(rows: list[sqlite3.Row], config: Mapping[str, Mapping[str, int]], legacy_present: list[str]) -> None:
    print(f"共 {len(rows)} 条用户记录\n")
    print(
        f"{'id':>8}  {'name':<18}  {'说书':^4}  {'染作者':^5}  "
        f"{'跑团DM':^6}  {'模组作者':^6}  {'位图':>4}"
    )
    print("-" * 72)
    for row in rows:
        row_dict = dict(row)
        migrated = migrate_row(row_dict, config)
        print(
            f"{row_dict['id']:>8}  {str(row_dict.get('name', '')):<18}  "
            f"{'是' if migrated[PERMISSION_STORYTELLER] else '否':^4}  "
            f"{'是' if migrated[PERMISSION_BOTC_EDITION_AUTHOR] else '否':^5}  "
            f"{'是' if migrated[PERMISSION_TRPG_DM] else '否':^6}  "
            f"{'是' if migrated[PERMISSION_TRPG_MODULE_AUTHOR] else '否':^6}  "
            f"{migrated[SCRIPT_BITMAP_COLUMN]:>4}"
        )

    if legacy_present:
        print("\n将删除的冗余列：")
        for name in legacy_present:
            print(f"  - {name}")
    else:
        print("\n将规范化 permission_script_bitmap（单一 bitmap）。")


def _rebuild_without_legacy_columns(
    conn: sqlite3.Connection,
    migrated_rows: list[dict[str, Any]],
) -> None:
    conn.execute("DROP TABLE IF EXISTS user_info_new")
    conn.execute(TARGET_USER_INFO_DDL)

    placeholders = ", ".join("?" for _ in INSERT_COLUMNS)
    insert_sql = f"""
        INSERT INTO user_info_new ({", ".join(INSERT_COLUMNS)})
        VALUES ({placeholders})
    """

    for item in migrated_rows:
        conn.execute(
            insert_sql,
            (
                item.get("id"),
                item.get("name"),
                item.get("password_hash"),
                item.get("icon"),
                item.get("title"),
                item[MANAGE_ACCOUNT_PERMISSION],
                item[SCRIPT_BITMAP_COLUMN],
                item[ASSOCIATION_ROLE_COLUMN],
                item.get("social_role") or "保密",
                item.get("contact_info") or "保密",
                max(int(item.get("activity_organized_count") or 0), 0),
                max(int(item.get("activity_joined_count") or 0), 0),
                max(int(item.get("activity_absent_count") or 0), 0),
                item.get("email"),
                int(_bool_like(item.get("email_verified"))),
                item.get("member_order_no"),
                item.get("member_review_note"),
                item.get("lastLogin"),
            ),
        )

    conn.execute("DROP TABLE user_info")
    conn.execute("ALTER TABLE user_info_new RENAME TO user_info")

    try:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_user_info_email ON user_info(email)")
    except sqlite3.Error:
        pass


def apply_migration(conn: sqlite3.Connection, config: Mapping[str, Mapping[str, int]], legacy_present: list[str]) -> int:
    columns = _row_column_set(conn)
    missing_new = [
        name
        for name in (MANAGE_ACCOUNT_PERMISSION, SCRIPT_BITMAP_COLUMN, ASSOCIATION_ROLE_COLUMN)
        if name not in columns
    ]
    for name in missing_new:
        if name == SCRIPT_BITMAP_COLUMN:
            conn.execute(f"ALTER TABLE user_info ADD COLUMN {name} INTEGER DEFAULT 0")
        elif name == MANAGE_ACCOUNT_PERMISSION:
            conn.execute(f"ALTER TABLE user_info ADD COLUMN {name} BOOLEAN DEFAULT 0")
        elif name == ASSOCIATION_ROLE_COLUMN:
            conn.execute(f"ALTER TABLE user_info ADD COLUMN {name} TEXT DEFAULT '普通玩家'")
        print(f"已补列: {name}")

    rows = load_rows(conn)
    migrated_rows: list[dict[str, Any]] = []
    for row in rows:
        row_dict = dict(row)
        migrated = migrate_row(row_dict, config)
        migrated_rows.append({**row_dict, **migrated})

    needs_rebuild = bool(legacy_present)
    if needs_rebuild:
        _rebuild_without_legacy_columns(conn, migrated_rows)
    else:
        for item in migrated_rows:
            conn.execute(
                f"""
                UPDATE user_info
                SET {SCRIPT_BITMAP_COLUMN} = ?,
                    {MANAGE_ACCOUNT_PERMISSION} = ?,
                    {ASSOCIATION_ROLE_COLUMN} = ?
                WHERE id = ?
                """,
                (
                    item[SCRIPT_BITMAP_COLUMN],
                    item[MANAGE_ACCOUNT_PERMISSION],
                    item[ASSOCIATION_ROLE_COLUMN],
                    item["id"],
                ),
            )

    conn.commit()
    return len(migrated_rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移 user_info 至单一 permission_script_bitmap")
    parser.add_argument("--db", type=Path, help="user_latest.sqlite 路径（默认读 config.txt）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不写库")
    parser.add_argument("--no-backup", action="store_true", help="执行时不备份（不推荐）")
    args = parser.parse_args()

    db_path = (args.db or default_db_path()).resolve()
    if not db_path.is_file():
        print(f"错误：找不到数据库 {db_path}", file=sys.stderr)
        return 1

    config = get_permission_bitmap_config()
    missing_bits = [k for k in USER_PERMISSION_KEYS if k not in config.get("script_subsystem", {})]
    if missing_bits:
        print(f"警告：config 缺少权限位定义: {', '.join(missing_bits)}", file=sys.stderr)

    conn = sqlite3.connect(db_path)
    try:
        columns = _row_column_set(conn)
        if "user_info" not in {t[0] for t in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            print("错误：库中无 user_info 表", file=sys.stderr)
            return 1

        legacy_present = [c for c in LEGACY_COLUMNS_TO_DROP if c in columns]
        rows = load_rows(conn)

        if args.dry_run:
            print(f"[dry-run] 数据库: {db_path}")
            print_preview(rows, config, legacy_present)
            return 0

        if not args.no_backup:
            backup = backup_database(db_path)
            print(f"已备份: {backup}")

        count = apply_migration(conn, config, legacy_present)
        if legacy_present:
            print(f"迁移完成：{count} 条用户记录")
            print("已删除列:", ", ".join(legacy_present))
        else:
            print(f"位图规范化完成：{count} 条用户记录（单一 permission_script_bitmap）")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
