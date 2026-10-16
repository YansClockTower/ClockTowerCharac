import os
import random
import sqlite3
from datetime import datetime, timedelta

from flask import g

from app.models.config import get_config
from app.subsystems.events.chat import (
    KIND_FREE,
    close_room,
    ensure_chat_schema,
    note_joined,
    note_left,
    open_room,
)

# 含历史「布鸽桌游活动」以便旧自由聚会记录归一化；新建自由聚会勿再用该类型
EVENT_TYPE_VALUES = (
    "轻桌游聚会",
    "布鸽桌游活动",
    "德州扑克",
    "德式桌游",
    "狼人杀",
    "阿瓦隆",
    "血染钟楼",
    "TRPG(跑团)",
    "其他",
)
# 自由聚会可选类型（布鸽改为固定聚会模式）
FREE_EVENT_TYPE_VALUES = (
    "轻桌游聚会",
    "德州扑克",
    "德式桌游",
    "狼人杀",
    "阿瓦隆",
    "血染钟楼",
    "TRPG(跑团)",
    "其他",
)

BROWSE_BOOKMARK_LIGHT_EVENT_TYPE = "轻桌游聚会"
# 活动列表里的社团周常书签，同时包含布鸽与 YOYO
CLUB_WEEKLY_LABEL = "社团周常活动"
BROWSE_BOOKMARK_PIGEON_LABEL = CLUB_WEEKLY_LABEL
FIXED_GATHERING_LABEL = "布鸽桌游聚会"
FIXED_GATHERING_LOCATION = "南体活动室(布鸽专用)"
# 周六晚：weekday==5（周六），且小时 >= 18
FIXED_GATHERING_EVENING_HOUR_START = 18
GATHERING_KIND_PIGEON = "pigeon"
GATHERING_KIND_YOYO = "yoyo"
YOYO_GATHERING_LABEL = "YOYO桌游聚会"
YOYO_GATHERING_LOCATIONS = ("华师四教312", "华师四教308")

# 兼容旧导入名
BROWSE_BOOKMARK_PIGEON_EVENT_TYPE = "布鸽桌游活动"
STAFF_ONLY_LOCATION = FIXED_GATHERING_LOCATION
ADMIN_ONLY_LOCATION = FIXED_GATHERING_LOCATION
PRESET_LOCATIONS = (
    "交大紫矜街(博雅厅)",
    "交大玉兰苑",
    "交大北博士公寓",
    "华师秋实",
    "华师冬日",
    "华师研寓",
)


# 创建/编辑时选持续时长，存成结束时间。
DURATION_HOUR_CHOICES = (1, 2, 3, 4, 5, 6, 8, 12)
DEFAULT_DURATION_HOURS = 3
# 补结束时间之前就存在的活动，按开始后 4 小时。
EXISTING_EVENT_DURATION_HOURS = 4


def parse_event_datetime(value: str):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M")


def _parse_stored_time(value):
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt, size in (("%Y-%m-%dT%H:%M", 16), ("%Y-%m-%d %H:%M", 16)):
        try:
            return datetime.strptime(raw[:size], fmt)
        except ValueError:
            continue
    return None


def duration_hours_between(starttime, endtime):
    """开始到结束的整点小时数。对不上可选项时返回 None。"""
    start = _parse_stored_time(starttime)
    end = _parse_stored_time(endtime)
    if start is None or end is None or end <= start:
        return None
    hours = int(round((end - start).total_seconds() / 3600))
    if hours not in DURATION_HOUR_CHOICES:
        return None
    return hours


def endtime_from_duration(starttime, hours):
    start = parse_event_datetime(starttime)
    return (start + timedelta(hours=int(hours))).strftime("%Y-%m-%dT%H:%M")


def schedule_labels(starttime, endtime):
    """卡片上的时间范围，以及单独的结束时间。同一天只把结束时刻接在开始时间后面。"""
    start = _parse_stored_time(starttime)
    end = _parse_stored_time(endtime)
    if start is None:
        start_label = (starttime or "").replace("T", " ").strip()
        return start_label, ""
    start_label = start.strftime("%Y-%m-%d %H:%M")
    if end is None or end <= start:
        return start_label, ""
    end_label = end.strftime("%Y-%m-%d %H:%M")
    if start.date() == end.date():
        return f"{start_label}–{end.strftime('%H:%M')}", end_label
    return f"{start_label} – {end_label}", end_label


def attach_duration(event_dict):
    time_range, end_label = schedule_labels(event_dict.get("starttime"), event_dict.get("endtime"))
    event_dict["time_range_label"] = time_range
    event_dict["endtime_label"] = end_label
    event_dict["duration_hours"] = duration_hours_between(
        event_dict.get("starttime"), event_dict.get("endtime")
    )
    return event_dict


def _event_interval(starttime, endtime):
    """报名占用的时段。没有结束时间时按 4 小时计。首尾相接不算重叠。"""
    start = _parse_stored_time(starttime)
    if start is None:
        return None
    end = _parse_stored_time(endtime)
    if end is None or end <= start:
        end = start + timedelta(hours=EXISTING_EVENT_DURATION_HOURS)
    return start, end


def _intervals_overlap(left, right):
    return left[0] < right[1] and right[0] < left[1]


def signup_time_conflict(player, starttime, endtime, *, exclude_free_id=None, exclude_fixed_id=None):
    """玩家已报名的其他活动与此时段相交时返回提示。只统计报名，不含仅作为组织者的场次。"""
    player = (player or "").strip()
    window = _event_interval(starttime, endtime)
    if not player or window is None:
        return None
    db = get_db()
    occupied = []
    free_rows = db.execute(
        """
        SELECT e.id AS id, e.name AS name, e.starttime AS starttime, e.endtime AS endtime
        FROM attendinfo a
        JOIN events e ON e.id = a.eventid
        WHERE a.player = ?
          AND TRIM(COALESCE(e.signcode, '')) != ?
        """,
        (player, ARCHIVED_SIGNCODE),
    ).fetchall()
    for row in free_rows:
        if exclude_free_id is not None and int(row["id"]) == int(exclude_free_id):
            continue
        occupied.append(row)
    fixed_rows = db.execute(
        """
        SELECT e.id AS id, e.name AS name, e.starttime AS starttime, e.endtime AS endtime
        FROM fixed_table_attend a
        JOIN fixed_events e ON e.id = a.fixed_event_id
        WHERE a.player = ?
          AND TRIM(COALESCE(e.signcode, '')) != ?
        """,
        (player, ARCHIVED_SIGNCODE),
    ).fetchall()
    for row in fixed_rows:
        if exclude_fixed_id is not None and int(row["id"]) == int(exclude_fixed_id):
            continue
        occupied.append(row)
    for row in occupied:
        other = _event_interval(row["starttime"], row["endtime"])
        if other is None or not _intervals_overlap(window, other):
            continue
        label, _end = schedule_labels(row["starttime"], row["endtime"])
        name = (row["name"] or "").strip() or "未命名活动"
        when = f"（{label}）" if label else ""
        return f"与已报名活动「{name}」{when}时间重叠。"
    return None


def is_event_in_progress(starttime, endtime, now=None):
    """当前时刻落在开始之后、结束之前。没有结束时间时按 4 小时。"""
    window = _event_interval(starttime, endtime)
    if window is None:
        return False
    moment = now or datetime.now()
    return window[0] < moment < window[1]


def _needs_signin(row, now):
    """与卡片上的签到区相同：进行中、未签到，且已达到最少人数（未设最少人数则直接可签）。"""
    if int(row["signed"] or 0) > 0:
        return False
    if not is_event_in_progress(row["starttime"], row["endtime"], now):
        return False
    minimum = row["minplayer"]
    if not minimum:
        return True
    return int(row["attendee_count"] or 0) >= int(minimum)


def board_signin_notices(player, now=None):
    """活动板上的签到提示。

    已报名、正在进行、已达到最少人数、尚未签到的活动最多一场。
    自己组的、正在进行的活动列出全部签到码，不要求已达到最少人数。
    只组局、未报名的场次不要求签到。
    """
    player = (player or "").strip()
    moment = now or datetime.now()
    if not player:
        return {"attend": None, "hosted": []}
    db = get_db()
    attend_rows = []
    hosted_rows = []
    free_attend = db.execute(
        """
        SELECT e.id AS id, e.name AS name, e.starttime AS starttime, e.endtime AS endtime,
               e.minplayer AS minplayer, IFNULL(a.signed, 0) AS signed,
               (SELECT COUNT(*) FROM attendinfo WHERE eventid = e.id) AS attendee_count
        FROM attendinfo a
        JOIN events e ON e.id = a.eventid
        WHERE a.player = ?
          AND TRIM(COALESCE(e.signcode, '')) != ?
        """,
        (player, ARCHIVED_SIGNCODE),
    ).fetchall()
    for row in free_attend:
        if not _needs_signin(row, moment):
            continue
        attend_rows.append(("free", row))
    fixed_attend = db.execute(
        """
        SELECT e.id AS id, e.name AS name, e.starttime AS starttime, e.endtime AS endtime,
               e.minplayer AS minplayer, IFNULL(a.signed, 0) AS signed,
               (SELECT COUNT(*) FROM fixed_table_attend WHERE fixed_event_id = e.id) AS attendee_count
        FROM fixed_table_attend a
        JOIN fixed_events e ON e.id = a.fixed_event_id
        WHERE a.player = ?
          AND TRIM(COALESCE(e.signcode, '')) != ?
        """,
        (player, ARCHIVED_SIGNCODE),
    ).fetchall()
    for row in fixed_attend:
        if not _needs_signin(row, moment):
            continue
        attend_rows.append(("fixed", row))
    attend_rows.sort(
        key=lambda item: _parse_stored_time(item[1]["starttime"]) or datetime.min,
        reverse=True,
    )
    attend = None
    if attend_rows:
        kind, row = attend_rows[0]
        when, _end = schedule_labels(row["starttime"], row["endtime"])
        attend = {
            "id": int(row["id"]),
            "kind": kind,
            "name": (row["name"] or "").strip() or "未命名活动",
            "when": when,
        }
    free_hosted = db.execute(
        """
        SELECT id, name, starttime, endtime, signcode
        FROM events
        WHERE inviter = ?
          AND TRIM(COALESCE(signcode, '')) != ?
        """,
        (player, ARCHIVED_SIGNCODE),
    ).fetchall()
    fixed_hosted = db.execute(
        """
        SELECT id, name, starttime, endtime, signcode
        FROM fixed_events
        WHERE inviter = ?
          AND TRIM(COALESCE(signcode, '')) != ?
        """,
        (player, ARCHIVED_SIGNCODE),
    ).fetchall()
    for kind, rows in (("free", free_hosted), ("fixed", fixed_hosted)):
        for row in rows:
            if not is_event_in_progress(row["starttime"], row["endtime"], moment):
                continue
            when, _end = schedule_labels(row["starttime"], row["endtime"])
            hosted_rows.append({
                "id": int(row["id"]),
                "kind": kind,
                "name": (row["name"] or "").strip() or "未命名活动",
                "when": when,
                "signcode": (row["signcode"] or "").strip(),
                "start": _parse_stored_time(row["starttime"]) or datetime.min,
            })
    hosted_rows.sort(key=lambda item: item["start"])
    for item in hosted_rows:
        item.pop("start", None)
    return {"attend": attend, "hosted": hosted_rows}


def _backfill_missing_endtimes(db):
    """还没有结束时间的活动，按开始时间后 4 小时写入。"""
    for table in ("events", "fixed_events"):
        rows = db.execute(
            f"SELECT id, starttime FROM {table} WHERE endtime IS NULL OR TRIM(endtime) = ''"
        ).fetchall()
        for row in rows:
            start = _parse_stored_time(row["starttime"])
            if start is None:
                continue
            end = (start + timedelta(hours=EXISTING_EVENT_DURATION_HOURS)).strftime("%Y-%m-%dT%H:%M")
            db.execute(
                f"UPDATE {table} SET endtime = ? WHERE id = ?",
                (end, int(row["id"])),
            )


def gathering_spec(kind: str):
    """社团周常的两种固定聚会。未知类型按布鸽处理，避免把会员活动放开。"""
    if kind == GATHERING_KIND_YOYO:
        return {
            "kind": GATHERING_KIND_YOYO,
            "label": YOYO_GATHERING_LABEL,
            "locations": YOYO_GATHERING_LOCATIONS,
            "members_only": False,
            "weekday": 6,
            "min_hour": None,
            "time_hint": "周日",
            "time_error": "YOYO桌游聚会须安排在周日。",
            "blurb": "地点为华师四教312或华师四教308，开始时间必须是周日。非会员也可以分桌报名。",
        }
    return {
        "kind": GATHERING_KIND_PIGEON,
        "label": FIXED_GATHERING_LABEL,
        "locations": (FIXED_GATHERING_LOCATION,),
        "members_only": True,
        "weekday": 5,
        "min_hour": FIXED_GATHERING_EVENING_HOUR_START,
        "time_hint": f"周六 {FIXED_GATHERING_EVENING_HOUR_START}:00 及以后",
        "time_error": (
            f"布鸽桌游聚会须安排在周六晚"
            f"（周六 {FIXED_GATHERING_EVENING_HOUR_START}:00 及以后）。"
        ),
        "blurb": "地点锁定南体活动室(布鸽专用)，开始时间必须是周六 18:00 及以后。由正式会员分桌报名。",
    }


def normalize_gathering_kind(kind) -> str:
    return GATHERING_KIND_YOYO if kind == GATHERING_KIND_YOYO else GATHERING_KIND_PIGEON


def gathering_label(kind) -> str:
    return gathering_spec(normalize_gathering_kind(kind))["label"]


def gathering_members_only(kind) -> bool:
    return gathering_spec(normalize_gathering_kind(kind))["members_only"]


def gathering_form_options():
    return [
        {
            "kind": spec["kind"],
            "label": spec["label"],
            "locations": list(spec["locations"]),
            "time_hint": spec["time_hint"],
            "members_only": spec["members_only"],
            "blurb": spec["blurb"],
        }
        for spec in (gathering_spec(GATHERING_KIND_PIGEON), gathering_spec(GATHERING_KIND_YOYO))
    ]


def gathering_starttime_error(kind, starttime) -> str:
    """符合该周常的开始时间时返回空字符串。"""
    spec = gathering_spec(normalize_gathering_kind(kind))
    try:
        dt = parse_event_datetime(starttime)
    except (TypeError, ValueError):
        return spec["time_error"]
    if dt.weekday() != spec["weekday"]:
        return spec["time_error"]
    if spec["min_hour"] is not None and dt.hour < spec["min_hour"]:
        return spec["time_error"]
    return ""


def is_saturday_evening(starttime: str) -> bool:
    """布鸽桌游聚会开始时间须为周六晚（周六、当地时间 18:00 及以后）。"""
    return not gathering_starttime_error(GATHERING_KIND_PIGEON, starttime)


def saturday_evening_error_message() -> str:
    return gathering_spec(GATHERING_KIND_PIGEON)["time_error"]


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
    """将活动标记为已归档（不删除记录与报名），并关闭临时聊天室。"""
    db = get_db()
    db.execute("UPDATE events SET signcode = ? WHERE id = ?", (ARCHIVED_SIGNCODE, event_id))
    close_room(db, KIND_FREE, event_id)
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


def _event_type_check_clause():
    allowed = ", ".join("'" + value.replace("'", "''") + "'" for value in EVENT_TYPE_VALUES)
    return f"CHECK(event_type IN ({allowed}))"


def _ensure_event_type_check(db):
    """旧库的 event_type CHECK 不含新类型时，重建 events 表以放行这些取值。"""
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'events'"
    ).fetchone()
    if row is None:
        return
    create_sql = row["sql"] or ""
    if "CHECK" not in create_sql.upper():
        return
    if all(value in create_sql for value in EVENT_TYPE_VALUES):
        return

    columns = db.execute("PRAGMA table_info(events)").fetchall()
    if not columns:
        return
    definitions = []
    names = []
    for column in columns:
        name = column["name"]
        names.append(name)
        quoted = '"' + name.replace('"', '""') + '"'
        if column["pk"] == 1 and name == "id":
            definitions.append(f"{quoted} INTEGER PRIMARY KEY AUTOINCREMENT")
            continue
        parts = [quoted, column["type"] or "TEXT"]
        if column["notnull"]:
            parts.append("NOT NULL")
        if column["dflt_value"] is not None:
            parts.append(f"DEFAULT {column['dflt_value']}")
        if name == "event_type":
            parts.append(_event_type_check_clause())
        definitions.append(" ".join(parts))

    index_rows = db.execute(
        """
        SELECT sql FROM sqlite_master
        WHERE type = 'index' AND tbl_name = 'events' AND sql IS NOT NULL
        """
    ).fetchall()
    quoted_names = ", ".join('"' + name.replace('"', '""') + '"' for name in names)
    db.execute("PRAGMA foreign_keys = OFF")
    try:
        db.execute("BEGIN")
        db.execute(f"CREATE TABLE events__typecheck ({', '.join(definitions)})")
        db.execute(
            f"INSERT INTO events__typecheck ({quoted_names}) SELECT {quoted_names} FROM events"
        )
        db.execute("DROP TABLE events")
        db.execute("ALTER TABLE events__typecheck RENAME TO events")
        for index_row in index_rows:
            db.execute(index_row["sql"])
        if db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sqlite_sequence'"
        ).fetchone():
            db.execute(
                "UPDATE sqlite_sequence SET name = 'events' WHERE name = 'events__typecheck'"
            )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    finally:
        db.execute("PRAGMA foreign_keys = ON")


def _ensure_events_schema(db):
    columns = db.execute("PRAGMA table_info(events)").fetchall()
    column_names = {row["name"] for row in columns}
    if "event_type" not in column_names and columns:
        db.execute("ALTER TABLE events ADD COLUMN event_type TEXT DEFAULT '其他'")
    if columns and "endtime" not in column_names:
        db.execute("ALTER TABLE events ADD COLUMN endtime TEXT")
    _ensure_event_type_check(db)
    if db.execute("PRAGMA table_info(events)").fetchall():
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
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS fixed_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signcode TEXT NOT NULL,
            name TEXT NOT NULL,
            inviter TEXT NOT NULL,
            location TEXT NOT NULL,
            starttime TEXT NOT NULL,
            locktime TEXT NOT NULL,
            endtime TEXT,
            description TEXT,
            minplayer INTEGER,
            maxplayer INTEGER,
            gathering_kind TEXT NOT NULL DEFAULT 'pigeon'
        )
        """
    )
    fixed_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(fixed_events)").fetchall()
    }
    if fixed_columns and "gathering_kind" not in fixed_columns:
        db.execute(
            "ALTER TABLE fixed_events ADD COLUMN gathering_kind TEXT NOT NULL DEFAULT 'pigeon'"
        )
    if fixed_columns and "endtime" not in fixed_columns:
        db.execute("ALTER TABLE fixed_events ADD COLUMN endtime TEXT")
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS fixed_tables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fixed_event_id INTEGER NOT NULL,
            host TEXT NOT NULL,
            board_game_id INTEGER NOT NULL,
            board_game_name TEXT NOT NULL,
            min_players INTEGER,
            max_players INTEGER NOT NULL,
            owner_name TEXT NOT NULL,
            holder_name TEXT,
            owner_confirmed INTEGER NOT NULL DEFAULT 0,
            holder_confirmed INTEGER NOT NULL DEFAULT 0,
            note TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(fixed_event_id) REFERENCES fixed_events(id) ON DELETE CASCADE
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS fixed_table_attend (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_id INTEGER NOT NULL,
            fixed_event_id INTEGER NOT NULL,
            player TEXT NOT NULL,
            note TEXT,
            signed INTEGER NOT NULL DEFAULT 0,
            UNIQUE(fixed_event_id, player),
            UNIQUE(table_id, player),
            FOREIGN KEY(table_id) REFERENCES fixed_tables(id) ON DELETE CASCADE,
            FOREIGN KEY(fixed_event_id) REFERENCES fixed_events(id) ON DELETE CASCADE
        )
        """
    )
    from app.subsystems.events.announcements import ensure_announcement_schema

    ensure_announcement_schema(db)
    ensure_chat_schema(db)
    _backfill_missing_endtimes(db)
    db.commit()


def close_db(e=None):
    db = getattr(g, "_events_db", None)
    if db is not None:
        db.close()
        g._events_db = None


_EVENT_LISTING_SELECT = """
        SELECT
            e.*,
            GROUP_CONCAT(a.player) AS attendee_list,
            GROUP_CONCAT(a.player || '::' || IFNULL(a.note, '') || '::' || IFNULL(a.friend, '0')  || '::' || IFNULL(a.signed, '0')) AS player_notes_raw,
            EXISTS(SELECT 1 FROM attendinfo WHERE eventid = e.id AND player = ?) AS is_attending,
            (SELECT IFNULL(note, '') || '::' || IFNULL(friend, '0') || '::' || IFNULL(signed, '0') FROM attendinfo WHERE eventid = e.id AND player = ?) AS user_info_raw
        FROM events e
        LEFT JOIN attendinfo a ON e.id = a.eventid
"""


def _browse_sql_filter_clause(filters, current_user):
    """与 apply_event_list_filters 语义一致，在 SQL 层筛选 events 行。"""
    if not filters:
        return "", []
    parts = []
    params = []
    et = filters.get("event_type")
    if et:
        parts.append("COALESCE(NULLIF(TRIM(e.event_type), ''), '其他') = ?")
        params.append(et)
    if filters.get("my_activities_only"):
        parts.append(
            "(e.inviter = ? OR EXISTS(SELECT 1 FROM attendinfo ai WHERE ai.eventid = e.id AND ai.player = ?))"
        )
        params.extend([current_user, current_user])
    if not parts:
        return "", []
    return " AND " + " AND ".join(parts), params


def _materialize_event_rows(rows):
    events_list = []
    for event in rows:
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
        attach_duration(event_dict)
        events_list.append(event_dict)
    return events_list


def count_browse_events(current_user, filters):
    """当前书签筛选下的活动总数（不按页截断）。"""
    where_extra, wp = _browse_sql_filter_clause(filters, current_user)
    db = get_db()
    row = db.execute(f"SELECT COUNT(*) AS c FROM events e WHERE 1=1 {where_extra}", wp).fetchone()
    return int(row["c"]) if row else 0


def get_browse_events_page(current_user, filters, limit, offset):
    """
    分页读取活动列表（与活动板书签筛选一致）。
    limit 为 None 时表示不限制条数（仅用于少量管理路径）。
    """
    db = get_db()
    where_extra, wp = _browse_sql_filter_clause(filters, current_user)
    sql = (
        _EVENT_LISTING_SELECT
        + f" WHERE 1=1 {where_extra} GROUP BY e.id ORDER BY e.id DESC"
    )
    params = [current_user, current_user] + wp
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])
    rows = db.execute(sql, tuple(params)).fetchall()
    return _materialize_event_rows(rows)


def get_event_listing_by_id(event_id, current_user):
    """单条活动的列表视图数据（含报名人数等），供 joininfo / 归档等使用。"""
    db = get_db()
    sql = _EVENT_LISTING_SELECT + " WHERE e.id = ? GROUP BY e.id"
    params = (current_user, current_user, int(event_id))
    row = db.execute(sql, params).fetchone()
    if row is None:
        return None
    return _materialize_event_rows([row])[0]


def get_all_events(current_user, browse_filters=None):
    """全部活动（无条数限制）；browse_filters 与活动板书签筛选语义一致。"""
    return get_browse_events_page(current_user, browse_filters or {}, limit=None, offset=0)


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
    attach_duration(event_dict)
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
    cur = db.execute(
        """
        INSERT INTO events
            (name, inviter, location, starttime, locktime, endtime, description, minplayer, maxplayer, signcode, event_type)
        VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["name"],
            data["inviter"],
            data["location"],
            data["starttime"],
            data["locktime"],
            data.get("endtime") or None,
            data["description"],
            data["minplayer"],
            data["maxplayer"],
            str(random.randint(0, 9999)).zfill(4),
            data["event_type"],
        ),
    )
    event_id = int(cur.lastrowid)
    open_room(db, KIND_FREE, event_id, data["inviter"])
    db.commit()
    return event_id


def update_event(event_id, data):
    db = get_db()
    db.execute(
        """
        UPDATE events
        SET name = ?, location = ?, starttime = ?, locktime = ?, endtime = ?, description = ?, minplayer = ?, maxplayer = ?, event_type = ?
        WHERE id = ?
        """,
        (
            data["name"],
            data["location"],
            data["starttime"],
            data["locktime"],
            data.get("endtime") or None,
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
    close_room(db, KIND_FREE, event_id)
    db.execute("DELETE FROM events WHERE id = ?", (event_id,))
    db.commit()


def join_event(event_id, player):
    db = get_db()
    row = db.execute(
        "SELECT signcode, inviter, starttime, endtime FROM events WHERE id = ?",
        (event_id,),
    ).fetchone()
    if row is None:
        return False, "活动不存在。"
    if is_event_archived(dict(row)):
        return False, "活动已归档，无法报名。"
    conflict = signup_time_conflict(
        player, row["starttime"], row["endtime"], exclude_free_id=event_id
    )
    if conflict:
        return False, conflict
    from app.user.blacklist import signup_block_reason

    blocked = signup_block_reason(row["inviter"] if row else "", player)
    if blocked:
        return False, blocked
    try:
        db.execute("INSERT INTO attendinfo (eventid, player) VALUES (?, ?)", (event_id, player))
        note_joined(db, KIND_FREE, event_id, player)
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
    if cursor.rowcount:
        note_left(db, KIND_FREE, event_id, player)
    db.commit()
    return cursor.rowcount > 0
