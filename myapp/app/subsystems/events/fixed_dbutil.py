"""固定聚会：独立表 CRUD 与报名/确认/签到规则。"""

from __future__ import annotations

import random
import sqlite3
from datetime import datetime
from typing import Optional, Tuple

from app.subsystems.boardgames import api as boardgames_api
from app.subsystems.events.chat import KIND_FIXED, close_room, note_joined, note_left, open_room
from app.subsystems.events.dbutil import (
    ARCHIVED_SIGNCODE,
    FIXED_GATHERING_LABEL,
    get_db,
    is_event_archived,
)

SELF_BROUGHT_GAME_ID = 0
SELF_BROUGHT_GAME_NAME = "组局者自备"


def _parse_times(event_dict):
    event_dict["starttime_obj"] = datetime.strptime(event_dict["starttime"], "%Y-%m-%dT%H:%M")
    event_dict["locktime_obj"] = datetime.strptime(event_dict["locktime"], "%Y-%m-%dT%H:%M")
    starttime = event_dict["starttime_obj"]
    locktime = event_dict["locktime_obj"]
    event_dict["locktime_select"] = str(int((starttime - locktime).total_seconds() / 3600))
    return event_dict


def _holder_confirmation_required(owner_name, holder_name) -> bool:
    owner = (owner_name or "").strip()
    holder = (holder_name or "").strip()
    if not holder:
        return False
    return holder != owner


def _commitments_satisfied(table) -> bool:
    if int(table.get("owner_confirmed") or 0) != 1:
        return False
    if not _holder_confirmation_required(table.get("owner_name"), table.get("holder_name")):
        return True
    return int(table.get("holder_confirmed") or 0) == 1


def table_is_valid(table) -> bool:
    min_p = table.get("min_players")
    count = int(table.get("attendee_count") or 0)
    if min_p is not None and count < int(min_p):
        return False
    # 组局者自备：无库内桌游，不检查所有者/持有者承诺
    if int(table.get("board_game_id") or 0) == SELF_BROUGHT_GAME_ID:
        return True
    return _commitments_satisfied(table)


def count_fixed_event_attendees(event_id, db=None) -> int:
    own = db is None
    if own:
        db = get_db()
    row = db.execute(
        "SELECT COUNT(*) AS c FROM fixed_table_attend WHERE fixed_event_id = ?",
        (event_id,),
    ).fetchone()
    return int(row["c"]) if row else 0


def get_player_table_id(event_id, player, db=None):
    own = db is None
    if own:
        db = get_db()
    row = db.execute(
        "SELECT table_id FROM fixed_table_attend WHERE fixed_event_id = ? AND player = ?",
        (event_id, player),
    ).fetchone()
    return int(row["table_id"]) if row else None


def create_fixed_event(data) -> int:
    db = get_db()
    cur = db.execute(
        """
        INSERT INTO fixed_events
            (name, inviter, location, starttime, locktime, description, minplayer, maxplayer, signcode)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["name"],
            data["inviter"],
            data["location"],
            data["starttime"],
            data["locktime"],
            data.get("description") or "",
            data.get("minplayer"),
            data.get("maxplayer"),
            str(random.randint(0, 9999)).zfill(4),
        ),
    )
    event_id = int(cur.lastrowid)
    open_room(db, KIND_FIXED, event_id, data["inviter"])
    db.commit()
    return event_id


def update_fixed_event(event_id, data):
    db = get_db()
    db.execute(
        """
        UPDATE fixed_events
        SET name = ?, location = ?, starttime = ?, locktime = ?, description = ?,
            minplayer = ?, maxplayer = ?
        WHERE id = ?
        """,
        (
            data["name"],
            data["location"],
            data["starttime"],
            data["locktime"],
            data.get("description") or "",
            data.get("minplayer"),
            data.get("maxplayer"),
            event_id,
        ),
    )
    db.commit()


def delete_fixed_event(event_id):
    db = get_db()
    close_room(db, KIND_FIXED, event_id)
    db.execute("DELETE FROM fixed_events WHERE id = ?", (event_id,))
    db.commit()


def archive_fixed_event(event_id):
    db = get_db()
    db.execute(
        "UPDATE fixed_events SET signcode = ? WHERE id = ?",
        (ARCHIVED_SIGNCODE, event_id),
    )
    close_room(db, KIND_FIXED, event_id)
    db.commit()


def get_fixed_event_by_id(event_id):
    db = get_db()
    row = db.execute("SELECT * FROM fixed_events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        return None
    return _parse_times(dict(row))


def get_fixed_event_attendance_records(event_id):
    db = get_db()
    rows = db.execute(
        """
        SELECT player, IFNULL(signed, 0) AS signed
        FROM fixed_table_attend
        WHERE fixed_event_id = ?
        """,
        (event_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _materialize_fixed_event(row, current_user, db):
    event = _parse_times(dict(row))
    event["mode"] = "fixed"
    event["event_type"] = FIXED_GATHERING_LABEL

    event_id = event["id"]
    event["attendee_count"] = count_fixed_event_attendees(event_id, db)
    tables = list_tables_for_event(event_id, current_user, db=db)
    event["table_count"] = len(tables)
    event["valid_table_count"] = sum(1 for t in tables if t.get("is_valid"))
    event["tables"] = tables
    player_table = get_player_table_id(event_id, current_user, db)
    event["is_attending"] = player_table is not None
    event["user_table_id"] = player_table
    event["user_signed"] = 0
    event["user_note"] = None
    if player_table is not None:
        attend = db.execute(
            """
            SELECT note, IFNULL(signed, 0) AS signed
            FROM fixed_table_attend
            WHERE fixed_event_id = ? AND player = ?
            """,
            (event_id, current_user),
        ).fetchone()
        if attend:
            event["user_signed"] = int(attend["signed"] or 0)
            event["user_note"] = attend["note"]
    # Flatten attendee notes for enrich helper / summary
    notes = []
    for t in tables:
        for a in t.get("attendees") or []:
            notes.append(a)
    event["attendee_notes"] = notes
    event["attendee_list"] = [a["player"] for a in notes]
    return event


def list_tables_for_event(event_id, current_user=None, db=None):
    own = db is None
    if own:
        db = get_db()
    rows = db.execute(
        """
        SELECT * FROM fixed_tables
        WHERE fixed_event_id = ?
        ORDER BY id ASC
        """,
        (event_id,),
    ).fetchall()
    tables = []
    for row in rows:
        table = dict(row)
        attends = db.execute(
            """
            SELECT player, IFNULL(note, '') AS note, IFNULL(signed, 0) AS signed
            FROM fixed_table_attend
            WHERE table_id = ?
            ORDER BY id ASC
            """,
            (table["id"],),
        ).fetchall()
        attendees = [
            {
                "player": a["player"],
                "note": a["note"] or "",
                "friends": 0,
                "signed": int(a["signed"] or 0),
            }
            for a in attends
        ]
        table["attendees"] = attendees
        table["attendee_count"] = len(attendees)
        table["is_full"] = table["attendee_count"] >= int(table["max_players"])
        table["is_self_brought"] = int(table.get("board_game_id") or 0) == SELF_BROUGHT_GAME_ID
        table["is_valid"] = table_is_valid(table)
        if table["is_self_brought"]:
            table["holder_required"] = False
            table["commitments_ok"] = True
        else:
            table["holder_required"] = _holder_confirmation_required(
                table.get("owner_name"), table.get("holder_name")
            )
            table["commitments_ok"] = _commitments_satisfied(table)
        owner_st = int(table.get("owner_confirmed") or 0)
        holder_st = int(table.get("holder_confirmed") or 0)
        table["owner_status"] = owner_st
        table["holder_status"] = holder_st
        table["can_confirm"] = False
        table["can_reject"] = False
        table["user_on_table"] = False
        table["user_is_owner"] = False
        table["user_is_holder"] = False
        if current_user and not table["is_self_brought"]:
            table["user_on_table"] = any(a["player"] == current_user for a in attendees)
            owner = (table.get("owner_name") or "").strip()
            holder = (table.get("holder_name") or "").strip()
            table["user_is_owner"] = current_user == owner
            table["user_is_holder"] = bool(holder) and current_user == holder
            if table["user_is_owner"]:
                table["can_confirm"] = owner_st != 1
                table["can_reject"] = owner_st != -1
            elif table["holder_required"] and table["user_is_holder"]:
                table["can_confirm"] = holder_st != 1
                table["can_reject"] = holder_st != -1
        elif current_user:
            table["user_on_table"] = any(a["player"] == current_user for a in attendees)
        tables.append(table)
    return tables


def get_fixed_event_detail(event_id, current_user):
    db = get_db()
    row = db.execute("SELECT * FROM fixed_events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        return None
    return _materialize_fixed_event(row, current_user, db)


def list_fixed_events_for_browse(current_user, filters=None):
    """返回用于面板的固定聚会列表（未分页）。"""
    filters = filters or {}
    # 轻桌游等自由类型书签不展示固定聚会；布鸽书签只展示固定聚会
    if filters.get("event_type") and not filters.get("fixed_only"):
        return []
    if filters.get("free_only"):
        return []
    db = get_db()
    sql = "SELECT * FROM fixed_events"
    params = []
    if filters.get("my_activities_only"):
        sql += """
            WHERE inviter = ?
               OR EXISTS (
                    SELECT 1 FROM fixed_table_attend a
                    WHERE a.fixed_event_id = fixed_events.id AND a.player = ?
               )
        """
        params.extend([current_user, current_user])
    sql += " ORDER BY id DESC"
    rows = db.execute(sql, tuple(params)).fetchall()
    return [_materialize_fixed_event(row, current_user, db) for row in rows]


def create_table(
    event_id,
    host,
    board_game_id,
    note="",
    min_players=None,
    max_players=None,
    self_game_name="",
) -> Tuple[bool, Optional[str], Optional[int]]:
    db = get_db()
    event = get_fixed_event_by_id(event_id)
    if event is None:
        return False, "活动不存在。", None
    if is_event_archived(event):
        return False, "活动已归档，无法开桌。", None
    if event["locktime_obj"] < datetime.now():
        return False, "名单已锁定，无法开桌。", None

    if get_player_table_id(event_id, host, db) is not None:
        return False, "您已报名本聚会的一张桌，不能再开新桌。", None

    maxp = event.get("maxplayer")
    if maxp is not None and count_fixed_event_attendees(event_id, db) >= int(maxp):
        return False, "聚会总人数已满，无法开桌。", None

    try:
        game_id = int(board_game_id) if board_game_id is not None else SELF_BROUGHT_GAME_ID
    except (TypeError, ValueError):
        return False, "请选择有效的桌游。", None

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    owner_confirmed = 0
    holder_confirmed = 0

    if game_id == SELF_BROUGHT_GAME_ID:
        # 组局者自备：临时桌游名与人数写入本桌字段；无所有者/持有者承诺
        custom_name = (self_game_name or "").strip()
        if not custom_name:
            return False, "组局者自备请填写桌游名称。", None
        if len(custom_name) > 80:
            return False, "桌游名称过长（最多 80 字）。", None
        try:
            max_players_val = int(max_players) if max_players not in (None, "") else None
            min_players_val = int(min_players) if min_players not in (None, "") else None
        except (TypeError, ValueError):
            return False, "请填写有效的人数上下限。", None
        if max_players_val is None or max_players_val < 1:
            return False, "请填写有效的最大人数。", None
        if min_players_val is None or min_players_val < 1:
            return False, "请填写有效的最小人数。", None
        if min_players_val > max_players_val:
            return False, "人数下限不能大于上限。", None
        board_game_name = custom_name
        owner_name = ""
        holder_name = None
        owner_confirmed = 1
        holder_confirmed = 1
    else:
        game = boardgames_api.get_game_by_id(game_id)
        if not game:
            return False, "所选桌游不存在。", None
        max_players_val = game.get("max_players")
        if max_players_val is None or int(max_players_val) < 1:
            return False, "该桌游未设置有效的人数上限，无法开桌。", None
        max_players_val = int(max_players_val)
        min_raw = game.get("min_players")
        min_players_val = int(min_raw) if min_raw is not None else None
        owner_name = (game.get("owner") or "").strip()
        if not owner_name:
            return False, "该桌游缺少所有者信息，无法开桌。", None
        holder_name = (game.get("current_holder") or "").strip() or None
        board_game_name = game.get("board_game_name") or f"游戏#{game_id}"

    try:
        cur = db.execute(
            """
            INSERT INTO fixed_tables (
                fixed_event_id, host, board_game_id, board_game_name,
                min_players, max_players, owner_name, holder_name,
                owner_confirmed, holder_confirmed, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                host,
                game_id,
                board_game_name,
                min_players_val,
                max_players_val,
                owner_name,
                holder_name,
                owner_confirmed,
                holder_confirmed,
                (note or "").strip(),
                created_at,
            ),
        )
        table_id = int(cur.lastrowid)
        db.execute(
            """
            INSERT INTO fixed_table_attend (table_id, fixed_event_id, player, note, signed)
            VALUES (?, ?, ?, '', 0)
            """,
            (table_id, event_id, host),
        )
        note_joined(db, KIND_FIXED, event_id, host)
        db.commit()
        return True, None, table_id
    except sqlite3.IntegrityError:
        db.rollback()
        return False, "开桌失败：您可能已报名其他桌。", None


def _first_table_player(table_id, db):
    row = db.execute(
        """
        SELECT player FROM fixed_table_attend
        WHERE table_id = ?
        ORDER BY id ASC
        LIMIT 1
        """,
        (table_id,),
    ).fetchone()
    return (row["player"] if row else "") or ""


def _resolve_table_game(board_game_id, min_players, max_players, self_game_name):
    """解析开桌/改桌时的桌游字段。返回 (ok, error, fields)。"""
    try:
        game_id = int(board_game_id) if board_game_id is not None else SELF_BROUGHT_GAME_ID
    except (TypeError, ValueError):
        return False, "请选择有效的桌游。", None

    if game_id == SELF_BROUGHT_GAME_ID:
        custom_name = (self_game_name or "").strip()
        if not custom_name:
            return False, "组局者自备请填写桌游名称。", None
        if len(custom_name) > 80:
            return False, "桌游名称过长（最多 80 字）。", None
        try:
            max_players_val = int(max_players) if max_players not in (None, "") else None
            min_players_val = int(min_players) if min_players not in (None, "") else None
        except (TypeError, ValueError):
            return False, "请填写有效的人数上下限。", None
        if max_players_val is None or max_players_val < 1:
            return False, "请填写有效的最大人数。", None
        if min_players_val is None or min_players_val < 1:
            return False, "请填写有效的最小人数。", None
        if min_players_val > max_players_val:
            return False, "人数下限不能大于上限。", None
        return True, None, {
            "game_id": game_id,
            "board_game_name": custom_name,
            "min_players": min_players_val,
            "max_players": max_players_val,
            "owner_name": "",
            "holder_name": None,
            "owner_confirmed": 1,
            "holder_confirmed": 1,
        }

    game = boardgames_api.get_game_by_id(game_id)
    if not game:
        return False, "所选桌游不存在。", None
    max_players_val = game.get("max_players")
    if max_players_val is None or int(max_players_val) < 1:
        return False, "该桌游未设置有效的人数上限。", None
    min_raw = game.get("min_players")
    owner_name = (game.get("owner") or "").strip()
    if not owner_name:
        return False, "该桌游缺少所有者信息。", None
    return True, None, {
        "game_id": game_id,
        "board_game_name": game.get("board_game_name") or f"游戏#{game_id}",
        "min_players": int(min_raw) if min_raw is not None else None,
        "max_players": int(max_players_val),
        "owner_name": owner_name,
        "holder_name": (game.get("current_holder") or "").strip() or None,
        "owner_confirmed": 0,
        "holder_confirmed": 0,
    }


def update_table(
    table_id,
    actor,
    *,
    is_admin,
    board_game_id,
    note="",
    min_players=None,
    max_players=None,
    self_game_name="",
) -> Tuple[bool, Optional[str]]:
    db = get_db()
    table_row = db.execute("SELECT * FROM fixed_tables WHERE id = ?", (table_id,)).fetchone()
    if table_row is None:
        return False, "桌不存在。"
    table = dict(table_row)
    event = get_fixed_event_by_id(table["fixed_event_id"])
    if event is None:
        return False, "活动不存在。"
    if is_event_archived(event):
        return False, "活动已结束，无法编辑此桌。"
    first_player = _first_table_player(table_id, db)
    if not is_admin and actor != first_player:
        return False, "只有管理员和该桌当前第一位玩家可以编辑此桌。"

    ok, err, fields = _resolve_table_game(board_game_id, min_players, max_players, self_game_name)
    if not ok:
        return False, err
    seated = db.execute(
        "SELECT COUNT(*) AS c FROM fixed_table_attend WHERE table_id = ?",
        (table_id,),
    ).fetchone()["c"]
    if int(fields["max_players"]) < int(seated):
        return False, f"当前已有 {int(seated)} 人，人数上限不能低于已报名人数。"

    same_commitment = (
        int(table.get("board_game_id") or 0) == int(fields["game_id"])
        and (table.get("owner_name") or "") == (fields["owner_name"] or "")
        and (table.get("holder_name") or "") == (fields["holder_name"] or "")
        and (table.get("board_game_name") or "") == fields["board_game_name"]
    )
    if same_commitment:
        fields["owner_confirmed"] = int(table.get("owner_confirmed") or 0)
        fields["holder_confirmed"] = int(table.get("holder_confirmed") or 0)

    db.execute(
        """
        UPDATE fixed_tables
        SET board_game_id = ?, board_game_name = ?, min_players = ?, max_players = ?,
            owner_name = ?, holder_name = ?, owner_confirmed = ?, holder_confirmed = ?,
            note = ?
        WHERE id = ?
        """,
        (
            fields["game_id"],
            fields["board_game_name"],
            fields["min_players"],
            fields["max_players"],
            fields["owner_name"],
            fields["holder_name"],
            fields["owner_confirmed"],
            fields["holder_confirmed"],
            (note or "").strip(),
            table_id,
        ),
    )
    db.commit()
    return True, None


def get_table_event_id(table_id):
    db = get_db()
    row = db.execute(
        "SELECT fixed_event_id FROM fixed_tables WHERE id = ?",
        (table_id,),
    ).fetchone()
    return int(row["fixed_event_id"]) if row else None


def join_table(table_id, player) -> Tuple[bool, Optional[str]]:
    db = get_db()
    table_row = db.execute("SELECT * FROM fixed_tables WHERE id = ?", (table_id,)).fetchone()
    if table_row is None:
        return False, "桌不存在。"
    table = dict(table_row)
    event = get_fixed_event_by_id(table["fixed_event_id"])
    if event is None:
        return False, "活动不存在。"
    if is_event_archived(event):
        return False, "活动已归档，无法报名。"
    if event["locktime_obj"] < datetime.now():
        return False, "名单已锁定，无法报名。"

    if get_player_table_id(event["id"], player, db) is not None:
        return False, "您已报名本聚会的一张桌，不能再报其他桌。"

    count = db.execute(
        "SELECT COUNT(*) AS c FROM fixed_table_attend WHERE table_id = ?",
        (table_id,),
    ).fetchone()
    table_count = int(count["c"]) if count else 0
    if table_count >= int(table["max_players"]):
        return False, "该桌人数已满。"

    maxp = event.get("maxplayer")
    if maxp is not None and count_fixed_event_attendees(event["id"], db) >= int(maxp):
        return False, "聚会总人数已满。"

    try:
        db.execute(
            """
            INSERT INTO fixed_table_attend (table_id, fixed_event_id, player, note, signed)
            VALUES (?, ?, ?, '', 0)
            """,
            (table_id, event["id"], player),
        )
        note_joined(db, KIND_FIXED, event["id"], player)
        db.commit()
        return True, None
    except sqlite3.IntegrityError:
        db.rollback()
        return False, "报名失败：您可能已报名其他桌。"


def leave_table(table_id, player) -> Tuple[bool, Optional[str]]:
    """退出该桌。建桌者与其他玩家无区别；仅当桌内无人时自动删除该桌。"""
    db = get_db()
    table_row = db.execute("SELECT * FROM fixed_tables WHERE id = ?", (table_id,)).fetchone()
    if table_row is None:
        return False, "桌不存在。"
    table = dict(table_row)
    event = get_fixed_event_by_id(table["fixed_event_id"])
    if event is None:
        return False, "活动不存在。"
    if is_event_archived(event):
        return False, "活动已归档，无法退桌。"
    if event["locktime_obj"] < datetime.now():
        return False, "名单已锁定，无法退桌。"

    cursor = db.execute(
        "DELETE FROM fixed_table_attend WHERE table_id = ? AND player = ?",
        (table_id, player),
    )
    if cursor.rowcount == 0:
        return False, "您未报名此桌。"
    note_left(db, KIND_FIXED, event["id"], player)

    remaining_rows = db.execute(
        """
        SELECT player FROM fixed_table_attend
        WHERE table_id = ?
        ORDER BY id ASC
        """,
        (table_id,),
    ).fetchall()
    if not remaining_rows:
        db.execute("DELETE FROM fixed_tables WHERE id = ?", (table_id,))
    else:
        # 若开桌记录人已离开，把 host 记为当前最早留在桌上的玩家（仅作审计，不区分展示）
        first_player = remaining_rows[0]["player"]
        if (table.get("host") or "") != first_player:
            db.execute(
                "UPDATE fixed_tables SET host = ? WHERE id = ?",
                (first_player, table_id),
            )
    db.commit()
    return True, None


def set_table_commitment(table_id, username, approved: bool) -> Tuple[bool, Optional[str]]:
    """所有者/持有者确认或拒绝本桌使用该桌游。approved=True 确认，False 拒绝。"""
    db = get_db()
    table_row = db.execute("SELECT * FROM fixed_tables WHERE id = ?", (table_id,)).fetchone()
    if table_row is None:
        return False, "桌不存在。"
    table = dict(table_row)
    event = get_fixed_event_by_id(table["fixed_event_id"])
    if event is None:
        return False, "活动不存在。"
    if is_event_archived(event):
        return False, "活动已归档，无法变更承诺。"

    owner = (table.get("owner_name") or "").strip()
    holder = (table.get("holder_name") or "").strip()
    user = (username or "").strip()
    if user != owner and user != holder:
        return False, "仅桌游所有者或持有者可确认或拒绝承诺。"

    value = 1 if approved else -1
    holder_req = _holder_confirmation_required(owner, holder)
    if user == owner:
        if holder_req:
            db.execute(
                "UPDATE fixed_tables SET owner_confirmed = ? WHERE id = ?",
                (value, table_id),
            )
        else:
            db.execute(
                """
                UPDATE fixed_tables
                SET owner_confirmed = ?, holder_confirmed = ?
                WHERE id = ?
                """,
                (value, value, table_id),
            )
    elif user == holder:
        db.execute(
            "UPDATE fixed_tables SET holder_confirmed = ? WHERE id = ?",
            (value, table_id),
        )
    db.commit()
    return True, None


def confirm_table_commitment(table_id, username) -> Tuple[bool, Optional[str]]:
    return set_table_commitment(table_id, username, True)


def signin_fixed_event(event_id, player, code) -> Tuple[bool, Optional[str]]:
    db = get_db()
    event = get_fixed_event_by_id(event_id)
    if event is None:
        return False, "活动不存在。"
    if is_event_archived(event):
        return False, "活动已归档，无法签到。"
    if str(event.get("signcode") or "") != str(code or "").strip():
        return False, "签到码错误！"
    if get_player_table_id(event_id, player, db) is None:
        return False, "您尚未报名本聚会的任何桌，无法签到。"
    try:
        db.execute(
            """
            UPDATE fixed_table_attend
            SET signed = 1
            WHERE fixed_event_id = ? AND player = ?
            """,
            (event_id, player),
        )
        db.commit()
        return True, None
    except Exception:
        return False, "系统内部错误。"


def merge_browse_items(free_events, fixed_events, limit=None, offset=0):
    """按 starttime 降序合并，再分页。条目均带 mode。"""
    items = []
    for e in free_events or []:
        e = dict(e)
        e["mode"] = "free"
        items.append(e)
    for e in fixed_events or []:
        e = dict(e)
        e.setdefault("mode", "fixed")
        items.append(e)

    def sort_key(ev):
        st = ev.get("starttime_obj") or datetime.min
        return (st, int(ev.get("id") or 0))

    items.sort(key=sort_key, reverse=True)
    total = len(items)
    if limit is None:
        page = items[offset:]
    else:
        page = items[offset : offset + int(limit)]
    return page, total
