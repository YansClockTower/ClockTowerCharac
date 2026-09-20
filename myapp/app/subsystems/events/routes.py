from datetime import datetime

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from app.identity import login_required_template, token_required
from app.identity.permissions import (
    ACTIVITY_ABSENT_COUNT_COLUMN,
    ACTIVITY_JOINED_COUNT_COLUMN,
    ACTIVITY_ORGANIZED_COUNT_COLUMN,
    ASSOCIATION_ROLE_COLUMN,
    CONTACT_INFO_COLUMN,
    MANAGE_ACCOUNT_PERMISSION,
    SCRIPT_BITMAP_COLUMN,
    SOCIAL_ROLE_COLUMN,
    ensure_user_permission_schema,
    user_is_admin,
    user_is_staff,
)
from app.models.database import get_user_db
from app.subsystems.boardgames import api as boardgames_api
from app.subsystems.events.attendee_ids import (
    enrich_events_attendees_user_ids,
    enrich_events_inviter_contacts,
)
from app.subsystems.events.dbutil import (
    BROWSE_BOOKMARK_LIGHT_EVENT_TYPE,
    BROWSE_BOOKMARK_PIGEON_LABEL,
    FIXED_GATHERING_LABEL,
    FIXED_GATHERING_LOCATION,
    FREE_EVENT_TYPE_VALUES,
    PRESET_LOCATIONS,
    archive_event,
    create_event,
    delete_event,
    get_browse_events_page,
    get_event_attendance_records,
    get_event_by_id,
    get_event_listing_by_id,
    friend_event,
    is_event_archived,
    is_saturday_evening,
    join_event,
    leave_event,
    note_event,
    saturday_evening_error_message,
    signin_event,
    update_event,
)
from app.subsystems.events import fixed_dbutil as fixed
from app.user.membership import user_is_member

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


def _is_admin(user_info) -> bool:
    return user_is_admin(user_info)


def _is_staff(user_info) -> bool:
    return user_is_staff(user_info)


def _render_add_event(user_info, selected_event_type="其他"):
    return render_template(
        "add.html",
        current_user=user_info["name"],
        current_user_is_admin=_is_admin(user_info),
        current_user_is_staff=_is_staff(user_info),
        event_type_values=FREE_EVENT_TYPE_VALUES,
        preset_locations=PRESET_LOCATIONS,
        selected_event_type=selected_event_type if selected_event_type in FREE_EVENT_TYPE_VALUES else "其他",
    )


def _render_edit_event(event, user_info):
    return render_template(
        "edit.html",
        event=event,
        current_user=user_info["name"],
        current_user_is_admin=_is_admin(user_info),
        current_user_is_staff=_is_staff(user_info),
        event_type_values=FREE_EVENT_TYPE_VALUES,
        preset_locations=PRESET_LOCATIONS,
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
            {ASSOCIATION_ROLE_COLUMN},
            {SOCIAL_ROLE_COLUMN},
            {CONTACT_INFO_COLUMN},
            {ACTIVITY_ORGANIZED_COUNT_COLUMN},
            {ACTIVITY_JOINED_COUNT_COLUMN},
            {ACTIVITY_ABSENT_COUNT_COLUMN},
            lastLogin
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            username,
            "",
            "",
            "",
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
    """活动板书签：tab=all | light | pigeon | my。"""
    tab = (tab_raw or "all").strip()
    if tab not in ("all", "light", "pigeon", "my"):
        tab = "all"
    filters = {}
    if tab == "light":
        filters["event_type"] = BROWSE_BOOKMARK_LIGHT_EVENT_TYPE
        filters["free_only"] = True
    elif tab == "pigeon":
        filters["fixed_only"] = True
    elif tab == "my":
        filters["my_activities_only"] = True
    return tab, filters


def _browse_filters_from_request():
    return _browse_tab_and_filters_for_tab(request.args.get("tab"))


def _browse_merged_page(current_user, browse_filters, limit, offset):
    """合并自由聚会与固定聚会，按开始时间降序分页。"""
    if browse_filters.get("fixed_only"):
        free = []
    else:
        free = get_browse_events_page(current_user, browse_filters, limit=None, offset=0)
    fixed_list = fixed.list_fixed_events_for_browse(current_user, browse_filters)
    page, total = fixed.merge_browse_items(free, fixed_list, limit=limit, offset=offset)
    return page, total


def _redirect_after_fixed_table_action(event_id=None):
    """开桌、编辑、报名、退桌、承诺后回到活动列表。event_id 仅保留给调用处，不再打开详情页。"""
    tab = (request.form.get("tab") or "").strip()
    if (request.form.get("next") or "").strip() == "browse":
        if tab:
            return redirect(url_for("events.browse_events", tab=tab))
        return redirect(url_for("events.browse_events"))
    return redirect(url_for("events.browse_events", tab="pigeon"))


@events_bp.route("/")
@login_required_template
def browse_events(user_info):
    current_user = user_info["name"]
    current_user_is_admin = user_is_admin(user_info)
    current_user_is_member = user_is_member(user_info)
    browse_tab, browse_filters = _browse_filters_from_request()
    events, events_total = _browse_merged_page(current_user, browse_filters, BROWSE_PAGE_SIZE, 0)
    enrich_events_attendees_user_ids(events)
    enrich_events_inviter_contacts(events)
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
        current_user_is_member=current_user_is_member,
        current_user_is_staff=_is_staff(user_info),
        pigeon_tab_label=BROWSE_BOOKMARK_PIGEON_LABEL,
        now=datetime.now,
        games=boardgames_api.list_picker_rows() if current_user_is_member else [],
        picker_owners=boardgames_api.PICKER_OWNER_FILTERS,
        self_brought_id=fixed.SELF_BROUGHT_GAME_ID,
        self_brought_name=fixed.SELF_BROUGHT_GAME_NAME,
    )


@events_bp.route("/browse_more")
@login_required_template
def browse_events_more(user_info):
    """分页追加活动卡片 HTML 片段（JSON）。"""
    current_user = user_info["name"]
    current_user_is_admin = user_is_admin(user_info)
    current_user_is_member = user_is_member(user_info)
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

    events, total = _browse_merged_page(current_user, browse_filters, limit, offset)
    enrich_events_attendees_user_ids(events)
    enrich_events_inviter_contacts(events)
    loaded_total = offset + len(events)
    html = render_template(
        "browse_cards_mixed.html",
        events=events,
        current_user=current_user,
        current_user_is_admin=current_user_is_admin,
        current_user_is_member=current_user_is_member,
        browse_tab=browse_tab,
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


@events_bp.route("/choose_mode")
@login_required_template
def choose_event_mode(user_info):
    return render_template(
        "choose_mode.html",
        current_user=user_info["name"],
        current_user_is_staff=_is_staff(user_info),
        current_user_is_member=user_is_member(user_info),
        fixed_label=FIXED_GATHERING_LABEL,
        fixed_location=FIXED_GATHERING_LOCATION,
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
    if request.method == "POST":
        try:
            minplayer_str = request.form.get("minplayer")
            maxplayer_str = request.form.get("maxplayer")
            minplayer = int(minplayer_str) if minplayer_str else None
            maxplayer = int(maxplayer_str) if maxplayer_str else None
        except ValueError:
            flash("最小/最大玩家数必须是数字！", "error")
            return _render_add_event(user_info, request.form.get("event_type", "其他"))

        event_type = request.form.get("event_type", "其他")
        if event_type not in FREE_EVENT_TYPE_VALUES:
            flash("活动类型无效，请重新选择。", "error")
            return _render_add_event(user_info, event_type)

        location = (request.form.get("location") or "").strip()
        if location == FIXED_GATHERING_LOCATION:
            flash("南体活动室仅用于布鸽桌游聚会（固定聚会）。", "error")
            return _render_add_event(user_info, event_type)

        data = {
            "name": request.form["name"],
            "inviter": user_info["name"],
            "location": location,
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
    return _render_add_event(user_info)


@events_bp.route("/edit/<int:event_id>", methods=["GET", "POST"])
@login_required_template
def edit_event_route(user_info, event_id):
    event = get_event_by_id(event_id)
    current_user = user_info["name"]
    current_user_is_admin = _is_admin(user_info)
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
            return _render_edit_event(event, user_info)

        event_type = request.form.get("event_type", "其他")
        if event_type not in FREE_EVENT_TYPE_VALUES:
            flash("活动类型无效，请重新选择。", "error")
            return _render_edit_event(event, user_info)

        location = (request.form.get("location") or "").strip()
        if location == FIXED_GATHERING_LOCATION:
            flash("南体活动室仅用于布鸽桌游聚会（固定聚会）。", "error")
            return _render_edit_event(event, user_info)

        data = {
            "name": request.form["name"],
            "location": location,
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
            return _render_edit_event(event, user_info)
    return _render_edit_event(event, user_info)


@events_bp.route("/delete/<int:event_id>", methods=["POST"])
@events_bp.route("/archive/<int:event_id>", methods=["POST"])
@login_required_template
def archive_event_route(user_info, event_id):
    ensure_user_permission_schema()
    event = get_event_by_id(event_id)
    current_user = user_info["name"]
    current_user_is_admin = user_is_admin(user_info)
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


# ----- 固定聚会（布鸽桌游聚会） -----


def _render_fixed_add(user_info):
    return render_template(
        "fixed_add.html",
        current_user=user_info["name"],
        fixed_label=FIXED_GATHERING_LABEL,
        fixed_location=FIXED_GATHERING_LOCATION,
    )


def _render_fixed_edit(event, user_info):
    return render_template(
        "fixed_edit.html",
        event=event,
        current_user=user_info["name"],
        fixed_label=FIXED_GATHERING_LABEL,
        fixed_location=FIXED_GATHERING_LOCATION,
    )


def _require_fixed_staff(user_info):
    if _is_staff(user_info):
        return None
    return "仅干事及以上可发布布鸽桌游聚会。"


def _require_fixed_member(user_info):
    if user_is_member(user_info):
        return None
    return "布鸽桌游聚会仅限正式会员查看与报名，请先验证会员资质。"


def _fixed_payload_from_form(form):
    starttime = form.get("starttime", "")
    if not is_saturday_evening(starttime):
        return None, saturday_evening_error_message()
    try:
        minplayer_str = form.get("minplayer")
        maxplayer_str = form.get("maxplayer")
        minplayer = int(minplayer_str) if minplayer_str else None
        maxplayer = int(maxplayer_str) if maxplayer_str else None
    except ValueError:
        return None, "最小/最大玩家数必须是数字！"
    data = {
        "name": (form.get("name") or "").strip(),
        "location": FIXED_GATHERING_LOCATION,
        "starttime": starttime,
        "locktime": form.get("locktime", ""),
        "description": form.get("description", ""),
        "minplayer": minplayer,
        "maxplayer": maxplayer,
    }
    if not (data["name"] and data["starttime"] and data["locktime"]):
        return None, "请完整填写名称、开始时间与锁定时间。"
    return data, None


@events_bp.route("/fixed/add", methods=["GET", "POST"])
@login_required_template
def fixed_add_route(user_info):
    deny = _require_fixed_staff(user_info)
    if deny:
        flash(deny, "error")
        return redirect(url_for("events.choose_event_mode"))
    if request.method == "POST":
        data, err = _fixed_payload_from_form(request.form)
        if err:
            flash(err, "error")
            return _render_fixed_add(user_info)
        data["inviter"] = user_info["name"]
        event_id = fixed.create_fixed_event(data)
        flash("布鸽桌游聚会已发布！会员可在活动面板创建分桌与报名。", "success")
        return redirect(url_for("events.browse_events", tab="pigeon"))
    return _render_fixed_add(user_info)


@events_bp.route("/fixed/<int:event_id>")
@login_required_template
def fixed_detail_route(user_info, event_id):
    """旧的分桌详情页已并入活动列表，保留地址以免旧链接失效。"""
    return redirect(url_for("events.browse_events", tab="pigeon"))


@events_bp.route("/fixed/<int:event_id>/tables", methods=["POST"])
@login_required_template
def fixed_create_table_route(user_info, event_id):
    deny = _require_fixed_member(user_info)
    if deny:
        flash(deny, "warning")
        return redirect(url_for("users.membership"))
    current_user = user_info["name"]
    raw_id = (request.form.get("board_game_id") or "").strip()
    if raw_id in ("", "0", "self"):
        board_game_id = fixed.SELF_BROUGHT_GAME_ID
    else:
        try:
            board_game_id = int(raw_id)
        except ValueError:
            flash("请选择有效的桌游。", "error")
            return _redirect_after_fixed_table_action(event_id)
    note = request.form.get("note") or ""
    min_players = request.form.get("self_min_players")
    max_players = request.form.get("self_max_players")
    self_game_name = request.form.get("self_game_name") or ""
    ok, err, _tid = fixed.create_table(
        event_id,
        current_user,
        board_game_id,
        note=note,
        min_players=min_players,
        max_players=max_players,
        self_game_name=self_game_name,
    )
    if ok:
        if board_game_id == fixed.SELF_BROUGHT_GAME_ID:
            flash("开桌成功（组局者自备）！您已自动加入该桌。", "success")
        else:
            flash("开桌成功！您已自动加入该桌。请催促桌游所有者/持有者确认承诺。", "success")
    else:
        flash(err or "开桌失败。", "error")
    return _redirect_after_fixed_table_action(event_id)


@events_bp.route("/fixed/tables/<int:table_id>/edit", methods=["POST"])
@login_required_template
def fixed_update_table_route(user_info, table_id):
    deny = _require_fixed_member(user_info)
    if deny and not _is_admin(user_info):
        flash(deny, "warning")
        return redirect(url_for("users.membership"))
    raw_id = (request.form.get("board_game_id") or "").strip()
    if raw_id in ("", "0", "self"):
        board_game_id = fixed.SELF_BROUGHT_GAME_ID
    else:
        try:
            board_game_id = int(raw_id)
        except ValueError:
            flash("请选择有效的桌游。", "error")
            return _redirect_after_fixed_table_action(fixed.get_table_event_id(table_id))
    ok, err = fixed.update_table(
        table_id,
        user_info["name"],
        is_admin=_is_admin(user_info),
        board_game_id=board_game_id,
        note=request.form.get("note") or "",
        min_players=request.form.get("self_min_players"),
        max_players=request.form.get("self_max_players"),
        self_game_name=request.form.get("self_game_name") or "",
    )
    if ok:
        flash("已保存对此桌的修改。", "success")
    else:
        flash(err or "编辑失败。", "error")
    return _redirect_after_fixed_table_action(fixed.get_table_event_id(table_id))


@events_bp.route("/fixed/tables/<int:table_id>/join", methods=["POST"])
@login_required_template
def fixed_join_table_route(user_info, table_id):
    deny = _require_fixed_member(user_info)
    if deny:
        flash(deny, "warning")
        return redirect(url_for("users.membership"))
    ok, err = fixed.join_table(table_id, user_info["name"])
    if ok:
        flash("已报名该桌。", "success")
    else:
        flash(err or "报名失败。", "warning")
    return _redirect_after_fixed_table_action()


@events_bp.route("/fixed/tables/<int:table_id>/leave", methods=["POST"])
@login_required_template
def fixed_leave_table_route(user_info, table_id):
    deny = _require_fixed_member(user_info)
    if deny:
        flash(deny, "warning")
        return redirect(url_for("users.membership"))
    ok, err = fixed.leave_table(table_id, user_info["name"])
    if ok:
        flash("已退出该桌。", "info")
    else:
        flash(err or "退桌失败。", "warning")
    return _redirect_after_fixed_table_action()


@events_bp.route("/fixed/tables/<int:table_id>/confirm", methods=["POST"], endpoint="fixed_confirm_table_route")
@events_bp.route("/fixed/tables/<int:table_id>/reject", methods=["POST"], endpoint="fixed_reject_table_route")
@login_required_template
def fixed_set_table_commitment_route(user_info, table_id):
    deny = _require_fixed_member(user_info)
    if deny:
        flash(deny, "warning")
        return redirect(url_for("users.membership"))
    approved = request.path.rstrip("/").endswith("/confirm")
    ok, err = fixed.set_table_commitment(table_id, user_info["name"], approved)
    if ok:
        flash(
            "已确认承诺：允许使用该桌游 / 能将桌游带到场地。"
            if approved
            else "已拒绝本桌使用该桌游。",
            "success" if approved else "info",
        )
    else:
        flash(err or "操作失败。", "warning")
    return _redirect_after_fixed_table_action()


@events_bp.route("/fixed/<int:event_id>/signin", methods=["POST"])
@token_required
def fixed_signin_route(current_user, event_id):
    if not user_is_member(current_user):
        return jsonify({"success": False, "message": "仅限正式会员签到"}), 200
    data = request.get_json(silent=True) or {}
    signcode = data.get("signcode")
    success, error = fixed.signin_fixed_event(event_id, current_user["name"], signcode)
    if success:
        return jsonify({"success": True, "message": "签到成功"}), 200
    return jsonify({"success": False, "message": error}), 200


@events_bp.route("/fixed/<int:event_id>/edit", methods=["GET", "POST"])
@login_required_template
def fixed_edit_route(user_info, event_id):
    event = fixed.get_fixed_event_by_id(event_id)
    current_user = user_info["name"]
    if event is None or (not _is_admin(user_info) and event["inviter"] != current_user):
        flash("您无权编辑此活动或活动不存在。", "error")
        return redirect(url_for("events.browse_events"))
    if is_event_archived(event):
        flash("该活动已归档，无法编辑。", "warning")
        return redirect(url_for("events.browse_events", tab="pigeon"))

    if request.method == "POST":
        data, err = _fixed_payload_from_form(request.form)
        if err:
            flash(err, "error")
            return _render_fixed_edit(event, user_info)
        fixed.update_fixed_event(event_id, data)
        flash("布鸽桌游聚会信息已更新。", "success")
        return redirect(url_for("events.browse_events", tab="pigeon"))
    return _render_fixed_edit(event, user_info)


@events_bp.route("/fixed/<int:event_id>/archive", methods=["POST"])
@login_required_template
def fixed_archive_route(user_info, event_id):
    ensure_user_permission_schema()
    event = fixed.get_fixed_event_by_id(event_id)
    current_user = user_info["name"]
    if event is None or (not _is_admin(user_info) and event["inviter"] != current_user):
        flash("您无权归档此活动或活动不存在。", "error")
        return redirect(url_for("events.browse_events"))
    if is_event_archived(event):
        flash("该活动已经归档。", "info")
        return redirect(url_for("events.browse_events"))

    detail = fixed.get_fixed_event_detail(event_id, current_user)
    attendee_count = int(detail.get("attendee_count", 0)) if detail else 0

    if _event_can_be_ended(event, attendee_count):
        attendance_records = fixed.get_fixed_event_attendance_records(event_id)
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
        fixed.archive_fixed_event(event_id)
        flash("固定聚会已结束，参与记录已归档。", "success")
    else:
        fixed.delete_fixed_event(event_id)
        flash("固定聚会及分桌报名已删除。", "success")

    return redirect(url_for("events.browse_events"))
