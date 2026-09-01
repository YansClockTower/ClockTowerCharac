"""微信订单号会员核销：升 association_role，不另建 is_member。"""

from __future__ import annotations

from typing import Optional, Tuple

from app.identity.permissions import (
    ASSOCIATION_ROLE_COLUMN,
    ASSOCIATION_ROLE_RANK,
    MEMBER_ORDER_NO_COLUMN,
    MEMBER_REVIEW_NOTE_COLUMN,
    ensure_user_permission_schema,
)
from app.models.database import get_user_db
from app.models.wechat_bills import (
    connect_wechat,
    is_valid_order_no,
    normalize_order_no,
    redeem_income_order,
)
from app.user.email_codes import find_user_by_username

MEMBER_ROLE = "协会玩家"


def _row_get(user, key, default=None):
    if user is None:
        return default
    try:
        if key in user.keys():
            return user[key]
    except Exception:
        pass
    return default


def association_role_of(user) -> str:
    role = _row_get(user, ASSOCIATION_ROLE_COLUMN, "普通玩家") or "普通玩家"
    return role if role in ASSOCIATION_ROLE_RANK else "普通玩家"


def user_is_member(user) -> bool:
    """协会玩家及以上视为会员（用于展示与锁凭证）。"""
    return ASSOCIATION_ROLE_RANK.get(association_role_of(user), 0) >= ASSOCIATION_ROLE_RANK[MEMBER_ROLE]


def user_member_locked(user) -> bool:
    order_no = (_row_get(user, MEMBER_ORDER_NO_COLUMN) or "").strip()
    return user_is_member(user) and bool(order_no)


def membership_credential_status(user) -> str:
    """会员凭证栏状态：未提交 / 待验证 / 已验证 / 无需验证。"""
    if user_is_member(user):
        order_no = (_row_get(user, MEMBER_ORDER_NO_COLUMN) or "").strip()
        if order_no:
            return "已验证"
        return "无需验证"
    order_no = (_row_get(user, MEMBER_ORDER_NO_COLUMN) or "").strip()
    if order_no:
        return "待验证"
    return "未提交"


def _grant_membership(username: str, order_no: str) -> None:
    ensure_user_permission_schema()
    db = get_user_db()
    try:
        row = db.execute("SELECT * FROM user_info WHERE name = ?", (username,)).fetchone()
        if not row:
            return
        current = association_role_of(row)
        new_role = current
        if ASSOCIATION_ROLE_RANK.get(current, 0) < ASSOCIATION_ROLE_RANK[MEMBER_ROLE]:
            new_role = MEMBER_ROLE
        db.execute(
            f"""
            UPDATE user_info
            SET {MEMBER_ORDER_NO_COLUMN} = ?,
                {MEMBER_REVIEW_NOTE_COLUMN} = NULL,
                {ASSOCIATION_ROLE_COLUMN} = ?
            WHERE name = ?
            """,
            (order_no, new_role, username),
        )
        db.commit()
    finally:
        db.close()


def _save_pending_order(username: str, order_no: str, note: Optional[str] = None) -> None:
    ensure_user_permission_schema()
    db = get_user_db()
    try:
        row = db.execute("SELECT * FROM user_info WHERE name = ?", (username,)).fetchone()
        if not row:
            return
        if user_member_locked(row):
            return
        db.execute(
            f"""
            UPDATE user_info
            SET {MEMBER_ORDER_NO_COLUMN} = ?, {MEMBER_REVIEW_NOTE_COLUMN} = ?
            WHERE name = ?
            """,
            (order_no, note, username),
        )
        db.commit()
    finally:
        db.close()


def _try_redeem_for_user(username: str, order_no: str) -> str:
    """尝试核销账单订单号。返回 granted / pending / used。"""
    conn = connect_wechat()
    try:
        status = redeem_income_order(conn, order_no, username)
    finally:
        conn.close()
    if status == "ok":
        _grant_membership(username, order_no)
        return "granted"
    if status == "used":
        # 已被他人核销：不锁定订单号到当前用户档案
        _save_pending_order(username, "", "该订单号已被核销，请更换凭证")
        return "used"
    return "pending"


def silent_verify_membership(username: str) -> Optional[str]:
    """每次访问时复核待审订单号。刚通过时返回 granted。"""
    user = find_user_by_username(username)
    if user is None:
        return None
    order_no = normalize_order_no(_row_get(user, MEMBER_ORDER_NO_COLUMN) or "")
    if user_is_member(user):
        if order_no:
            conn = connect_wechat()
            try:
                redeem_income_order(conn, order_no, username)
            finally:
                conn.close()
        return None
    if not order_no:
        return None
    result = _try_redeem_for_user(username, order_no)
    return result if result == "granted" else None


def submit_member_order(username: str, order_no: str) -> Tuple[bool, str, str]:
    """提交订单号凭证。返回 (ok, status, message)。status: granted/pending/used/error。"""
    user = find_user_by_username(username)
    if user is None:
        return False, "error", "未找到账号"
    if user_member_locked(user):
        return False, "error", "会员凭证已锁定，不能再修改"

    order_no = normalize_order_no(order_no)
    if not is_valid_order_no(order_no):
        return False, "error", "请填写有效的微信支付交易单号"

    ensure_user_permission_schema()
    db = get_user_db()
    try:
        owner = db.execute(
            f"""
            SELECT name FROM user_info
            WHERE {MEMBER_ORDER_NO_COLUMN} = ?
              AND name != ?
              AND {ASSOCIATION_ROLE_COLUMN} IN ('协会玩家', '核心玩家', '管理员')
            """,
            (order_no, username),
        ).fetchone()
    finally:
        db.close()

    if owner:
        _save_pending_order(username, "", "该订单号已被核销，请更换凭证")
        return False, "used", "该订单号已被核销，请更换凭证"

    result = _try_redeem_for_user(username, order_no)
    if result == "granted":
        return True, "granted", "验证通过，会员资质已生效"
    if result == "used":
        return False, "used", "该订单号已被核销，请更换凭证"

    _save_pending_order(username, order_no)
    return True, "pending", "订单号已保存，账单同步后将自动审核"
