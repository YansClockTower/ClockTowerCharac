"""活动临时聊天室。自由聚会与固定聚会各一间，用 event_kind 区分撞号的 id。"""

import os
import shutil
import uuid
from datetime import datetime

from app.models.config import get_config

KIND_FREE = "free"
KIND_FIXED = "fixed"
CHAT_KINDS = (KIND_FREE, KIND_FIXED)
MSG_TEXT = "text"
MSG_IMAGE = "image"
MSG_GAME = "game"
MAX_BODY_LEN = 500
MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_EXT = {"jpg", "jpeg", "png", "gif", "webp"}
SYSTEM_SENDER = "系统"
_CONTACT_PATH = "“主页->桌游协会事务->联系我们”"
_BLANK_CONTACTS = {"", "保密", "未填写", "无", "-", "—"}


def ensure_chat_schema(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS event_chat_rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_kind TEXT NOT NULL,
            event_id INTEGER NOT NULL,
            UNIQUE(event_kind, event_id)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS event_chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            sender TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            msg_type TEXT NOT NULL DEFAULT 'text',
            FOREIGN KEY(room_id) REFERENCES event_chat_rooms(id) ON DELETE CASCADE
        )
        """
    )
    columns = {row["name"] for row in db.execute("PRAGMA table_info(event_chat_messages)").fetchall()}
    if "msg_type" not in columns:
        db.execute(
            "ALTER TABLE event_chat_messages ADD COLUMN msg_type TEXT NOT NULL DEFAULT 'text'"
        )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_event_chat_messages_room
        ON event_chat_messages (room_id, id)
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS event_chat_reads (
            room_id INTEGER NOT NULL,
            player TEXT NOT NULL,
            last_read_message_id INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (room_id, player),
            FOREIGN KEY(room_id) REFERENCES event_chat_rooms(id) ON DELETE CASCADE
        )
        """
    )
    _backfill_rooms(db)
    _seed_system_notices(db)


def open_room(db, kind, event_id, inviter):
    """创建聊天室。新房间由系统发一句联系说明，并把组织者记为参与者。"""
    db.execute(
        """
        INSERT OR IGNORE INTO event_chat_rooms (event_kind, event_id)
        VALUES (?, ?)
        """,
        (kind, int(event_id)),
    )
    room_id = _room_id(db, kind, event_id)
    if room_id is None:
        return None
    _insert_system_notice(db, room_id, inviter)
    if (inviter or "").strip():
        _ensure_participant(db, room_id, inviter.strip())
    return room_id


def close_room(db, kind, event_id):
    room_id = _room_id(db, kind, event_id)
    db.execute(
        "DELETE FROM event_chat_rooms WHERE event_kind = ? AND event_id = ?",
        (kind, int(event_id)),
    )
    if room_id is not None:
        _delete_room_images(room_id)


def note_joined(db, kind, event_id, player):
    """报名时写入已读行。已有行不改游标，避免把未读清掉。"""
    player = (player or "").strip()
    if not player:
        return
    room_id = _room_id(db, kind, event_id)
    if room_id is None:
        return
    _ensure_participant(db, room_id, player)


def note_left(db, kind, event_id, player):
    """退出报名则移出聊天列表。组织者仍保留。"""
    player = (player or "").strip()
    if not player:
        return
    if player == (_inviter(db, kind, event_id) or ""):
        return
    room_id = _room_id(db, kind, event_id)
    if room_id is None:
        return
    db.execute(
        "DELETE FROM event_chat_reads WHERE room_id = ? AND player = ?",
        (room_id, player),
    )


def list_rooms_for(player, *, is_admin=False):
    """参与者看到自己的聊天室；管理员额外看到所有未归档活动的聊天室。"""
    db = _db()
    rows = db.execute(
        """
        SELECT
            r.id AS room_id,
            r.event_kind AS event_kind,
            r.event_id AS event_id,
            CASE r.event_kind WHEN ? THEN e.name ELSE f.name END AS event_name,
            CASE r.event_kind WHEN ? THEN e.starttime ELSE f.starttime END AS starttime,
            rd.last_read_message_id AS last_read_message_id,
            (
                SELECT CASE
                    WHEN COALESCE(m.msg_type, 'text') = 'image' THEN '[图片]'
                    WHEN COALESCE(m.msg_type, 'text') = 'game' THEN '[桌游]'
                    ELSE m.body
                END
                FROM event_chat_messages m
                WHERE m.room_id = r.id ORDER BY m.id DESC LIMIT 1
            ) AS last_body,
            (
                SELECT m.created_at FROM event_chat_messages m
                WHERE m.room_id = r.id ORDER BY m.id DESC LIMIT 1
            ) AS last_at,
            (
                SELECT COALESCE(MAX(m.id), 0) FROM event_chat_messages m
                WHERE m.room_id = r.id
            ) AS last_id
        FROM event_chat_rooms r
        LEFT JOIN event_chat_reads rd
            ON rd.room_id = r.id AND rd.player = ?
        LEFT JOIN events e
            ON r.event_kind = ? AND e.id = r.event_id
            AND TRIM(COALESCE(e.signcode, '')) != '0'
        LEFT JOIN fixed_events f
            ON r.event_kind = ? AND f.id = r.event_id
            AND TRIM(COALESCE(f.signcode, '')) != '0'
        WHERE (
            (r.event_kind = ? AND e.id IS NOT NULL)
            OR (r.event_kind = ? AND f.id IS NOT NULL)
          )
          AND (? OR rd.player IS NOT NULL)
        """,
        (
            KIND_FREE,
            KIND_FREE,
            player,
            KIND_FREE,
            KIND_FIXED,
            KIND_FREE,
            KIND_FIXED,
            1 if is_admin else 0,
        ),
    ).fetchall()
    rooms = []
    for row in rows:
        item = dict(row)
        last_id = int(item["last_id"] or 0)
        # 管理员尚未进入过的房间不计入未读，避免顶栏信件图标被刷爆
        if item["last_read_message_id"] is None:
            last_read = last_id
        else:
            last_read = int(item["last_read_message_id"] or 0)
        item["unread"] = last_id > last_read
        item["preview"] = _snippet(item.get("last_body"))
        item["time_label"] = format_chat_time(item.get("last_at") or "")
        item["sort_key"] = item.get("last_at") or item.get("starttime") or ""
        rooms.append(item)
    rooms.sort(key=lambda r: r["sort_key"], reverse=True)
    return rooms


def has_unread(player, *, is_admin=False):
    """未读只统计本人已在聊天室名单里的房间（管理员也一样）。"""
    del is_admin
    db = _db()
    row = db.execute(
        """
        SELECT 1
        FROM event_chat_reads rd
        JOIN event_chat_rooms r ON r.id = rd.room_id
        LEFT JOIN events e
            ON r.event_kind = ? AND e.id = r.event_id
            AND TRIM(COALESCE(e.signcode, '')) != '0'
        LEFT JOIN fixed_events f
            ON r.event_kind = ? AND f.id = r.event_id
            AND TRIM(COALESCE(f.signcode, '')) != '0'
        WHERE rd.player = ?
          AND (
            (r.event_kind = ? AND e.id IS NOT NULL)
            OR (r.event_kind = ? AND f.id IS NOT NULL)
          )
          AND EXISTS (
            SELECT 1 FROM event_chat_messages m
            WHERE m.room_id = r.id AND m.id > rd.last_read_message_id
          )
        LIMIT 1
        """,
        (KIND_FREE, KIND_FIXED, player, KIND_FREE, KIND_FIXED),
    ).fetchone()
    return row is not None


def get_open_room(kind, event_id):
    """未归档活动的聊天室。不存在或已关闭则返回 None。"""
    if kind not in CHAT_KINDS:
        return None
    db = _db()
    room_id = _room_id(db, kind, event_id)
    if room_id is None:
        return None
    event = _event_row(db, kind, event_id)
    if event is None or _is_archived_signcode(event["signcode"]):
        return None
    return {
        "id": room_id,
        "event_kind": kind,
        "event_id": int(event_id),
        "name": event["name"],
        "inviter": event["inviter"],
    }


def is_participant(room_id, player):
    db = _db()
    row = db.execute(
        "SELECT 1 FROM event_chat_reads WHERE room_id = ? AND player = ?",
        (int(room_id), player),
    ).fetchone()
    return row is not None


def can_access_room(room_id, player, *, is_admin=False):
    """报名者、组织者（已有读游标）或管理员可进入未关闭聊天室。"""
    if is_participant(room_id, player):
        return True
    if not is_admin:
        return False
    db = _db()
    row = db.execute(
        "SELECT event_kind, event_id FROM event_chat_rooms WHERE id = ?",
        (int(room_id),),
    ).fetchone()
    if row is None:
        return False
    return get_open_room(row["event_kind"], row["event_id"]) is not None


def ensure_viewer(room_id, player):
    """管理员首次进入时写入读游标，便于列表与已读统计。"""
    db = _db()
    _ensure_participant(db, room_id, player)
    db.commit()


def list_messages(room_id, after_id=0, limit=500):
    db = _db()
    after_id = max(0, int(after_id or 0))
    rows = db.execute(
        """
        SELECT id, room_id, sender, body, created_at, COALESCE(msg_type, 'text') AS msg_type
        FROM event_chat_messages
        WHERE room_id = ? AND id > ?
        ORDER BY id ASC
        LIMIT ?
        """,
        (int(room_id), after_id, int(limit)),
    ).fetchall()
    return [dict(row) for row in rows]


def get_message(message_id):
    db = _db()
    row = db.execute(
        """
        SELECT id, room_id, sender, body, created_at, COALESCE(msg_type, 'text') AS msg_type
        FROM event_chat_messages
        WHERE id = ?
        """,
        (int(message_id),),
    ).fetchone()
    return dict(row) if row else None


def latest_message_id(room_id):
    db = _db()
    return _latest_message_id(db, room_id)


def mark_read(room_id, player):
    db = _db()
    tip = _latest_message_id(db, room_id)
    db.execute(
        """
        UPDATE event_chat_reads
        SET last_read_message_id = ?
        WHERE room_id = ? AND player = ? AND last_read_message_id < ?
        """,
        (tip, int(room_id), player, tip),
    )
    db.commit()
    return tip


def post_message(room_id, sender, body):
    text = (body or "").strip()
    if not text:
        return False, "请输入消息。", None
    if len(text) > MAX_BODY_LEN:
        return False, f"消息过长（最多 {MAX_BODY_LEN} 字）。", None
    return _insert_message(room_id, sender, text, MSG_TEXT)


def post_image(room_id, sender, file_storage):
    if file_storage is None or not getattr(file_storage, "filename", None):
        return False, "请选择图片。", None
    filename = (file_storage.filename or "").strip()
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_IMAGE_EXT:
        return False, "仅支持 jpg / png / gif / webp。", None
    data = file_storage.read(MAX_IMAGE_BYTES + 1)
    if not data:
        return False, "图片为空。", None
    if len(data) > MAX_IMAGE_BYTES:
        return False, "图片过大（最多 5MB）。", None
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    dest_dir = _room_image_dir(room_id)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, stored_name)
    with open(dest_path, "wb") as fh:
        fh.write(data)
    return _insert_message(room_id, sender, stored_name, MSG_IMAGE)


def post_game(room_id, sender, game_id):
    from app.subsystems.boardgames import api as boardgames_api

    try:
        gid = int(game_id)
    except (TypeError, ValueError):
        return False, "请选择有效的桌游。", None
    game = boardgames_api.get_game_by_id(gid)
    if not game:
        return False, "桌游不存在。", None
    return _insert_message(room_id, sender, str(gid), MSG_GAME)


def image_file_path(message):
    if not message or (message.get("msg_type") or MSG_TEXT) != MSG_IMAGE:
        return None
    name = os.path.basename((message.get("body") or "").strip())
    if not name or name != (message.get("body") or "").strip():
        return None
    path = os.path.join(_room_image_dir(message["room_id"]), name)
    if not os.path.isfile(path):
        return None
    return path


def format_chat_time(value):
    raw = (value or "").strip()
    if not raw:
        return ""
    dt = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            dt = datetime.strptime(raw[:19] if fmt.startswith("%Y-%m-%d ") else raw[:16], fmt)
            break
        except ValueError:
            continue
    if dt is None:
        return raw
    now = datetime.now()
    if dt.date() == now.date():
        return dt.strftime("%H:%M")
    if dt.year == now.year:
        return dt.strftime("%m-%d %H:%M")
    return dt.strftime("%Y-%m-%d %H:%M")


def _insert_message(room_id, sender, body, msg_type):
    db = _db()
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = db.execute(
        """
        INSERT INTO event_chat_messages (room_id, sender, body, created_at, msg_type)
        VALUES (?, ?, ?, ?, ?)
        """,
        (int(room_id), sender, body, created_at, msg_type),
    )
    db.commit()
    message = {
        "id": int(cur.lastrowid),
        "room_id": int(room_id),
        "sender": sender,
        "body": body,
        "created_at": created_at,
        "msg_type": msg_type,
    }
    mark_read(room_id, sender)
    return True, None, message


def _insert_system_notice(db, room_id, inviter):
    if _latest_message_id(db, room_id) > 0:
        return
    wechat = _organizer_wechat(inviter)
    if wechat:
        body = (
            f"如有问题可联系组局者（微信）：{wechat}，"
            f"或前往{_CONTACT_PATH}寻找管理员。"
        )
    else:
        body = f"如有问题可前往{_CONTACT_PATH}寻找管理员。"
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        """
        INSERT INTO event_chat_messages (room_id, sender, body, created_at, msg_type)
        VALUES (?, ?, ?, ?, ?)
        """,
        (int(room_id), SYSTEM_SENDER, body, created_at, MSG_TEXT),
    )
    tip = _latest_message_id(db, room_id)
    db.execute(
        """
        UPDATE event_chat_reads
        SET last_read_message_id = ?
        WHERE room_id = ? AND last_read_message_id < ?
        """,
        (tip, int(room_id), tip),
    )


def _seed_system_notices(db):
    """给还没有任何消息的聊天室补上系统说明（只补一次）。"""
    rows = db.execute(
        """
        SELECT r.id AS room_id, r.event_kind AS event_kind, r.event_id AS event_id
        FROM event_chat_rooms r
        WHERE NOT EXISTS (
            SELECT 1 FROM event_chat_messages m WHERE m.room_id = r.id
        )
        """
    ).fetchall()
    for row in rows:
        inviter = _inviter(db, row["event_kind"], row["event_id"])
        _insert_system_notice(db, row["room_id"], inviter)


def _organizer_wechat(inviter):
    name = (inviter or "").strip()
    if not name:
        return ""
    try:
        from app.identity.permissions import ensure_user_permission_schema
        from app.models.database import get_user_db

        ensure_user_permission_schema()
        user_db = get_user_db()
    except Exception:
        return ""
    try:
        row = user_db.execute(
            "SELECT contact_info FROM user_info WHERE name = ?",
            (name,),
        ).fetchone()
    finally:
        user_db.close()
    if row is None:
        return ""
    raw = (row["contact_info"] or "").strip()
    return "" if raw in _BLANK_CONTACTS else raw


def _snippet(body):
    text = " ".join((body or "").split())
    if not text:
        return "还没有消息"
    if len(text) > 36:
        return text[:36] + "…"
    return text


def _db():
    from app.subsystems.events.dbutil import get_db

    return get_db()


def _chat_root():
    if get_config("development"):
        base_path = get_config("database_path_dev")
    else:
        base_path = get_config("database_path")
    return os.path.join(base_path, "chat_images")


def _room_image_dir(room_id):
    return os.path.join(_chat_root(), str(int(room_id)))


def _delete_room_images(room_id):
    path = _room_image_dir(room_id)
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def _table_exists(db, name):
    row = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _room_id(db, kind, event_id):
    row = db.execute(
        "SELECT id FROM event_chat_rooms WHERE event_kind = ? AND event_id = ?",
        (kind, int(event_id)),
    ).fetchone()
    return int(row["id"]) if row else None


def _latest_message_id(db, room_id):
    row = db.execute(
        "SELECT COALESCE(MAX(id), 0) AS m FROM event_chat_messages WHERE room_id = ?",
        (int(room_id),),
    ).fetchone()
    return int(row["m"]) if row else 0


def _ensure_participant(db, room_id, player):
    tip = _latest_message_id(db, room_id)
    db.execute(
        """
        INSERT OR IGNORE INTO event_chat_reads (room_id, player, last_read_message_id)
        VALUES (?, ?, ?)
        """,
        (int(room_id), player, tip),
    )


def _inviter(db, kind, event_id):
    event = _event_row(db, kind, event_id)
    if event is None:
        return ""
    return (event["inviter"] or "").strip()


def _event_row(db, kind, event_id):
    if kind == KIND_FREE:
        if not _table_exists(db, "events"):
            return None
        row = db.execute(
            "SELECT id, name, inviter, signcode FROM events WHERE id = ?",
            (int(event_id),),
        ).fetchone()
    elif kind == KIND_FIXED:
        if not _table_exists(db, "fixed_events"):
            return None
        row = db.execute(
            "SELECT id, name, inviter, signcode FROM fixed_events WHERE id = ?",
            (int(event_id),),
        ).fetchone()
    else:
        return None
    return dict(row) if row else None


def _is_archived_signcode(signcode):
    return str(signcode or "").strip() == "0"


def _backfill_rooms(db):
    if _table_exists(db, "events"):
        rows = db.execute(
            """
            SELECT id, inviter FROM events
            WHERE TRIM(COALESCE(signcode, '')) != '0'
            """
        ).fetchall()
        for row in rows:
            open_room(db, KIND_FREE, row["id"], row["inviter"])
            if _table_exists(db, "attendinfo"):
                players = db.execute(
                    "SELECT player FROM attendinfo WHERE eventid = ?",
                    (row["id"],),
                ).fetchall()
                for player in players:
                    note_joined(db, KIND_FREE, row["id"], player["player"])
    if _table_exists(db, "fixed_events"):
        rows = db.execute(
            """
            SELECT id, inviter FROM fixed_events
            WHERE TRIM(COALESCE(signcode, '')) != '0'
            """
        ).fetchall()
        for row in rows:
            open_room(db, KIND_FIXED, row["id"], row["inviter"])
            if _table_exists(db, "fixed_table_attend"):
                players = db.execute(
                    """
                    SELECT DISTINCT player FROM fixed_table_attend
                    WHERE fixed_event_id = ?
                    """,
                    (row["id"],),
                ).fetchall()
                for player in players:
                    note_joined(db, KIND_FIXED, row["id"], player["player"])
