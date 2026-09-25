"""组织者黑名单：被拉黑的玩家不能报名该用户组织的活动。"""

from __future__ import annotations

from datetime import datetime

from app.models.database import get_user_db
from app.subsystems.events.dbutil import ARCHIVED_SIGNCODE
from app.user.email_codes import find_user_by_username

JOIN_BLOCKED_REASON = "你在该活动组织者的黑名单中，无法报名。"


def ensure_blacklist_schema() -> None:
    db = get_user_db()
    try:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_blacklist (
                owner_id INTEGER NOT NULL,
                blocked_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (owner_id, blocked_id)
            )
            """
        )
        db.commit()
    finally:
        db.close()


def is_blocked(owner_id: int, blocked_id: int) -> bool:
    ensure_blacklist_schema()
    db = get_user_db()
    try:
        row = db.execute(
            """
            SELECT 1 FROM user_blacklist
            WHERE owner_id = ? AND blocked_id = ?
            """,
            (int(owner_id), int(blocked_id)),
        ).fetchone()
        return row is not None
    finally:
        db.close()


def organizer_blocks_player(organizer_name, player_name) -> bool:
    """组织者的黑名单是否包含这名玩家。按用户名对应账号。"""
    organizer = (organizer_name or "").strip()
    player = (player_name or "").strip()
    if not organizer or not player or organizer == player:
        return False
    owner = find_user_by_username(organizer)
    blocked = find_user_by_username(player)
    if not owner or not blocked:
        return False
    if int(owner["id"]) == int(blocked["id"]):
        return False
    return is_blocked(owner["id"], blocked["id"])


def _kick_from_organizer_events(organizer_name: str, player_name: str) -> int:
    """把玩家移出该组织者尚未归档的活动。返回移出的活动场数。"""
    from app.subsystems.events.dbutil import get_db, leave_event
    from app.subsystems.events.fixed_dbutil import leave_table

    organizer = organizer_name.strip()
    player = player_name.strip()
    removed = 0
    db = get_db()
    free_rows = db.execute(
        """
        SELECT e.id
        FROM events e
        JOIN attendinfo a ON a.eventid = e.id
        WHERE e.inviter = ? AND a.player = ? AND e.signcode != ?
        """,
        (organizer, player, ARCHIVED_SIGNCODE),
    ).fetchall()
    fixed_rows = db.execute(
        """
        SELECT a.table_id
        FROM fixed_table_attend a
        JOIN fixed_events e ON e.id = a.fixed_event_id
        WHERE e.inviter = ? AND a.player = ? AND e.signcode != ?
        """,
        (organizer, player, ARCHIVED_SIGNCODE),
    ).fetchall()

    for row in free_rows:
        if leave_event(int(row["id"]), player):
            removed += 1
    for row in fixed_rows:
        ok, _err = leave_table(int(row["table_id"]), player, force=True)
        if ok:
            removed += 1
    return removed


def add_to_blacklist(owner_id: int, blocked_id: int, organizer_name: str, player_name: str) -> tuple[bool, str]:
    if int(owner_id) == int(blocked_id):
        return False, "不能把自己加入黑名单。"
    ensure_blacklist_schema()
    db = get_user_db()
    try:
        existing = db.execute(
            "SELECT 1 FROM user_blacklist WHERE owner_id = ? AND blocked_id = ?",
            (int(owner_id), int(blocked_id)),
        ).fetchone()
        if existing:
            return False, "对方已在你的黑名单中。"
        db.execute(
            """
            INSERT INTO user_blacklist (owner_id, blocked_id, created_at)
            VALUES (?, ?, ?)
            """,
            (int(owner_id), int(blocked_id), datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        db.commit()
    finally:
        db.close()

    removed = _kick_from_organizer_events(organizer_name, player_name)
    if removed:
        return True, f"已加入黑名单，并将其移出你组织的 {removed} 场活动。"
    return True, "已加入黑名单。"


def remove_from_blacklist(owner_id: int, blocked_id: int) -> tuple[bool, str]:
    if int(owner_id) == int(blocked_id):
        return False, "不能对自己操作黑名单。"
    ensure_blacklist_schema()
    db = get_user_db()
    try:
        cur = db.execute(
            "DELETE FROM user_blacklist WHERE owner_id = ? AND blocked_id = ?",
            (int(owner_id), int(blocked_id)),
        )
        db.commit()
        if cur.rowcount:
            return True, "已解除黑名单。"
        return False, "对方不在你的黑名单中。"
    finally:
        db.close()
