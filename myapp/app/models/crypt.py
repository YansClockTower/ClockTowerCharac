import hashlib, os, binascii

from flask import request
import jwt

from app.models.config import get_config
from app.models.database import get_user_db

def hash_password(password: str) -> str:
    salt = os.urandom(16)  # 生成随机盐
    dk = hashlib.pbkdf2_hmac(
        'sha256',                # 使用 HMAC-SHA256
        password.encode(),       # 明文密码
        salt,                    # 盐
        100_000                  # 迭代次数（推荐 >=100000）
    )
    return binascii.hexlify(salt + dk).decode()

def verify_password(stored: str, password: str) -> bool:
    raw = binascii.unhexlify(stored.encode())
    salt, stored_dk = raw[:16], raw[16:]
    new_dk = hashlib.pbkdf2_hmac(
        'sha256', password.encode(), salt, 100_000
    )
    return new_dk == stored_dk

def user_me():
    token = request.cookies.get('token')
    if token:
        try:
            token_data = jwt.decode(token, get_config('secret_key'), algorithms=["HS256"])
        except Exception:
            return {}
        user_db = get_user_db()
        current_user = user_db.execute("SELECT * FROM user_info WHERE id=?", (token_data['user_id'],)).fetchone()
        user_db.close()
        return current_user
    else:
        return {}