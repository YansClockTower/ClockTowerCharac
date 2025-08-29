from flask import Blueprint, render_template, request, jsonify, make_response
import jwt
import datetime
from functools import wraps

from app.models.database import get_user_db
from app.models.crypt import hash_password, verify_password
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
        {"user_id": user['id'], "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=1)},
        get_config('secret_key'),
        algorithm="HS256"
    )

    resp = make_response(jsonify({"status": "success", "token": token}))

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
    return jsonify(
        {
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
    )
