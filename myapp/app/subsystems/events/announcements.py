"""待发到微信群的活动公告队列。WechatRobot 拉取后回告删除。"""

import hmac
import math
from datetime import datetime

from app.models.config import get_config
from app.subsystems.events.chat import (
    KIND_FIXED,
    KIND_FREE,
    _organizer_wechat,
    post_announcement_message,
)

SOURCE_CREATED = "event_created"
SOURCE_UPDATED = "event_updated"
SOURCE_ORGANIZER = "organizer"
EVENT_SOURCES = (SOURCE_CREATED, SOURCE_UPDATED)
COOLDOWN_SECONDS = 60 * 60
SIGNUP_URL = "https://yanice.online/lightboard"
_TIME_FMT = "%Y-%m-%d %H:%M:%S"


def ensure_announcement_schema(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            event_kind TEXT NOT NULL,
            event_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pending_announcements_event
        ON pending_announcements (event_kind, event_id)
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS announcement_cooldowns (
            event_kind TEXT NOT NULL,
            event_id INTEGER NOT NULL,
            last_at TEXT NOT NULL,
            PRIMARY KEY (event_kind, event_id)
        )
        """
    )


def robot_authorized(authorization_header):
    expected = _configured_token()
    if not expected:
        return False
    header = authorization_header or ""
    prefix = "Bearer "
    if not header.startswith(prefix):
        return False
    provided = header[len(prefix):].strip()
    if not provided:
        return False
    return hmac.compare_digest(provided, expected)


def enqueue_event_created(event_kind, event_id):
    _enqueue_event(event_kind, event_id, SOURCE_CREATED, replace=False)


def enqueue_event_updated(event_kind, event_id):
    """未发出的活动公告只保留一条：已有则刷新正文并保持来源，否则记为更新。"""
    _enqueue_event(event_kind, event_id, SOURCE_UPDATED, replace=True)


def clear_pending_announcements(event_kind, event_id):
    db = _db()
    db.execute(
        "DELETE FROM pending_announcements WHERE event_kind = ? AND event_id = ?",
        (event_kind, int(event_id)),
    )
    db.commit()


def list_pending_announcements():
    db = _db()
    rows = db.execute(
        """
        SELECT id, source, event_kind, event_id, text, created_at
        FROM pending_announcements
        ORDER BY id ASC
        """
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "source": row["source"],
            "event_kind": row["event_kind"],
            "event_id": int(row["event_id"]),
            "text": row["text"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def remove_sent_announcement(announcement_id):
    db = _db()
    cur = db.execute(
        "DELETE FROM pending_announcements WHERE id = ?",
        (int(announcement_id),),
    )
    db.commit()
    return cur.rowcount > 0


def cooldown_remaining_seconds(event_kind, event_id):
    db = _db()
    row = db.execute(
        """
        SELECT last_at FROM announcement_cooldowns
        WHERE event_kind = ? AND event_id = ?
        """,
        (event_kind, int(event_id)),
    ).fetchone()
    if row is None:
        return 0
    try:
        last = datetime.strptime(row["last_at"], _TIME_FMT)
    except ValueError:
        return 0
    remain = COOLDOWN_SECONDS - (datetime.now() - last).total_seconds()
    if remain <= 0:
        return 0
    return int(math.ceil(remain))


def publish_organizer_announcement(event_kind, event_id, room_id, sender, note):
    """写入聊天室，并单独入队一条组织者公告。冷却按活动计算。"""
    text = (note or "").strip()
    if not text:
        return False, "请输入公告内容。", None, 0
    remain = cooldown_remaining_seconds(event_kind, event_id)
    if remain > 0:
        minutes = max(1, math.ceil(remain / 60))
        return False, f"公告冷却中，请 {minutes} 分钟后再试。", None, remain
    event = _load_event(event_kind, event_id)
    if event is None:
        return False, "活动不存在。", None, 0
    ok, err, message = post_announcement_message(room_id, sender, text)
    if not ok:
        return False, err or "发送失败。", None, 0
    now = datetime.now().strftime(_TIME_FMT)
    db = _db()
    db.execute(
        """
        INSERT INTO pending_announcements (source, event_kind, event_id, text, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            SOURCE_ORGANIZER,
            event_kind,
            int(event_id),
            _organizer_text(event, text),
            now,
        ),
    )
    db.execute(
        """
        INSERT INTO announcement_cooldowns (event_kind, event_id, last_at)
        VALUES (?, ?, ?)
        ON CONFLICT(event_kind, event_id) DO UPDATE SET last_at = excluded.last_at
        """,
        (event_kind, int(event_id), now),
    )
    db.commit()
    return True, None, message, COOLDOWN_SECONDS


def _enqueue_event(event_kind, event_id, source, *, replace):
    if event_kind not in (KIND_FREE, KIND_FIXED):
        return
    event = _load_event(event_kind, event_id)
    if event is None:
        return
    text = _event_text(event, event_kind, source if not replace else SOURCE_UPDATED)
    db = _db()
    now = datetime.now().strftime(_TIME_FMT)
    if replace:
        row = db.execute(
            """
            SELECT id, source FROM pending_announcements
            WHERE event_kind = ? AND event_id = ? AND source IN (?, ?)
            ORDER BY id DESC
            LIMIT 1
            """,
            (event_kind, int(event_id), SOURCE_CREATED, SOURCE_UPDATED),
        ).fetchone()
        if row is not None:
            kept = row["source"] if row["source"] in EVENT_SOURCES else SOURCE_UPDATED
            refreshed = _event_text(event, event_kind, kept)
            db.execute(
                """
                UPDATE pending_announcements
                SET text = ?, created_at = ?
                WHERE id = ?
                """,
                (refreshed, now, int(row["id"])),
            )
            db.commit()
            return
        text = _event_text(event, event_kind, SOURCE_UPDATED)
    db.execute(
        """
        INSERT INTO pending_announcements (source, event_kind, event_id, text, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (source if not replace else SOURCE_UPDATED, event_kind, int(event_id), text, now),
    )
    db.commit()


def _event_text(event, event_kind, source):
    title = "【新活动】" if source == SOURCE_CREATED else "【活动更新】"
    name = (event.get("name") or "").strip()
    if event_kind == KIND_FIXED:
        from app.subsystems.events.dbutil import FIXED_GATHERING_LABEL

        event_type = FIXED_GATHERING_LABEL
    else:
        event_type = (event.get("event_type") or "").strip() or "其他"
    lines = [f"{title}{name}", f"类型：{event_type}"]
    start = _display_time(event.get("starttime"))
    if start:
        lines.append(f"时间：{start}")
    location = (event.get("location") or "").strip()
    if location:
        lines.append(f"地点：{location}")
    players = _player_line(event)
    if players:
        lines.append(players)
    lines.append(_organizer_line(event))
    description = (event.get("description") or "").strip()
    if description:
        lines.append(f"说明：{description}")
    lines.append(f"报名：{SIGNUP_URL}")
    return "\n".join(lines)


def _organizer_text(event, note):
    lines = [f"【公告】{(event.get('name') or '').strip()}"]
    start = _display_time(event.get("starttime"))
    if start:
        lines.append(f"时间：{start}")
    location = (event.get("location") or "").strip()
    if location:
        lines.append(f"地点：{location}")
    lines.append(note.strip())
    return "\n".join(lines)


def _organizer_line(event):
    name = (event.get("inviter") or "").strip() or "未知"
    wechat = _organizer_wechat(name)
    if wechat:
        return f"组织者：{name}（微信：{wechat}）"
    return f"组织者：{name}"


def _player_line(event):
    minimum = _as_int(event.get("minplayer"))
    maximum = _as_int(event.get("maxplayer"))
    if minimum is not None and maximum is not None:
        return f"人数：{minimum}-{maximum}"
    if maximum is not None:
        return f"人数：最多 {maximum} 人"
    if minimum is not None:
        return f"人数：至少 {minimum} 人"
    return ""


def _as_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _display_time(value):
    return (value or "").replace("T", " ").strip()


def _load_event(event_kind, event_id):
    db = _db()
    if event_kind == KIND_FREE:
        row = db.execute("SELECT * FROM events WHERE id = ?", (int(event_id),)).fetchone()
    elif event_kind == KIND_FIXED:
        row = db.execute(
            "SELECT * FROM fixed_events WHERE id = ?",
            (int(event_id),),
        ).fetchone()
    else:
        return None
    if row is None:
        return None
    return dict(row)


def _configured_token():
    try:
        raw = get_config("wechat_robot_token")
    except Exception:
        return ""
    if raw is None:
        return ""
    return str(raw).strip()


def _db():
    from app.subsystems.events.dbutil import get_db

    return get_db()
