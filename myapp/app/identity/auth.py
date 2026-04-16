import datetime
from functools import wraps

import jwt
from flask import jsonify, make_response, redirect, request, url_for

from app.models.config import get_config
from app.models.database import get_user_db
from app.identity.permissions import enrich_user_permissions


def _extract_token():
    token = request.cookies.get("token")
    if token:
        return token

    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1]
    return None


def get_current_user(update_last_login=True):
    token = _extract_token()
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
    @wraps(f)
    def decorated(*args, **kwargs):
        user_info = get_current_user()
        if user_info is None:
            return make_response(redirect(url_for("users.user_login")))
        return f(user_info, *args, **kwargs)

    return decorated


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        current_user = get_current_user()
        if current_user is None:
            return jsonify({"status": "failed", "reason": "Authentication failed"}), 401
        return f(current_user, *args, **kwargs)

    return decorated
