#!/usr/bin/env python3
"""Reset one user's password_hash to empty string."""

import sqlite3
import sys
from pathlib import Path

# ======= Configure here =======
DB_PATH = Path("./user_latest.sqlite")
TARGET_USERNAME = "水十"
# ==============================


def reset_password_to_empty(db_path: Path, username: str) -> int:
    if not db_path.exists():
        print(f"[ERROR] Database file not found: {db_path}")
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        table_info = conn.execute("PRAGMA table_info(user_info)").fetchall()
        columns = {row["name"] for row in table_info}
        if "password_hash" not in columns:
            print("[ERROR] Column 'password_hash' not found in table 'user_info'.")
            return 1

        user = conn.execute("SELECT id, name FROM user_info WHERE name = ?", (username,)).fetchone()
        if user is None:
            print(f"[ERROR] User not found: {username}")
            return 1

        conn.execute("UPDATE user_info SET password_hash = '' WHERE name = ?", (username,))
        conn.commit()
        print(f"[OK] Password cleared for user '{username}'.")
        print("[OK] This account is now a temporary account and must register again to set password.")
        return 0
    finally:
        conn.close()


def main() -> int:
    if not TARGET_USERNAME or TARGET_USERNAME == "replace_with_username":
        print("[ERROR] Please set TARGET_USERNAME at the top of this script.")
        return 1
    return reset_password_to_empty(DB_PATH, TARGET_USERNAME)


if __name__ == "__main__":
    sys.exit(main())
