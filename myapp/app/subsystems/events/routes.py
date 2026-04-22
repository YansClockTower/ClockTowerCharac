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
from app.subsystems.events.dbutil import (
    EVENT_TYPE_VALUES,
    create_event,
    delete_event,
    friend_event,
    get_all_events,
    get_event_attendance_records,
    get_event_by_id,
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


@events_bp.route("/")
@login_required_template
def browse_events(user_info):
    current_user = user_info["name"]
    current_user_is_admin = user_info.get("association_role") == "管理员"
    events = get_all_events(current_user)
    return render_template(
        "browse.html",
        events=events,
        current_user=current_user,
        current_user_is_admin=current_user_is_admin,
        now=datetime.now,
    )


@events_bp.route("/join/<int:event_id>", methods=["POST"])
@login_required_template
def join_event_route(user_info, event_id):
    current_user = user_info["name"]
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
    note = data.get("note")
    if note:
        success, error = note_event(event_id, current_username, note)
        if success:
            return jsonify({"success": True, "message": "备注已成功保存"}), 200
        return jsonify({"success": False, "message": f"备注失败：{error}"}), 200

    friend = data.get("friend")
    try:
        for event in get_all_events(current_username):
            if int(event["id"]) == int(event_id):
                if friend == "+":
                    if event["maxplayer"] > event["attendee_count"]:
                        success, error = friend_event(event_id, current_username, int(event["user_friends"]) + 1)
                        if success:
                            return jsonify({"success": True, "message": "随行人已成功保存"}), 200
                        return jsonify({"success": False, "message": f"随行人设置失败：{error}"}), 200
                    return jsonify({"success": False, "message": "随行人设置失败：已达人数上限。"}), 200
                if friend == "-":
                    if int(event["user_friends"]) > 0:
                        success, error = friend_event(event_id, current_username, int(event["user_friends"]) - 1)
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
@login_required_template
def delete_event_route(user_info, event_id):
    ensure_user_permission_schema()
    event = get_event_by_id(event_id)
    current_user = user_info["name"]
    current_user_is_admin = user_info.get("association_role") == "管理员"
    if event is None or (not current_user_is_admin and event["inviter"] != current_user):
        flash("您无权删除此活动或活动不存在。", "error")
        return redirect(url_for("events.browse_events"))

    attendee_count = 0
    for listed_event in get_all_events(current_user):
        if int(listed_event["id"]) == int(event_id):
            attendee_count = int(listed_event.get("attendee_count", 0))
            break

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
        delete_event(event_id)
        flash("活动已结束，参与档案已归档并删除活动。", "success")
    else:
        delete_event(event_id)
        flash("活动和所有相关报名记录已成功删除！", "success")

    return redirect(url_for("events.browse_events"))

