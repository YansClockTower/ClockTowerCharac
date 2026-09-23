#!/usr/bin/env python3
"""一次性清空桌游库里的借用者（原「持有者」，列 current_holder）。

未借用应为空。历史数据里常把所有者又写进持有者，本脚本把所有非空借用者都清成空。
所有者与存放地点不动。活动分桌里已经记下的 holder_name 是当时的快照，也不改。

默认只打印将清空的行；加 --apply 才写入，并先备份数据库。

用法（在 myapp 目录）：
    python3 scripts/clear_board_game_holders.py
    python3 scripts/clear_board_game_holders.py --apply
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.chdir(ROOT)

from app.models.config import get_config  # noqa: E402


def _db_path() -> Path:
    if get_config("development"):
        base = Path(get_config("database_path_dev"))
    else:
        base = Path(get_config("database_path"))
    return base / "board_games.sqlite"


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def main() -> int:
    parser = argparse.ArgumentParser(description="清空桌游借用者（current_holder）")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="写入数据库。省略时只预览。",
    )
    args = parser.parse_args()

    path = _db_path()
    if not path.is_file():
        print(f"找不到桌游库：{path}", file=sys.stderr)
        return 1

    conn = _connect(path)
    rows = conn.execute(
        """
        SELECT id, board_game_name, owner, current_holder
        FROM registered_board_games
        WHERE current_holder IS NOT NULL AND TRIM(current_holder) != ''
        ORDER BY id
        """
    ).fetchall()

    print(f"数据库：{path}")
    print(f"将清空借用者的桌游：{len(rows)} 条")
    for row in rows:
        print(
            f"  #{row['id']} {row['board_game_name']}  "
            f"所有者={row['owner']}  借用者={row['current_holder']}"
        )

    if not rows:
        conn.close()
        print("没有需要清空的借用者。")
        return 0

    if not args.apply:
        conn.close()
        print("\n以上为预览。确认后执行：")
        print("  python3 scripts/clear_board_game_holders.py --apply")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.pre_clear_holders_{stamp}")
    shutil.copy2(path, backup)
    print(f"\n已备份：{backup}")

    cur = conn.execute(
        """
        UPDATE registered_board_games
        SET current_holder = NULL
        WHERE current_holder IS NOT NULL AND TRIM(current_holder) != ''
        """
    )
    conn.commit()
    print(f"已清空 {cur.rowcount} 条借用者。")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
