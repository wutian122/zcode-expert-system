"""认证业务编排：注册 / 登录 / 刷新（Task 4）。"""
import hashlib
import secrets
import time
from datetime import datetime, timezone

from .jwt_util import sign
from .password_util import hash_password, verify_password
from .user_repository import UserRepository
from .refresh_token_repository import RefreshTokenRepository


class DuplicateAccountError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class InvalidRefreshTokenError(Exception):
    pass


def _hash_token(token: str) -> str:
    """对 refresh token 做 sha256。列中只存哈希，令牌明文不入库。

    令牌明文由 secrets 生成（R2），入库与查询前统一经此函数哈希，
    数据库泄露时攻击者只能拿到哈希，无法直接重放令牌。
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthService:
    def __init__(self, conn, secret, access_ttl=900, refresh_ttl=604800):
        self.conn = conn
        self.secret = secret
        self.access_ttl = access_ttl
        self.refresh_ttl = refresh_ttl
        self.users = UserRepository(conn)
        self.refresh_tokens = RefreshTokenRepository(conn)

    def register(self, username, email, password):
        if self.users.find_by_username(username) or self.users.find_by_email(email):
            raise DuplicateAccountError("DUPLICATE_ACCOUNT")
        return self.users.insert(username, email, hash_password(password))

    def login(self, username_or_email, password):
        user = self.users.find_by_username(username_or_email) or self.users.find_by_email(
            username_or_email
        )
        if user is None or not verify_password(password, user[3]):
            raise InvalidCredentialsError("INVALID_CREDENTIALS")
        user_id = user[0]
        access = sign({"sub": str(user_id)}, self.secret, self.access_ttl)
        # R2：refresh token 由 secrets 密码学随机生成（256 位熵），
        # 不再用 sha256(user_id:time_ns) 的确定性派生（可预测、可逼近枚举）。
        refresh_token_value = secrets.token_urlsafe(32)
        exp_iso = datetime.fromtimestamp(
            time.time() + self.refresh_ttl, tz=timezone.utc
        ).isoformat()
        # 存库前哈希：token_hash 列只存 sha256，不存令牌明文。
        self.refresh_tokens.insert(user_id, _hash_token(refresh_token_value), exp_iso)
        return access, refresh_token_value

    def refresh(self, refresh_token):
        # 查询前哈希：列存哈希，客户端回传的是令牌明文，先哈希再查。
        row = self.refresh_tokens.find_by_token_hash(_hash_token(refresh_token))
        if row is None:
            raise InvalidRefreshTokenError("INVALID_REFRESH_TOKEN")
        expires_at = row[3]
        revoked_at = row[4]
        # R1：expires_at 存的是 ISO 8601 字符串（login 写入），
        # 用 datetime.fromisoformat 解析；解析失败归一化为刷新失败，
        # 避免 float(ISO 串) 抛 ValueError 泄漏为 500。
        try:
            expires_at_dt = datetime.fromisoformat(expires_at)
        except (ValueError, TypeError):
            raise InvalidRefreshTokenError("INVALID_REFRESH_TOKEN")
        if revoked_at is not None or expires_at_dt.timestamp() <= time.time():
            raise InvalidRefreshTokenError("INVALID_REFRESH_TOKEN")
        # 单用旋转：吊销旧令牌（UTC 时基，与 expires_at 一致）
        self.refresh_tokens.revoke(
            _hash_token(refresh_token),
            datetime.now(timezone.utc).isoformat(),
        )
        user_id = row[1]
        new_access = sign({"sub": str(user_id)}, self.secret, self.access_ttl)
        # R2：新令牌同样用 secrets 随机生成，存库前哈希。
        new_rt = secrets.token_urlsafe(32)
        new_exp_iso = datetime.fromtimestamp(
            time.time() + self.refresh_ttl, tz=timezone.utc
        ).isoformat()
        self.refresh_tokens.insert(user_id, _hash_token(new_rt), new_exp_iso)
        return new_access, new_rt