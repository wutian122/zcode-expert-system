"""users 仓库（Task 3）——类式接口。"""
from .schema import new_id, now_iso


class UserRepository:
    def __init__(self, conn):
        self.conn = conn

    def find_by_username(self, username):
        cur = self.conn.execute(
            "SELECT id, username, email, password_hash, created_at FROM users WHERE username = ?",
            (username,),
        )
        return cur.fetchone()

    def find_by_email(self, email):
        cur = self.conn.execute(
            "SELECT id, username, email, password_hash, created_at FROM users WHERE email = ?",
            (email,),
        )
        return cur.fetchone()

    def insert(self, username, email, password_hash):
        uid = new_id()
        self.conn.execute(
            "INSERT INTO users (id, username, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            (uid, username, email, password_hash, now_iso()),
        )
        self.conn.commit()
        return uid