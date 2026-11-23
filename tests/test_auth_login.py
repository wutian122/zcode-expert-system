"""Task 2 登录部分：JWT 工具与登录服务（TDD RED 先行）。

先写失败测试，确认 RED 后再实现。断言按 OpenSpec
openspec/changes/jwt-auth-system/specs/auth/spec.md 的 Scenario:
Successful Login / Login — Invalid Credentials。
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from auth.jwt_util import sign, verify, TokenExpiredError, TokenInvalidError
from auth.password_util import hash_password, verify_password
from auth.auth_service import AuthService, InvalidRefreshTokenError
from auth.user_repository import UserRepository
from auth.refresh_token_repository import RefreshTokenRepository


# ---------- JWT 工具 ----------

def test_jwt_roundtrip():
    token = sign({"sub": "u1"}, secret="s3cret", ttl=60)
    payload = verify(token, secret="s3cret")
    assert payload["sub"] == "u1"


def test_jwt_expired_rejected():
    token = sign({"sub": "u1"}, secret="s3cret", ttl=-1)
    with pytest.raises(TokenExpiredError):
        verify(token, secret="s3cret")


def test_jwt_tampered_rejected():
    token = sign({"sub": "u1"}, secret="s3cret", ttl=60)
    tampered = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
    with pytest.raises(TokenInvalidError):
        verify(tampered, secret="s3cret")


# ---------- 密码工具 ----------

def test_password_roundtrip():
    h = hash_password("correct-horse")
    assert verify_password("correct-horse", h)
    assert not verify_password("wrong", h)


# ---------- 登录服务 ----------

@pytest.fixture()
def service(tmp_path):
    import sqlite3
    from auth.schema import create_tables
    conn = sqlite3.connect(str(tmp_path / "auth.db"))
    create_tables(conn)
    return AuthService(conn, secret="s3cret", access_ttl=900, refresh_ttl=604800)


def test_login_success_returns_tokens(service):
    uid = service.register("alice", "alice@example.com", "pw-alice")
    access, refresh = service.login("alice", "pw-alice")
    assert access and refresh
    payload = verify(access, secret="s3cret")
    assert payload["sub"] == str(uid)


def test_login_wrong_password(service):
    service.register("alice", "alice@example.com", "pw-alice")
    with pytest.raises(Exception) as exc:
        service.login("alice", "wrong")
    # 不区分账号错/密码错，统一错误
    assert "INVALID_CREDENTIALS" in str(exc.value) or "Invalid" in type(exc.value).__name__


def test_login_unknown_user_same_error(service):
    with pytest.raises(Exception) as exc:
        service.login("ghost", "whatever")
    assert "INVALID_CREDENTIALS" in str(exc.value) or "Invalid" in type(exc.value).__name__


# ---------- JWT header 校验（R3：verify 不校验 typ/alg） ----------

import base64
import hashlib
import hmac
import json


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_signed_jwt(header: dict, payload: dict, secret: str) -> str:
    """构造 header 自定义、但签名有效的 JWT（用于测试 header 校验）。

    关键：签名用真实 secret 的 HMAC-SHA256 生成，保证验签通过；payload
    带未来 exp，保证过期检查通过。使 R3 的 header 校验成为唯一判定依据——
    若 verify 不校验 header，这类"签名有效、未过期、但 alg/typ 异常"的
    令牌会被错误放行。
    """
    payload = dict(payload)
    payload.setdefault("exp", time.time() + 600)
    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64url(sig)}"


def test_verify_rejects_wrong_alg():
    """R3：签名有效但 alg 非 HS256 的令牌必须拒绝（header 白名单校验）。"""
    token = _make_signed_jwt({"alg": "none", "typ": "JWT"}, {"sub": "u1"}, "s3cret")
    with pytest.raises(TokenInvalidError):
        verify(token, secret="s3cret")


def test_verify_rejects_wrong_typ():
    """R3：签名有效但 typ 非 JWT 的令牌必须拒绝。"""
    token = _make_signed_jwt({"alg": "HS256", "typ": "JWE"}, {"sub": "u1"}, "s3cret")
    with pytest.raises(TokenInvalidError):
        verify(token, secret="s3cret")


def test_verify_rejects_missing_header():
    """R3：header 不可解析的令牌必须拒绝。"""
    header_b64 = _b64url(b"not-json")
    payload_b64 = _b64url(json.dumps({"sub": "u1", "exp": time.time() + 600}).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = hmac.new("s3cret".encode("utf-8"), signing_input, hashlib.sha256).digest()
    bad = f"{header_b64}.{payload_b64}.{_b64url(sig)}"
    with pytest.raises(TokenInvalidError):
        verify(bad, secret="s3cret")


def test_verify_accepts_valid_hs256_jwt():
    """R3 回归：合法 HS256+JWT 令牌仍正常通过。"""
    token = sign({"sub": "u1"}, secret="s3cret", ttl=60)
    payload = verify(token, secret="s3cret")
    assert payload["sub"] == "u1"


# ---------- refresh 刷新令牌（R1：refresh() 对 ISO 8601 expires_at 必崩） ----------

def test_refresh_success_returns_rotated_tokens(service):
    """R1：refresh 必须成功旋转，不再因 float(ISO 串) 抛 ValueError。"""
    uid = service.register("alice", "alice@example.com", "pw-alice")
    _, refresh = service.login("alice", "pw-alice")
    new_access, new_rt = service.refresh(refresh)
    assert new_access and new_rt
    payload = verify(new_access, secret="s3cret")
    assert payload["sub"] == str(uid)


def test_refresh_old_token_revoked_after_rotation(service):
    """单用旋转：旧 refresh 二次使用必须被拒。"""
    service.register("alice", "alice@example.com", "pw-alice")
    _, refresh = service.login("alice", "pw-alice")
    service.refresh(refresh)
    with pytest.raises(InvalidRefreshTokenError):
        service.refresh(refresh)


def test_refresh_unknown_token_rejected(service):
    with pytest.raises(InvalidRefreshTokenError):
        service.refresh("nonexistent-token-hash")


def test_refresh_expired_rejected(service):
    """过期 refresh 必须拒绝（R1：ISO 串解析失败应归一化为拒绝，而非 ValueError 泄漏）。"""
    service.register("alice", "alice@example.com", "pw-alice")
    _, refresh = service.login("alice", "pw-alice")
    # 把过期时间改为过去，验证过期分支走通（修复后不再抛 ValueError）
    import sqlite3
    import hashlib
    from datetime import datetime, timezone
    past = datetime.now(timezone.utc).timestamp() - 60
    expired_iso = datetime.fromtimestamp(past, tz=timezone.utc).isoformat()
    service.refresh_tokens.conn.execute(
        "UPDATE refresh_tokens SET expires_at = ? WHERE token_hash = ?",
        (expired_iso, hashlib.sha256(refresh.encode()).hexdigest()),
    )
    service.refresh_tokens.conn.commit()
    with pytest.raises(InvalidRefreshTokenError):
        service.refresh(refresh)


def test_refresh_token_not_predictable(service):
    """R2：同一用户两次 login 的 refresh token 不可预测（引入 secrets 随机源）。"""
    service.register("bob", "bob@example.com", "pw-bob")
    _, rt1 = service.login("bob", "pw-bob")
    _, rt2 = service.login("bob", "pw-bob")
    assert rt1 != rt2
    # 不是 sha256(user_id:time_ns) 的确定性派生：两次不同即非纯时间派生
    assert not rt1.startswith("sha256")


def test_refresh_token_stored_as_hash_not_plaintext(service):
    """R2：token_hash 列存的是哈希而非明文令牌。

    契约：列存哈希，查询传哈希值。用 _hash_token 哈希后查询应命中，
    且列值等于哈希、不等于令牌明文。
    """
    import hashlib

    service.register("bob", "bob@example.com", "pw-bob")
    _, rt = service.login("bob", "pw-bob")
    row = service.refresh_tokens.find_by_token_hash(hashlib.sha256(rt.encode()).hexdigest())
    assert row is not None
    stored = row[2]
    assert stored != rt, "token_hash 不得存明文"
    assert stored == hashlib.sha256(rt.encode()).hexdigest()