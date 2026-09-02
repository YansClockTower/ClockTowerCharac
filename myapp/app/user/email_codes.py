"""邮箱验证码：发码、校验（存在 user_latest.sqlite 的 email_codes 表）。"""

from __future__ import annotations

import random
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple

from app.identity.permissions import ensure_user_permission_schema
from app.models.database import get_user_db

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CODE_TTL_MINUTES = 10
CODE_COOLDOWN_SECONDS = 60
CODE_HOURLY_LIMIT = 5
CONFIRM_RESEND_MESSAGE = "监测到您当前有一个有效的验证码可以直接填写。确认重发吗？"
_DATETIME_FMT = "%Y-%m-%d %H:%M:%S"


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


def _parse_db_time(value: str) -> datetime:
    return datetime.strptime(value, _DATETIME_FMT)


def _format_db_time(when: datetime) -> str:
    return when.strftime(_DATETIME_FMT)


def find_active_email_code(email: str, purpose: str = "register"):
    """返回尚未使用且未过期的验证码记录，否则 None。"""
    ensure_user_permission_schema()
    email = normalize_email(email)
    db = get_user_db()
    try:
        row = db.execute(
            """
            SELECT * FROM email_codes
            WHERE email = ? AND purpose = ? AND used = 0
            ORDER BY id DESC LIMIT 1
            """,
            (email, purpose),
        ).fetchone()
        if not row:
            return None
        if datetime.utcnow() > _parse_db_time(row["expires_at"]):
            return None
        return row
    finally:
        db.close()


def _check_send_cooldown(db, email: str, purpose: str, now: datetime) -> Optional[str]:
    recent = db.execute(
        """
        SELECT created_at FROM email_codes
        WHERE email = ? AND purpose = ?
        ORDER BY id DESC LIMIT 1
        """,
        (email, purpose),
    ).fetchone()
    if not recent:
        return None
    last = _parse_db_time(recent["created_at"])
    if now - last < timedelta(seconds=CODE_COOLDOWN_SECONDS):
        return "发送过于频繁，请稍后再试"
    return None


def _check_hourly_limit(db, email: str, purpose: str, now: datetime) -> Optional[str]:
    hour_count = db.execute(
        """
        SELECT COUNT(*) AS n FROM email_codes
        WHERE email = ? AND purpose = ? AND created_at >= ?
        """,
        (email, purpose, _format_db_time(now - timedelta(hours=1))),
    ).fetchone()["n"]
    if hour_count >= CODE_HOURLY_LIMIT:
        return "该邮箱一小时内验证码次数过多"
    return None


def _refresh_active_code(db, row, now: datetime) -> str:
    expires_at = _format_db_time(now + timedelta(minutes=CODE_TTL_MINUTES))
    created_at = _format_db_time(now)
    db.execute(
        "UPDATE email_codes SET expires_at = ?, created_at = ? WHERE id = ?",
        (expires_at, created_at, row["id"]),
    )
    db.commit()
    return row["code"]


def create_email_code(
    email: str,
    purpose: str = "register",
    *,
    confirm_resend: bool = False,
) -> Tuple[Optional[str], Optional[str], bool]:
    """发码 / 重发。返回 (code, error, need_confirm_resend)。"""
    ensure_user_permission_schema()
    email = normalize_email(email)
    db = get_user_db()
    try:
        now = datetime.utcnow()
        active = None
        row = db.execute(
            """
            SELECT * FROM email_codes
            WHERE email = ? AND purpose = ? AND used = 0
            ORDER BY id DESC LIMIT 1
            """,
            (email, purpose),
        ).fetchone()
        if row and datetime.utcnow() <= _parse_db_time(row["expires_at"]):
            active = row

        if active and not confirm_resend:
            return None, None, True

        if active and confirm_resend:
            return _refresh_active_code(db, active, now), None, False

        cooldown_err = _check_send_cooldown(db, email, purpose, now)
        if cooldown_err:
            return None, cooldown_err, False

        hourly_err = _check_hourly_limit(db, email, purpose, now)
        if hourly_err:
            return None, hourly_err, False

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
                _format_db_time(now + timedelta(minutes=CODE_TTL_MINUTES)),
                _format_db_time(now),
            ),
        )
        db.commit()
        return code, None, False
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
        expires = _parse_db_time(row["expires_at"])
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
