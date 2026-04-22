import datetime
from functools import wraps
from urllib.parse import quote

import jwt
from flask import jsonify, make_response, redirect, request, url_for

from app.models.config import get_config
from app.models.database import get_user_db
from app.identity.permissions import enrich_user_permissions

# 须与 app/user/static/js/auth_client.js 中 AUTH_TOKEN_STORAGE_KEY 一致
AUTH_TOKEN_LOCAL_STORAGE_KEY = "clocktower_auth_token"


def extract_auth_token():
    """读取 JWT：优先 ``Authorization: Bearer``（避免陈旧 Cookie 覆盖新 token），否则 Cookie ``token``。"""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1]
    token = request.cookies.get("token")
    if token:
        return token
    return None


def safe_redirect_target(candidate):
    """仅允许站内相对路径，防止开放重定向。"""
    if candidate is None:
        return None
    s = str(candidate).strip()
    if not s.startswith("/"):
        return None
    if s.startswith("//"):
        return None
    return s


def get_current_user(update_last_login=True):
    token = extract_auth_token()
    if not token:
        return None

    try:
        data = jwt.decode(token, get_config("secret_key"), algorithms=["HS256"])
    except Exception:
        return None

    user_db = get_user_db()
    current_user = user_db.execute(
        "SELECT * FROM user_info WHERE id=?",
        (data["user_id"],),
    ).fetchone()

    if not current_user:
        user_db.close()
        return None

    if update_last_login:
        user_db.execute(
            "UPDATE user_info SET lastLogin=? WHERE id=?",
            (datetime.datetime.utcnow(), data["user_id"]),
        )
        user_db.commit()

    user_db.close()

    user_dict = enrich_user_permissions(dict(current_user))
    user_dict.pop("password_hash", None)
    user_dict["authenticated"] = True
    return user_dict


def login_required_template(f):
    """
    服务端渲染页：优先 Cookie；无 Cookie 时整页 GET 无法带 Bearer，故未登录时重定向到登录页并附带 next。
    客户端应在登录页用 localStorage 中的 JWT 调用 ``POST /user/establish_session`` 尝试补写 Cookie 后再访问 next。
    与 Cookie 并行的 JWT 见 ``AUTH_TOKEN_LOCAL_STORAGE_KEY`` / ``Authorization: Bearer``。
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        user_info = get_current_user()
        if user_info is None:
            n = safe_redirect_target(request.full_path) or safe_redirect_target(request.path)
            login_url = url_for("users.user_login")
            if n:
                login_url = login_url + "?next=" + quote(n, safe="")
            return make_response(redirect(login_url))
        return f(user_info, *args, **kwargs)

    return decorated


def token_required(f):
    """
    JSON API：须携带有效 JWT（Cookie ``token`` 或 ``Authorization: Bearer <JWT>``）。
    前端对受本装饰器保护的路由发起 fetch 时，请使用 ``ClockTowerAuth.authHeaders`` / ``authFetch`` 附带 Bearer。
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        current_user = get_current_user()
        if current_user is None:
            return jsonify({"status": "failed", "reason": "Authentication failed"}), 401
        return f(current_user, *args, **kwargs)

    return decorated
