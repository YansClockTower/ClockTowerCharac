import hashlib
import hmac
import io
import json
import os
from flask import Blueprint, redirect, render_template, request, jsonify, make_response, send_file, url_for
import jwt
import datetime
from functools import wraps

from app.models.database import get_user_db
from app.models.crypt import hash_password, user_me, verify_password
from app.models.config import get_config

from PIL import Image

from app.models.usericon import save_user_icon, user_icon_url

# 注意：db和app在主程序中初始化，然后注入
users_bp = Blueprint("users", __name__, url_prefix="/user")

# from . import get_config, get_user_db, hash_password, verify_password 

# --- 辅助函数：从请求中获取用户信息 ---
def get_user_data_from_request():
    """尝试从 Cookie 中获取 token，并返回用户信息字典，失败则返回 None"""
    token = request.cookies.get('token')
    if not token:
        # 尝试从 Authorization Header 中获取 token（以防前端是 AJAX 请求）
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
        if not token:
            return None # Token 缺失

    try:
        data = jwt.decode(token, get_config('secret_key'), algorithms=["HS256"])
        user_db = get_user_db()
        current_user = user_db.execute("SELECT * FROM user_info WHERE id=?", (data['user_id'],)).fetchone()
        
        # 更新 lastLogin 字段
        user_db.execute("UPDATE user_info SET lastLogin=? WHERE id=?", (datetime.datetime.utcnow(), data['user_id']))
        user_db.commit()
        user_db.close()
        
        if not current_user:
             return None # 用户 ID 无效
             
        # 将用户数据转换为字典，便于 Jinja2 使用
        user_dict = dict(current_user)
        # 移除敏感字段
        user_dict.pop('password_hash', None)
        user_dict['authenticated'] = True # 标记为已认证
        
        return user_dict
        
    except Exception as e:
        # Token 无效或过期
        print(f"Token error: {e}") # 调试用
        return None

# --- 新装饰器：用于渲染模板的视图函数 ---
def login_required_template(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user_info = get_user_data_from_request()

        if user_info is None:
            # Token 无效或缺失，重定向到登录页
            # 注意：使用 url_for('users.user_login') 确保路径正确
            response = make_response(redirect(url_for('users.user_login')))
            # 清除可能存在的无效 token cookie
            # response.delete_cookie('token')
            return response
        
        # 将 user_info 传递给视图函数
        return f(user_info, *args, **kwargs)
    return decorated
    
# ---------------- JWT 装饰器 ----------------
# --- 现有 JWT 装饰器（用于 AJAX 接口，无需修改） ---
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        current_user = get_user_data_from_request()
        if current_user is None:
            return jsonify({"status": "failed", "reason": "Authentication failed"}), 401
        
        # 传递原始的 user dict (或您需要的其他格式)
        return f(current_user, *args, **kwargs)
    return decorated

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

    user_db = get_user_db()
    existing_user = user_db.execute("SELECT * FROM user_info WHERE name=?", (username,)).fetchone()

    if existing_user:
        return jsonify({"status": "failed", "reason": "Username already exists"})

    hashed_pw = hash_password(password)
    new_user = (username, hashed_pw, '', '', False, False, False, False, False, False, datetime.datetime.utcnow())
    user_db.execute("""INSERT INTO user_info 
    (name, password_hash, icon, title, 
    permission_manage_accounts, permission_manage_own_editions, permission_manage_all_editions, permission_manage_create_editions, permission_storyteller, permission_storyteller_vocal, 
    lastLogin) 
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", new_user)
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