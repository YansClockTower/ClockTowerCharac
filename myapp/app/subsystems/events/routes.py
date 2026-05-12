from datetime import datetime

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from app.identity import login_required_template, token_required
from app.identity.permissions import (
    ACTIVITY_ABSENT_COUNT_COLUMN,
    ACTIVITY_JOINED_COUNT_COLUMN,
    ACTIVITY_ORGANIZED_COUNT_COLUMN,
    ASSOCIATION_ROLE_COLUMN,
    CONTACT_INFO_COLUMN,
    LIGHTBOARD_BITMAP_COLUMN,
    MANAGE_ACCOUNT_PERMISSION,
    SCRIPT_BITMAP_COLUMN,
    SOCIAL_ROLE_COLUMN,
    ensure_user_permission_schema,
)
from app.models.database import get_user_db
from app.subsystems.events.attendee_ids import enrich_events_attendees_user_ids
from app.subsystems.events.dbutil import (
    BROWSE_BOOKMARK_LIGHT_EVENT_TYPE,
    EVENT_TYPE_VALUES,
    archive_event,
    count_browse_events,
    create_event,
    delete_event,
    get_browse_events_page,
    get_event_attendance_records,
    get_event_by_id,
    get_event_listing_by_id,
    friend_event,
    is_event_archived,
    join_event,
    leave_event,
    note_event,
    signin_event,
    update_event,
)

events_bp = Blueprint(
    "events",
    __name__,
    url_prefix="/lightboard",
    template_folder="templates",
    static_folder="static",
    static_url_path="/static",
)

BROWSE_PAGE_SIZE = 5
BROWSE_MORE_MAX_LIMIT = 20


def _event_can_be_ended(event, attendee_count):
    is_started = event["starttime_obj"] < datetime.now()
    minplayer = event.get("minplayer")
    enough_people = (minplayer is None) or (attendee_count >= minplayer)
    return is_started and enough_people


def _render_add_event(current_user, selected_event_type="其他"):
    return render_template(
        "add.html",
        current_user=current_user,
        event_type_values=EVENT_TYPE_VALUES,
        selected_event_type=selected_event_type if selected_event_type in EVENT_TYPE_VALUES else "其他",
    )


def _ensure_temporary_user(user_db, username):
    existing = user_db.execute("SELECT id FROM user_info WHERE name=?", (username,)).fetchone()
    if existing:
        return
    user_db.execute(
        f"""
        INSERT INTO user_info (
            name,
            password_hash,
            icon,
            title,
            {MANAGE_ACCOUNT_PERMISSION},
            {SCRIPT_BITMAP_COLUMN},
            {LIGHTBOARD_BITMAP_COLUMN},
            {ASSOCIATION_ROLE_COLUMN},
            {SOCIAL_ROLE_COLUMN},
            {CONTACT_INFO_COLUMN},
            {ACTIVITY_ORGANIZED_COUNT_COLUMN},
            {ACTIVITY_JOINED_COUNT_COLUMN},
            {ACTIVITY_ABSENT_COUNT_COLUMN},
            lastLogin
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            username,
            "",
            "",
            "",
            0,
            0,
            0,
            "普通玩家",
            "保密",
            "保密",
            0,
            0,
            0,
            datetime.utcnow(),
        ),
    )


def _browse_tab_and_filters_for_tab(tab_raw):
    """活动板书签：tab=all | light | my。"""
    tab = (tab_raw or "all").strip()
    if tab not in ("all", "light", "my"):
        tab = "all"
    filters = {}
    if tab == "light":
        filters["event_type"] = BROWSE_BOOKMARK_LIGHT_EVENT_TYPE
    elif tab == "my":
        filters["my_activities_only"] = True
    return tab, filters


def _browse_filters_from_request():
    return _browse_tab_and_filters_for_tab(request.args.get("tab"))


@events_bp.route("/")
@login_required_template
def browse_events(user_info):
    current_user = user_info["name"]
    current_user_is_admin = user_info.get("association_role") == "管理员"
    browse_tab, browse_filters = _browse_filters_from_request()
    events_total = count_browse_events(current_user, browse_filters)
    events = get_browse_events_page(current_user, browse_filters, BROWSE_PAGE_SIZE, 0)
    enrich_events_attendees_user_ids(events)
    events_loaded = len(events)
    has_more_browse = events_loaded < events_total
    browse_next_offset = events_loaded
    return render_template(
        "browse.html",
        events=events,
        events_total=events_total,
        events_loaded=events_loaded,
        browse_tab=browse_tab,
        browse_page_size=BROWSE_PAGE_SIZE,
        browse_next_offset=browse_next_offset,
        browse_has_more=has_more_browse,
        has_more_browse=has_more_browse,
        current_user=current_user,
        current_user_is_admin=current_user_is_admin,
        now=datetime.now,
    )


@events_bp.route("/browse_more")
@login_required_template
def browse_events_more(user_info):
    """分页追加活动卡片 HTML 片段（JSON）。"""
    current_user = user_info["name"]
    current_user_is_admin = user_info.get("association_role") == "管理员"
    browse_tab, browse_filters = _browse_tab_and_filters_for_tab(request.args.get("tab"))
    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError:
        offset = 0
    try:
        limit = int(request.args.get("limit", BROWSE_PAGE_SIZE))
    except ValueError:
        limit = BROWSE_PAGE_SIZE
    limit = max(1, min(BROWSE_MORE_MAX_LIMIT, limit))

    total = count_browse_events(current_user, browse_filters)
    events = get_browse_events_page(current_user, browse_filters, limit, offset)
    enrich_events_attendees_user_ids(events)
    loaded_total = offset + len(events)
    html = render_template(
        "event_cards_rows.html",
        events=events,
        current_user=current_user,
        current_user_is_admin=current_user_is_admin,
        now=datetime.now,
    )
    return jsonify(
        {
            "status": "success",
            "html": html,
            "next_offset": loaded_total,
            "has_more": loaded_total < total,
            "loaded_total": loaded_total,
            "total": total,
        }
    )


@events_bp.route("/join/<int:event_id>", methods=["POST"])
@login_required_template
def join_event_route(user_info, event_id):
    current_user = user_info["name"]
    ev = get_event_by_id(event_id)
    if ev is None:
        flash("活动不存在。", "error")
        return redirect(url_for("events.browse_events"))
    if is_event_archived(ev):
        flash("活动已归档，无法报名。", "warning")
        return redirect(url_for("events.browse_events"))
    success, error = join_event(event_id, current_user)
    if success:
        flash("报名成功！期待您的参与。", "success")
    else:
        flash(error, "warning")
    return redirect(url_for("events.browse_events"))


@events_bp.route("/signin/<int:event_id>", methods=["POST"])
@token_required
def signin_event_route(current_user, event_id):  # fetch 须带 Cookie 或 Authorization: Bearer（见 browse.html）
    data = request.get_json()
    signcode = data.get("signcode")
    success, error = signin_event(event_id, current_user["name"], signcode)
    if success:
        return jsonify({"success": True, "message": "签到成功"}), 200
    return jsonify({"success": False, "message": error}), 200


@events_bp.route("/leave/<int:event_id>", methods=["POST"])
@login_required_template
def leave_event_route(user_info, event_id):
    current_user = user_info["name"]
    ev = get_event_by_id(event_id)
    if ev and is_event_archived(ev):
        flash("活动已归档，无法取消报名。", "warning")
        return redirect(url_for("events.browse_events"))
    if leave_event(event_id, current_user):
        flash("已取消报名。", "info")
    else:
        flash("您未曾报名此活动。", "error")
    return redirect(url_for("events.browse_events"))


@events_bp.route("/set_joininfo/<int:event_id>", methods=["POST"])
@token_required
def set_joininfo_route(current_user, event_id):  # fetch 须带 Cookie 或 Authorization: Bearer（见 browse.html）
    if not request.is_json:
        return jsonify({"success": False, "message": "Missing JSON in request"}), 400

    data = request.get_json()
    current_username = current_user["name"]
    ev = get_event_by_id(event_id)
    if ev is None:
        return jsonify({"success": False, "message": "活动不存在"}), 200
    if is_event_archived(ev):
        return jsonify({"success": False, "message": "活动已归档"}), 200

    note = data.get("note")
    if note:
        success, error = note_event(event_id, current_username, note)
        if success:
            return jsonify({"success": True, "message": "备注已成功保存"}), 200
        return jsonify({"success": False, "message": f"备注失败：{error}"}), 200

    friend = data.get("friend")
    listing = get_event_listing_by_id(event_id, current_username)
    if listing is None:
        return jsonify({"success": False, "message": "活动不存在"}), 200
    try:
        if friend == "+":
            maxp = listing.get("maxplayer")
            if maxp is not None and int(maxp) > int(listing.get("attendee_count", 0)):
                success, error = friend_event(event_id, current_username, int(listing["user_friends"]) + 1)
                if success:
                    return jsonify({"success": True, "message": "随行人已成功保存"}), 200
                return jsonify({"success": False, "message": f"随行人设置失败：{error}"}), 200
            return jsonify({"success": False, "message": "随行人设置失败：已达人数上限。"}), 200
        if friend == "-":
            if int(listing["user_friends"]) > 0:
                success, error = friend_event(event_id, current_username, int(listing["user_friends"]) - 1)
                if success:
                    return jsonify({"success": True, "message": "随行人已成功保存"}), 200
                return jsonify({"success": False, "message": f"随行人设置失败：{error}"}), 200
            return jsonify({"success": False, "message": "随行人设置失败：你没有随行人。"}), 200
    except Exception:
        return jsonify({"success": False, "message": "服务器内部错误"}), 500

    return jsonify({"success": False, "message": "服务器内部错误"}), 500


@events_bp.route("/add", methods=["GET", "POST"])
@login_required_template
def add_event_route(user_info):
    current_user = user_info["name"]
    if request.method == "POST":
        try:
            minplayer_str = request.form.get("minplayer")
            maxplayer_str = request.form.get("maxplayer")
            minplayer = int(minplayer_str) if minplayer_str else None
            maxplayer = int(maxplayer_str) if maxplayer_str else None
        except ValueError:
            flash("最小/最大玩家数必须是数字！", "error")
            return _render_add_event(current_user, request.form.get("event_type", "其他"))

        event_type = request.form.get("event_type", "其他")
        if event_type not in EVENT_TYPE_VALUES:
            flash("活动类型无效，请重新选择。", "error")
            return _render_add_event(current_user, event_type)

        data = {
            "name": request.form["name"],
            "inviter": current_user,
            "location": request.form["location"],
            "starttime": request.form["starttime"],
            "locktime": request.form["locktime"],
            "description": request.form.get("description", ""),
            "minplayer": minplayer,
            "maxplayer": maxplayer,
            "event_type": event_type,
        }
        if data["name"] and data["location"] and data["starttime"]:
            create_event(data)
            flash("活动添加成功！", "success")
            return redirect(url_for("events.browse_events"))
    return _render_add_event(current_user)


@events_bp.route("/edit/<int:event_id>", methods=["GET", "POST"])
@login_required_template
def edit_event_route(user_info, event_id):
    event = get_event_by_id(event_id)
    current_user = user_info["name"]
    current_user_is_admin = user_info.get("association_role") == "管理员"
    if event is None or (not current_user_is_admin and event["inviter"] != current_user):
        flash("您无权编辑此活动或活动不存在。", "error")
        return redirect(url_for("events.browse_events"))

    if is_event_archived(event):
        flash("该活动已归档，无法编辑。", "warning")
        return redirect(url_for("events.browse_events"))

    if request.method == "POST":
        try:
            minplayer_str = request.form.get("minplayer")
            maxplayer_str = request.form.get("maxplayer")
            minplayer = int(minplayer_str) if minplayer_str else None
            maxplayer = int(maxplayer_str) if maxplayer_str else None
        except ValueError:
            flash("最小/最大玩家数必须是数字！", "error")
            return render_template("edit.html", event=event, current_user=current_user, event_type_values=EVENT_TYPE_VALUES)

        event_type = request.form.get("event_type", "其他")
        if event_type not in EVENT_TYPE_VALUES:
            flash("活动类型无效，请重新选择。", "error")
            return render_template("edit.html", event=event, current_user=current_user, event_type_values=EVENT_TYPE_VALUES)

        data = {
            "name": request.form["name"],
            "location": request.form["location"],
            "starttime": request.form["starttime"],
            "locktime": request.form["locktime"],
            "description": request.form.get("description", ""),
            "minplayer": minplayer,
            "maxplayer": maxplayer,
            "event_type": event_type,
        }
        if data["name"] and data["location"] and data["starttime"]:
            update_event(event_id, data)
            flash("活动更新成功！", "success")
            return redirect(url_for("events.browse_events"))
        else:
            flash("活动信息不完整（名字/地点/开始时间）！", "error")
            return render_template("edit.html", event=event, current_user=current_user, event_type_values=EVENT_TYPE_VALUES)
    return render_template("edit.html", event=event, current_user=current_user, event_type_values=EVENT_TYPE_VALUES)


@events_bp.route("/delete/<int:event_id>", methods=["POST"])
@events_bp.route("/archive/<int:event_id>", methods=["POST"])
@login_required_template
def archive_event_route(user_info, event_id):
    ensure_user_permission_schema()
    event = get_event_by_id(event_id)
    current_user = user_info["name"]
    current_user_is_admin = user_info.get("association_role") == "管理员"
    if event is None or (not current_user_is_admin and event["inviter"] != current_user):
        flash("您无权归档此活动或活动不存在。", "error")
        return redirect(url_for("events.browse_events"))

    if is_event_archived(event):
        flash("该活动已经归档。", "info")
        return redirect(url_for("events.browse_events"))

    listing = get_event_listing_by_id(event_id, current_user)
    attendee_count = int(listing.get("attendee_count", 0)) if listing else 0

    if _event_can_be_ended(event, attendee_count):
        attendance_records = get_event_attendance_records(event_id)
        user_db = get_user_db()
        _ensure_temporary_user(user_db, event["inviter"])

        user_db.execute(
            f"""
            UPDATE user_info
            SET {ACTIVITY_ORGANIZED_COUNT_COLUMN} = COALESCE({ACTIVITY_ORGANIZED_COUNT_COLUMN}, 0) + 1
            WHERE name = ?
            """,
            (event["inviter"],),
        )
        for attendance in attendance_records:
            player = attendance["player"]
            _ensure_temporary_user(user_db, player)
            if int(attendance.get("signed", 0)) > 0:
                user_db.execute(
                    f"""
                    UPDATE user_info
                    SET {ACTIVITY_JOINED_COUNT_COLUMN} = COALESCE({ACTIVITY_JOINED_COUNT_COLUMN}, 0) + 1
                    WHERE name = ?
                    """,
                    (player,),
                )
            else:
                user_db.execute(
                    f"""
                    UPDATE user_info
                    SET {ACTIVITY_ABSENT_COUNT_COLUMN} = COALESCE({ACTIVITY_ABSENT_COUNT_COLUMN}, 0) + 1
                    WHERE name = ?
                    """,
                    (player,),
                )
        user_db.commit()
        user_db.close()
        archive_event(event_id)
        flash("活动已结束，参与记录已归档。", "success")
    else:
        # 如果活动无法结束（可能根本没组起来），就直接删除即可，不需要归档。
        delete_event(event_id)
        flash("活动和所有相关报名记录已成功删除！", "success")

    return redirect(url_for("events.browse_events"))
