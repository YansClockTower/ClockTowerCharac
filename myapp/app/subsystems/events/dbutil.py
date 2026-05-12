import os
import random
import sqlite3
from datetime import datetime

from flask import g

from app.models.config import get_config

EVENT_TYPE_VALUES = ("轻桌游聚会", "德州扑克", "德式桌游", "狼人杀", "血染钟楼", "其他")

# 活动板「轻桌游聚会」书签对应的类型，须与 EVENT_TYPE_VALUES 中该项一致
BROWSE_BOOKMARK_LIGHT_EVENT_TYPE = "轻桌游聚会"

# signcode 置为该值表示活动已归档（结束），不再允许报名/编辑等操作
ARCHIVED_SIGNCODE = "0"


def is_event_archived(event) -> bool:
    """根据 events 行 dict 判断是否为已归档活动。"""
    if not event:
        return False
    sc = event.get("signcode")
    if sc is None:
        return False
    return str(sc).strip() == ARCHIVED_SIGNCODE


def archive_event(event_id):
    """将活动标记为已归档（不删除记录与报名）。"""
    db = get_db()
    db.execute("UPDATE events SET signcode = ? WHERE id = ?", (ARCHIVED_SIGNCODE, event_id))
    db.commit()


def _events_db_path():
    if get_config("development"):
        base_path = get_config("database_path_dev")
    else:
        base_path = get_config("database_path")
    return os.path.join(base_path, "events.sqlite")


def get_db():
    db = getattr(g, "_events_db", None)
    if db is None:
        db = g._events_db = sqlite3.connect(_events_db_path())
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        _ensure_events_schema(db)
    return db


def _ensure_events_schema(db):
    columns = db.execute("PRAGMA table_info(events)").fetchall()
    column_names = {row["name"] for row in columns}
    if "event_type" not in column_names:
        db.execute("ALTER TABLE events ADD COLUMN event_type TEXT DEFAULT '其他'")
    db.execute(
        f"""
        UPDATE events
        SET event_type = CASE
            WHEN event_type IN ({",".join(["?"] * len(EVENT_TYPE_VALUES))}) THEN event_type
            ELSE '其他'
        END
        """,
        EVENT_TYPE_VALUES,
    )
    db.commit()


def close_db(e=None):
    db = getattr(g, "_events_db", None)
    if db is not None:
        db.close()
        g._events_db = None


def get_all_events(current_user):
    db = get_db()
    events_with_attendees = db.execute(
        """
        SELECT
            e.*,
            GROUP_CONCAT(a.player) AS attendee_list,
            GROUP_CONCAT(a.player || '::' || IFNULL(a.note, '') || '::' || IFNULL(a.friend, '0')  || '::' || IFNULL(a.signed, '0')) AS player_notes_raw,
            EXISTS(SELECT 1 FROM attendinfo WHERE eventid = e.id AND player = ?) AS is_attending,
            (SELECT IFNULL(note, '') || '::' || IFNULL(friend, '0') || '::' || IFNULL(signed, '0') FROM attendinfo WHERE eventid = e.id AND player = ?) AS user_info_raw
        FROM events e
        LEFT JOIN attendinfo a ON e.id = a.eventid
        GROUP BY e.id
        ORDER BY e.id DESC
        """,
        (current_user, current_user),
    ).fetchall()

    events_list = []
    for event in events_with_attendees:
        event_dict = dict(event)
        attend_count = 0
        if event_dict["attendee_list"]:
            event_dict["attendee_list"] = event_dict["attendee_list"].split(",")
        else:
            event_dict["attendee_list"] = []

        player_notes = []
        raw_string = event_dict.pop("player_notes_raw")
        if raw_string:
            for player_note_pair in raw_string.split(","):
                parts = player_note_pair.split("::", 3)
                player_notes.append(
                    {
                        "player": parts[0],
                        "note": parts[1] if len(parts) > 1 else "",
                        "friends": int(parts[2]) if len(parts) > 2 else 0,
                        "signed": int(parts[3]) if len(parts) > 3 else 0,
                    }
                )
                attend_count += 1 + (int(parts[2]) if len(parts) > 2 else 0)

        event_dict["attendee_count"] = attend_count
        event_dict["attendee_notes"] = player_notes

        user_info_raw = event_dict.pop("user_info_raw")
        if user_info_raw:
            user_parts = user_info_raw.split("::", 2)
            event_dict["user_note"] = user_parts[0] if len(user_parts) > 0 else ""
            event_dict["user_friends"] = int(user_parts[1]) if len(user_parts) > 1 else 0
            event_dict["user_signed"] = int(user_parts[2]) if len(user_parts) > 2 else 0
        else:
            event_dict["user_note"] = None
            event_dict["user_friends"] = 0
            event_dict["user_signed"] = 0

        event_dict["starttime_obj"] = datetime.strptime(event_dict["starttime"], "%Y-%m-%dT%H:%M")
        event_dict["locktime_obj"] = datetime.strptime(event_dict["locktime"], "%Y-%m-%dT%H:%M")
        starttime = datetime.strptime(event_dict["starttime"], "%Y-%m-%dT%H:%M")
        locktime = datetime.strptime(event_dict["locktime"], "%Y-%m-%dT%H:%M")
        event_dict["locktime_select"] = str(int((starttime - locktime).seconds / 3600))
        events_list.append(event_dict)
    return events_list


def apply_event_list_filters(events, *, current_user, now, filters):
    """
    按条件筛选已展开的活动列表（get_all_events 的返回值）。

    filters 为 dict，键均可缺省；空 dict 表示不过滤。
      event_type: str，须与 EVENT_TYPE_VALUES 中某项一致
      my_activities_only: bool，仅保留「我组织的」或「我已报名的」活动
    """
    if not filters:
        return list(events)
    out = []
    for e in events:
        et = filters.get("event_type")
        if et and (e.get("event_type") or "其他") != et:
            continue
        if filters.get("my_activities_only"):
            if e.get("inviter") != current_user and not e.get("is_attending"):
                continue
        out.append(e)
    return out


def get_event_by_id(event_id):
    db = get_db()
    row = db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        return None
    event_dict = dict(row)
    event_dict["starttime_obj"] = datetime.strptime(event_dict["starttime"], "%Y-%m-%dT%H:%M")
    event_dict["locktime_obj"] = datetime.strptime(event_dict["locktime"], "%Y-%m-%dT%H:%M")
    starttime = datetime.strptime(event_dict["starttime"], "%Y-%m-%dT%H:%M")
    locktime = datetime.strptime(event_dict["locktime"], "%Y-%m-%dT%H:%M")
    event_dict["locktime_select"] = str(int((starttime - locktime).seconds / 3600))
    return event_dict


def get_event_attendance_records(event_id):
    db = get_db()
    rows = db.execute(
        """
        SELECT player, IFNULL(friend, 0) AS friend, IFNULL(signed, 0) AS signed
        FROM attendinfo
        WHERE eventid = ?
        """,
        (event_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def create_event(data):
    db = get_db()
    db.execute(
        """
        INSERT INTO events
            (name, inviter, location, starttime, locktime, description, minplayer, maxplayer, signcode, event_type)
        VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["name"],
            data["inviter"],
            data["location"],
            data["starttime"],
            data["locktime"],
            data["description"],
            data["minplayer"],
            data["maxplayer"],
            str(random.randint(0, 9999)).zfill(4),
            data["event_type"],
        ),
    )
    db.commit()


def update_event(event_id, data):
    db = get_db()
    db.execute(
        """
        UPDATE events
        SET name = ?, location = ?, starttime = ?, locktime = ?, description = ?, minplayer = ?, maxplayer = ?, event_type = ?
        WHERE id = ?
        """,
        (
            data["name"],
            data["location"],
            data["starttime"],
            data["locktime"],
            data["description"],
            data["minplayer"],
            data["maxplayer"],
            data["event_type"],
            event_id,
        ),
    )
    db.commit()


def delete_event(event_id):
    db = get_db()
    db.execute("DELETE FROM events WHERE id = ?", (event_id,))
    db.commit()


def join_event(event_id, player):
    db = get_db()
    row = db.execute("SELECT signcode FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        return False, "活动不存在。"
    if is_event_archived(dict(row)):
        return False, "活动已归档，无法报名。"
    try:
        db.execute("INSERT INTO attendinfo (eventid, player) VALUES (?, ?)", (event_id, player))
        db.commit()
        return True, None
    except sqlite3.IntegrityError:
        return False, "您已经报名了此活动。"


def signin_event(event_id, player, code):
    db = get_db()
    row = db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        return False, "活动不存在。"
    ev = dict(row)
    if is_event_archived(ev):
        return False, "活动已归档，无法签到。"
    expected_code = ev["signcode"]
    if expected_code != code:
        return False, "签到码错误！"

    try:
        db.execute(
            """
            UPDATE attendinfo
            SET signed = 1
            WHERE eventid = ? AND player = ?;
            """,
            (event_id, player),
        )
        db.commit()
        return True, None
    except Exception:
        return False, "系统内部错误。"


def note_event(event_id, player, note):
    db = get_db()
    row = db.execute("SELECT signcode FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None or is_event_archived(dict(row)):
        return False, "活动已归档或不存在。"
    try:
        db.execute(
            """
            UPDATE attendinfo
            SET note = ?
            WHERE eventid = ? AND player = ?;
            """,
            (note, event_id, player),
        )
        db.commit()
        return True, None
    except Exception:
        return False, "出错了"


def friend_event(event_id, player, friend):
    db = get_db()
    row = db.execute("SELECT signcode FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None or is_event_archived(dict(row)):
        return False, "活动已归档或不存在。"
    try:
        db.execute(
            """
            UPDATE attendinfo
            SET friend = ?
            WHERE eventid = ? AND player = ?;
            """,
            (friend, event_id, player),
        )
        db.commit()
        return True, None
    except Exception:
        return False, "出错了"


def leave_event(event_id, player):
    db = get_db()
    row = db.execute("SELECT signcode FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None or is_event_archived(dict(row)):
        return False
    cursor = db.execute("DELETE FROM attendinfo WHERE eventid = ? AND player = ?", (event_id, player))
    db.commit()
    return cursor.rowcount > 0
