import hashlib
import hmac
import json
from flask import Blueprint, redirect, render_template, request, jsonify, make_response, url_for
import jwt
import datetime
from functools import wraps

from app.models.database import get_user_db
from app.models.crypt import hash_password, user_me, verify_password
from app.models.config import get_config

# 注意：db和app在主程序中初始化，然后注入
users_bp = Blueprint("users", __name__, url_prefix="/user")


# ---------------- JWT 装饰器 ----------------
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get('token')
        if not token:
            return jsonify({"status": "failed", "reason": "Token missing"}), 401
        try:
            data = jwt.decode(token, get_config('secret_key'), algorithms=["HS256"])
            user_db = get_user_db()
            current_user = user_db.execute("SELECT * FROM user_info WHERE id=?", (data['user_id'],)).fetchone()
            user_db.execute("UPDATE user_info SET lastLogin=? WHERE id=?", (datetime.datetime.utcnow(), data['user_id']))
            user_db.commit()
            user_db.close()
        except Exception:
            return jsonify({"status": "failed", "reason": "Invalid token"}), 401
        return f(current_user, *args, **kwargs)
    return decorated


# ---------------- 路由 ----------------
@users_bp.route("/")
def user_page():
    return render_template(
            'login.html'
    )


@users_bp.route("/register_submit", methods=["POST"])
def register():
    username = request.form.get("username") or (request.json.get("username") if request.is_json else None)
    password = request.form.get("password") or (request.json.get("password") if request.is_json else None)

    if not username or not password:
        return jsonify({"status": "failed", "reason": "Missing username or password"})

    user_db = get_user_db()
    existing_user = user_db.execute("SELECT * FROM user_info WHERE name=?", (username,)).fetchone()

    if existing_user:
        return jsonify({"status": "failed", "reason": "Username already exists"})

    hashed_pw = hash_password(password)
    new_user = (username, hashed_pw, '', '', False, False, False, False, False, False, datetime.datetime.utcnow())
    user_db.execute("INSERT INTO user_info (name, password_hash, icon, title, permission_manage_accounts, permission_manage_own_editions, permission_manage_all_editions, permission_manage_create_editions, permission_storyteller, permission_storyteller_vocal, lastLogin) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", new_user)
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

    if not user or not verify_password(user['password_hash'], password):
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
        "permission_manage_accounts": current_user['permission_manage_accounts'],
        "permission_manage_own_editions": current_user['permission_manage_own_editions'],
        "permission_manage_all_editions": current_user['permission_manage_all_editions'],
        "permission_manage_create_editions": current_user['permission_manage_create_editions'],
        "permission_storyteller": current_user['permission_storyteller'],
        "permission_storyteller_vocal": current_user['permission_storyteller_vocal'],
        "lastLogin": current_user['lastLogin']
    }

    # 序列化为字符串（确保顺序一致）
    payload = json.dumps(user_data, sort_keys=True, separators=(",", ":"))

    # 使用 HMAC-SHA256 生成签名
    signature = hmac.new(
        secret_key.encode("utf-8"), 
        payload.encode("utf-8"), 
        hashlib.sha256
    ).hexdigest()

    # 返回带签名的数据
    return jsonify({**user_data, "signature": signature})

@users_bp.route("/view_user/<int:user_id>", methods=["POST"])
def view_user(user_id):
    user_db = get_user_db()
    user = user_db.execute("SELECT * FROM user_info WHERE id=?", (user_id,)).fetchone()
    user_db.close()
    if not user:
        return jsonify({"status": "failed", "reason": "User not found"})
    return jsonify(
        {
            "status": "success", 
            "username": user['name'],
            "id": user['id'],
            "permission_manage_accounts": user['permission_manage_accounts'],
            "permission_manage_own_editions": user['permission_manage_own_editions'],
            "permission_manage_all_editions": user['permission_manage_all_editions'],
            "permission_manage_create_editions": user['permission_manage_create_editions'],
            "permission_storyteller": user['permission_storyteller'],
            "permission_storyteller_vocal": user['permission_storyteller_vocal'],
            "lastLogin": user['lastLogin']
        }
    )

@users_bp.route("/edit_user", methods=["GET"])
def edit_user():
    user = user_me()
    if not user:
        return redirect(url_for('users.user_page'))
    if not user['permission_manage_accounts']:
        return "❌ 您没有权限编辑其他用户，请联系管理员。"
    return render_template("edit_user.html")

@users_bp.route("/permission_update", methods=["POST"])
def permission_update():
    user = user_me()
    if not user:
        return redirect(url_for('users.user_page'))
    if not user['permission_manage_accounts']:
        return jsonify({"status": "failed", "reason": "您没有权限编辑其他用户"})
    
    username = request.form.get("username") or (request.json.get("username") if request.is_json else None)

    permission_manage_accounts = request.form.get("permission_manage_accounts") or (request.json.get("permission_manage_accounts") if request.is_json else None)
    permission_manage_own_editions = request.form.get("permission_manage_own_editions") or (request.json.get("permission_manage_own_editions") if request.is_json else None)
    permission_manage_all_editions = request.form.get("permission_manage_all_editions") or (request.json.get("permission_manage_all_editions") if request.is_json else None)
    permission_manage_create_editions = request.form.get("permission_manage_create_editions") or (request.json.get("permission_manage_create_editions") if request.is_json else None)
    permission_storyteller = request.form.get("permission_storyteller") or (request.json.get("permission_storyteller") if request.is_json else None)
    permission_storyteller_vocal = request.form.get("permission_storyteller_vocal") or (request.json.get("permission_storyteller_vocal") if request.is_json else None)

    user_db = get_user_db()
    user = user_db.execute("SELECT * FROM user_info WHERE name=?", (username,)).fetchone()
    if not user:
        return jsonify({"status": "failed", "reason": "目标用户不存在"})

    user_db.execute("""UPDATE user_info SET 
    permission_manage_accounts=?,
    permission_manage_own_editions=?, 
    permission_manage_all_editions=?, 
    permission_manage_create_editions=?, 
    permission_storyteller=?, 
    permission_storyteller_vocal=? 
    WHERE name=?""", 
        (
        permission_manage_accounts,
        permission_manage_own_editions, 
        permission_manage_all_editions, 
        permission_manage_create_editions, 
        permission_storyteller, 
        permission_storyteller_vocal, 
        username)
    )
    user_db.commit()
    user_db.close()

    return jsonify({"status": "success"})