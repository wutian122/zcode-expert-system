"""密码哈希工具（Task 2）。PBKDF2-HMAC-SHA256（10 万次迭代 + 16 字节随机盐），零新增依赖。"""
import base64
import hashlib
import hmac
import os


def hash_password(plain: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, 100_000)
    return base64.b64encode(salt + dk).decode("ascii")


def verify_password(plain: str, stored: str) -> bool:
    try:
        raw = base64.b64decode(stored.encode("ascii"))
    except Exception:
        return False
    salt, dk = raw[:16], raw[16:]
    expected = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, 100_000)
    return hmac.compare_digest(dk, expected)
