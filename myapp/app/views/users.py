import hashlib
import hmac
import json
from urllib.parse import unquote

from flask import Blueprint, flash, redirect, render_template, request, jsonify, make_response, send_file, url_for
import jwt
import datetime

from app.models.database import get_user_db
from app.models.crypt import hash_password, verify_password
from app.models.config import get_config
from app.models.mailer import send_verification_code
from app.identity import get_current_user, login_required_template, token_required
from app.identity.auth import extract_auth_token, safe_redirect_target
from app.identity.permissions import (
    ACTIVITY_ABSENT_COUNT_COLUMN,
    ACTIVITY_JOINED_COUNT_COLUMN,
    ACTIVITY_ORGANIZED_COUNT_COLUMN,
    ASSOCIATION_ROLE_COLUMN,
    ASSOCIATION_ROLE_VALUES,
    CONTACT_INFO_COLUMN,
    EMAIL_COLUMN,
    EMAIL_VERIFIED_COLUMN,
    MANAGE_ACCOUNT_PERMISSION,
    MEMBER_ORDER_NO_COLUMN,
    MEMBER_REVIEW_NOTE_COLUMN,
    SCRIPT_BITMAP_COLUMN,
    SOCIAL_ROLE_COLUMN,
    SOCIAL_ROLE_VALUES,
    LIGHTBOARD_BITMAP_COLUMN,
    build_permission_update_fields,
    enrich_user_permissions,
    ensure_user_permission_schema,
    permission_bitmap_descriptions,
)
from app.user.email_codes import (
    bind_user_email,
    consume_email_code,
    create_email_code,
    find_user_by_account,
    find_user_by_email,
    is_valid_email,
    normalize_email,
    user_email_verified,
)
from app.user.membership import (
    silent_verify_membership,
    submit_member_order,
    user_is_member,
    user_member_locked,
)

from app.models.usericon import save_user_icon, user_icon_url

# 注意：db和app在主程序中初始化，然后注入
users_bp = Blueprint(
    "users",
    __name__,
    url_prefix="/user",
    template_folder="../user/templates",
    static_folder="../user/static",
    static_url_path="/user/static",
)


def _is_temporary_user(user_row) -> bool:
    if not user_row:
        return False
    password_hash = user_row["password_hash"] if "password_hash" in user_row.keys() else None
    return password_hash is None or password_hash == ""


def _row_get(user, key, default=None):
    if not user:
        return default
    try:
        if key in user.keys():
            val = user[key]
            return default if val is None else val
    except Exception:
        pass
    return default


def _issue_auth_response(user, extra=None):
    token = jwt.encode(
        {"user_id": user["id"], "exp": datetime.datetime.utcnow() + datetime.timedelta(days=365)},
        get_config("secret_key"),
        algorithm="HS256",
    )
    if isinstance(token, bytes):
        token = token.decode("ascii")
    payload = {"status": "success", "id": user["id"], "token": token}
    if extra:
        payload.update(extra)
    resp = make_response(jsonify(payload))
    resp.set_cookie("token", token, httponly=True, samesite="Lax")
    return resp


def _json_body():
    if request.is_json:
        return request.get_json(silent=True) or {}
    return {}


def _req_val(*keys):
    body = _json_body()
    for key in keys:
        v = request.form.get(key)
        if v is None:
            v = body.get(key)
        if v is not None and str(v).strip() != "":
            return v if not isinstance(v, str) else v.strip()
    return None


def _serialize_user_profile(user):
    member_order = _row_get(user, MEMBER_ORDER_NO_COLUMN, "") or ""
    email = _row_get(user, EMAIL_COLUMN, "") or ""
    return {
        "status": "success",
        "username": user["name"],
        "id": user["id"],
        "permission_manage_account": user[MANAGE_ACCOUNT_PERMISSION],
        "permission_manage_accounts": user["permission_manage_accounts"],
        "permission_manage_own_editions": user["permission_manage_own_editions"],
        "permission_manage_all_editions": user["permission_manage_all_editions"],
        "permission_manage_create_editions": user["permission_manage_create_editions"],
        "permission_storyteller": user["permission_storyteller"],
        "permission_storyteller_vocal": user["permission_storyteller_vocal"],
        SCRIPT_BITMAP_COLUMN: user[SCRIPT_BITMAP_COLUMN],
        LIGHTBOARD_BITMAP_COLUMN: user[LIGHTBOARD_BITMAP_COLUMN],
        ASSOCIATION_ROLE_COLUMN: user.get(ASSOCIATION_ROLE_COLUMN, "普通玩家"),
        SOCIAL_ROLE_COLUMN: user.get(SOCIAL_ROLE_COLUMN, "保密"),
        CONTACT_INFO_COLUMN: user.get(CONTACT_INFO_COLUMN, "保密"),
        ACTIVITY_ORGANIZED_COUNT_COLUMN: user.get(ACTIVITY_ORGANIZED_COUNT_COLUMN, 0),
        ACTIVITY_JOINED_COUNT_COLUMN: user.get(ACTIVITY_JOINED_COUNT_COLUMN, 0),
        ACTIVITY_ABSENT_COUNT_COLUMN: user.get(ACTIVITY_ABSENT_COUNT_COLUMN, 0),
        "email": email,
        "email_verified": bool(_row_get(user, EMAIL_VERIFIED_COLUMN, 0)),
        "member_order_no": member_order,
        "member_review_note": _row_get(user, MEMBER_REVIEW_NOTE_COLUMN, "") or "",
        "is_member": user_is_member(user),
        "member_locked": user_member_locked(user),
        "member_pending": bool(member_order) and not user_is_member(user),
        "lastLogin": user["lastLogin"],
    }


# ---------------- 路由 ----------------
@users_bp.route("/")
@login_required_template
def user_page(user_info):
    ensure_user_permission_schema()
    user_db = get_user_db()
    row = user_db.execute("SELECT * FROM user_info WHERE id=?", (user_info["id"],)).fetchone()
    user_db.close()
    profile = enrich_user_permissions(dict(row)) if row else user_info
    return render_template("view_user.html", user_info=profile)


@users_bp.route("/profile/<int:user_id>", methods=["GET"])
@login_required_template
def view_user_profile(user_info, user_id):
    """查看其他用户公开资料（只读）；与本人中心区分。"""
    if int(user_id) == int(user_info["id"]):
        return redirect(url_for("users.user_page"))

    ensure_user_permission_schema()
    user_db = get_user_db()
    row = user_db.execute("SELECT * FROM user_info WHERE id=?", (user_id,)).fetchone()
    user_db.close()
    if not row:
        flash("未找到该用户。", "error")
        return redirect(url_for("events.browse_events"))

    profile = enrich_user_permissions(dict(row))
    profile.pop("password_hash", None)
    return render_template("view_user_public.html", profile=profile)


@users_bp.route("/login")
def user_login():
    raw_next = request.args.get("next")
    next_url = ""
    if raw_next:
        next_url = safe_redirect_target(unquote(raw_next)) or ""
    return render_template("login.html", next_url=next_url)

@users_bp.route("/register_submit", methods=["POST"])
def register():
    username = _req_val("username")
    password = _req_val("password")
    email = normalize_email(_req_val("email") or "")
    code = _req_val("code")

    if not username or not password:
        return jsonify({"status": "failed", "reason": "Missing username or password"})
    if not email or not is_valid_email(email):
        return jsonify({"status": "failed", "reason": "请填写有效邮箱"})
    if not code:
        return jsonify({"status": "failed", "reason": "请填写邮箱验证码"})
    if len(password) < 6:
        return jsonify({"status": "failed", "reason": "密码至少 6 位"})

    ensure_user_permission_schema()
    if find_user_by_email(email):
        return jsonify({"status": "failed", "reason": "该邮箱已被注册"})

    if not consume_email_code(email, code, purpose="register"):
        return jsonify({"status": "failed", "reason": "验证码无效或已过期"})

    user_db = get_user_db()
    existing_user = user_db.execute("SELECT * FROM user_info WHERE name=?", (username,)).fetchone()

    if existing_user and not _is_temporary_user(existing_user):
        user_db.close()
        return jsonify({"status": "failed", "reason": "Username already exists"})

    hashed_pw = hash_password(password)
    if existing_user and _is_temporary_user(existing_user):
        user_db.execute(
            f"""
            UPDATE user_info
            SET
                password_hash = ?,
                icon = ?,
                title = ?,
                {MANAGE_ACCOUNT_PERMISSION} = 0,
                {SCRIPT_BITMAP_COLUMN} = 0,
                {LIGHTBOARD_BITMAP_COLUMN} = 0,
                {ASSOCIATION_ROLE_COLUMN} = '普通玩家',
                {SOCIAL_ROLE_COLUMN} = '保密',
                {CONTACT_INFO_COLUMN} = '保密',
                {EMAIL_COLUMN} = ?,
                {EMAIL_VERIFIED_COLUMN} = 1,
                lastLogin = ?
            WHERE name = ?
            """,
            (hashed_pw, "", "", email, datetime.datetime.utcnow(), username),
        )
    else:
        user_db.execute(
            f"""INSERT INTO user_info
            (
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
                {EMAIL_COLUMN},
                {EMAIL_VERIFIED_COLUMN},
                lastLogin
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                username,
                hashed_pw,
                "",
                "",
                False,
                0,
                0,
                "普通玩家",
                "保密",
                "保密",
                0,
                0,
                0,
                email,
                1,
                datetime.datetime.utcnow(),
            ),
        )
    user_db.commit()
    user = user_db.execute("SELECT * FROM user_info WHERE name=?", (username,)).fetchone()
    user_db.close()
    return _issue_auth_response(user)


@users_bp.route("/send_code", methods=["POST"])
def send_code():
    email = normalize_email(_req_val("email") or "")
    if not email or not is_valid_email(email):
        return jsonify({"status": "failed", "reason": "请填写有效邮箱"})
    if find_user_by_email(email):
        return jsonify({"status": "failed", "reason": "该邮箱已被注册"})
    code, err = create_email_code(email, purpose="register")
    if err:
        return jsonify({"status": "failed", "reason": err})
    ok, detail = send_verification_code(email, code, purpose="register")
    if not ok:
        return jsonify({"status": "failed", "reason": f"发送失败：{detail}"})
    return jsonify({"status": "success", "delivery": detail})


@users_bp.route("/send_reset_code", methods=["POST"])
def send_reset_code():
    account = _req_val("account", "username", "email") or ""
    user = find_user_by_account(account)
    if not user:
        return jsonify({"status": "failed", "reason": "未找到该账号"})
    if not user_email_verified(user):
        return jsonify({"status": "failed", "reason": "尚未验证邮箱，无法重设密码"})
    email = normalize_email(user["email"])
    code, err = create_email_code(email, purpose="reset")
    if err:
        return jsonify({"status": "failed", "reason": err})
    ok, detail = send_verification_code(email, code, purpose="reset")
    if not ok:
        return jsonify({"status": "failed", "reason": f"发送失败：{detail}"})
    return jsonify({"status": "success", "delivery": detail})


@users_bp.route("/reset_password_submit", methods=["POST"])
def reset_password_submit():
    account = _req_val("account", "username", "email") or ""
    code = _req_val("code") or ""
    password = _req_val("password", "new_password") or ""
    password2 = _req_val("password2", "new_password2")
    if not account or not code or not password:
        return jsonify({"status": "failed", "reason": "请填写完整信息"})
    if len(password) < 6:
        return jsonify({"status": "failed", "reason": "密码至少 6 位"})
    if password2 is not None and password != password2:
        return jsonify({"status": "failed", "reason": "两次密码不一致"})

    user = find_user_by_account(account)
    if not user:
        return jsonify({"status": "failed", "reason": "未找到该账号"})
    if not user_email_verified(user):
        return jsonify({"status": "failed", "reason": "尚未验证邮箱，无法重设密码"})
    email = normalize_email(user["email"])
    if not consume_email_code(email, code, purpose="reset"):
        return jsonify({"status": "failed", "reason": "验证码无效或已过期"})

    ensure_user_permission_schema()
    user_db = get_user_db()
    user_db.execute(
        "UPDATE user_info SET password_hash = ? WHERE id = ?",
        (hash_password(password), user["id"]),
    )
    user_db.commit()
    latest = user_db.execute("SELECT * FROM user_info WHERE id = ?", (user["id"],)).fetchone()
    user_db.close()
    return _issue_auth_response(latest)


@users_bp.route("/send_bind_code", methods=["POST"])
@token_required
def send_bind_code(current_user):
    email = normalize_email(_req_val("email") or "")
    if not email or not is_valid_email(email):
        return jsonify({"status": "failed", "reason": "请填写有效邮箱"})
    other = find_user_by_email(email)
    if other and other["id"] != current_user["id"]:
        return jsonify({"status": "failed", "reason": "该邮箱已被其他账号使用"})
    code, err = create_email_code(email, purpose="bind")
    if err:
        return jsonify({"status": "failed", "reason": err})
    ok, detail = send_verification_code(email, code, purpose="bind")
    if not ok:
        return jsonify({"status": "failed", "reason": f"发送失败：{detail}"})
    return jsonify({"status": "success", "delivery": detail})


@users_bp.route("/bind_email_submit", methods=["POST"])
@token_required
def bind_email_submit(current_user):
    email = normalize_email(_req_val("email") or "")
    code = _req_val("code") or ""
    if not email or not is_valid_email(email):
        return jsonify({"status": "failed", "reason": "请填写有效邮箱"})
    if not code:
        return jsonify({"status": "failed", "reason": "请填写验证码"})
    if not consume_email_code(email, code, purpose="bind"):
        return jsonify({"status": "failed", "reason": "验证码无效或已过期"})
    ok, err = bind_user_email(current_user["name"], email)
    if not ok:
        return jsonify({"status": "failed", "reason": err or "绑定失败"})
    return jsonify({"status": "success", "email": email, "email_verified": True})


@users_bp.route("/login_submit", methods=["POST"])
def login():
    username = _req_val("username")
    password = _req_val("password")

    if not username or not password:
        return jsonify({"status": "failed", "reason": "Missing username or password"})

    user_db = get_user_db()
    user = user_db.execute("SELECT * FROM user_info WHERE name=?", (username,)).fetchone()
    user_db.close()

    if not user or _is_temporary_user(user):
        return jsonify({"status": "failed", "reason": "用户不存在，请先注册"})
    if not verify_password(user["password_hash"], password):
        return jsonify({"status": "failed", "reason": "密码有误"})

    return _issue_auth_response(user)
@users_bp.route("/logout", methods=["POST"])
def logout():
    resp = make_response(jsonify({"status": "success"}))
    resp.delete_cookie("token")
    return resp


@users_bp.route("/establish_session", methods=["POST"])
def establish_session():
    """用 Cookie 或 Bearer 中的 JWT 校验后（再）下发 HttpOnly Cookie，便于整页导航与 WebView 补全会话。"""
    token = extract_auth_token()
    if not token:
        return jsonify({"status": "failed", "reason": "缺少 token"}), 401
    user = get_current_user(update_last_login=False)
    if not user:
        return jsonify({"status": "failed", "reason": "无效或过期 token"}), 401
    resp = make_response(jsonify({"status": "success"}))
    resp.set_cookie("token", token, httponly=True, samesite="Lax")
    return resp


@users_bp.route("/me", methods=["GET"])
@token_required
def me(current_user):  # 须 Cookie 或 Authorization: Bearer；前端请用 ClockTowerAuth.authFetch
    ensure_user_permission_schema()
    user_db = get_user_db()
    row = user_db.execute("SELECT * FROM user_info WHERE id=?", (current_user["id"],)).fetchone()
    user_db.close()
    if not row:
        return jsonify({"status": "failed", "reason": "User not found"}), 404
    user = enrich_user_permissions(dict(row))
    user_data = _serialize_user_profile(user)

    secret_key = get_config("secret_key")
    payload = json.dumps(user_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    signature = hmac.new(
        secret_key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return jsonify({**user_data, "signature": signature})


@users_bp.route("/membership", methods=["GET", "POST"])
@login_required_template
def membership(user_info):
    ensure_user_permission_schema()
    if request.method == "POST":
        order_no = request.form.get("order_no") or ""
        ok, status, message = submit_member_order(user_info["name"], order_no)
        flash(message, "success" if ok else "error")
        if status == "granted":
            flash("会员资质已通过验证。", "success")
        return redirect(url_for("users.membership"))

    user_db = get_user_db()
    row = user_db.execute("SELECT * FROM user_info WHERE id=?", (user_info["id"],)).fetchone()
    user_db.close()
    profile = enrich_user_permissions(dict(row)) if row else user_info
    return render_template(
        "membership.html",
        user=profile,
        is_member=user_is_member(profile),
        member_locked=user_member_locked(profile),
        current_user=user_info["name"],
    )


@users_bp.route("/skip_email_prompt", methods=["POST"])
@token_required
def skip_email_prompt(_current_user):
    """前端可用 localStorage；此接口返回成功以便兼容。"""
    return jsonify({"status": "success"})


@users_bp.route("/read_icon/<int:id>", methods=["GET"])
def read_icon(id):
    return send_file(user_icon_url(id), mimetype=f'image/jpg')
    
# --- 新增上传头像路由 ---
@users_bp.route("/upload_icon", methods=["POST"])
@token_required
def upload_icon(current_user):  # current_user 由 token_required；fetch 须带 Cookie 或 Authorization: Bearer
    # 确保上传目录存在
    # 1. 检查请求中是否有文件部分
    if 'image' not in request.files:
        return jsonify({"status": "failed", "reason": "未找到图片文件"}), 400

    image = request.files['image']

    # 2. 检查文件名是否为空
    if image.filename == '':
        return jsonify({"status": "failed", "reason": "文件名不能为空"}), 400

    status, reason = save_user_icon(current_user['id'], image)
    if status:
        return jsonify({
            "status": "success",
            "reason": "成功上传"
        })
    else:
        return jsonify({"status": "failed", "reason": reason}), 500
        
@users_bp.route("/view_user/<int:user_id>", methods=["POST"])
def view_user(user_id):
    user_db = get_user_db()
    user = user_db.execute("SELECT * FROM user_info WHERE id=?", (user_id,)).fetchone()
    user_db.close()
    if not user:
        return jsonify({"status": "failed", "reason": "User not found"})
    user = enrich_user_permissions(dict(user))
    return jsonify(_serialize_user_profile(user))


@users_bp.route("/view_user_by_name", methods=["POST"])
def view_user_by_name():
    # 须 Cookie 或 Authorization: Bearer；前端请用 ClockTowerAuth.authFetch（与 token_required 一致）
    operator = get_current_user(update_last_login=False)
    if not operator:
        return jsonify({"status": "failed", "reason": "请先登录"}), 401
    if not operator['permission_manage_accounts']:
        return jsonify({"status": "failed", "reason": "您没有权限查看其他用户档案"}), 403

    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None:
        payload = {}
    username = request.form.get("username") or payload.get("username")
    if not username:
        return jsonify({"status": "failed", "reason": "缺少用户名"})

    user_db = get_user_db()
    user = user_db.execute("SELECT * FROM user_info WHERE name=?", (username,)).fetchone()
    user_db.close()
    if not user:
        return jsonify({"status": "failed", "reason": "目标用户不存在"})
    user = enrich_user_permissions(dict(user))
    return jsonify(_serialize_user_profile(user))

@users_bp.route("/edit_user", methods=["GET"])
def edit_user():
    user = get_current_user(update_last_login=False)
    if not user:
        return redirect(url_for('users.user_page'))
    if not user['permission_manage_accounts']:
        return "❌ 您没有权限编辑其他用户，请联系管理员。"
    return render_template("edit_user.html")

@users_bp.route("/permission_update", methods=["POST"])
def permission_update():
    # 须 Cookie 或 Authorization: Bearer；前端请用 ClockTowerAuth.authFetch
    ensure_user_permission_schema()
    user = get_current_user(update_last_login=False)
    if not user:
        return redirect(url_for('users.user_page'))
    if not user['permission_manage_accounts']:
        return jsonify({"status": "failed", "reason": "您没有权限编辑其他用户"})
    
    username = request.form.get("username") or (request.json.get("username") if request.is_json else None)

    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None:
        payload = {}
    form_payload = request.form.to_dict() if request.form else {}
    merged_payload = {}
    merged_payload.update(form_payload)
    merged_payload.update(payload)

    user_db = get_user_db()
    user = user_db.execute("SELECT * FROM user_info WHERE name=?", (username,)).fetchone()
    if not user:
        user_db.close()
        return jsonify({"status": "failed", "reason": "目标用户不存在"})
    update_fields = build_permission_update_fields(merged_payload, dict(user))
    set_clause = ", ".join(f"{key}=?" for key in update_fields)
    update_values = list(update_fields.values())
    update_values.append(username)
    user_db.execute(f"UPDATE user_info SET {set_clause} WHERE name=?", update_values)
    user_db.commit()
    user_db.close()

    return jsonify({"status": "success"})


@users_bp.route("/association_role_update", methods=["POST"])
def association_role_update():
    # 须 Cookie 或 Authorization: Bearer；前端请用 ClockTowerAuth.authFetch
    ensure_user_permission_schema()
    user = get_current_user(update_last_login=False)
    if not user:
        return redirect(url_for('users.user_page'))
    if not user['permission_manage_accounts']:
        return jsonify({"status": "failed", "reason": "您没有权限编辑其他用户"})

    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None:
        payload = {}
    username = request.form.get("username") or payload.get("username")
    association_role = request.form.get(ASSOCIATION_ROLE_COLUMN) or payload.get(ASSOCIATION_ROLE_COLUMN)

    if not username:
        return jsonify({"status": "failed", "reason": "缺少目标用户名"})
    if association_role not in ASSOCIATION_ROLE_VALUES:
        return jsonify({"status": "failed", "reason": "无效的协会身份"})

    user_db = get_user_db()
    target = user_db.execute("SELECT id FROM user_info WHERE name=?", (username,)).fetchone()
    if not target:
        user_db.close()
        return jsonify({"status": "failed", "reason": "目标用户不存在"})
    user_db.execute(
        f"UPDATE user_info SET {ASSOCIATION_ROLE_COLUMN}=? WHERE name=?",
        (association_role, username),
    )
    user_db.commit()
    user_db.close()
    return jsonify({"status": "success", ASSOCIATION_ROLE_COLUMN: association_role})


@users_bp.route("/social_role_update", methods=["POST"])
@users_bp.route("/profile_update", methods=["POST"])
@token_required
def social_role_update(current_user):  # 须 Cookie 或 Authorization: Bearer
    ensure_user_permission_schema()
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None:
        payload = {}
    social_role = request.form.get(SOCIAL_ROLE_COLUMN) or payload.get(SOCIAL_ROLE_COLUMN)
    contact_info = request.form.get(CONTACT_INFO_COLUMN) or payload.get(CONTACT_INFO_COLUMN)

    update_parts = []
    update_values = []
    if social_role is not None:
        if social_role not in SOCIAL_ROLE_VALUES:
            return jsonify({"status": "failed", "reason": "无效的社会身份"})
        update_parts.append(f"{SOCIAL_ROLE_COLUMN}=?")
        update_values.append(social_role)

    if contact_info is not None:
        contact_info = str(contact_info).strip()
        if len(contact_info) > 128:
            return jsonify({"status": "failed", "reason": "联系方式过长（最多128字符）"})
        if not contact_info:
            contact_info = "保密"
        update_parts.append(f"{CONTACT_INFO_COLUMN}=?")
        update_values.append(contact_info)

    if not update_parts:
        return jsonify({"status": "failed", "reason": "未提供可更新字段"})

    user_db = get_user_db()
    update_values.append(current_user["id"])
    user_db.execute(f"UPDATE user_info SET {', '.join(update_parts)} WHERE id=?", update_values)
    user_db.commit()
    latest = user_db.execute(
        f"SELECT {SOCIAL_ROLE_COLUMN}, {CONTACT_INFO_COLUMN} FROM user_info WHERE id=?",
        (current_user["id"],),
    ).fetchone()
    user_db.close()
    return jsonify(
        {
            "status": "success",
            SOCIAL_ROLE_COLUMN: latest[SOCIAL_ROLE_COLUMN] if latest else (social_role or "保密"),
            CONTACT_INFO_COLUMN: latest[CONTACT_INFO_COLUMN] if latest else (contact_info or "保密"),
        }
    )


@users_bp.route("/permission_bitmap_definition", methods=["GET"])
@token_required
def permission_bitmap_definition(_current_user):  # 须 Cookie 或 Authorization: Bearer
    return jsonify({"status": "success", "bitmap_definition": permission_bitmap_descriptions()})