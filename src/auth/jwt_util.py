"""JWT 签发/验证工具（Task 2）。HS256，可选 PyJWT，回退为标准库 hmac。"""
import base64
import hashlib
import hmac
import json
import time


class TokenError(Exception):
    pass


class TokenExpiredError(TokenError):
    pass


class TokenInvalidError(TokenError):
    pass


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def sign(payload: dict, secret: str, ttl: int) -> str:
    header = _b64url(b'{"alg":"HS256","typ":"JWT"}')
    now = int(time.time())
    body = dict(payload)
    body["iat"] = now
    body["exp"] = now + ttl
    payload_b64 = _b64url(json.dumps(body, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header}.{payload_b64}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{signing_input.decode('ascii')}.{_b64url(sig)}"


def verify(token: str, secret: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        raise TokenInvalidError("jwt malformed")
    header_b64, payload_b64, sig_b64 = parts

    # R3：先解析 header 并白名单校验 alg/typ，再验签。
    # 防止算法混淆（如 alg=none 等）：对"签名有效但 alg/typ 异常"的
    # 令牌一律拒绝，不进入验签与过期检查。
    try:
        header = json.loads(_b64url_decode(header_b64).decode("utf-8"))
    except Exception:
        raise TokenInvalidError("jwt header invalid")
    if not isinstance(header, dict) or header.get("alg") != "HS256" or header.get("typ") != "JWT":
        raise TokenInvalidError("jwt header alg/typ invalid")

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        actual = _b64url_decode(sig_b64)
    except Exception:
        raise TokenInvalidError("jwt signature invalid")
    if not hmac.compare_digest(expected, actual):
        raise TokenInvalidError("jwt signature invalid")
    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception:
        raise TokenInvalidError("jwt payload invalid")
    now = int(time.time())
    if payload.get("exp", 0) <= now:
        raise TokenExpiredError("jwt expired")
    return payload
