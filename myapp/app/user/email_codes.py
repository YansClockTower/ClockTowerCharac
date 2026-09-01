"""邮箱验证码：发码、校验（存在 user_latest.sqlite 的 email_codes 表）。"""

from __future__ import annotations

import random
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple

from app.identity.permissions import ensure_user_permission_schema
from app.models.database import get_user_db

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email or ""))


def find_user_by_username(username: str):
    ensure_user_permission_schema()
    db = get_user_db()
    try:
        return db.execute("SELECT * FROM user_info WHERE name = ?", (username,)).fetchone()
    finally:
        db.close()


def find_user_by_email(email: str):
    ensure_user_permission_schema()
    email = normalize_email(email)
    db = get_user_db()
    try:
        return db.execute("SELECT * FROM user_info WHERE email = ?", (email,)).fetchone()
    finally:
        db.close()


def find_user_by_account(account: str):
    """按用户名或邮箱查找账号。"""
    account = (account or "").strip()
    if not account:
        return None
    user = find_user_by_username(account)
    if user:
        return user
    if "@" in account:
        return find_user_by_email(account)
    return None


def user_email_verified(user) -> bool:
    if user is None:
        return False
    email = user["email"] if "email" in user.keys() else None
    verified = user["email_verified"] if "email_verified" in user.keys() else 0
    return bool(email and verified)


def create_email_code(email: str, purpose: str = "register") -> Tuple[Optional[str], Optional[str]]:
    ensure_user_permission_schema()
    email = normalize_email(email)
    db = get_user_db()
    try:
        now = datetime.utcnow()
        recent = db.execute(
            """
            SELECT created_at FROM email_codes
            WHERE email = ? AND purpose = ?
            ORDER BY id DESC LIMIT 1
            """,
            (email, purpose),
        ).fetchone()
        if recent:
            last = datetime.strptime(recent["created_at"], "%Y-%m-%d %H:%M:%S")
            if now - last < timedelta(seconds=60):
                return None, "发送过于频繁，请稍后再试"

        hour_count = db.execute(
            """
            SELECT COUNT(*) AS n FROM email_codes
            WHERE email = ? AND purpose = ? AND created_at >= ?
            """,
            (email, purpose, (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")),
        ).fetchone()["n"]
        if hour_count >= 5:
            return None, "该邮箱一小时内验证码次数过多"

        code = f"{random.randint(0, 999999):06d}"
        db.execute(
            """
            INSERT INTO email_codes (email, code, purpose, expires_at, used, created_at)
            VALUES (?, ?, ?, ?, 0, ?)
            """,
            (
                email,
                code,
                purpose,
                (now + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S"),
                now.strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        db.commit()
        return code, None
    finally:
        db.close()


def consume_email_code(email: str, code: str, purpose: str = "register") -> bool:
    ensure_user_permission_schema()
    email = normalize_email(email)
    code = (code or "").strip()
    db = get_user_db()
    try:
        row = db.execute(
            """
            SELECT * FROM email_codes
            WHERE email = ? AND code = ? AND purpose = ? AND used = 0
            ORDER BY id DESC LIMIT 1
            """,
            (email, code, purpose),
        ).fetchone()
        if not row:
            return False
        expires = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S")
        if datetime.utcnow() > expires:
            return False
        db.execute("UPDATE email_codes SET used = 1 WHERE id = ?", (row["id"],))
        db.commit()
        return True
    finally:
        db.close()


def bind_user_email(username: str, email: str) -> Tuple[bool, Optional[str]]:
    ensure_user_permission_schema()
    email = normalize_email(email)
    db = get_user_db()
    try:
        other = db.execute(
            "SELECT id FROM user_info WHERE email = ? AND name != ?",
            (email, username),
        ).fetchone()
        if other:
            return False, "该邮箱已被其他账号使用"
        db.execute(
            "UPDATE user_info SET email = ?, email_verified = 1 WHERE name = ?",
            (email, username),
        )
        db.commit()
        return True, None
    finally:
        db.close()
