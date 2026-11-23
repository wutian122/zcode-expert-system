"""refresh_tokens 仓库（Task 3）——类式接口。"""
from .schema import new_id, now_iso


class RefreshTokenRepository:
    def __init__(self, conn):
        self.conn = conn

    def insert(self, user_id, token_hash, expires_at):
        rid = new_id()
        self.conn.execute(
            "INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at, revoked_at, created_at) VALUES (?, ?, ?, ?, NULL, ?)",
            (rid, user_id, token_hash, expires_at, now_iso()),
        )
        self.conn.commit()
        return rid

    def find_by_token_hash(self, token_hash):
        cur = self.conn.execute(
            "SELECT id, user_id, token_hash, expires_at, revoked_at, created_at FROM refresh_tokens WHERE token_hash = ?",
            (token_hash,),
        )
        return cur.fetchone()

    def revoke(self, token_hash, revoked_at):
        self.conn.execute(
            "UPDATE refresh_tokens SET revoked_at = ? WHERE token_hash = ?",
            (revoked_at, token_hash),
        )
        self.conn.commit()