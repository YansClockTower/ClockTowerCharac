import hashlib, os, binascii

from app.identity import get_current_user

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
    user = get_current_user(update_last_login=False)
    if user is None:
        return {}
    return user