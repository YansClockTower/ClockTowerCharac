import hashlib
import hmac
import json
from flask import Blueprint, redirect, render_template, request, jsonify, make_response, send_file, url_for
import jwt
import datetime

from app.models.database import get_user_db
from app.models.crypt import hash_password, verify_password
from app.models.config import get_config
from app.identity import get_current_user, login_required_template, token_required
from app.identity.permissions import (
    ACTIVITY_ABSENT_COUNT_COLUMN,
    ACTIVITY_JOINED_COUNT_COLUMN,
    ACTIVITY_ORGANIZED_COUNT_COLUMN,
    ASSOCIATION_ROLE_COLUMN,
    ASSOCIATION_ROLE_VALUES,
    CONTACT_INFO_COLUMN,
    MANAGE_ACCOUNT_PERMISSION,
    SCRIPT_BITMAP_COLUMN,
    SOCIAL_ROLE_COLUMN,
    SOCIAL_ROLE_VALUES,
    LIGHTBOARD_BITMAP_COLUMN,
    build_permission_update_fields,
    enrich_user_permissions,
    ensure_user_permission_schema,
    permission_bitmap_descriptions,
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


def _serialize_user_profile(user):
    return {
        "status": "success",
        "username": user['name'],
        "id": user['id'],
        "permission_manage_account": user[MANAGE_ACCOUNT_PERMISSION],
        "permission_manage_accounts": user['permission_manage_accounts'],
        "permission_manage_own_editions": user['permission_manage_own_editions'],
        "permission_manage_all_editions": user['permission_manage_all_editions'],
        "permission_manage_create_editions": user['permission_manage_create_editions'],
        "permission_storyteller": user['permission_storyteller'],
        "permission_storyteller_vocal": user['permission_storyteller_vocal'],
        SCRIPT_BITMAP_COLUMN: user[SCRIPT_BITMAP_COLUMN],
        LIGHTBOARD_BITMAP_COLUMN: user[LIGHTBOARD_BITMAP_COLUMN],
        ASSOCIATION_ROLE_COLUMN: user.get(ASSOCIATION_ROLE_COLUMN, "普通玩家"),
        SOCIAL_ROLE_COLUMN: user.get(SOCIAL_ROLE_COLUMN, "保密"),
        CONTACT_INFO_COLUMN: user.get(CONTACT_INFO_COLUMN, "保密"),
        ACTIVITY_ORGANIZED_COUNT_COLUMN: user.get(ACTIVITY_ORGANIZED_COUNT_COLUMN, 0),
        ACTIVITY_JOINED_COUNT_COLUMN: user.get(ACTIVITY_JOINED_COUNT_COLUMN, 0),
        ACTIVITY_ABSENT_COUNT_COLUMN: user.get(ACTIVITY_ABSENT_COUNT_COLUMN, 0),
        "lastLogin": user['lastLogin'],
    }


# ---------------- 路由 ----------------
@users_bp.route("/")
@login_required_template
def user_page(user_info):
    return render_template(
            'view_user.html',user_info=user_info # 将从数据库获取的字典传递给前端模板
    )

@users_bp.route("/login")
def user_login():
    return render_template(
            'login.html'
    )

@users_bp.route("/register_submit", methods=["POST"])
def register():
    username = request.form.get("username") or (request.json.get("username") if request.is_json else None)
    password = request.form.get("password") or (request.json.get("password") if request.is_json else None)

    if not username or not password:
        return jsonify({"status": "failed", "reason": "Missing username or password"})

    ensure_user_permission_schema()
    user_db = get_user_db()
    existing_user = user_db.execute("SELECT * FROM user_info WHERE name=?", (username,)).fetchone()

    if existing_user and not _is_temporary_user(existing_user):
        return jsonify({"status": "failed", "reason": "Username already exists"})

    hashed_pw = hash_password(password)
    if existing_user and _is_temporary_user(existing_user):
        # 覆盖临时用户，但保留其活动统计数据。
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
                lastLogin = ?
            WHERE name = ?
            """,
            (hashed_pw, "", "", datetime.datetime.utcnow(), username),
        )
    else:
        new_user = (
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
            datetime.datetime.utcnow(),
        )
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
                lastLogin
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            new_user,
        )
    user_db.commit()
    user_db.close()

    return jsonify({"status": "success"})


@users_bp.route("/login_submit", methods=["POST"])
def login():
    username = request.form.get("username") or (request.json.get("username") if request.is_json else None)
    password = request.form.get("password") or (request.json.get("password") if request.is_json else None)

    if not username or not password:
        return jsonify({"status": "failed", "reason": "Missing username or password"})

    user_db = get_user_db()
    user = user_db.execute("SELECT * FROM user_info WHERE name=?", (username,)).fetchone()
    user_db.close()

    if not user or _is_temporary_user(user):
        return jsonify({"status": "failed", "reason": "用户不存在请注册"})
    if not verify_password(user['password_hash'], password):
        return jsonify({"status": "failed", "reason": "Invalid username or password"})

    token = jwt.encode(
        {"user_id": user['id'], "exp": datetime.datetime.utcnow() + datetime.timedelta(days=365)},
        get_config('secret_key'),
        algorithm="HS256"
    )

    resp = make_response(jsonify({"status": "success", "id": user['id'], "token": token}))

    # generate cookies
    resp.set_cookie("token", token, httponly=True, samesite="Lax")

    return resp

@users_bp.route("/logout", methods=["POST"])
def logout():
    resp = make_response(jsonify({"status": "success"}))
    resp.delete_cookie("token")
    return resp


@users_bp.route("/me", methods=["GET"])
@token_required
def me(current_user):
    secret_key = get_config('secret_key')
    # 用户信息数据（不含签名）
    user_data = {
        "status": "success", 
        "username": current_user['name'],
        "id": current_user['id'],
        "permission_manage_account": current_user[MANAGE_ACCOUNT_PERMISSION],
        "permission_manage_accounts": current_user['permission_manage_accounts'],
        "permission_manage_own_editions": current_user['permission_manage_own_editions'],
        "permission_manage_all_editions": current_user['permission_manage_all_editions'],
        "permission_manage_create_editions": current_user['permission_manage_create_editions'],
        "permission_storyteller": current_user['permission_storyteller'],
        "permission_storyteller_vocal": current_user['permission_storyteller_vocal'],
        SCRIPT_BITMAP_COLUMN: current_user[SCRIPT_BITMAP_COLUMN],
        LIGHTBOARD_BITMAP_COLUMN: current_user[LIGHTBOARD_BITMAP_COLUMN],
        ASSOCIATION_ROLE_COLUMN: current_user.get(ASSOCIATION_ROLE_COLUMN, "普通玩家"),
        SOCIAL_ROLE_COLUMN: current_user.get(SOCIAL_ROLE_COLUMN, "保密"),
        CONTACT_INFO_COLUMN: current_user.get(CONTACT_INFO_COLUMN, "保密"),
        ACTIVITY_ORGANIZED_COUNT_COLUMN: current_user.get(ACTIVITY_ORGANIZED_COUNT_COLUMN, 0),
        ACTIVITY_JOINED_COUNT_COLUMN: current_user.get(ACTIVITY_JOINED_COUNT_COLUMN, 0),
        ACTIVITY_ABSENT_COUNT_COLUMN: current_user.get(ACTIVITY_ABSENT_COUNT_COLUMN, 0),
        "lastLogin": current_user['lastLogin']
    }

    # 序列化为字符串（确保顺序一致）
    payload = json.dumps(user_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    # 使用 HMAC-SHA256 生成签名
    signature = hmac.new(
        secret_key.encode("utf-8"), 
        payload.encode("utf-8"), 
        hashlib.sha256
    ).hexdigest()

    # 返回带签名的数据
    return jsonify({**user_data, "signature": signature})


@users_bp.route("/read_icon/<int:id>", methods=["GET"])
def read_icon(id):
    return send_file(user_icon_url(id), mimetype=f'image/jpg')
    
# --- 新增上传头像路由 ---
@users_bp.route("/upload_icon", methods=["POST"])
@token_required
def upload_icon(current_user): # current_user 由 token_required 装饰器提供
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
def social_role_update(current_user):
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
def permission_bitmap_definition(_current_user):
    return jsonify({"status": "success", "bitmap_definition": permission_bitmap_descriptions()})